"""Products of the interstellar comet 3I/ATLAS page (#/comet): SPHEREx movies, a CO2 map, a rough spectrum and the sky
path, written to web/data/comet/.

    python scripts/comet_build.py                 # every stage (downloads ~1.1 GB the first time)
    python scripts/comet_build.py --stage build   # re-make the products from the cache
(set SX_INSECURE=1 behind a TLS-intercepting proxy)

Stages
  match   IRSA's table of SPHEREx images of 3I/ATLAS (obscore_3I_Atlas.vot, 259 rows) points at the retired QR2 release.
          Each row is looked up again in the current releases (sxlib.archive.search_images at the comet's predicted
          position, +-0.01 d) and matched on obs_id + detector.                     -> cache/comet/match.json
  fetch   a 0.2 deg cutout at the comet's predicted position from every matched image  -> cache/comet/cutouts/
          (each IRSA cutout carries the 3.8 MB ePSF table, so ~4.2 MB per download; only the pixels are kept)
  horizons JPL Horizons geocentric ephemeris (sky path, distances, brightness)        -> cache/comet/horizons_*.json
          and heliocentric positions of the comet, Earth, Mars and Jupiter (top view)  -> cache/comet/vectors_*.json
  build   every exposure resampled onto a comet-centred, north-up grid (6.2"/px), then
          - movies: one sprite sheet per epoch and detector pair (frames in time order), with time and wavelength
          - CO2: stacks of the exposures whose wavelength AT THE COMET'S PIXEL is in the CO2 band (4.20-4.32 um) and in
            the continuum on either side (3.90-4.10, 4.45-4.60 um); band - continuum interpolated to 4.26 um
          - a large-aperture brightness for every exposure (indicative only: the comet is extended and faint), and
            the CO2 band's integrated flux from the single exposures inside the band
          - the sky path over the two epochs and a top view of the orbit
                                                                                     -> web/data/comet/
          the CO2 numbers and a position check also go to web/data/validation/comet.json
IRSA's caveat, repeated on the page: at SPHEREx's resolution 3I/ATLAS is extended at many wavelengths and has low
signal-to-noise at many wavelengths; point-source spectrophotometry is not appropriate for it.
"""
import argparse
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE as _CACHE_ROOT, DATA, VALIDATION, read_json, write_json  # noqa: E402

CACHE = _CACHE_ROOT / "comet"
OUT = DATA / "comet"
TABLE_URL = "https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/obscore_3I_Atlas.vot"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
SIZE_DEG = 0.2              # cutout side
PIX = 6.15                  # arcsec per pixel of the comet-centred grid (SPHEREx's native scale)
GRID = 101                  # comet-centred grid side (pixels): 10.4 arcmin (corners may fall off the 0.2 deg cutout)
CO2_BAND = (4.20, 4.32)     # um: CO2 nu3 band at 4.26 um, at SPHEREx's resolution (R ~ 40-130)
CONT_BLUE = (3.90, 4.10)
CONT_RED = (4.45, 4.60)
CO2_LAM = 4.26
ARCSEC_PER_RAD = 206264.806
PIX_SR = (PIX / ARCSEC_PER_RAD) ** 2  # solid angle of one grid pixel (sr)
C_UM_S = 2.99792458e14                # speed of light (um/s)
AU_M = 1.495978707e11
AU_KM = 149597870.7
NTHREADS = 6                          # parallel IRSA requests
TABLE_NAME = "obscore_3I_Atlas.vot"
EPH_SPAN = ("2025-07-01", "2026-01-31", "1 d")        # geocentric ephemeris (sky path)
VEC_SPAN = ("2025-05-01", "2026-04-30", "2 d")        # heliocentric vectors (top view)
BODIES = (("comet", "DES=C/2025 N1;"), ("earth", "399"), ("mars", "499"), ("jupiter", "599"))
PROFILE_RADII = range(0, 37, 2)       # radial-profile rings (grid pixels)
PROFILE_BG = (38, 48)                 # radial-profile background ring (grid pixels)


# ---------------------------------------------------------------------------------------------- pure helpers (tested)
def read_obs_table(path):
    """IRSA's 3I/ATLAS observation table -> [{obs_id, det, comet_ra, comet_dec, t_min, t_max}] in time order."""
    from astropy.io.votable import parse_single_table
    t = parse_single_table(str(path)).to_table()
    rows = [{"obs_id": str(r["obs_id"]), "det": int(str(r["spherex_detector"]).lstrip("D")),
             "comet_ra": float(r["comet_ra"]), "comet_dec": float(r["comet_dec"]),
             "t_min": float(r["t_min"]), "t_max": float(r["t_max"])} for r in t]
    return sorted(rows, key=lambda r: (r["t_min"], r["det"]))


def epoch_of(mjd):
    """'aug' (2025-08-01..15) or 'dec' (2025-12-08..15)."""
    return "aug" if mjd < 60950 else "dec"


def band_of(lam):
    """Which CO2-map stack an exposure belongs to, from the wavelength at the comet's pixel (um)."""
    for name, (a, b) in (("co2", CO2_BAND), ("blue", CONT_BLUE), ("red", CONT_RED)):
        if a <= lam <= b:
            return name
    return None


def interp_continuum(c_blue, lam_blue, c_red, lam_red, lam=CO2_LAM):
    """Continuum at `lam`, linear in wavelength between the two continuum stacks (arrays or numbers)."""
    w = (lam - lam_blue) / (lam_red - lam_blue)
    return (1 - w) * np.asarray(c_blue) + w * np.asarray(c_red)


@lru_cache(maxsize=8)
def _grid(n, c=None):
    """Pixel coordinates (xx, yy) of an n x n grid and the distance r from c (default: the centre); cached, read-only."""
    c = (n - 1) / 2 if c is None else c
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(xx - c, yy - c)
    for a in (xx, yy, r):
        a.flags.writeable = False
    return xx, yy, r


