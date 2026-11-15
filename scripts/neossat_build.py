#!/usr/bin/env python
"""NEOSSat (Canadian Space Agency) products for the site.

  pm <target>  R10, cross-mission proper motion: the star's position in NEOSSat's optical frames (Barnard's Star
               2019, Teegarden's Star 2020), each frame calibrated against Gaia DR3 by sxlib.neossat.solve, against
               its position in SPHEREx's infrared pass stacks (2025-26), compared with Gaia DR3's prediction.
               -> web/data/neossat/<target>/{optical.webp, infrared.webp, result.json}
               -> web/data/validation/neossat.json (all targets built so far)
  comet        R4: 3I/ATLAS on 2025-12-02 (24 NEOSSat frames), stacked along its JPL Horizons motion (comet sharp)
               and on the stars, on the same north-up grid; detection test and limiting magnitude.
               -> web/data/comet/neossat.webp, neossat_stars.webp, neossat.json
  coverage     R11: CADC coverage for every analysed field and quick look -> cache/neossat/coverage/*.json
  all          everything above

  python scripts/neossat_build.py all|pm [targets]|comet|coverage|validation   (SX_INSECURE=1 behind a TLS proxy)

Downloads go to cache/neossat/files (Barnard 571 raw sub-frames ~0.25 GB, Teegarden 13 frames, 3I 24 frames).
Data: "Contains data from the Canadian Space Agency's NEOSSat mission, Open Government Licence - Canada"; archive CADC.
"""
import json
import math
import os
import sys
import time
import urllib.parse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATA, FIELDS, QUICK, VALIDATION, WEB, read_json, write_json  # noqa: E402
from sxlib import neossat as N                       # noqa: E402
from sxlib.targets import TARGETS, position_at        # noqa: E402

OUT = DATA / "neossat"
VALID = VALIDATION / "neossat.json"
COMET = DATA / "comet"
NPROC = min(8, os.cpu_count() or 1)          # frame solving is CPU-bound (one process per frame)
NTHREADS = 6                                 # parallel CADC downloads
AU_KM = 1.495978707e8

PM = {
    "barnard": {
        "name": "Barnard's Star", "name_zh": "巴納德星", "field": "barnard",
        "astro": TARGETS["barnard"],
    },
    "teegarden": {
        "name": "Teegarden's Star", "name_zh": "Teegarden 星", "field": "q043p280+16p853s15",
        # Gaia DR3 35227046884571776 (ESA Gaia archive, queried 2026-11-13)
        "astro": {"name": "Teegarden's Star", "source": "Gaia DR3 35227046884571776", "ra": 43.26964247679057,
                  "dec": 16.86437381897744, "pmra": 3429.0828268077694, "pmdec": -3805.54112273733,
                  "plx": 260.98844068047276, "epoch": 2016.0, "g": 12.26},
    },
}
PM["barnard"]["astro"] = {**PM["barnard"]["astro"], "g": 8.19}

GRID_ARCSEC, GRID_PIX = 240.0, 1.0           # blink grid: 4' across, 1"/px, north up
SAT_RAW = 62000                              # raw ADU above which the 16-bit readout is (near) saturated


def mjd_iso(m):
    from astropy.time import Time
    return Time(m, format="mjd").isot[:10]


def offs(ra, dec, ra0, dec0):
    """(east, north) arcsec of (ra, dec) about (ra0, dec0) (tangent plane)."""
    xi, eta = N.tan_project(ra, dec, ra0, dec0)
    return np.asarray(xi) * 3600, np.asarray(eta) * 3600


# --------------------------------------------------------------------------------------------- NEOSSat frames

_G = {}


def _init(gaia_rows):
    _G["rows"] = gaia_rows


def measure_frame(args):
    """Calibrate one frame against Gaia (the target itself excluded) and fit the target. Runs in a worker."""
    path, astro = args
    try:
        d, h, _ = N.read(path)
        img = N.preprocess(d, h)
        year, mjd = N.frame_year(h)
        pra, pdec = position_at(astro, mjd)
        pra, pdec = float(pra[0]), float(pdec[0])
        sol = N.solve(img, h, gaia_rows=_G["rows"], exclude=[(pra, pdec)])
        if sol is None:
            return {"path": str(path), "mjd": mjd, "ok": False, "why": "no astrometric solution"}
        w = sol["wcs"]
        x, y = (float(v) for v in w.all_world2pix(pra, pdec, 0))
        trim = N._sec(h.get("TRIMSEC")) or (slice(None), slice(None))
        raw = d[trim]
        f = None
        if 3 <= x < img.shape[1] - 3 and 3 <= y < img.shape[0] - 3:
            c = N.centroid(img, x, y, hw=5)                 # start from the brightest light near the prediction
            # a star whose core clips at the 16-bit ceiling keeps a symmetric, flat-topped profile, so the Gaussian
            # centre is still its centre (masking the clipped pixels was tried: fitting the wings alone tripled
            # the frame-to-frame scatter of Teegarden's Star, from 0.15" to 0.45")
            f = N.fit_gauss(img, c[0], c[1], hw=5)
        if f is None:
            return {"path": str(path), "mjd": mjd, "ok": False, "why": "target not on the frame", "rms": sol["rms_arcsec"]}
        fx, fy, ex, ey, fwhm, amp = f
        mra, mdec = (float(v) for v in w.all_pix2world(fx, fy, 0))
        de, dn = offs(mra, mdec, pra, pdec)
        yi, xi = int(round(fy)), int(round(fx))
        peak = float(raw[max(0, yi - 3): yi + 4, max(0, xi - 3): xi + 4].max())
        stem = Path(path).stem.split("_")
        return {"path": str(path), "obs_id": stem[2], "product": stem[3] if len(stem) > 3 else "raw",
                "mjd": mjd, "year": year, "ok": True,
                "rms": sol["rms_arcsec"], "n_match": sol["n_match"], "x": fx, "y": fy, "fwhm": fwhm,
                "ra": mra, "dec": mdec, "de": float(de), "dn": float(dn), "peak_raw": peak,
                "exp": float(h.get("EXPOSURE", 0) or 0), "roll": h.get("OBJCTROL"),
                "wcs": w.to_header_string(relax=True), "shape": list(img.shape)}
    except Exception as e:  # noqa: BLE001
        return {"path": str(path), "ok": False, "why": repr(e)}


