"""NEOSSat (Canadian Space Agency) images: CADC search, download, reading, preprocessing and astrometric
calibration against Gaia DR3.

NEOSSat is a 15 cm optical space telescope (400-900 nm, ~3"/px, 1024x1024 science CCD) in low Earth orbit.
Its images are archived at the Canadian Astronomy Data Centre (CADC) and mirrored on the CSA open-data site.

  search(ra, dec)          frames whose footprint contains a position (CADC ObsCore TAP, ~30 s-2 min, disk-cached)
  download(row)            the FITS file (CADC raven -> minoc redirect), cached under cache/neossat/files/
  read(path)               science pixels (float32), header, and the header WCS when there is one
  preprocess(...)          the CSA tutorial's overscan (bias) correction, then dark and flat when given
  detect(img)              stars: background-subtracted, smoothed local maxima, windowed centroids
  solve(img, hdr, ...)     a TAN WCS fitted to Gaia DR3 stars: pattern (triangle) match from the approximate
                           pointing, then iterative least squares; returns the WCS and its residuals

Data licence: "Contains data from the Canadian Space Agency's NEOSSat mission, Open Government Licence - Canada",
archive: Canadian Astronomy Data Centre (CADC).
"""
import csv
import hashlib
import io
import math
import os
import threading
import time
import warnings
from pathlib import Path

import numpy as np

CADC_TAP = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus/sync"
DATALINK = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/caom2ops/datalink"
RAVEN = "https://cadc-west-01.canfar.net/raven/files/cadc:NEOSSAT/"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
VERIFY = os.environ.get("SX_INSECURE") != "1"
ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("SX_CACHE", ROOT / "cache")) / "neossat"
UA = {"User-Agent": "sx-research-client/1.0"}
PIX_ARCSEC = 3.0                     # nominal unbinned pixel scale
CREDIT_EN = ("Contains data from the Canadian Space Agency's NEOSSat mission, Open Government Licence – Canada. "
             "Archive: Canadian Astronomy Data Centre (CADC).")
CREDIT_ZH = "含加拿大太空總署 NEOSSat 任務資料（加拿大開放政府授權）。資料庫：加拿大天文資料中心（CADC）。"

FLOAT_COLS = {"s_ra", "s_dec", "t_min", "t_max", "t_exptime", "s_fov", "calib_level", "ra", "dec",
              "phot_g_mean_mag", "pmra", "pmdec", "parallax", "bp_rp", "ref_epoch"}
GAIA_EPOCH = 2016.0
FWHM_TO_SIGMA = 1 / 2.355

# requests and astropy.wcs are imported on first use: the web server imports this module at start-up
_local = threading.local()


def _http():
    """(requests module, a keep-alive session for this thread)."""
    import requests
    s = getattr(_local, "session", None)
    if s is None:
        if not VERIFY:
            requests.packages.urllib3.disable_warnings()
        s = _local.session = requests.Session()
        s.headers.update(UA)
    return requests, s


def _WCS(*a, **kw):
    """astropy.wcs.WCS, with its FITSFixedWarning chatter about NEOSSat headers silenced."""
    from astropy.wcs import WCS, FITSFixedWarning
    warnings.filterwarnings("ignore", category=FITSFixedWarning)
    return WCS(*a, **kw)


# ----------------------------------------------------------------------------------------------- CADC access

def _cache_path(kind, key, ext):
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    p = CACHE / kind / f"{h}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write(p, data):
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data) if isinstance(data, bytes) else tmp.write_text(data)
    os.replace(tmp, p)


def tap(adql, url=CADC_TAP, timeout=600, max_age_s=None, tries=3):
    """Run an ADQL query (sync, CSV) and return a list of dicts; the CSV is cached on disk by query text."""
    p = _cache_path("tap", url + "\n" + adql, "csv")
    if p.exists() and (max_age_s is None or time.time() - p.stat().st_mtime < max_age_s):
        return parse_csv(p.read_text())
    requests, session = _http()
    last = None
    for k in range(tries):
        try:
            r = session.post(url, data={"LANG": "ADQL", "FORMAT": "csv", "QUERY": adql, "REQUEST": "doQuery"},
                             timeout=timeout, verify=VERIFY)
            if r.status_code >= 500:
                raise requests.HTTPError(str(r.status_code))
            r.raise_for_status()
            txt = r.text
            if txt.lstrip().startswith("<"):            # a VOTable error document
                raise RuntimeError(txt[:300])
            _atomic_write(p, txt)
            return parse_csv(txt)
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last = e
            time.sleep(3 * (k + 1))
    raise last