def radial_masks(n, r_ap, r_in, r_out, c=None):
    """Aperture disc and background annulus on an n x n grid centred at c (default: the centre)."""
    r = _grid(n, c)[2]
    return r <= r_ap, (r >= r_in) & (r <= r_out)


def _profile(img, r):
    """Azimuthal means at PROFILE_RADII minus the median of the PROFILE_BG ring."""
    bg = np.nanmedian(img[(r >= PROFILE_BG[0]) & (r <= PROFILE_BG[1])])
    return [float(np.nanmean(img[(r >= r0 - 1) & (r < r0 + 1)] if r0 else img[r < 1]) - bg) for r0 in PROFILE_RADII]


def aperture_flux(img, var, r_ap, r_in, r_out):
    """Background-subtracted sum in a disc (image units x pixels) and its 1-sigma error from the variance and the
    annulus scatter. Returns (flux, err, coverage): coverage is the finite fraction of the aperture; when it is under
    0.9 the result is (nan, nan, coverage)."""
    n = img.shape[0]
    ap, ann = radial_masks(n, r_ap, r_in, r_out)
    ok = np.isfinite(img)
    cov = float(ok[ap].mean())
    b = img[ann & ok]
    if cov < 0.9 or b.size < 20:
        return float("nan"), float("nan"), cov
    med = float(np.median(b))
    sig_b = 1.4826 * float(np.median(np.abs(b - med)))
    n_ap = int(ap.sum())
    vals = np.where(ok, img, med)[ap]
    flux = float(np.sum(vals - med))
    v = var[ap & ok] if var is not None else np.array([])
    err_pix = float(np.sqrt(np.nansum(v))) if v.size else 0.0
    # pixel noise, plus the uncertainty of the background level over the aperture, plus the annulus' own scatter
    # applied to every aperture pixel (stars and structure in the annulus make this conservative)
    err = float(np.sqrt(err_pix ** 2 + (n_ap * sig_b / np.sqrt(b.size)) ** 2 + n_ap * sig_b ** 2))
    return flux, err, cov


def weighted_mean(vals, errs):
    """Inverse-variance mean and its error, with the error scaled up by sqrt(reduced chi2) when the points scatter more
    than their errors say (never down)."""
    v, e = np.asarray(vals, float), np.asarray(errs, float)
    ok = np.isfinite(v) & np.isfinite(e) & (e > 0)
    v, e = v[ok], e[ok]
    if not v.size:
        return float("nan"), float("nan"), 0
    w = 1 / e ** 2
    m = float(np.sum(w * v) / np.sum(w))
    err = float(np.sqrt(1 / np.sum(w)))
    if v.size > 1:
        chi2 = float(np.sum(w * (v - m) ** 2) / (v.size - 1))
        err *= np.sqrt(max(1.0, chi2))
    return m, err, int(v.size)


def parse_horizons(text):
    """Rows of a Horizons CSV observer table (QUANTITIES 1,9,19,20,23,24 with ANG_FORMAT=DEG) -> list of dicts."""
    a, b = text.find("$$SOE"), text.find("$$EOE")
    head = text[:a].strip().splitlines()
    cols = [c.strip() for c in head[-2].split(",")] if len(head) >= 2 else []
    out = []
    for ln in text[a + 5:b].strip().splitlines():
        p = [x.strip() for x in ln.split(",")]
        d = dict(zip(cols, p))

        def num(k):
            try:
                return float(d.get(k, "nan"))
            except ValueError:
                return float("nan")
        out.append({"date": d.get("Date__(UT)__HR:MN", p[0]), "ra": num("R.A._(ICRF)"), "dec": num("DEC_(ICRF)"),
                    "T_mag": num("T-mag"), "r_au": num("r"), "delta_au": num("delta"), "elong": num("S-O-T"),
                    "phase": num("S-T-O")})
    return out


def north_up_wcs(ra, dec, n=GRID, pix=PIX):
    """TAN grid n x n, north up and east left, centred on (ra, dec)."""
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix / 3600, pix / 3600]
    return w


def resample(img, wcs_in, ra, dec, n=GRID, pix=PIX, order=1):
    """Values of img (in the frame of wcs_in) on the comet-centred north-up grid; NaN off the image."""
    from scipy.ndimage import map_coordinates
    w = north_up_wcs(ra, dec, n, pix)
    xx, yy, _ = _grid(n)
    sky = w.pixel_to_world_values(xx, yy)
    px, py = wcs_in.world_to_pixel_values(*sky)
    good = np.isfinite(img)
    src = np.where(good, img, 0.0)
    out = map_coordinates(src, [py, px], order=order, mode="constant", cval=np.nan)
    # a sample touching a bad or missing pixel is bad
    bad = map_coordinates((~good).astype(float), [py, px], order=1, mode="constant", cval=1.0) > 0.01
    out[bad] = np.nan
    return out


# ---------------------------------------------------------------------------------------------------------- stages
def stage_match(rows):
    from sxlib import archive
    f = CACHE / "match.json"
    done = read_json(f, {})
    todo = sorted({r["obs_id"] for r in rows} - set(done))
    by_obs = {}
    for r in rows:
        by_obs.setdefault(r["obs_id"], []).append(r)

    def one(oid):
        r = by_obs[oid][0]
        try:
            res = archive.search_images(r["comet_ra"], r["comet_dec"], radius=0.001, mjd_range=(r["t_min"] - 0.01, r["t_max"] + 0.01))
        except Exception as e:  # noqa: BLE001
            return oid, None, str(e)
        return oid, [m for m in res if m["obs_id"] == oid], None

    with ThreadPoolExecutor(NTHREADS) as ex:
        for k, (oid, res, err) in enumerate(ex.map(one, todo)):
            if res is None:
                print("search failed", oid, err)
                continue
            done[oid] = res
            if k % 20 == 0:
                print(f"match {k + 1}/{len(todo)}", flush=True)
    write_json(f, done, indent=None)
    matched = []
    for r in rows:
        m = [x for x in done.get(r["obs_id"], []) if x["detector"] == r["det"]]
        if m:
            matched.append({**r, "meta": m[0]})
    print(f"matched {len(matched)}/{len(rows)} rows; releases:",
          {c: sum(1 for x in matched if x["meta"]["collection"] == c) for c in {x["meta"]["collection"] for x in matched}})
    return matched


