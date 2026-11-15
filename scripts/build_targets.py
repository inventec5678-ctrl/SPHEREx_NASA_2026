"""Build the challenge's test-target fields: python scripts/build_targets.py analyze|annotate [ids...]

analyze  runs the full pipeline (sxlib.analyze.analyze_field) on a 0.3 deg field centred on each target at 2026.0.
annotate re-reads the cached cutouts, writes the lab products (sxlib.products: pass x band stacks, cube, flags,
         Gaia/CatWISE overlays) and, for a named target, its predicted position on every frame (proper motion +
         parallax) with forced photometry there -> light curve and spectrum. Works on any field id.

annotate() is also called by web/worker.py (``from scripts.build_targets import annotate``).
"""
import shutil
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MODELS, read_json  # noqa: E402
from sxlib import pipeline, targets  # noqa: E402
from sxlib.analyze import write_doc  # noqa: E402
from sxlib.products import R_AP, build as build_products, phot  # noqa: E402

SIZE = 0.3                      # field side (deg)
PIX_ARCSEC = 6.15               # SPHEREx pixel scale
# PSF-wing annulus and sky ring (px) for saturated targets (also quoted by sxlib/varsearch.py)
W_IN, W_OUT, W_SKY0, W_SKY1 = 4.5, 7.5, 10.0, 14.0
MOTION_BAND = {"wise0855": 6, "epsindi": 6}     # band used for the measured motion (default 0 = all detectors)
FLAG_BAD, FLAG_FEAT_MASK = 1, 6                 # 1 bad; feature bits 2|4 -> 4 ghost, 8 outlier (as the cube)


def analyze(tid):
    from sxlib.analyze import analyze_field
    from sxlib.rbnet import Scorer
    t = targets.TARGETS[tid]
    if (FIELDS / tid / "field.json").exists():
        print(tid, "already analysed"); return
    ra, dec = targets.centre_2026(t)
    scorer = Scorer(MODELS / "rb_cnn.pt")
    try:
        analyze_field(tid, t["name"], ra, dec, SIZE, FIELDS, scorer, description=t["about"], log=lambda m: print(tid, m, flush=True))
    except Exception:
        shutil.rmtree(FIELDS / tid, ignore_errors=True)
        raise


def target_points(f, doc, t):
    """Predicted position and forced photometry of a named target on every exposure."""
    idx = {(e["obs_id"], e["detector"]): e["i"] for e in doc["exposures"]}
    ra, de = targets.position_at(t, f.mjd)
    xs, ys = f.world_to_pix(ra, de)                  # all exposures in one WCS call
    xs, ys = np.atleast_1d(xs), np.atleast_1d(ys)
    ny, nx = f.shape[0], f.shape[1]
    pts = []
    for k, e in enumerate(f.exps):
        i = idx.get((e["obs_id"], e["detector"]))
        if i is None:
            continue
        x, y = float(xs[k]), float(ys[k])
        p = phot(f.img[k], f.var[k], f.bad[k], x, y)
        xi, yi = int(round(x)), int(round(y))
        inside = 0 <= yi < ny and 0 <= xi < nx
        lam = float(f.lam[k][yi, xi]) if inside and np.isfinite(f.lam[k][yi, xi]) else e["lam_um"]
        fl = int(f.bad[k][yi, xi]) | (int(f.feat[k][yi, xi]) & FLAG_FEAT_MASK) << 1 if inside else FLAG_BAD
        pts.append({"i": i, "x": round(x, 2), "y": round(y, 2), "mjd": round(e["mjd"], 5), "det": int(e["detector"]), "lam": round(lam, 4),
                    "f": None if p is None else round(p[0], 2), "e": None if p is None else round(p[1], 2), "flag": fl})
    pts.sort(key=lambda p: p["i"])
    passes = []
    for q in doc["products"]["passes"]:
        pr, pd = targets.position_at(t, [(q["mjd0"] + q["mjd1"]) / 2])
        px, py = f.world_to_pix(pr[0], pd[0])
        passes.append(q | {"x": round(float(px), 2), "y": round(float(py), 2)})
    return pts, passes