def parse_csv(txt):
    rows = list(csv.DictReader(io.StringIO(txt)))
    if not rows:
        return rows
    num = [k for k in rows[0] if k in FLOAT_COLS]
    for r in rows:
        for k in num:
            v = r[k]
            try:
                r[k] = float(v) if v not in ("", None) else None
            except ValueError:
                pass
    return rows


OBS_COLS = "obs_publisher_did, obs_id, target_name, s_ra, s_dec, s_region, t_min, t_exptime, calib_level, dataproduct_type"


def search_adql(ra, dec, radius=None, mjd0=None, mjd1=None, calib=None, target=None):
    """ObsCore query text: frames whose footprint contains (ra, dec) or whose centre lies within `radius` deg."""
    w = ["obs_collection = 'NEOSSAT'"]
    if radius is None:
        w.append(f"CONTAINS(POINT('ICRS', {ra:.5f}, {dec:.5f}), s_region) = 1")
    else:
        w.append(f"CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', {ra:.5f}, {dec:.5f}, {radius:.4f})) = 1")
    if mjd0 is not None:
        w.append(f"t_min >= {mjd0:.5f}")
    if mjd1 is not None:
        w.append(f"t_min <= {mjd1:.5f}")
    if calib is not None:
        w.append(f"calib_level = {int(calib)}")
    if target:
        w.append(f"target_name = '{target}'")
    return f"SELECT {OBS_COLS} FROM ivoa.ObsCore WHERE " + " AND ".join(w)


def search(ra, dec, radius=None, mjd0=None, mjd1=None, calib=None, target=None, timeout=600, max_age_s=None):
    rows = tap(search_adql(ra, dec, radius, mjd0, mjd1, calib, target), timeout=timeout, max_age_s=max_age_s)
    for r in rows:
        r["product"] = r["obs_publisher_did"].rsplit("/", 1)[-1]
    return sorted(rows, key=lambda r: (r["t_min"] or 0, r["product"]))


def product_of(row):
    return row.get("product") or row["obs_publisher_did"].rsplit("/", 1)[-1]


def file_name(obs_id, product):
    """CADC file name: raw frames are NEOS_SCI_<id>.fits, processed ones NEOS_SCI_<id>_<product>.fits."""
    return f"NEOS_SCI_{obs_id}.fits" if product == "raw" else f"NEOS_SCI_{obs_id}_{product}.fits"


def file_url(obs_id, product):
    return RAVEN + file_name(obs_id, product)


def thumb_url(obs_id, product, size=256):
    """CADC's own preview PNG (listed as #thumbnail / #preview in the datalink document)."""
    return RAVEN + (f"{obs_id}_{product}_prev_{size}.png" if size else f"{obs_id}_{product}_prev.png")


def download(row_or_url, dest=None, tries=4):
    """Fetch one FITS file (following the raven -> minoc redirect) into cache/neossat/files/; returns the path."""
    if isinstance(row_or_url, dict):
        url = file_url(row_or_url["obs_id"], product_of(row_or_url))
    else:
        url = row_or_url
    name = url.rsplit("/", 1)[-1].split("?")[0]
    dest = Path(dest or CACHE / "files") / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    requests, session = _http()
    last = None
    for k in range(tries):
        try:
            r = session.get(url, timeout=300, verify=VERIFY, allow_redirects=True)
            r.raise_for_status()
            if not r.content.startswith(b"SIMPLE"):
                raise RuntimeError(f"not a FITS file: {url}")
            _atomic_write(dest, r.content)
            return dest
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError, RuntimeError) as e:
            last = e
            time.sleep(2 * (k + 1))
    raise last


# ----------------------------------------------------------------------------------------------- reading, preprocessing

def _sec(s):
    """'[x0:x1,y0:y1]' (1-based, inclusive) -> numpy slices."""
    s = (s or "").strip().strip("[]")
    if not s or ":" not in s:
        return None
    xs, ys = s.split(",")
    x0, x1 = (int(v) for v in xs.split(":"))
    y0, y1 = (int(v) for v in ys.split(":"))
    return slice(y0 - 1, y1), slice(x0 - 1, x1)


def read(path):
    """(data float32, header, wcs-or-None). The WCS is only returned when the header has a celestial one."""
    from astropy.io import fits
    with fits.open(path, memmap=False) as h:
        data = h[0].data.astype(np.float32)
        hdr = h[0].header.copy()
    w = None
    if hdr.get("CTYPE1", "").startswith("RA---"):
        try:
            w = _WCS(hdr, naxis=2)
        except Exception:  # noqa: BLE001 - an unreadable header WCS is simply not used
            w = None
    return data, hdr, w