def fetch_one(row):
    from sxlib import archive
    try:
        return archive.fetch_cutout(row["meta"], row["comet_ra"], row["comet_dec"], SIZE_DEG, keep_psf=False, cache=CACHE)
    except Exception as e:  # noqa: BLE001
        print("fetch failed", row["obs_id"], row["det"], e, flush=True)
        return None


def stage_fetch(matched):
    with ThreadPoolExecutor(NTHREADS) as ex:
        got = 0
        for k, e in enumerate(ex.map(fetch_one, matched)):
            got += e is not None
            if k % 20 == 0:
                print(f"fetch {k + 1}/{len(matched)}", flush=True)
    print(f"fetched {got}/{len(matched)}")


def _horizons_text(q):
    from sxlib import archive
    return archive._get(HORIZONS + "?" + urllib.parse.urlencode(q), {}, timeout=120).text


def horizons(start, stop, step):
    f = CACHE / f"horizons_{start}_{stop}_{step.replace(' ', '')}.json"
    if f.exists():
        return read_json(f)
    q = {"format": "text", "COMMAND": "'DES=C/2025 N1;'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES", "EPHEM_TYPE": "OBSERVER",
         "CENTER": "'500'", "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'", "STEP_SIZE": f"'{step}'",
         "QUANTITIES": "'1,9,19,20,23,24'", "CSV_FORMAT": "YES", "ANG_FORMAT": "DEG"}
    rows = parse_horizons(_horizons_text(q))
    write_json(f, rows, indent=None)
    return rows


def parse_vectors(text):
    """Rows of a Horizons CSV VECTORS table (VEC_TABLE=1) -> [{jd, x, y, z}] (au)."""
    a, b = text.find("$$SOE"), text.find("$$EOE")
    out = []
    for ln in text[a + 5:b].strip().splitlines():
        p = [x.strip() for x in ln.split(",")]
        out.append({"jd": float(p[0]), "date": p[1].replace("A.D. ", "")[:11], "x": float(p[2]), "y": float(p[3]), "z": float(p[4])})
    return out


def horizons_vectors(command, start, stop, step):
    """Heliocentric ecliptic positions (au) from JPL Horizons, cached."""
    tag = "".join(ch for ch in command if ch.isalnum())
    f = CACHE / f"vectors_{tag}_{start}_{stop}_{step.replace(' ', '')}.json"
    if f.exists():
        return read_json(f)
    q = {"format": "text", "COMMAND": f"'{command}'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS",
         "CENTER": "'500@10'", "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'", "STEP_SIZE": f"'{step}'",
         "VEC_TABLE": "1", "REF_PLANE": "ECLIPTIC", "CSV_FORMAT": "YES", "OUT_UNITS": "AU-D"}
    rows = parse_vectors(_horizons_text(q))
    write_json(f, rows, indent=None)
    return rows


# ----------------------------------------------------------------------------------------------------------- build
R_AP, R_IN, R_OUT = 4, 20, 30        # photometry aperture and background annulus (grid pixels of 6.15"); the coma
                                     # is still faintly there at 20 px (2 arcmin), so totals are slight underestimates
R_BG = 22                            # per-frame background and noise from pixels farther than this from the comet
MIN_BG_PIX = 200                     # a frame needs this many finite background pixels
MOVIE_COLS = 16                      # sprite-sheet columns


def to_grid(row):
    """One exposure on the comet-centred grid: background-subtracted image (MJy/sr), variance, the wavelength at the
    comet's pixel and the frame's robust noise."""
    e = fetch_one(row)
    if e is None:
        return None
    ra, dec = row["comet_ra"], row["comet_dec"]
    x, y = e.wcs.world_to_pixel_values(ra, dec)
    if not (0 <= x < e.img.shape[1] and 0 <= y < e.img.shape[0]):
        return None
    lam = float(e.wavelength_um(np.array([float(x)]), np.array([float(y)]))[0])
    if not np.isfinite(lam):                     # no wavelength solution at the comet's pixel
        return None
    img = e.img.astype(float).copy()
    img[e.bad_mask()] = np.nan
    g = resample(img, e.wcs, ra, dec)
    v = resample(np.where(np.isfinite(e.var), e.var, np.nan), e.wcs, ra, dec)
    # small holes (flagged pixels: saturated or persistent star cores, hot pixels) are filled from their neighbours;
    # areas off the detector stay empty
    g, filled = fill_holes(g)
    _, far = radial_masks(GRID, 0, R_BG, GRID)
    b = g[far & np.isfinite(g)]
    if b.size < MIN_BG_PIX or not np.isfinite(g[GRID // 2, GRID // 2]):
        return None
    bg = float(np.median(b))
    sig = float(1.4826 * np.median(np.abs(b - bg)))
    mjd = 0.5 * (row["t_min"] + row["t_max"])
    return {"obs_id": row["obs_id"], "det": row["det"], "mjd": mjd, "epoch": epoch_of(mjd), "lam": lam,
            "ra": ra, "dec": dec, "img": g - bg, "raw": np.where(filled, np.nan, g - bg), "var": v, "sig": sig, "bg": bg, "filled": filled,
            "release": row["meta"]["collection"].replace("spherex_", "").upper(), "pix_sr": PIX_SR}


def stretch_snr(img, sig, lo=-2.0, hi=45.0, soft=2.0):
    """8-bit picture of a frame in units of its own noise: asinh, so a faint coma and a bright star both read."""
    s = img / sig
    a = np.arcsinh((np.clip(s, lo, hi) - lo) / soft) / np.arcsinh((hi - lo) / soft)
    return np.where(np.isfinite(a), np.round(a * 255), 0).astype(np.uint8)


def sprite(tiles, cols):
    from PIL import Image
    n, h, w = len(tiles), tiles[0].shape[0], tiles[0].shape[1]
    rows = (n + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w), np.uint8)
    for j, t in enumerate(tiles):
        r, c = divmod(j, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = t
    return Image.fromarray(sheet, "L")


def fill_holes(img, max_area=120):
    """Fill NaN islands (flagged pixels: saturated or persistent star cores, hot pixels) of up to max_area pixels that do
    not touch the border, from their neighbours (normalised Gaussian convolution with a growing width). Areas off the
    detector stay NaN. Returns (image, filled mask)."""
    from scipy.ndimage import gaussian_filter, label
    bad = ~np.isfinite(img)
    if not bad.any():
        return img, np.zeros(img.shape, bool)
    lab, n = label(bad)
    edge = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])) - {0}
    sizes = np.bincount(lab.ravel())
    fill = np.isin(lab, [k for k in range(1, n + 1) if k not in edge and sizes[k] <= max_area])
    out = img.copy()
    ok = np.isfinite(out)
    todo = fill.copy()
    for s in (1.0, 2.0, 4.0, 8.0):
        if not todo.any():
            break
        num = gaussian_filter(np.where(ok, out, 0.0), s)
        den = gaussian_filter(ok.astype(float), s)
        got = todo & (den > 0.05)
        out[got] = num[got] / den[got]
        ok |= got
        todo &= ~got
    return out, fill