def fit_position(img, x0, y0, r=6.0):
    """Gaussian + background fit to the pixels around (x0, y0). Saturated cores are NaN in the stacks, so a
    saturated star is fitted on its wings alone. Returns (x, y, sigma_px) or None."""
    from scipy.optimize import curve_fit
    n0, n1 = img.shape
    ys, xs = np.mgrid[max(0, int(y0 - r)):min(n0, int(y0 + r) + 1), max(0, int(x0 - r)):min(n1, int(x0 + r) + 1)]
    v = img[ys, xs]
    ok = np.isfinite(v) & (np.hypot(xs - x0, ys - y0) <= r)
    if ok.sum() < 12:
        return None
    X, Y, V = xs[ok].astype(float), ys[ok].astype(float), v[ok].astype(float)

    def g(c, a, xc, yc, sg, b):
        return a * np.exp(-((c[0] - xc) ** 2 + (c[1] - yc) ** 2) / (2 * sg * sg)) + b
    b0 = float(np.percentile(V, 10))
    try:
        p, cov = curve_fit(g, (X, Y), V, p0=[max(float(V.max()) - b0, 1e-3) * 2, x0, y0, 1.2, b0],
                           bounds=([0, x0 - 3, y0 - 3, 0.5, -np.inf], [np.inf, x0 + 3, y0 + 3, 4.0, np.inf]), maxfev=4000)
    except Exception:  # noqa: BLE001
        return None
    e = np.sqrt(np.clip(np.diag(cov), 0, None))
    if not np.all(np.isfinite(e[1:3])) or e[1] > 1 or e[2] > 1:
        return None
    return float(p[1]), float(p[2]), float(np.hypot(e[1], e[2]))


def _read_stacks(path):
    """pass/stacks.bin -> float32 array [P, B, n, n] (header: four little-endian int32)."""
    raw = Path(path).read_bytes()
    P, B, n, _ = struct.unpack("<4i", raw[:16])
    return np.frombuffer(raw[16:], np.float16).astype(np.float32).reshape(P, B, n, n)


def measured_motion(out, passes, band):
    """Fit the target's position in each pass's stack; compare the first-to-last shift with the catalogue's."""
    st = _read_stacks(out / "pass" / "stacks.bin")
    fits = []
    for q in passes:
        fp = fit_position(st[q["k"], band], q["x"], q["y"])
        q["fit"] = None if fp is None else {"x": round(fp[0], 3), "y": round(fp[1], 3), "err": round(fp[2], 3)}
        fits.append(fp)
    if len(passes) < 2 or fits[0] is None or fits[-1] is None:
        return None
    a, b = passes[0], passes[-1]
    dmeas = np.hypot(fits[-1][0] - fits[0][0], fits[-1][1] - fits[0][1]) * PIX_ARCSEC
    dpred = np.hypot(b["x"] - a["x"], b["y"] - a["y"]) * PIX_ARCSEC
    err = np.hypot(fits[0][2], fits[-1][2]) * PIX_ARCSEC
    return {"band": band, "measured_arcsec": round(float(dmeas), 2), "predicted_arcsec": round(float(dpred), 2),
            "err_arcsec": round(float(err), 2), "days": round((b["mjd0"] + b["mjd1"] - a["mjd0"] - a["mjd1"]) / 2, 1)}