def frames_for(key):
    """CADC rows for the star's NEOSSat frames: footprints containing its position at a typical epoch; processed
    ('clean'/'cor') versions preferred over raw when both exist."""
    t = PM[key]["astro"]
    rows0 = N.search(ra=t["ra"], dec=t["dec"], radius=0.6)
    if not rows0:
        return []
    mjd = float(np.median([r["t_min"] for r in rows0]))
    ra, dec = position_at(t, mjd)
    rows = N.search(ra=float(ra[0]), dec=float(dec[0]))
    best = {}
    rank = {"cord": 0, "cor": 1, "clean": 2, "raw": 9}
    for r in rows:
        k = r["obs_id"]
        if k not in best or rank.get(r["product"], 5) < rank.get(best[k]["product"], 5):
            best[k] = r
    return sorted(best.values(), key=lambda r: r["t_min"])


def download_all(rows, threads=NTHREADS):
    def one(r):
        try:
            return N.download(r)
        except Exception as e:  # noqa: BLE001
            print("download failed", r["obs_id"], e, flush=True)
            return None
    with ThreadPoolExecutor(threads) as ex:
        return list(ex.map(one, rows))


def robust_mean(v):
    v = np.asarray(v, float)
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med)) or 1e-3
    k = np.abs(v - med) < 4 * mad
    return float(np.mean(v[k])), float(np.std(v[k], ddof=1) / math.sqrt(max(1, k.sum() - 1))) if k.sum() > 1 else 0.0, k


def stack_on_grid(frames, w_out, n, exp_norm=True):
    """Sigma-clipped mean of background-subtracted frames resampled onto w_out (each with its own Gaia WCS)."""
    from astropy.io import fits
    from astropy.wcs import WCS
    cube = []
    for fr in frames:
        d, h, _ = N.read(fr["path"])
        img = N.preprocess(d, h)
        r, _ = N.remove_background(img)
        if exp_norm and fr.get("exp"):
            r = r / fr["exp"]
        w = WCS(fits.Header.fromstring(fr["wcs"]))
        cube.append(N.resample(r, w, w_out, (n, n)))
    cube = np.array(cube)
    med = np.nanmedian(cube, axis=0)
    mad = 1.4826 * np.nanmedian(np.abs(cube - med), axis=0)
    good = np.abs(cube - med) <= 3 * np.maximum(mad, 1e-6)
    return np.nanmean(np.where(good, cube, np.nan), axis=0), len(cube)


def to_webp(img, path, size=None, fill_nan_max=False, smooth=0.0, black=1.0, knee=4.0, top=None):
    """Noise-aware asinh stretch -> 8-bit greyscale WebP, north up (row 0 = north). Black sits `black` noise sigmas
    below the sky, the asinh knee at `knee` sigmas (so the noise stays dim and faint stars show), white at the
    brightest star (or `top`, in sigmas)."""
    from PIL import Image
    from scipy.ndimage import gaussian_filter, maximum_filter
    a = np.array(img, float)
    if fill_nan_max:                                  # a saturated core (NaN) inside a star is drawn white
        m = maximum_filter(np.nan_to_num(a, nan=-np.inf), size=5)
        a = np.where(np.isnan(a) & np.isfinite(m) & (m > np.nanpercentile(a, 99)), np.nanmax(a), a)
    if smooth:
        good = np.isfinite(a)
        num = gaussian_filter(np.where(good, a, 0), smooth)
        den = gaussian_filter(good.astype(float), smooth)
        a = np.where(good, num / np.maximum(den, 1e-6), np.nan)
    v = a[np.isfinite(a)]
    med = float(np.median(v))
    sig = float(1.4826 * np.median(np.abs(v - med))) or 1e-6
    lo = med - black * sig
    hi = float(np.max(v)) if top is None else med + top * sig
    y = np.arcsinh(np.clip(a - lo, 0, None) / (knee * sig)) / np.arcsinh(max(hi - lo, sig) / (knee * sig))
    y = np.clip(np.nan_to_num(y, nan=0.0), 0, 1)
    im = Image.fromarray((y[::-1] * 255).astype(np.uint8))
    if size:
        im = im.resize((size, size), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=90, method=6)


def fill_saturated(img, passes=4):
    """A saturated star's core is NaN in the SPHEREx stacks; for the picture only, fill NaN pixels next to bright
    ones with their brightest neighbour so the star is drawn white, not with a black hole."""
    from scipy.ndimage import maximum_filter
    a = np.array(img, np.float32)
    bright = np.nanpercentile(a, 99.0)
    for _ in range(passes):
        nan = np.isnan(a)
        if not nan.any():
            break
        m = maximum_filter(np.nan_to_num(a, nan=-np.inf), size=3)
        fill = nan & np.isfinite(m) & (m > bright)
        if not fill.any():
            break
        a[fill] = m[fill]
    return a


# --------------------------------------------------------------------------------------------- SPHEREx side

def spherex_field(fid):
    from astropy.wcs import WCS
    from sxlib.products import read_stacks
    for base in (FIELDS, QUICK):
        p = base / fid / "field.json"
        if p.exists() and (base / fid / "pass" / "stacks.bin").exists():
            f = read_json(p)
            w = WCS(naxis=2)
            w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
            w.wcs.crval = f["wcs"]["crval"]
            w.wcs.crpix = f["wcs"]["crpix"]          # FITS 1-based, as lib.js pix2world uses it with 0-based x
            w.wcs.cdelt = f["wcs"]["cdelt"]
            return f, w, read_stacks(base / fid / "pass" / "stacks.bin").astype(np.float32), base / fid
    raise FileNotFoundError(fid)