def stack(imgs, sigs=None, k=3.0):
    """Per-pixel mean after dropping values more than k noise sigmas from the median (a star that crosses one frame of
    a comet-centred stack). Plain median when the frames' noise is not given."""
    a = np.stack(imgs)
    with np.errstate(all="ignore"):
        med = np.nanmedian(a, 0)
        if sigs is None or len(imgs) < 3:
            return med if len(imgs) >= 3 else np.nanmean(a, 0)
        s = np.asarray(sigs, float)[:, None, None]
        keep = np.abs(a - med) <= k * s
        return np.where(keep.any(0), np.nansum(np.where(keep, a, 0), 0) / keep.sum(0), med)


def to_mjy(sum_mjy_sr):
    """Sum over grid pixels of MJy/sr -> mJy."""
    return sum_mjy_sr * PIX_SR * 1e9


def colour(img, lo, hi, cmap="inferno", gamma=1.0):
    import matplotlib
    from PIL import Image
    t = np.clip((img - lo) / (hi - lo), 0, 1) ** gamma
    rgb = (matplotlib.colormaps[cmap](np.where(np.isfinite(t), t, 0))[..., :3] * 255).round().astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def diverging(img, lim):
    """Excess map: black at zero, amber for positive, blue for negative (the site's difference-frame colours)."""
    from PIL import Image
    t = np.clip(np.where(np.isfinite(img), img, 0) / lim, -1, 1)
    a = np.abs(t) ** 0.8
    pos = np.stack([14 + 241 * a, 16 + 170 * a, 24 + 30 * a], -1)
    neg = np.stack([14 + 40 * a, 16 + 120 * a, 24 + 230 * a], -1)
    rgb = np.where((t >= 0)[..., None], pos, neg).round().astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def smooth(img, s=1.0):
    from scipy.ndimage import gaussian_filter
    ok = np.isfinite(img)
    num = gaussian_filter(np.where(ok, img, 0.0), s)
    den = gaussian_filter(ok.astype(float), s)
    with np.errstate(all="ignore"):
        return np.where(den > 0.3, num / den, np.nan)


def empty_apertures(img, r, n_ang=16, rings=(26, 34)):
    """Standard deviation of aperture sums (mJy) at n_ang x len(rings) empty places around the comet, each with its own
    local background annulus: the noise of an aperture measurement on that map, star residuals included."""
    c = (img.shape[0] - 1) / 2
    xx, yy, _ = _grid(img.shape[0])
    vals = []
    for ang in np.linspace(0, 2 * np.pi, n_ang, endpoint=False):
        for rr in rings:
            d = np.hypot(xx - (c + rr * np.cos(ang)), yy - (c + rr * np.sin(ang)))
            m, bm = d <= r, (d >= r + 2) & (d <= r + 6)
            if np.isfinite(img[m]).mean() > 0.9 and np.isfinite(img[bm]).sum() > 20:
                vals.append(to_mjy(np.nansum(img[m] - np.nanmedian(img[bm]))))
    return float(np.std(vals)) if len(vals) > 8 else float("nan")