def wing_flux(out, doc):
    """Relative brightness from the PSF wings (an annulus outside a saturated core), from the stored cube.
    For a fixed PSF the wings carry a fixed fraction of the light, so within one detector the wing flux tracks
    the total flux even when the core is saturated. Units are arbitrary per detector."""
    img = np.load(out / "cube" / "img.npy", mmap_mode="r")
    fl = np.load(out / "cube" / "flag.npy", mmap_mode="r")
    n = img.shape[1]
    for p in doc["target"]["points"]:
        p.pop("w", None)
        i, x, y = p["i"], p["x"], p["y"]
        y0, y1 = max(0, int(y - W_SKY1 - 1)), min(n, int(y + W_SKY1 + 2))
        x0, x1 = max(0, int(x - W_SKY1 - 1)), min(n, int(x + W_SKY1 + 2))
        im = img[i, y0:y1, x0:x1].astype(np.float32)
        good = ~(fl[i, y0:y1, x0:x1] & 1).astype(bool) & np.isfinite(im)
        r = np.hypot(np.arange(x0, x1)[None, :] - x, np.arange(y0, y1)[:, None] - y)
        ann = (r >= W_IN) & (r < W_OUT)
        sky = (r >= W_SKY0) & (r < W_SKY1) & good
        g = ann & good
        n_ann, n_g = ann.sum(), g.sum()             # numpy int64: keeps the float64 product of the original
        if n_ann == 0 or n_g < 0.7 * n_ann or sky.sum() < 30:
            continue
        p["w"] = round(float((im[g] - np.median(im[sky])).sum() * n_ann / n_g), 2)


def neighbours(out, passes, max_arcsec=24.0):
    """Gaia stars close enough to leak into the target's aperture (at the middle pass)."""
    try:
        ov = read_json(out / "overlays.json")
    except OSError:
        return []
    gaia = ov.get("gaia", [])
    if not passes or not gaia:
        return []
    mid = passes[len(passes) // 2]
    m = (mid["mjd0"] + mid["mjd1"]) / 2
    col = {k: np.array([s[k] for s in gaia], float) for k in ("x", "y", "pmx", "pmy", "mjd0")}
    dt = (m - col["mjd0"]) / 365.25
    d = np.hypot(col["x"] + col["pmx"] * dt - mid["x"], col["y"] + col["pmy"] * dt - mid["y"]) * PIX_ARCSEC
    keep = np.flatnonzero((d > 1.0) & (d < max_arcsec))   # the target itself (if in Gaia) is at ~0
    res = [{"sep": round(float(d[j]), 1), "g": gaia[j]["m"]} for j in keep]
    return sorted(res, key=lambda r: r["sep"])


def annotate(tid):
    """Rebuild the field from the cutout cache, write the lab products, and add the named target."""
    out = FIELDS / tid
    doc = read_json(out / "field.json")

    def log(m):
        print(tid, m, flush=True)
    exps = pipeline.load_exposures(doc["ra"], doc["dec"], doc["size_deg"], log=log)
    f = pipeline.build_field(exps, doc["ra"], doc["dec"], doc["size_deg"])
    del exps
    build_products(f, doc, out, log=log)
    t = targets.TARGETS.get(tid)
    if t:
        pts, passes = target_points(f, doc, t)
        doc["target"] = {"id": tid, "name": t["name"], "kind": t["kind"], "about": t["about"], "source": t["source"],
                         "ra": t["ra"], "dec": t["dec"], "pmra": t["pmra"], "pmdec": t["pmdec"], "plx": t["plx"], "epoch": t["epoch"],
                         "pm_total": round(float(np.hypot(t["pmra"], t["pmdec"])) / 1000, 3),
                         "points": pts, "passes": passes, "aperture_px": R_AP, "neighbours": neighbours(out, passes)}
        wing_flux(out, doc)
        if t["kind"] == "pm":
            doc["target"]["motion"] = measured_motion(out, passes, MOTION_BAND.get(tid, 0))
            print(tid, "motion:", doc["target"]["motion"], flush=True)
        print(tid, f"target: {len(pts)} frames, {sum(p['f'] is not None for p in pts)} with photometry", flush=True)
    write_doc(out, doc)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit(__doc__.splitlines()[0])
    cmd, ids = argv[0], argv[1:] or list(targets.TARGETS)
    for tid in ids:
        t0 = time.time()
        (analyze if cmd == "analyze" else annotate)(tid)
        print(tid, cmd, f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