def overscan_correct(data, hdr, overscan_width=None):
    """Bias removal as in the CSA tutorial (02_Pre Processing): subtract each row's median overscan level.
    The overscan columns are taken from BIASSEC when the header gives one, else the tutorial's last 50 columns
    when OVERSCAN=1. Returns (science pixels, overscan-corrected), trimmed to DATASEC/TRIMSEC when given."""
    if not int(hdr.get("OVERSCAN", 0) or 0) and overscan_width is None:
        return data
    bias = _sec(hdr.get("BIASSEC"))
    if bias is not None and data[bias].size:
        ov = data[bias]
    else:
        w = overscan_width or 50
        ov = data[:, -w:]
    med = np.median(ov, axis=1)
    out = data - med[:, None]
    trim = _sec(hdr.get("TRIMSEC")) or _sec(hdr.get("DATASEC"))
    if trim is not None:
        out = out[trim]
    elif bias is None:
        out = out[:, : data.shape[1] - (overscan_width or 50)]
    return out


def master_dark(paths):
    """Median of overscan-corrected dark frames (the CSA tutorial's create_master_dark)."""
    frames = [overscan_correct(d, h) for d, h, _ in map(read, paths)]
    shape = min(f.shape for f in frames)
    return np.median(np.stack([f[: shape[0], : shape[1]] for f in frames]), axis=0)


def preprocess(data, hdr, dark=None, flat=None):
    """Overscan/bias, then a scaled master dark and a flat when given (the CSA tutorial's order)."""
    img = overscan_correct(data, hdr)
    if dark is not None:
        h = min(img.shape[0], dark.shape[0]); w = min(img.shape[1], dark.shape[1])
        img = img[:h, :w] - dark[:h, :w]
    if flat is not None:
        f = flat[: img.shape[0], : img.shape[1]]
        img = img / np.where(f > 0.05, f, 1.0)
    return img.astype(np.float32)