def band_integral(lam, mjy, err, band=(4.15, 4.37), cont=((3.90, 4.15), (4.37, 4.60)), n_mc=2000, seed=1):
    """Integrated CO2 band flux (W m^-2) from single exposures: the excess over a straight continuum (fitted to the
    exposures in the `cont` ranges) of the exposures inside `band`, as F_lambda, integrated over wavelength (trapezoid,
    zero at the band edges). Each exposure samples the band through its own ~0.1 um wide filter, and the integral of
    the filtered profile equals the band's flux. Error: Monte Carlo over the points' errors, with the continuum points'
    scatter about the line added to theirs. Returns (flux, err, continuum [slope, intercept], n_band, n_cont)."""
    lam, mjy, err = (np.asarray(v, float) for v in (lam, mjy, err))
    ok = np.isfinite(lam) & np.isfinite(mjy) & np.isfinite(err)
    lam, mjy, err = lam[ok], mjy[ok], err[ok]
    ic = np.zeros(lam.size, bool)
    for a, b in cont:
        ic |= (lam >= a) & (lam <= b)
    ib = (lam > band[0]) & (lam < band[1])
    if ic.sum() < 3 or ib.sum() < 2:
        return float("nan"), float("nan"), None, int(ib.sum()), int(ic.sum())
    keep = ic.copy()
    for _ in range(3):                               # drop continuum points 3 sigma off the line (a star in the aperture)
        coef = np.polyfit(lam[keep], mjy[keep], 1)
        res = mjy - np.polyval(coef, lam)
        sc = 1.4826 * np.median(np.abs(res[keep])) + 1e-9
        keep = ic & (np.abs(res) <= 3 * np.hypot(sc, err))
    coef = np.polyfit(lam[keep], mjy[keep], 1)
    scat = float(np.std(mjy[keep] - np.polyval(coef, lam[keep])))
    o = np.argsort(lam[ib])
    lb, fb, eb = lam[ib][o], mjy[ib][o], err[ib][o]
    lc, fcont, ec = lam[keep], mjy[keep], np.hypot(err[keep], scat)

    def integral(fb_, cf):
        exc = fb_ - np.polyval(cf, lb)
        flam = exc * 1e-29 * C_UM_S / lb ** 2           # mJy -> W m^-2 um^-1
        x = np.r_[band[0], lb, band[1]]
        y = np.r_[0.0, flam, 0.0]
        return float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2))
    F = integral(fb, coef)
    # Monte Carlo: the draws keep the original order (band, then continuum, per trial) so the numbers are unchanged;
    # the continuum fits and the integrals are then done for all trials at once
    rng = np.random.default_rng(seed)
    db, dc = np.empty((n_mc, lb.size)), np.empty((n_mc, lc.size))
    for t in range(n_mc):
        db[t] = rng.normal(0, eb)
        dc[t] = rng.normal(0, ec)
    cf = np.polyfit(lc, (fcont + dc).T, 1)                                  # (2, n_mc)
    y = np.zeros((n_mc, lb.size + 2))
    y[:, 1:-1] = (fb + db - (cf[0][:, None] * lb + cf[1][:, None])) * 1e-29 * C_UM_S / lb ** 2
    dx = np.diff(np.r_[band[0], lb, band[1]])
    mc = np.sum(dx * (y[:, 1:] + y[:, :-1]) / 2, axis=1)
    return F, float(np.std(mc)), [float(coef[0]), float(coef[1])], int(ib.sum()), int(keep.sum())


def co2_epoch(fr, rng, n_boot=400):
    """CO2 band against the continuum on either side, from the exposures whose wavelength at the comet is in each
    range. Returns (summary dict, images dict) or (None, None) when a range has no exposure."""
    from astropy.time import Time
    sel = {k: [f for f in fr if band_of(f["lam"]) == k] for k in ("co2", "blue", "red")}
    if any(len(v) == 0 for v in sel.values()):
        return {"n": {k: len(v) for k, v in sel.items()}, "measured": False}, None
    lam_b = float(np.mean([f["lam"] for f in sel["blue"]]))
    lam_r = float(np.mean([f["lam"] for f in sel["red"]]))
    lam_c = float(np.mean([f["lam"] for f in sel["co2"]]))
    # stacks use only measured pixels (filled-in ones are left out)
    S = {k: stack([f["raw"] for f in v], [f["sig"] for f in v]) for k, v in sel.items()}
    cont = interp_continuum(S["blue"], lam_b, S["red"], lam_r, lam_c)
    exc = S["co2"] - cont

    radii = (2, 3, R_AP, 6)

    def ap(img, r):
        return to_mjy(aperture_flux(img, None, r, R_IN, R_OUT)[0])
    F = {r: {k: ap(img, r) for k, img in (*S.items(), ("cont", cont), ("excess", exc))} for r in radii}
    # uncertainty 1: rebuild the three stacks from exposures drawn with replacement
    boot = {r: [] for r in radii}
    for _ in range(n_boot):
        Sb = {}
        for k, v in sel.items():
            jj = rng.integers(0, len(v), len(v))
            Sb[k] = stack([v[j]["raw"] for j in jj], [v[j]["sig"] for j in jj])
        eb = Sb["co2"] - interp_continuum(Sb["blue"], lam_b, Sb["red"], lam_r, lam_c)
        for r in radii:
            boot[r].append(ap(eb, r))
    # uncertainty 2: the same aperture and annulus at 32 empty places of each map (pixel noise, star residuals,
    # background structure): the noise of the measurement
    empty = {r: {k: empty_apertures(img, r) for k, img in (("co2", S["co2"]), ("cont", cont), ("excess", exc))} for r in radii}
    by_r = []
    for r in radii:
        bt = np.array(boot[r]); bt = bt[np.isfinite(bt)]
        e_boot = float(np.std(bt)) if bt.size > 10 else float("nan")
        e_noise = empty[r]["excess"]
        by_r.append({"r_arcsec": round(r * PIX, 1), "excess_mjy": round(F[r]["excess"], 3),
                     "err_noise_mjy": round(e_noise, 3), "err_exposures_mjy": round(e_boot, 3),
                     "snr_noise": round(F[r]["excess"] / e_noise, 1) if e_noise > 0 else None,
                     "flux_mjy": {k: round(float(v), 3) for k, v in F[r].items()},
                     "cont_noise_mjy": round(empty[r]["cont"], 3)})
    head = next(x for x in by_r if x["r_arcsec"] == round(R_AP * PIX, 1))
    fc = F[R_AP]
    c_lim = 3 * head["cont_noise_mjy"]
    out = {"measured": True, "n": {k: len(v) for k, v in sel.items()},
           "lam": {"co2": round(lam_c, 3), "blue": round(lam_b, 3), "red": round(lam_r, 3)},
           "lam_each": {k: [round(f["lam"], 3) for f in v] for k, v in sel.items()},
           "dates": {k: sorted({Time(f["mjd"], format="mjd").isot[:10] for f in v}) for k, v in sel.items()},
           "flux_mjy": {k: round(float(v), 3) for k, v in fc.items()},
           # the excess, its noise (empty apertures) and how much it changes with the choice of exposures (bootstrap):
           # the band exposures sample the CO2 band at different wavelengths, so the second is much the larger
           "excess_mjy": head["excess_mjy"], "err_noise_mjy": head["err_noise_mjy"], "err_exposures_mjy": head["err_exposures_mjy"],
           "snr_noise": head["snr_noise"], "cont_noise_mjy": head["cont_noise_mjy"],
           # band over continuum when the continuum is measured (3 noise sigma), else a lower limit
           "ratio": round(fc["co2"] / fc["cont"], 1) if fc["cont"] > c_lim else None,
           "ratio_min": round(fc["co2"] / c_lim, 0) if fc["cont"] <= c_lim and c_lim > 0 else None,
           "aperture_arcsec": round(R_AP * PIX, 1), "annulus_arcsec": [round(R_IN * PIX, 1), round(R_OUT * PIX, 1)],
           "by_aperture": by_r}
    # radial profiles (azimuthal mean, MJy/sr) of the band, the continuum and the excess, for "how extended"
    r = _grid(GRID)[2]
    profs = {k: _profile(img, r) for k, img in (("co2", S["co2"]), ("cont", cont), ("excess", exc))}
    out["profile"] = [{"r_arcsec": round(r0 * PIX, 1), **{k: round(v[j], 5) for k, v in profs.items()}}
                      for j, r0 in enumerate(PROFILE_RADII)]
    return out, {"blue": S["blue"], "co2": S["co2"], "red": S["red"], "cont": cont, "excess": exc}