def gaia_tie(img, w, gaia_rows, mjd, pix_arcsec, skip=()):
    """Median offset (east, north, arcsec) of isolated, unsaturated Gaia stars measured in a SPHEREx stack."""
    from astropy.time import Time
    year = Time(mjd, format="mjd").jyear
    ra, dec, g = N.gaia_at(gaia_rows, year)
    out = []
    for i in np.argsort(g):
        if not 9.5 < g[i] < 14.0:
            continue
        if any(abs((ra[i] - sr) * math.cos(math.radians(sd))) < 30 / 3600 and abs(dec[i] - sd) < 30 / 3600 for sr, sd in skip):
            continue
        near = np.hypot((ra - ra[i]) * math.cos(math.radians(dec[i])), dec - dec[i]) * 3600
        if np.sum((near < 20) & (g < g[i] + 3)) > 1:
            continue
        x, y = (float(v) for v in w.all_world2pix(ra[i], dec[i], 0))
        if not (5 <= x < img.shape[1] - 5 and 5 <= y < img.shape[0] - 5):
            continue
        cut = img[int(y) - 2:int(y) + 3, int(x) - 2:int(x) + 3]
        if np.isnan(cut).any():
            continue
        f = N.fit_gauss(img, x, y, hw=4, fwhm0=1.5)
        if f is None or not (0.8 < f[4] < 4) or f[2] > 0.3:
            continue
        mra, mdec = w.all_pix2world(f[0], f[1], 0)
        de, dn = offs(float(mra), float(mdec), ra[i], dec[i])
        out.append((float(de), float(dn)))
    if len(out) < 3:
        return None
    a = np.array(out)
    med = np.median(a, axis=0)
    sc = 1.4826 * np.median(np.abs(a - med), axis=0)
    return {"de": float(med[0]), "dn": float(med[1]), "scatter": [float(sc[0]), float(sc[1])], "n": len(out),
            "err": [float(sc[0] / math.sqrt(len(out))), float(sc[1] / math.sqrt(len(out)))]}


def spherex_passes(key, gaia_rows):
    """The target's position in each SPHEREx pass stack (all bands), tied to Gaia stars in the same stack."""
    cfg = PM[key]
    t = cfg["astro"]
    f, w, stacks, fdir = spherex_field(cfg["field"])
    pix = abs(f["wcs"]["cdelt"][0]) * 3600
    exp_mjd = np.array([e["mjd"] for e in f["exposures"]])
    out = []
    tg = (f.get("target") or {}) if (f.get("target") or {}).get("id") == key else {}
    for k, ps in enumerate(f["products"]["passes"]):
        sel = (exp_mjd >= ps["mjd0"] - 1e-3) & (exp_mjd <= ps["mjd1"] + 1e-3)
        mjd = float(np.median(exp_mjd[sel])) if sel.any() else 0.5 * (ps["mjd0"] + ps["mjd1"])
        pra, pdec = position_at(t, mjd)
        pra, pdec = float(pra[0]), float(pdec[0])
        img = stacks[k, 0]
        src = "gauss fit"
        fit = (tg.get("passes") or [{}] * 3)[k].get("fit") if tg.get("passes") and k < len(tg["passes"]) else None
        if fit:
            fx, fy, ferr = fit["x"], fit["y"], fit["err"]
            src = "pipeline PSF fit"
        else:
            x, y = (float(v) for v in w.all_world2pix(pra, pdec, 0))
            g = N.fit_gauss(img, x, y, hw=4, fwhm0=1.5)
            if g is None:
                continue
            fx, fy, ferr = g[0], g[1], float(np.hypot(g[2], g[3]))
        mra, mdec = (float(v) for v in w.all_pix2world(fx, fy, 0))
        tie = gaia_tie(img, w, gaia_rows, mjd, pix, skip=[(pra, pdec)])
        de, dn = offs(mra, mdec, pra, pdec)
        de, dn = float(de), float(dn)
        if tie:                                       # put the measurement on Gaia's frame
            mra -= tie["de"] / 3600 / math.cos(math.radians(mdec))
            mdec -= tie["dn"] / 3600
            de -= tie["de"]
            dn -= tie["dn"]
        err = math.hypot(ferr * pix, math.hypot(*tie["err"]) if tie else 0.5)
        out.append({"k": k, "mjd": mjd, "date": mjd_iso(mjd), "n": int(sel.sum()), "ra": mra, "dec": mdec,
                    "de": de, "dn": dn, "err": err, "fit": src, "tie": tie, "x": fx, "y": fy})
    return out, f, w, stacks, pix


# --------------------------------------------------------------------------------------------- R10 driver