def remove_background(img, box=64):
    """Coarse background: median of each box, bilinearly interpolated, subtracted. Returns (img - bg, robust sigma)."""
    from scipy.ndimage import zoom
    ny, nx = img.shape
    gy, gx = max(1, ny // box), max(1, nx // box)
    t = img[: gy * box, : gx * box].reshape(gy, box, gx, box).swapaxes(1, 2).reshape(gy, gx, -1)
    med = np.nanmedian(t, axis=2)
    bg = zoom(med, (ny / gy, nx / gx), order=1)[:ny, :nx]
    if bg.shape != img.shape:
        bg = np.pad(bg, ((0, ny - bg.shape[0]), (0, nx - bg.shape[1])), mode="edge")
    r = img - bg
    v = r[np.isfinite(r)]
    sig = 1.4826 * np.median(np.abs(v - np.median(v))) if v.size else 1.0
    return r, float(max(sig, 1e-6))


def detect(img, nsig=6.0, fwhm=3.0, max_n=300, edge=8, max_sharp=0.3):
    """Point sources: background-subtracted, Gaussian-smoothed local maxima above nsig, centroided with a
    Gaussian-weighted window. Hot pixels and cosmic rays are dropped: their central pixel holds more than
    max_sharp of the 5x5 flux (a star with FWHM 3 px holds ~0.1). Returns an array (n, 4) of x, y (0-based
    pixels), flux, peak, brightest first."""
    from scipy.ndimage import gaussian_filter, maximum_filter
    r, sig = remove_background(img)
    s = gaussian_filter(np.nan_to_num(r), fwhm / 2.355)
    ssig = sig / (2 * math.sqrt(math.pi) * fwhm / 2.355)       # noise of the smoothed white-noise image
    peaks = (s == maximum_filter(s, size=5)) & (s > nsig * ssig)
    peaks[:edge] = peaks[-edge:] = False
    peaks[:, :edge] = peaks[:, -edge:] = False
    ys, xs = np.nonzero(peaks)
    out = []
    hw = 4
    yy, xx = np.mgrid[-hw: hw + 1, -hw: hw + 1]
    two_s2 = 2 * (fwhm / 2.355) ** 2
    for y, x in zip(ys, xs):
        cut = r[y - hw: y + hw + 1, x - hw: x + hw + 1]
        if cut.shape != yy.shape:
            continue
        pos = np.clip(cut, 0, None)
        cx, cy = float(x), float(y)
        for _ in range(4):                                     # windowed centroid (SExtractor-like)
            w = np.exp(-((xx - (cx - x)) ** 2 + (yy - (cy - y)) ** 2) / two_s2) * pos
            tot = w.sum()
            if tot <= 0:
                break
            ncx = x + float((w * xx).sum() / tot); ncy = y + float((w * yy).sum() / tot)
            if abs(ncx - cx) < 1e-3 and abs(ncy - cy) < 1e-3:
                cx, cy = ncx, ncy
                break
            cx, cy = ncx, ncy
        if abs(cx - x) > 2 or abs(cy - y) > 2:
            continue
        flux = float(pos[2:-2, 2:-2].sum())
        if flux <= 0 or r[y, x] / flux > max_sharp:
            continue
        out.append((cx, cy, flux, float(img[y, x])))
    if not out:
        return np.zeros((0, 4))
    a = np.array(out)
    a = a[np.argsort(-a[:, 2])]
    return a[:max_n]


# ----------------------------------------------------------------------------------------------- Gaia DR3

def gaia_cone(ra, dec, radius, gmax=15.0, timeout=300):
    """Gaia DR3 sources (ra, dec, G, pmra, pmdec, parallax, epoch 2016.0) within radius deg; cached on disk.
    The ESA archive TAP (disk-cached) first; when it fails, sxlib.gaia's other services (MAST)."""
    q = (f"SELECT source_id, ra, dec, phot_g_mean_mag, pmra, pmdec, parallax FROM gaiadr3.gaia_source "
         f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.4f}, {dec:.4f}, {radius:.4f})) = 1 "
         f"AND phot_g_mean_mag < {gmax:.2f}")
    try:
        return tap(q, url=GAIA_TAP, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - ESA down: the same query through MAST
        from . import gaia
        try:
            rows = gaia.query(q, timeout=timeout, services=("mast",))
        except gaia.GaiaError:
            raise e from None
        p = _cache_path("tap", GAIA_TAP + "\n" + q, "csv")
        if rows:
            head = list(rows[0])
            buf = io.StringIO()
            wr = csv.writer(buf, lineterminator="\n")
            wr.writerow(head)
            wr.writerows([r[k] for k in head] for r in rows)
            _atomic_write(p, buf.getvalue())
        return parse_csv(p.read_text()) if rows else []


def gaia_at(rows, year):
    """Gaia positions moved from 2016.0 to `year` with proper motion (deg arrays ra, dec) plus G."""
    ra = np.array([r["ra"] for r in rows], float)
    dec = np.array([r["dec"] for r in rows], float)
    pmra = np.array([r["pmra"] if r["pmra"] is not None else 0.0 for r in rows], float)
    pmdec = np.array([r["pmdec"] if r["pmdec"] is not None else 0.0 for r in rows], float)
    g = np.array([r["phot_g_mean_mag"] for r in rows], float)
    dt = year - GAIA_EPOCH
    dec2 = dec + pmdec * dt / 3.6e6
    ra2 = ra + pmra * dt / 3.6e6 / np.cos(np.radians(dec))
    return ra2, dec2, g


# ----------------------------------------------------------------------------------------------- astrometric solution

def tan_project(ra, dec, ra0, dec0):
    """Gnomonic projection, standard coordinates xi, eta in degrees (xi toward +RA, i.e. east)."""
    a, d, a0, d0 = (np.radians(np.asarray(v, float)) for v in (ra, dec, ra0, dec0))
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / cosc
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return np.degrees(xi), np.degrees(eta)


def _affine(src, dst):
    """Least-squares affine dst = A @ src + b (src, dst arrays (n, 2)). Returns (A, b)."""
    M = np.hstack([src, np.ones((len(src), 1))])
    sol, *_ = np.linalg.lstsq(M, dst, rcond=None)
    return sol[:2].T, sol[2]


def match_vote(pix, sky, scale_deg, radius_px, step_deg=None, bin_px=3.0, roll_hint=None, roll_range=180.0):
    """Pattern match by voting: for every trial rotation (both parities) the detections are rotated and scaled to
    the catalogue's standard coordinates, and every detection-star pair votes for a translation; the rotation
    whose best translation collects the most votes wins. pix: (n, 2) pixel offsets from the frame centre;
    sky: (m, 2) standard coordinates xi, eta in degrees about the approximate pointing. Returns
    (A, b, n_votes, angle, parity) with xi_eta = A @ pix + b, or None."""
    from scipy.spatial import cKDTree
    if len(pix) < 3 or len(sky) < 3:
        return None
    s = sky / scale_deg                                          # catalogue in nominal pixels
    rmax = float(np.max(np.hypot(pix[:, 0], pix[:, 1]))) or 1.0
    step = step_deg or min(0.5, math.degrees(bin_px / 2 / rmax))
    if roll_hint is None:
        angles = np.arange(0, 360, step)
    else:
        angles = (roll_hint + np.arange(-roll_range, roll_range + step / 2, step)) % 360
    nb = int(2 * radius_px / bin_px) + 1
    best = None
    for parity in (1, -1):
        P = np.array([[parity, 0], [0, 1]], float)
        for ang in angles:
            c, si = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            R = np.array([[c, -si], [si, c]]) @ P
            q = pix @ R.T
            off = (s[None, :, :] - q[:, None, :]).reshape(-1, 2)
            ij = np.floor((off + radius_px) / bin_px).astype(int)
            ok = (ij >= 0).all(1) & (ij < nb).all(1)
            if not ok.any():
                continue
            # coarse bins straddle the true offset: count each pair in its bin and the three neighbours above/right
            flat = ij[ok, 0] * nb + ij[ok, 1]
            h = np.bincount(flat, minlength=nb * nb).reshape(nb, nb)
            h2 = h[:-1, :-1] + h[1:, :-1] + h[:-1, 1:] + h[1:, 1:]
            k = int(np.argmax(h2))
            v = int(h2.flat[k])
            if best is None or v > best[0]:
                i, j = divmod(k, nb - 1)
                o = np.array([(i + 1) * bin_px - radius_px, (j + 1) * bin_px - radius_px])
                best = (v, ang, parity, R, o)
    if best is None:
        return None
    v, ang, parity, R, o = best
    # refine: pairs within 2.5 bins of the voted transform, then an affine fit, then one more matching round
    tree = cKDTree(s)
    A, b = R, o
    for rr in (2.5 * bin_px, 1.5 * bin_px):
        d, j = tree.query(pix @ A.T + b, distance_upper_bound=rr)
        ok = np.isfinite(d)
        if ok.sum() < 3:
            return None
        A, b = _affine(pix[ok], s[j[ok]]) if ok.sum() >= 4 else (A, b)
    return A * scale_deg, b * scale_deg, int(ok.sum()), float(ang), int(parity)


def wcs_from_affine(A, b, ra0, dec0, shape, centre):
    """TAN WCS whose standard coordinates (deg, xi east-positive) are A @ (p - centre) + b for 0-based pixels p.
    FITS intermediate coordinates are east-positive too, so CD = A."""
    w = _WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra0, dec0]
    p0 = np.asarray(centre, float) - np.linalg.solve(A, b)       # the pixel that maps to the tangent point
    w.wcs.crpix = [p0[0] + 1, p0[1] + 1]
    w.wcs.cd = A
    w.pixel_shape = (shape[1], shape[0])
    return w