def build(matched):
    from astropy.time import Time
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    frames = []
    with ThreadPoolExecutor(NTHREADS) as ex:
        for f in ex.map(to_grid, matched):
            if f is not None:
                frames.append(f)
    frames.sort(key=lambda f: (f["mjd"], f["det"]))
    print(f"{len(frames)} frames on the comet grid")
    rng = np.random.default_rng(42)
    res = {"n_table": None, "n_matched": len(matched), "n_frames": len(frames), "grid": GRID, "pix_arcsec": PIX,
           "epochs": {}}
    half = GRID // 2
    c = (GRID - 1) / 2
    xx, yy, rr = _grid(GRID)
    bg_far = radial_masks(GRID, 0, R_BG, GRID)[1]
    ap_mask = radial_masks(GRID, R_AP, R_IN, R_OUT)[0]
    for ep in ("aug", "dec"):
        fr = [f for f in frames if f["epoch"] == ep]
        if not fr:
            continue
        # movie: every frame in time order, one tile each, stretched by its own noise
        tiles = [stretch_snr(f["img"][::-1], f["sig"]) for f in fr]          # row 0 = north (top)
        cols = MOVIE_COLS
        sprite(tiles, cols).save(OUT / f"movie_{ep}.webp", quality=82, method=6)
        meta = [{"t": round(f["mjd"], 5), "iso": Time(f["mjd"], format="mjd").isot[:16].replace("T", " "), "det": f["det"],
                 "lam": round(f["lam"], 3), "band": band_of(f["lam"]), "obs": f["obs_id"], "rel": f["release"],
                 "cover": round(float(np.isfinite(f["img"]).mean()), 2)} for f in fr]
        # deep pictures: median of noise-normalised frames, short (D1-D3) and long (D4-D6) wavelengths
        deep = {}
        for nm, dets in (("short", (1, 2, 3)), ("long", (4, 5, 6))):
            sub = [f for f in fr if f["det"] in dets]
            if len(sub) >= 3:
                d = stack([f["raw"] / f["sig"] for f in sub])
                deep[nm] = {"n": len(sub), "lam": [round(min(f["lam"] for f in sub), 2), round(max(f["lam"] for f in sub), 2)]}
                s_d = 1.4826 * np.nanmedian(np.abs(d[bg_far]))
                pic = stretch_snr(smooth(d, 0.6)[::-1], s_d, lo=-2, hi=60, soft=2.5)
                Image.fromarray(pic, "L").save(OUT / f"deep_{ep}_{nm}.webp", lossless=True)
                # how far from the grid centre is the light's centroid (checks the predicted positions)
                m = (rr <= 3) & np.isfinite(d)
                w = np.where(m, np.clip(np.nan_to_num(d), 0, None), 0.0)
                if w.sum() > 0:
                    deep[nm]["centroid_offset_arcsec"] = [round(float((w * (xx - c)).sum() / w.sum() * PIX), 1),
                                                          round(float((w * (yy - c)).sum() / w.sum() * PIX), 1)]
                peak = d[half - 1:half + 2, half - 1:half + 2]
                deep[nm]["peak_snr"] = round(float(np.nanmean(peak) / s_d), 1)
                # azimuthal profile (relative to the centre), same rings as the CO2 profile
                pr = _profile(d, rr)
                deep[nm]["profile"] = [round(v / pr[0], 4) for v in pr]
        # rough spectrum: large-aperture brightness of every frame
        sed = []
        n_filled = 0
        for j, f in enumerate(fr):
            if f["filled"][ap_mask].mean() > 0.2:         # too much of the aperture was filled in from neighbours
                n_filled += 1
                continue
            fl, er, cov = aperture_flux(f["img"], f["var"], R_AP, R_IN, R_OUT)
            if np.isfinite(fl):
                sed.append({"i": j, "lam": round(f["lam"], 3), "det": f["det"], "mjy": round(to_mjy(fl), 3), "err": round(to_mjy(er), 3)})
        co2, imgs = co2_epoch(fr, rng)
        F, eF, coef, nb, nc = band_integral([x["lam"] for x in sed], [x["mjy"] for x in sed], [x["err"] for x in sed])
        co2["line"] = {"flux_w_m2": float(f"{F:.3g}") if np.isfinite(F) else None, "err_w_m2": float(f"{eF:.2g}") if np.isfinite(eF) else None,
                       "snr": round(F / eF, 1) if eF > 0 else None, "n_band": nb, "n_cont": nc,
                       "cont_mjy_at_4p26": round(float(np.polyval(coef, CO2_LAM)), 2) if coef else None,
                       "cont_coef": [round(v, 4) for v in coef] if coef else None,
                       "peak": max(([x["lam"], x["mjy"]] for x in sed if 4.15 < x["lam"] < 4.37), key=lambda v: v[1], default=None)}
        if imgs:
            lim_hi = np.nanpercentile(np.r_[imgs["co2"][half - 6:half + 7, half - 6:half + 7].ravel()], 99.5)
            lo = -0.005 * lim_hi
            # one scale for the band and both continua, so the eye compares like with like
            for k in ("blue", "co2", "red", "cont"):
                colour(smooth(imgs[k], 0.7)[::-1], lo, lim_hi, gamma=0.5).save(OUT / f"co2_{ep}_{k}.webp", lossless=True)
            diverging(smooth(imgs["excess"], 0.7)[::-1], lim_hi * 0.6).save(OUT / f"co2_{ep}_excess.webp", lossless=True)
            co2["scale_mjy_sr"] = [round(float(lo), 4), round(float(lim_hi), 4)]
        res["epochs"][ep] = {"n": len(fr), "frames": meta, "movie": {"url": f"/data/comet/movie_{ep}.webp", "cols": cols, "tile": GRID},
                             "deep": deep, "sed": sed, "sed_skipped_filled": n_filled, "co2": co2,
                             "mjd": [round(fr[0]["mjd"], 3), round(fr[-1]["mjd"], 3)],
                             "noise_mjy_sr_median": round(float(np.median([f["sig"] for f in fr])), 4)}
        print(ep, len(fr), "frames; CO2:", {k: co2.get(k) for k in ("n", "excess_mjy", "err_noise_mjy", "err_exposures_mjy", "ratio", "ratio_min")},
              "band flux:", co2.get("line"), "; deep stacks:", {k: (v["n"], v.get("centroid_offset_arcsec")) for k, v in deep.items()})
    res.update(sky_and_orbit(frames))
    tab = CACHE / TABLE_NAME
    res["n_table"] = len(read_obs_table(tab)) if tab.exists() else None
    res["built"] = Time.now().isot[:16]
    write_json(OUT / "comet.json", clean(res), compact=True, allow_nan=False)
    write_validation(res)
    return res