def build_pm(key):
    t0 = time.time()
    cfg = PM[key]
    t = cfg["astro"]
    rows = frames_for(key)
    print(f"[{key}] {len(rows)} NEOSSat exposures, products {sorted({r['product'] for r in rows})}", flush=True)
    paths = download_all(rows)
    ok_rows = [(r, p) for r, p in zip(rows, paths) if p]
    mjd_mid = float(np.median([r["t_min"] for r, _ in ok_rows]))
    cra, cdec = (float(v[0]) for v in position_at(t, mjd_mid))
    gaia = N.gaia_cone(cra, cdec, 0.85, gmax=16.0)
    print(f"[{key}] Gaia DR3 stars G<16 within 0.85 deg: {len(gaia)}", flush=True)
    # per-frame astrometry is cached (cache/neossat/pm_<key>.json): rebuilding after a SPHEREx field changes takes
    # seconds; NEOSSAT_REFRESH=1 recomputes
    fcache = N.CACHE / f"pm_{key}.json"
    paths = [str(p) for _, p in ok_rows]
    res = None
    if fcache.exists() and os.environ.get("NEOSSAT_REFRESH") != "1":
        old = read_json(fcache)
        if sorted(r["path"] for r in old) == sorted(paths):
            res = old
    if res is None:
        with ProcessPoolExecutor(NPROC, initializer=_init, initargs=(gaia,)) as ex:
            res = list(ex.map(measure_frame, [(p, t) for p in paths], chunksize=4))
        write_json(fcache, res, indent=None)
    solved = [r for r in res if r.get("ok")]
    print(f"[{key}] solved {len(solved)}/{len(res)}; why not: "
          f"{sorted({r.get('why') for r in res if not r.get('ok')})[:4]}", flush=True)
    rms = np.array([r["rms"] for r in solved])
    rms_cut = min(1.6, float(np.median(rms) * 1.6)) if len(rms) else 0
    good = [r for r in solved if r["rms"] <= rms_cut and r["n_match"] >= 10 and 1.0 < r["fwhm"] < 9]
    if not good:
        raise SystemExit(f"[{key}] no usable frames")
    de_m, de_e, kde = robust_mean([r["de"] for r in good])
    dn_m, dn_e, kdn = robust_mean([r["dn"] for r in good])
    keep = [r for r, a, b in zip(good, kde, kdn) if a and b]
    n_sat = sum(r["peak_raw"] >= SAT_RAW for r in solved)
    mjd_n = float(np.mean([r["mjd"] for r in keep]))
    # error: frames of one night share the roll angle and pointing, so their errors are not independent. The spread
    # of the nightly means (roll-dependent systematics) is used, undivided, as the uncertainty of the mean position;
    # with a single night, the WCS fit's own uncertainty (rms / sqrt(n stars)) is the floor
    nights = {}
    for r in keep:
        nights.setdefault(int(r["mjd"]), []).append(r)
    night_means = np.array([[np.mean([r["de"] for r in v]), np.mean([r["dn"] for r in v])] for v in nights.values()])
    sys_e = float(np.median([r["rms"] / math.sqrt(r["n_match"]) for r in keep]))
    if len(nights) >= 3:
        sys_e = max(sys_e, float(np.hypot(*np.std(night_means, axis=0, ddof=1))))
    nra, ndec = (float(v[0]) for v in position_at(t, mjd_n))
    neo = {"n_exposures": len(rows), "n_solved": len(solved), "n_used": len(keep), "n_saturated": int(n_sat),
           "first": mjd_iso(min(r["mjd"] for r in keep)), "last": mjd_iso(max(r["mjd"] for r in keep)),
           "mjd": mjd_n, "date": mjd_iso(mjd_n), "exp_s": round(float(np.median([r["exp"] for r in keep])), 2),
           "rms_arcsec": round(float(np.median([r["rms"] for r in keep])), 2),
           "n_gaia_per_frame": int(np.median([r["n_match"] for r in keep])),
           "de": de_m, "dn": dn_m, "err": float(math.hypot(math.hypot(de_e, dn_e), sys_e)),
           "scatter_arcsec": [float(np.std([r["de"] for r in keep])), float(np.std([r["dn"] for r in keep]))],
           "ra": nra + de_m / 3600 / math.cos(math.radians(ndec)), "dec": ndec + dn_m / 3600,
           "products": sorted({r["product"] for r in keep}), "n_nights": len(nights),
           "nights": [{"date": mjd_iso(float(np.mean([r["mjd"] for r in v]))), "n": len(v),
                       "de": round(float(np.mean([r["de"] for r in v])), 3), "dn": round(float(np.mean([r["dn"] for r in v])), 3)}
                      for _, v in sorted(nights.items())]}
    print(f"[{key}] NEOSSat {neo['first']}..{neo['last']}: {len(keep)} frames, rms {neo['rms_arcsec']}\", "
          f"offset from Gaia ({de_m:+.2f}, {dn_m:+.2f})\" +- {neo['err']:.2f}", flush=True)

    sp, f, wsx, stacks, sx_pix = spherex_passes(key, gaia)
    for p in sp:
        print(f"[{key}] SPHEREx pass {p['k']} {p['date']}: offset from Gaia ({p['de']:+.2f}, {p['dn']:+.2f})\" "
              f"+- {p['err']:.2f} ({p['fit']}; tie {p['tie'] and (round(p['tie']['de'], 2), round(p['tie']['dn'], 2), p['tie']['n'])})", flush=True)
    # SPHEREx: the pass-to-pass spread of the offsets from Gaia is the realistic error of one pass (for a saturated
    # star the PSF fit's formal error is far too small)
    if len(sp) >= 2:
        spread = float(np.hypot(*np.std([[p["de"], p["dn"]] for p in sp], axis=0, ddof=1)))
        for p in sp:
            p["err_formal"] = p["err"]
            p["err"] = max(p["err"], spread)
    s0 = sp[0]

    # displacement NEOSSat -> SPHEREx pass 0: measured (both measured positions) vs Gaia's prediction
    pr0 = position_at(t, neo["mjd"])
    pr1 = position_at(t, s0["mjd"])
    pde, pdn = offs(float(pr1[0][0]), float(pr1[1][0]), float(pr0[0][0]), float(pr0[1][0]))
    mde, mdn = offs(s0["ra"], s0["dec"], neo["ra"], neo["dec"])
    pde, pdn, mde, mdn = float(pde), float(pdn), float(mde), float(mdn)
    err = math.hypot(neo["err"], s0["err"])
    years = (s0["mjd"] - neo["mjd"]) / 365.25
    disp = {"years": years, "measured": {"de": mde, "dn": mdn, "total": math.hypot(mde, mdn),
                                         "pa": math.degrees(math.atan2(mde, mdn)) % 360},
            "predicted": {"de": pde, "dn": pdn, "total": math.hypot(pde, pdn), "pa": math.degrees(math.atan2(pde, pdn)) % 360},
            "err": err, "diff": math.hypot(mde - pde, mdn - pdn),
            "pm_measured": math.hypot(mde, mdn) / years, "pm_gaia": math.hypot(t["pmra"], t["pmdec"]) / 1000}
    disp["diff_sigma"] = disp["diff"] / err if err else None
    print(f"[{key}] {years:.2f} yr: measured {disp['measured']['total']:.2f}\" (PA {disp['measured']['pa']:.1f}) vs "
          f"Gaia {disp['predicted']['total']:.2f}\" (PA {disp['predicted']['pa']:.1f}); diff {disp['diff']:.2f}\" "
          f"= {disp['diff_sigma']:.1f} sigma", flush=True)

    # Gaia's predicted path (with the parallax wobble) relative to the NEOSSat-epoch prediction, every 8 days
    mj = np.arange(neo["mjd"], max(p["mjd"] for p in sp) + 8, 8.0)
    tra, tdec = position_at(t, mj)
    tde, tdn = offs(tra, tdec, float(pr0[0][0]), float(pr0[1][0]))
    track = [[round(float(a), 2), round(float(b), 2), round(float(m), 1)] for a, b, m in zip(tde, tdn, mj)]

    def rel(ra, dec):
        a, b = offs(ra, dec, float(pr0[0][0]), float(pr0[1][0]))
        return round(float(a), 2), round(float(b), 2)

    points = [{"mission": "NEOSSat", "date": neo["date"], "mjd": neo["mjd"], "e": rel(neo["ra"], neo["dec"])[0],
               "n": rel(neo["ra"], neo["dec"])[1], "err": round(neo["err"], 2)}]
    for p in sp:
        e, n_ = rel(p["ra"], p["dec"])
        points.append({"mission": "SPHEREx", "pass": p["k"], "date": p["date"], "mjd": p["mjd"], "e": e, "n": n_,
                       "err": round(p["err"], 2)})

    # the aligned blink: both epochs on one north-up grid centred between the two measured positions
    cra = 0.5 * (neo["ra"] + s0["ra"])
    cdec = 0.5 * (neo["dec"] + s0["dec"])
    wg, n = N.north_up_wcs(cra, cdec, GRID_ARCSEC, GRID_PIX)
    best = sorted(keep, key=lambda r: r["rms"])[:200]
    opt, n_st = stack_on_grid(best, wg, n)
    ir = N.resample(fill_saturated(stacks[0, 0]), wsx, wg, (n, n), order=1)
    d = OUT / key
    to_webp(opt, d / "optical.webp", size=2 * n, smooth=0.8, black=0.0, knee=6.0)
    to_webp(ir, d / "infrared.webp", size=2 * n)
    # the star measured in the optical stack too (a check on the per-frame mean)
    gx, gy = (float(v) for v in wg.all_world2pix(neo["ra"], neo["dec"], 0))
    gs = N.fit_gauss(opt, gx, gy, hw=10, fwhm0=4)
    stack_check = None
    if gs:
        sra, sdec = (float(v) for v in wg.all_pix2world(gs[0], gs[1], 0))
        a, b = offs(sra, sdec, neo["ra"], neo["dec"])
        stack_check = {"de": round(float(a), 2), "dn": round(float(b), 2)}

    def gpix(ra, dec):
        x, y = (float(v) for v in wg.all_world2pix(ra, dec, 0))
        return round((x + 0.5) / n, 4), round(1 - (y + 0.5) / n, 4)    # fractions of the image from the top left

    grid = {"ra": cra, "dec": cdec, "size_arcsec": GRID_ARCSEC, "pix_arcsec": GRID_PIX, "n": n,
            "optical": {"img": f"/data/neossat/{key}/optical.webp", "label": f"NEOSSat {neo['first'][:7]}",
                        "n_frames": n_st, "xy": gpix(neo["ra"], neo["dec"])},
            "infrared": {"img": f"/data/neossat/{key}/infrared.webp", "label": f"SPHEREx {s0['date'][:7]}",
                         "xy": gpix(s0["ra"], s0["dec"])},
            "predicted": {"optical": gpix(float(pr0[0][0]), float(pr0[1][0])), "infrared": gpix(float(pr1[0][0]), float(pr1[1][0]))}}
    res = {"id": key, "name": cfg["name"], "name_zh": cfg["name_zh"], "source": t.get("source"), "g_mag": t.get("g"),
           "pm_arcsec_yr": round(math.hypot(t["pmra"], t["pmdec"]) / 1000, 3), "parallax_mas": t["plx"],
           "neossat": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in neo.items()},
           "neossat_stack_check": stack_check,
           "spherex": [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in p.items() if k not in ("x", "y")} for p in sp],
           "spherex_field": cfg["field"], "spherex_pix_arcsec": round(sx_pix, 3),
           "displacement": json.loads(json.dumps(disp), parse_float=lambda s: round(float(s), 3)),
           "track": track, "points": points, "grid": grid, "built_s": round(time.time() - t0, 1)}
    write_json(d / "result.json", res, indent=None, ensure_ascii=False)
    # frame-level table for anyone who wants to check (not shown on the page)
    write_json(d / "frames.json", [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
                                    if k not in ("wcs", "path")} for r in solved], indent=None)
    write_validation()
    return res