def refine_wcs(w, pix, ra, dec, rmatch_px=3.0, iters=4, sip=None):
    """Match detections to catalogue stars with the current WCS and refit a TAN (+SIP when sip>0) WCS by least
    squares. Returns (wcs, residual rms arcsec, n matched, per-star residuals arcsec (n, 2))."""
    from astropy.coordinates import SkyCoord
    from astropy.wcs.utils import fit_wcs_from_points
    from scipy.spatial import cKDTree
    import astropy.units as u
    stats = (None, 0, np.zeros((0, 2)))
    for k in range(iters):
        cx, cy = w.all_world2pix(ra, dec, 0)
        ok = np.isfinite(cx) & np.isfinite(cy)
        tree = cKDTree(np.c_[cx[ok], cy[ok]])
        idx_ok = np.nonzero(ok)[0]
        d, j = tree.query(pix, distance_upper_bound=rmatch_px)
        m = np.isfinite(d)
        if m.sum() < 6:
            break
        # one detection per star
        jj = idx_ok[j[m]]
        _, first = np.unique(jj, return_index=True)
        sel = np.nonzero(m)[0][first]
        jj = jj[first]
        sc = SkyCoord(ra[jj] * u.deg, dec[jj] * u.deg)
        w2 = fit_wcs_from_points((pix[sel, 0], pix[sel, 1]), sc, projection="TAN", sip_degree=sip)
        px, py = w2.all_world2pix(ra[jj], dec[jj], 0)
        scale = math.sqrt(abs(np.linalg.det(w2.pixel_scale_matrix))) * 3600
        res = np.c_[pix[sel, 0] - px, pix[sel, 1] - py] * scale
        r = np.hypot(res[:, 0], res[:, 1])
        clip = r < max(3 * np.median(r) * 1.48, 0.5 * scale)
        if clip.sum() >= 6 and clip.sum() < len(clip):
            w2 = fit_wcs_from_points((pix[sel[clip], 0], pix[sel[clip], 1]), sc[clip], projection="TAN", sip_degree=sip)
            px, py = w2.all_world2pix(ra[jj[clip]], dec[jj[clip]], 0)
            res = np.c_[pix[sel[clip], 0] - px, pix[sel[clip], 1] - py] * scale
        w = w2
        rms = float(np.sqrt(np.mean(np.sum(res ** 2, axis=1))))
        stats = (rms, int(len(res)), res)
        rmatch_px = max(1.5, min(rmatch_px, 4 * rms / scale))
    w.pixel_shape = w.pixel_shape
    return w, stats[0], stats[1], stats[2]