G_CO2_1AU = 2.86e-3          # CO2 nu3 fluorescence efficiency at 1 au (photons s^-1 molecule^-1), Crovisier & Encrenaz 1983
E_CO2 = 6.62607015e-34 * 2.99792458e8 / 4.26e-6


def rough_q_co2(flux_w_m2, r_au, delta_au, rho_arcsec):
    """Order-of-magnitude CO2 production rate (molecules/s) from the band flux in a circular aperture: molecules in the
    aperture N = 4 pi Delta^2 F / (g E), and for a coma expanding at v = 0.85 r^-0.5 km/s with no photodissociation
    inside the aperture, N = Q pi rho / (2 v). Not the team's method (no Haser model, no opacity, no aperture correction
    for the background ring): a check that the measured flux is of a sensible size, good to a factor of about two."""
    n = 4 * np.pi * (delta_au * AU_M) ** 2 * flux_w_m2 / (G_CO2_1AU / r_au ** 2 * E_CO2)
    rho = rho_arcsec / ARCSEC_PER_RAD * delta_au * AU_M
    v = 850.0 / np.sqrt(r_au)
    return 2 * v * n / (np.pi * rho)


def write_validation(res):
    ep = res["epochs"]
    out = {"what": "3I/ATLAS in SPHEREx DR1 (scripts/comet_build.py)", "n_table_rows": res.get("n_table"),
           "n_matched_current_release": res["n_matched"], "n_frames_used": res["n_frames"],
           "position_check": {k: {nm: v.get("centroid_offset_arcsec") for nm, v in ep[k]["deep"].items()} for k in ep},
           "position_check_note": "offset (east, north; arcsec) of the light's centroid within 18 arcsec of IRSA's predicted position in the comet-centred stacks",
           "co2": {}}
    for k, e in ep.items():
        c = e["co2"]
        if not c.get("measured"):
            out["co2"][k] = {"measured": False, "n": c.get("n")}
            continue
        f = res["facts"]["epochs"][k]
        line = c["line"]
        q = rough_q_co2(line["flux_w_m2"], f["r_au"], f["delta_au"], c["aperture_arcsec"]) if line.get("flux_w_m2") else None
        out["co2"][k] = {"n_exposures": c["n"], "aperture_arcsec": c["aperture_arcsec"], "annulus_arcsec": c["annulus_arcsec"],
                         "stack_excess_mjy": c["excess_mjy"], "noise_mjy": c["err_noise_mjy"], "exposure_choice_spread_mjy": c["err_exposures_mjy"],
                         "snr_vs_noise": c["snr_noise"], "band_over_continuum": c["ratio"], "band_over_continuum_min_3sigma": c["ratio_min"],
                         "band_flux_w_m2": line["flux_w_m2"], "band_flux_err_w_m2": line["err_w_m2"], "band_flux_snr": line["snr"],
                         "rough_q_co2_per_s": float(f"{q:.2g}") if q else None}
    out["notes"] = ["The comet is extended at SPHEREx's resolution; IRSA advises against point-source spectrophotometry for it.",
                    "Band-flux errors are the noise only (Monte Carlo over per-exposure errors); calibration and the coarse "
                    "sampling of the band (one wavelength per exposure, August exposures spread over two weeks) are not included.",
                    "rough_q_co2_per_s is an order-of-magnitude check (simple 1/rho coma, v = 0.85 r^-0.5 km/s, g = 2.86e-3 / r^2), not a result."]
    write_json(VALIDATION / "comet.json", clean(out), indent=1, allow_nan=False)