def write_validation():
    docs = []
    for key in PM:
        p = OUT / key / "result.json"
        if p.exists():
            r = read_json(p)
            docs.append({k: r[k] for k in ("id", "name", "name_zh", "source", "g_mag", "pm_arcsec_yr", "parallax_mas",
                                          "neossat", "spherex", "displacement", "track", "points", "grid",
                                          "spherex_field", "spherex_pix_arcsec", "neossat_stack_check")})
    write_json(VALID, {
        "about": "Cross-mission proper motion: NEOSSat optical frames (Gaia-calibrated here) vs SPHEREx infrared pass "
                 "stacks, compared with Gaia DR3's prediction (proper motion + parallax at both epochs).",
        "method": "Each NEOSSat frame: overscan/bias correction (CSA tutorial), star detection, pattern match to Gaia DR3 "
                  "(epoch-propagated, the target excluded), TAN WCS least-squares fit; the target is fitted with a 2-D "
                  "Gaussian. SPHEREx: the pipeline's PSF fit (or a 2-D Gaussian) in each pass stack, tied to the Gaia "
                  "stars measured in the same stack.",
        "credit_en": N.CREDIT_EN, "credit_zh": N.CREDIT_ZH,
        "targets": docs, "updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}, indent=None, ensure_ascii=False)


# --------------------------------------------------------------------------------------------- R4: 3I/ATLAS

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"


def horizons_comet(start, stop, step="1m"):
    """Geocentric astrometric RA/Dec, distance and magnitudes of 3I/ATLAS (C/2025 N1), cached."""
    import requests
    f = N.CACHE / f"horizons_3I_{start}_{stop}_{step}.json".replace(" ", "T").replace(":", "")
    if f.exists():
        return read_json(f)
    q = {"format": "text", "COMMAND": "'DES=C/2025 N1;'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
         "EPHEM_TYPE": "OBSERVER", "CENTER": "'500'", "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'",
         "STEP_SIZE": f"'{step}'", "QUANTITIES": "'1,9,19,20,23'", "CSV_FORMAT": "YES", "ANG_FORMAT": "DEG",
         "EXTRA_PREC": "YES"}
    r = requests.get(HORIZONS + "?" + urllib.parse.urlencode(q), timeout=120, verify=N.VERIFY, headers=N.UA)
    r.raise_for_status()
    txt = r.text
    a, b = txt.find("$$SOE"), txt.find("$$EOE")
    head = txt[:a].strip().splitlines()
    cols = [c.strip() for c in head[-2].split(",")]
    from astropy.time import Time
    rows = []
    for ln in txt[a + 5:b].strip().splitlines():
        p = [x.strip() for x in ln.split(",")]
        d = dict(zip(cols, p))

        def num(k):
            try:
                return float(d.get(k, "nan"))
            except ValueError:
                return float("nan")
        t = Time(datetime_from_horizons(p[0]), format="isot", scale="utc")
        rows.append({"mjd": float(t.mjd), "ra": num("R.A._(ICRF)"), "dec": num("DEC_(ICRF)"), "T_mag": num("T-mag"),
                     "N_mag": num("N-mag"), "r_au": num("r"), "delta_au": num("delta"), "elong": num("S-O-T")})
    write_json(f, rows, indent=None)
    return rows


def datetime_from_horizons(s):
    from datetime import datetime
    s = s.strip()
    for fmt in ("%Y-%b-%d %H:%M:%S.%f", "%Y-%b-%d %H:%M:%S", "%Y-%b-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    raise ValueError(s)


def comet_topo(eph, mjd, sc_km):
    """Comet direction seen from the spacecraft: the geocentric ephemeris interpolated to mjd, shifted by the
    spacecraft's J2000 position (header JPOS2_*, km) -- ~5" of parallax from low Earth orbit at ~2 au."""
    m = np.array([e["mjd"] for e in eph])
    ra = np.interp(mjd, m, np.unwrap(np.radians([e["ra"] for e in eph])))
    dec = np.interp(mjd, m, np.radians([e["dec"] for e in eph]))
    dist = np.interp(mjd, m, [e["delta_au"] for e in eph]) * AU_KM
    v = dist * np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]) - np.asarray(sc_km)
    r = np.linalg.norm(v)
    return math.degrees(math.atan2(v[1], v[0])) % 360, math.degrees(math.asin(v[2] / r))


def comet_frame(args):
    path, = args
    try:
        d, h, w0 = N.read(path)
        img = N.preprocess(d, h)
        ra0 = dec0 = None
        if w0 is not None:
            ra0, dec0 = (float(v) for v in w0.all_pix2world(img.shape[1] / 2, img.shape[0] / 2, 0))
        sol = N.solve(img, h, gaia_rows=_G["rows"], ra0=ra0, dec0=dec0, sip=2)
        if sol is None:
            return {"path": str(path), "ok": False}
        year, mjd = N.frame_year(h)
        sc = [float(h.get(f"JPOS2_{i}", 0) or 0) for i in (1, 2, 3)]
        return {"path": str(path), "ok": True, "mjd": mjd, "rms": sol["rms_arcsec"], "n_match": sol["n_match"],
                "exp": float(h.get("EXPOSURE", 0) or 0), "sc_km": sc, "wcs": sol["wcs"].to_header_string(relax=True)}
    except Exception as e:  # noqa: BLE001
        return {"path": str(path), "ok": False, "why": repr(e)}


def aperture(img, x, y, r, r_in, r_out):
    """Sum in a disc of radius r about (x, y) minus the median of the (r_in, r_out) annulus, and the pixel count.
    Only the box enclosing the annulus is looked at (the result is the same as over the whole image)."""
    rmax = max(r, r_out)
    y0, y1 = max(0, int(math.floor(y - rmax))), min(img.shape[0], int(math.ceil(y + rmax)) + 1)
    x0, x1 = max(0, int(math.floor(x - rmax))), min(img.shape[1], int(math.ceil(x + rmax)) + 1)
    sub = img[y0:y1, x0:x1]
    yy, xx = np.ogrid[y0:y1, x0:x1]
    rr = np.hypot(xx - x, yy - y)
    fin = np.isfinite(sub)
    ann = sub[(rr >= r_in) & (rr < r_out) & fin]
    ap = (rr < r) & fin
    bg = float(np.median(ann)) if ann.size else 0.0
    return float(np.sum(sub[ap] - bg)), int(ap.sum())


def build_comet():
    from astropy.io import fits
    from astropy.wcs import WCS
    rows = N.search(ra=178.70, dec=1.08, mjd0=61011.0, mjd1=61012.5)
    rows = [r for r in rows if r["target_name"].strip() == "3I"]
    pref = {}
    for r in rows:
        if r["product"] in ("cord", "cor") and (r["obs_id"] not in pref or r["product"] == "cord"):
            pref[r["obs_id"]] = r
    rows = sorted(pref.values(), key=lambda r: r["t_min"])
    print(f"[comet] {len(rows)} NEOSSat exposures of '3I' on 2025-12-02 ({sorted({r['product'] for r in rows})})", flush=True)
    paths = [p for p in download_all(rows) if p]
    t_lo = min(r["t_min"] for r in rows)
    t_hi = max(r["t_min"] for r in rows)
    from astropy.time import Time
    start = Time(t_lo - 0.01, format="mjd").strftime("%Y-%m-%d %H:%M")
    stop = Time(t_hi + 0.02, format="mjd").strftime("%Y-%m-%d %H:%M")
    eph = horizons_comet(start, stop, "1m")
    mid = eph[len(eph) // 2]
    gaia = N.gaia_cone(178.74, 1.067, 0.75, gmax=16.0)
    print(f"[comet] Horizons: RA {mid['ra']:.4f} Dec {mid['dec']:.4f}, T-mag {mid['T_mag']}, N-mag {mid['N_mag']}, "
          f"delta {mid['delta_au']:.3f} au; Gaia {len(gaia)} stars", flush=True)
    with ProcessPoolExecutor(NPROC, initializer=_init, initargs=(gaia,)) as ex:
        fr = list(ex.map(comet_frame, [(p,) for p in paths]))
    ok = [f for f in fr if f.get("ok") and f["rms"] < 3.0]
    print(f"[comet] solved {len(ok)}/{len(fr)}; rms median {np.median([f['rms'] for f in ok]):.2f}\"", flush=True)
    size, pix = 360.0, 1.5
    tmid = float(np.mean([f["mjd"] for f in ok]))
    sc_mid = np.mean([f["sc_km"] for f in ok], axis=0)
    cra, cdec = comet_topo(eph, tmid, sc_mid)
    w_star, n = N.north_up_wcs(cra, cdec, size, pix)
    cube_c, cube_s = [], []
    for f in ok:
        d, h, _ = N.read(f["path"])
        img = N.preprocess(d, h)
        r, _ = N.remove_background(img, box=48)
        r = r / f["exp"]
        w = WCS(fits.Header.fromstring(f["wcs"]))
        ra, dec = comet_topo(eph, f["mjd"], f["sc_km"])
        w_c, _ = N.north_up_wcs(ra, dec, size, pix)
        cube_c.append(N.resample(r, w, w_c, (n, n)))
        cube_s.append(N.resample(r, w, w_star, (n, n)))

    def clip_mean(c):
        c = np.array(c)
        med = np.nanmedian(c, axis=0)
        mad = 1.4826 * np.nanmedian(np.abs(c - med), axis=0)
        return np.nanmean(np.where(np.abs(c - med) <= 3 * np.maximum(mad, 1e-9), c, np.nan), axis=0)

    comet_img = clip_mean(cube_c)
    star_img = clip_mean(cube_s)
    # comet-frame stack, with the stars removed: subtract the star-aligned stack shifted to each frame? Simpler and
    # honest: measure in the comet-centred stack with an aperture, noise from the same aperture at random places
    c0 = (n - 1) / 2
    r_ap = 6.0 / pix * 1.5           # 9" radius
    flux, npx = aperture(comet_img, c0, c0, r_ap, r_ap * 2, r_ap * 3.5)
    rng = np.random.default_rng(1)
    samples = []
    for _ in range(400):
        x, y = rng.uniform(r_ap * 3.5, n - r_ap * 3.5, 2)
        if math.hypot(x - c0, y - c0) < r_ap * 4:
            continue
        samples.append(aperture(comet_img, x, y, r_ap, r_ap * 2, r_ap * 3.5)[0])
    samples = np.array(samples)
    noise = 1.4826 * float(np.median(np.abs(samples - np.median(samples))))
    snr = flux / noise if noise > 0 else 0.0
    # photometric zero point from Gaia stars in the star-aligned stack (G band ~ NEOSSat's clear 400-900 nm)
    ra_g, dec_g, g = N.gaia_at(gaia, Time(tmid, format="mjd").jyear)
    zps = []
    for i in np.argsort(g):
        if not 11.0 < g[i] < 15.0:
            continue
        x, y = (float(v) for v in w_star.all_world2pix(ra_g[i], dec_g[i], 0))
        if not (r_ap * 4 < x < n - r_ap * 4 and r_ap * 4 < y < n - r_ap * 4):
            continue
        fl, _ = aperture(star_img, x, y, r_ap, r_ap * 2, r_ap * 3.5)
        if fl > 0:
            zps.append(g[i] + 2.5 * math.log10(fl))
    zp = float(np.median(zps)) if zps else None
    lim5 = zp - 2.5 * math.log10(5 * noise) if zp and noise > 0 else None
    mag = zp - 2.5 * math.log10(flux) if zp and flux > 0 else None
    t_mag = float(np.interp(tmid, [e["mjd"] for e in eph], [e["T_mag"] for e in eph]))
    n_mag = float(np.interp(tmid, [e["mjd"] for e in eph], [e["N_mag"] for e in eph]))
    detected = bool(snr >= 5)
    print(f"[comet] aperture 9\": SNR {snr:.1f}; ZP from {len(zps)} Gaia stars {zp}; 5-sigma limit {lim5}; "
          f"measured mag {mag}; Horizons T-mag {t_mag:.2f}, N-mag {n_mag:.2f}", flush=True)
    COMET.mkdir(parents=True, exist_ok=True)
    to_webp(comet_img, COMET / "neossat.webp", size=2 * n, smooth=0.7, top=400)
    to_webp(star_img, COMET / "neossat_stars.webp", size=2 * n, smooth=0.7, top=400)
    exp_total = float(sum(f["exp"] for f in ok))
    if detected:
        note_en = (f"3I/ATLAS is detected in the stack of {len(ok)} NEOSSat frames ({exp_total / 60:.0f} min in all) "
                   f"aligned on its motion: signal-to-noise {snr:.0f} in a 9\" aperture, about magnitude "
                   f"{mag:.1f} in NEOSSat's clear band (JPL predicts total magnitude {t_mag:.1f}).")
        note_zh = (f"把 {len(ok)} 張 NEOSSat 影像（共 {exp_total / 60:.0f} 分鐘）沿著彗星的移動疊加後，看得到 3I/ATLAS："
                   f"9 角秒孔徑內訊噪比 {snr:.0f}，在 NEOSSat 的無濾鏡波段約 {mag:.1f} 等（JPL 預測總星等 {t_mag:.1f}）。")
    else:
        note_en = (f"3I/ATLAS is not detected in the stack of {len(ok)} NEOSSat frames ({exp_total / 60:.0f} min in all) "
                   f"aligned on its motion: signal-to-noise {snr:.1f} in a 9\" aperture. JPL predicts total magnitude "
                   f"{t_mag:.1f}; the stack reaches about magnitude {lim5:.1f} (5 sigma) for a point source, so a diffuse "
                   f"coma spread over a larger area falls below the limit.")
        note_zh = (f"把 {len(ok)} 張 NEOSSat 影像（共 {exp_total / 60:.0f} 分鐘）沿著彗星的移動疊加，仍看不到 3I/ATLAS："
                   f"9 角秒孔徑內訊噪比只有 {snr:.1f}。JPL 預測它的總星等是 {t_mag:.1f}，而這張疊加圖對點狀天體只到約 "
                   f"{lim5:.1f} 等（5 倍雜訊），彗髮散開後更暗，低於極限。")
    doc = {"date": "2025-12-02", "n_frames": len(ok), "exp_s": round(float(np.median([f["exp"] for f in ok])), 2),
           "exp_total_s": round(exp_total, 1), "pixscale_arcsec": pix, "width_arcsec": size,
           "detected": detected, "snr": round(float(snr), 2), "aperture_arcsec": round(r_ap * pix, 1),
           "mag_measured": round(mag, 2) if mag else None, "limit_mag_5sigma": round(lim5, 2) if lim5 else None,
           "zp_n_stars": len(zps), "T_mag": round(t_mag, 2), "N_mag": round(n_mag, 2),
           "expected_mag_note": "JPL Horizons total (T-mag) and nuclear (N-mag) magnitudes, V-band-like",
           "delta_au": round(float(mid["delta_au"]), 4), "r_au": round(float(mid["r_au"]), 4),
           "ra": round(cra, 5), "dec": round(cdec, 5), "mjd_mid": round(tmid, 5),
           "time_span_min": round((max(f["mjd"] for f in ok) - min(f["mjd"] for f in ok)) * 1440, 1),
           "motion_arcsec": round(float(np.hypot(*offs(*comet_topo(eph, max(f["mjd"] for f in ok), sc_mid),
                                                         *comet_topo(eph, min(f["mjd"] for f in ok), sc_mid)))), 1),
           "astrometry_rms_arcsec": round(float(np.median([f["rms"] for f in ok])), 2),
           "img": "/data/comet/neossat.webp", "img_stars": "/data/comet/neossat_stars.webp",
           "north_up": True, "east_left": True,
           "note_zh": note_zh, "note_en": note_en, "credit_en": N.CREDIT_EN, "credit_zh": N.CREDIT_ZH,
           "cadc_target": "3I", "pi": "D. Balam (proposal C10P001)"}
    write_json(COMET / "neossat.json", doc, indent=None, ensure_ascii=False)
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    return doc


# --------------------------------------------------------------------------------------------- R11 coverage

def build_coverage():
    if str(WEB) not in sys.path:
        sys.path.insert(0, str(WEB))
    from web import api_neossat as A
    todo = []
    for base in (FIELDS, QUICK):
        for p in sorted(base.glob("*/field.json")):
            if "." in p.parent.name:
                continue
            try:
                f = read_json(p)
                todo.append((p.parent.name, float(f["ra"]), float(f["dec"])))
            except Exception:  # noqa: BLE001
                continue
    print(f"[coverage] {len(todo)} positions", flush=True)

    def one(item):
        fid, ra, dec = item
        t = time.time()
        doc = A.coverage_now(ra, dec)
        return fid, doc.get("n", 0), len(doc.get("dates", [])), round(time.time() - t, 1), doc.get("status")
    with ThreadPoolExecutor(3) as ex:
        for fid, n, nd, dt, st in ex.map(one, todo):
            print(f"  {fid:28s} {st:8s} {n:5d} exposures on {nd:3d} dates ({dt}s)", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):          # Chinese notes printed on a non-UTF-8 (Windows) console
        sys.stdout.reconfigure(errors="backslashreplace")
    what = sys.argv[1:] or ["all"]
    if what[0] == "pm":
        for k in what[1:] or list(PM):
            build_pm(k)
    elif what[0] == "comet":
        build_comet()
    elif what[0] == "coverage":
        build_coverage()
    elif what[0] == "validation":
        write_validation()
    elif what[0] == "all":
        for k in PM:
            build_pm(k)
        build_comet()
        build_coverage()
    else:
        raise SystemExit(__doc__)