def header_pointing(hdr):
    """Approximate pointing (ra, dec deg) and roll (deg) from the header: RA/DEC (actual), else the WCS CRVAL."""
    from astropy.coordinates import Angle
    import astropy.units as u
    ra = dec = None
    for kr, kd in (("RA", "DEC"), ("OBJCTRA", "OBJCTDEC"), ("CMDRA", "CMDDEC")):
        if hdr.get(kr) and hdr.get(kd):
            try:
                ra = Angle(str(hdr[kr]).replace(" ", ":"), unit=u.hourangle).deg
                dec = Angle(str(hdr[kd]).replace(" ", ":"), unit=u.deg).deg
                break
            except Exception:
                continue
    if ra is None and "CRVAL1" in hdr:
        ra, dec = float(hdr["CRVAL1"]), float(hdr["CRVAL2"])
    roll = hdr.get("OBJCTROL", hdr.get("CMDROL"))
    return ra, dec, (float(roll) if roll is not None else None)


def frame_year(hdr):
    from astropy.time import Time
    t = Time(str(hdr.get("DATE-OBS")).strip(), format="isot", scale="utc")
    exp = float(hdr.get("EXPOSURE", hdr.get("AEXPTIME", 0)) or 0)
    tm = Time(t.mjd + exp / 2 / 86400, format="mjd", scale="utc")
    return float(tm.jyear), float(tm.mjd)


def solve(img, hdr=None, gaia_rows=None, ra0=None, dec0=None, year=None, margin_deg=0.1, exclude=(), sip=None,
          det=None, n_det=40, scale_arcsec=PIX_ARCSEC, hint=None, gmax=16.0, verbose=False):
    """Astrometric calibration of one frame against Gaia DR3 (positions moved to the frame's epoch).

    The approximate pointing comes from the header (or ra0/dec0). Detections are matched to catalogue stars by
    a rotation/parity/translation vote (match_vote), then a TAN WCS (plus SIP when sip>0) is fitted by iterative
    least squares. Stars within 20" of any (ra, dec) in `exclude` (e.g. the target being measured) are left out
    of the fit. `hint` = (angle, parity) from a previous frame narrows the rotation search to +-3 deg.
    Returns {wcs, rms_arcsec, n_match, n_det, det, year, angle, parity, residuals} or None."""
    if ra0 is None:
        ra0, dec0, _ = header_pointing(hdr)
    if year is None:
        year, _ = frame_year(hdr)
    ny, nx = img.shape
    scale = scale_arcsec / 3600
    half = 0.5 * math.hypot(nx, ny) * scale
    R = half + margin_deg
    if gaia_rows is None:
        gaia_rows = gaia_cone(ra0, dec0, R, gmax=gmax)
    gra, gdec, gg = gaia_at(gaia_rows, year)
    keep = np.isfinite(gra) & np.isfinite(gg)
    for (xra, xdec) in exclude:
        keep &= np.hypot((gra - xra) * math.cos(math.radians(xdec)), gdec - xdec) > 20 / 3600
    gra, gdec, gg = gra[keep], gdec[keep], gg[keep]
    o = np.argsort(gg)
    gra, gdec, gg = gra[o], gdec[o], gg[o]
    if det is None:
        det = detect(img)
    if len(det) < 5:
        return None
    centre = np.array([(nx - 1) / 2, (ny - 1) / 2])
    pix = det[:n_det, :2] - centre
    xi, eta = tan_project(gra, gdec, ra0, dec0)
    inside = np.hypot(xi, eta) < R
    area_ratio = math.pi * R ** 2 / (nx * ny * scale ** 2)
    m = int(min(inside.sum(), max(30, 1.5 * len(pix) * area_ratio)))
    sky = np.c_[xi, eta][inside][:m]
    rmax = float(np.max(np.hypot(pix[:, 0], pix[:, 1])))
    bin_px = 3.0 if max(nx, ny) <= 400 else 6.0
    kw = {} if hint is None else {"roll_hint": hint[0], "roll_range": 3.0}
    best = match_vote(pix, sky, scale, radius_px=R / scale + rmax, bin_px=bin_px, **kw)
    if best is None or best[2] < 5:
        return None
    A, b, n, ang, parity = best
    w = wcs_from_affine(A, b, ra0, dec0, img.shape, centre)
    w, rms, nm, res = refine_wcs(w, det[:, :2], gra, gdec, rmatch_px=2.5 * bin_px, sip=sip)
    if rms is None:
        return None
    if verbose:
        print(f"  vote {n} pairs at {ang:.1f} deg parity {parity}; fit {nm} stars, rms {rms:.2f}\"")
    return {"wcs": w, "rms_arcsec": rms, "n_match": nm, "n_det": int(len(det)), "det": det, "year": year,
            "angle": ang, "parity": parity, "residuals": res}