def clean(o):
    """NaN and infinities -> None, so the file is valid JSON."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def isoday(s):
    """'2025-Oct-29' -> '2025-10-29'"""
    from datetime import datetime
    return datetime.strptime(s[:11], "%Y-%b-%d").strftime("%Y-%m-%d")


MU_SUN = 2.9591220828559115e-04       # au^3 / d^2


def v_infinity_kms(vec):
    """Speed far from the Sun (km/s) from consecutive heliocentric positions: v_inf^2 = v^2 - 2 mu / r."""
    t = np.array([p["jd"] for p in vec], float)
    xyz = np.array([[p["x"], p["y"], p["z"]] for p in vec], float)
    v2 = np.sum((np.diff(xyz, axis=0) / np.diff(t)[:, None]) ** 2, axis=1)
    r = np.sqrt(np.sum(((xyz[:-1] + xyz[1:]) / 2) ** 2, axis=1))
    return float(np.median(np.sqrt(np.maximum(0.0, v2 - 2 * MU_SUN / r)) * AU_KM / 86400))


def galactic_plane(ra_lim, dec_lim, step=0.5):
    """The Milky Way's mid-plane (b = 0) inside an RA/Dec box, as [ra, dec] runs."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    l = np.arange(0, 360, step)
    c = SkyCoord(l=l * u.deg, b=np.zeros_like(l) * u.deg, frame="galactic").icrs
    ra, dec = c.ra.deg, c.dec.deg
    ok = (ra >= ra_lim[0]) & (ra <= ra_lim[1]) & (dec >= dec_lim[0]) & (dec <= dec_lim[1])
    return sorted([round(float(a), 2), round(float(d), 2)] for a, d in zip(ra[ok], dec[ok]))


def sky_and_orbit(frames):
    from astropy.time import Time
    eph = horizons(*EPH_SPAN)
    path = [{"d": e["date"][:11], "ra": round(e["ra"], 3), "dec": round(e["dec"], 3), "r": round(e["r_au"], 3),
             "delta": round(e["delta_au"], 3), "T": e["T_mag"]} for e in eph]
    peri = min(eph, key=lambda e: e["r_au"])
    obs = [{"ra": round(f["ra"], 3), "dec": round(f["dec"], 3), "t": round(f["mjd"], 4), "ep": f["epoch"]} for f in frames]
    ras, decs = [e["ra"] for e in eph], [e["dec"] for e in eph]
    gal = galactic_plane((min(ras) - 15, max(ras) + 15), (min(decs) - 15, max(decs) + 15))

    def at(mjd):
        iso = Time(mjd, format="mjd").isot[:10]
        d = Time(iso).strftime("%Y-%b-%d")
        return next((e for e in eph if e["date"].startswith(d)), None)
    epochs = {}
    for ep in ("aug", "dec"):
        t = [f["mjd"] for f in frames if f["epoch"] == ep]
        if t:
            e = at(float(np.median(t)))
            epochs[ep] = {"first": Time(min(t), format="mjd").isot[:10], "last": Time(max(t), format="mjd").isot[:10],
                          "r_au": round(e["r_au"], 2), "delta_au": round(e["delta_au"], 2), "T_mag": e["T_mag"],
                          "phase_deg": round(e["phase"], 1), "elong_deg": round(e["elong"], 1)}
    ne = next((e for e in eph if e["date"].startswith("2025-Dec-02")), None)
    # top view of the inner Solar System: the comet, Earth (where SPHEREx is), Mars and Jupiter
    vec = {k: horizons_vectors(c, *VEC_SPAN) for k, c in BODIES}
    orbit = {k: [[round(p["x"], 3), round(p["y"], 3), p["date"]] for p in v] for k, v in vec.items()}

    def pos(v, mjd):
        jd = mjd + 2400000.5
        t = np.array([p["jd"] for p in v])
        return [round(float(np.interp(jd, t, [p[k] for p in v])), 3) for k in ("x", "y")]
    peri_mjd = Time(isoday(peri["date"])).mjd
    orbit["marks"] = {ep: {"comet": pos(vec["comet"], m), "earth": pos(vec["earth"], m), "mjd": round(m, 2)}
                      for ep, m in ((ep, float(np.median([f["mjd"] for f in frames if f["epoch"] == ep]))) for ep in ("aug", "dec"))
                      if any(f["epoch"] == ep for f in frames)}
    orbit["marks"]["peri"] = {"comet": pos(vec["comet"], peri_mjd), "mjd": round(peri_mjd, 2)}
    return {"path": path, "obs": obs, "galactic_plane": gal, "facts": {
        "perihelion": {"date": peri["date"][:11], "r_au": round(peri["r_au"], 2)},
        "v_inf_kms": round(v_infinity_kms(vec["comet"]), 1),
        "closest_earth": (lambda e: {"date": e["date"][:11], "delta_au": round(e["delta_au"], 2)})(min(eph, key=lambda e: e["delta_au"])),
        "epochs": epochs, "neossat_day": {"date": "2025-12-02", "ra": ne["ra"], "dec": ne["dec"], "r_au": round(ne["r_au"], 2),
                                          "delta_au": round(ne["delta_au"], 2), "T_mag": ne["T_mag"]} if ne else None},
        "orbit": orbit}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "match", "fetch", "horizons", "build"])
    ap.add_argument("--table", default=str(CACHE / TABLE_NAME))
    a = ap.parse_args()
    tab = Path(a.table)
    if not tab.exists():
        from sxlib import archive
        CACHE.mkdir(parents=True, exist_ok=True)
        tab.write_bytes(archive._get(TABLE_URL, {}, timeout=120).content)
    rows = read_obs_table(tab)
    print(f"{len(rows)} rows in IRSA's table")
    matched = stage_match(rows)
    if a.stage in ("all", "fetch"):
        stage_fetch(matched)
    if a.stage in ("all", "horizons"):
        horizons(*EPH_SPAN)
        for _, c in BODIES:
            horizons_vectors(c, *VEC_SPAN)
    if a.stage in ("all", "build"):
        build(matched)


if __name__ == "__main__":
    main()