# ----------------------------------------------------------------------------------------------- resampling

def north_up_wcs(ra, dec, size_arcsec, pix_arcsec):
    """A north-up, east-left TAN grid centred on (ra, dec)."""
    n = int(round(size_arcsec / pix_arcsec))
    w = _WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix_arcsec / 3600, pix_arcsec / 3600]
    w.pixel_shape = (n, n)
    return w, n


def resample(img, w_in, w_out, shape_out, order=1):
    """Resample img (on w_in) onto w_out by inverse mapping with spline interpolation (fast, adequate for display
    and centroiding of well-sampled stars)."""
    from scipy.ndimage import map_coordinates
    ny, nx = shape_out
    yy, xx = np.mgrid[0:ny, 0:nx]
    ra, dec = w_out.all_pix2world(xx.ravel(), yy.ravel(), 0)
    px, py = w_in.all_world2pix(ra, dec, 0)
    out = map_coordinates(np.nan_to_num(img), [py, px], order=order, mode="constant", cval=np.nan)
    inside = (px >= 0) & (py >= 0) & (px <= img.shape[1] - 1) & (py <= img.shape[0] - 1)
    out[~inside] = np.nan
    return out.reshape(ny, nx)


def centroid(img, x0, y0, hw=6, fwhm=3.0, iters=8):
    """Gaussian-windowed centroid near (x0, y0) after a local background (annulus median) is removed. Returns
    (x, y, flux, peak).

    Everything it uses lies within 2.5 hw (the annulus) of the start or within hw of the centroid, so it works on
    a sub-image around (x0, y0) rather than the whole frame; if the centroid wanders out of that box, the whole
    frame is used, as before."""
    n0, n1 = img.shape
    b = int(math.ceil(2.5 * hw)) + hw + 2
    xi, yi = int(math.floor(x0)), int(math.floor(y0))
    xa, xb, ya, yb = max(0, xi - b), min(n1, xi + b + 1), max(0, yi - b), min(n0, yi + b + 1)
    out = _centroid_box(img, x0, y0, hw, fwhm, iters, xa, xb, ya, yb, whole=(xa, ya, xb, yb) == (0, 0, n1, n0))
    return out if out is not None else _centroid_box(img, x0, y0, hw, fwhm, iters, 0, n1, 0, n0, whole=True)


def _centroid_box(img, x0, y0, hw, fwhm, iters, xa, xb, ya, yb, whole):
    sub = img[ya:yb, xa:xb]
    yy, xx = np.mgrid[ya:yb, xa:xb]
    cx, cy = float(x0), float(y0)
    sig = fwhm / 2.355

    def inside(cx_, cy_):                        # the window |x - cx| <= hw lies within the box
        return whole or (xa <= cx_ - hw - 1 and cx_ + hw + 1 < xb and ya <= cy_ - hw - 1 and cy_ + hw + 1 < yb)

    if not inside(cx, cy):
        return None
    rr = np.hypot(xx - cx, yy - cy)
    ann = sub[(rr > hw * 1.5) & (rr < hw * 2.5) & np.isfinite(sub)]
    bg = float(np.median(ann)) if ann.size else 0.0
    r = np.nan_to_num(sub - bg)
    pos = np.clip(r, 0, None)
    for _ in range(iters):
        win = (np.abs(xx - cx) <= hw) & (np.abs(yy - cy) <= hw)
        w = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sig ** 2)) * pos * win
        tot = w.sum()
        if tot <= 0:
            break
        ncx, ncy = float((w * xx).sum() / tot), float((w * yy).sum() / tot)
        done = abs(ncx - cx) < 1e-4 and abs(ncy - cy) < 1e-4
        cx, cy = ncx, ncy
        if not inside(cx, cy):
            return None
        if done:
            break
    win = np.hypot(xx - cx, yy - cy) <= hw
    return cx, cy, float(r[win].sum()), float(np.nanmax(np.where(win, sub, np.nan)))


def coverage_summary(rows):
    """Group ObsCore rows by UT date: one entry per date with frame count, targets and exposure range, plus a
    preview thumbnail (CADC #thumbnail PNG) of a processed frame when there is one. One count per exposure:
    raw and processed versions of the same exposure are counted once."""
    by = {}
    for r in rows:
        by.setdefault(r["obs_id"], []).append(r)
    from astropy.time import Time
    timed = [(oid, rs) for oid, rs in by.items() if rs[0].get("t_min") is not None]
    dates = Time([rs[0]["t_min"] for _, rs in timed], format="mjd").isot if timed else []   # one conversion for all
    days = {}
    for (oid, rs), iso in zip(timed, dates):
        r0 = rs[0]
        date = iso[:10]
        d = days.setdefault(date, {"date": date, "n": 0, "targets": set(), "exp": [], "products": set(), "best": None})
        d["n"] += 1
        d["targets"].add((r0.get("target_name") or "").strip())
        if r0.get("t_exptime"):
            d["exp"].append(float(r0["t_exptime"]))
        prods = {product_of(r) for r in rs}
        d["products"] |= prods
        cal = [p for p in prods if p != "raw"]
        if d["best"] is None or (cal and d["best"][1] == "raw"):
            d["best"] = (oid, cal[0] if cal else "raw")
    out = []
    for date in sorted(days):
        d = days[date]
        oid, prod = d["best"]
        out.append({"date": date, "n": d["n"], "targets": sorted(t for t in d["targets"] if t)[:4],
                    "exp_s": [round(min(d["exp"]), 1), round(max(d["exp"]), 1)] if d["exp"] else None,
                    "calibrated": any(p != "raw" for p in d["products"]),
                    "thumb": thumb_url(oid, prod), "obs_id": oid, "product": prod})
    return out


def fit_gauss(img, x0, y0, hw=5, fwhm0=2.5):
    """Least-squares 2-D Gaussian (+ constant) fit in a (2hw+1)^2 box around (x0, y0); NaN pixels (e.g. a
    saturated core) are ignored. Returns (x, y, sx_err, sy_err, fwhm, amplitude) in pixels, or None."""
    from scipy.optimize import least_squares
    xi, yi = int(round(x0)), int(round(y0))
    y_lo, y_hi = max(0, yi - hw), min(img.shape[0], yi + hw + 1)
    x_lo, x_hi = max(0, xi - hw), min(img.shape[1], xi + hw + 1)
    cut = np.asarray(img[y_lo:y_hi, x_lo:x_hi], float)
    yy, xx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
    ok = np.isfinite(cut)
    if ok.sum() < 12:
        return None
    z, X, Y = cut[ok], xx[ok], yy[ok]
    bg0 = float(np.percentile(z, 20))
    amp0 = float(max(z.max() - bg0, 1e-6))
    s0 = fwhm0 / 2.355

    def model(p):
        a, x, y, s, b = p
        return a * np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2 * s * s)) + b

    try:
        r = least_squares(lambda p: model(p) - z, [amp0, x0, y0, s0, bg0],
                          bounds=([0, x0 - hw, y0 - hw, 0.3, -np.inf], [np.inf, x0 + hw, y0 + hw, 3 * hw, np.inf]))
    except Exception:  # noqa: BLE001
        return None
    a, x, y, s, b = r.x
    dof = max(1, z.size - 5)
    resid = r.fun
    try:
        cov = np.linalg.inv(r.jac.T @ r.jac) * float(resid @ resid) / dof
        ex, ey = float(np.sqrt(cov[1, 1])), float(np.sqrt(cov[2, 2]))
    except np.linalg.LinAlgError:
        ex = ey = float("nan")
    return float(x), float(y), ex, ey, float(2.355 * s), float(a)
