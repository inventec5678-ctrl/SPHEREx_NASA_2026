"""Is the bright spot at field pixel (x, y) really a star? For the web page (/api/field/<id>/starcheck), run in the
measurement worker pool like sxlib/measure.py.

The model is a point source: a star is a point of light, so in the image it takes the shape of the telescope's
point-spread function (PSF), the same for every star in the field. The check, all on the calibrated data cube:

  1. the median of all exposures around the spot (SPHEREx sees the field through different parts of its detectors
     each time, so detector artefacts, cosmic rays and ghosts, which do not stay on one sky position, drop out);
  2. its signal-to-noise against the surrounding sky;
  3. a fit of a round Gaussian (the PSF model) to it, its width compared with the width of catalogued stars in the
     same field: much wider is not a single star (a galaxy, a nebula, a blend), much narrower is not light from the
     sky (a bad pixel);
  4. in how many single exposures it is there on its own (a star is there every time);
  5. what the pixel flags say (saturated, ghost, persistence);
  6. whether Gaia or CatWISE has a star there (positions carried to the time of the observations).
"""
import warnings
from functools import lru_cache
from pathlib import Path

from .measure import _cube, _doc, _mtime, _render

R = 9          # half-size of the stamp, pixels
FL_BAD, FL_GHOST, FL_OUTLIER, FL_SAT, FL_PERSIST = 1, 4, 8, 16, 32
N_REF = 25             # reference stars for the field's PSF width
REF_MIN_SNR = 20       # ... at least this bright in the median stack
SAT_SKIP = 0.3         # a spot saturated in more than this share of exposures is not fitted
MATCH_PX = 1.5         # catalogue match radius


def _paths(fdir):
    fdir = Path(fdir)
    doc = _doc(str(fdir / "field.json"), _mtime(fdir / "field.json"))
    c = _cube(str(fdir / "cube"), _mtime(fdir / "cube" / "img.npy"))
    return fdir, doc, c


def _stamp(c, x0, y0):
    import numpy as np
    n = c["img"].shape[1]
    ya, yb, xa, xb = max(0, y0 - R), min(n, y0 + R + 1), max(0, x0 - R), min(n, x0 + R + 1)
    img = np.asarray(c["img"][:, ya:yb, xa:xb], dtype=np.float32)
    var = np.asarray(c["var"][:, ya:yb, xa:xb], dtype=np.float32)
    fl = np.asarray(c["flag"][:, ya:yb, xa:xb])
    img[(fl & FL_BAD) != 0] = np.nan
    return img, var, fl, xa, ya


def _bkg(med, cx, cy):
    """Sky level and its scatter in an annulus 5-9 px around (cx, cy) of the stamp."""
    import numpy as np
    yy, xx = np.mgrid[:med.shape[0], :med.shape[1]]
    r = np.hypot(xx - cx, yy - cy)
    a = med[(r >= 5) & (r <= 9) & np.isfinite(med)]
    if a.size < 10:
        return 0.0, 1.0
    b = float(np.median(a))
    return b, float(1.4826 * np.median(np.abs(a - b))) or 1e-6


def _fit(med, cx, cy, b):
    """Round Gaussian + flat sky on the 7x7 pixels around (cx, cy): returns (fwhm_px, fraction of light the model
    misses) or None."""
    import numpy as np
    from scipy.optimize import least_squares
    h = 3
    ys, xs = slice(max(0, cy - h), cy + h + 1), slice(max(0, cx - h), cx + h + 1)
    z = med[ys, xs]
    yy, xx = np.mgrid[ys, xs]
    ok = np.isfinite(z)
    if ok.sum() < 12:
        return None
    z, yy, xx = z[ok] - b, yy[ok], xx[ok]
    a0 = float(np.nanmax(z))
    if a0 <= 0:
        return None

    def res(p):
        a, x, y, s, c0 = p
        return a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s * s)) + c0 - z

    try:
        r = least_squares(res, [a0, cx, cy, 0.8, 0.0], bounds=([0, cx - 2, cy - 2, 0.2, -a0], [10 * a0, cx + 2, cy + 2, 6, a0]))
    except Exception:  # noqa: BLE001
        return None
    resid = float(np.sum(np.abs(r.fun)) / max(np.sum(np.abs(z)), 1e-6))
    return 2.3548 * float(r.x[3]), resid


def _catalogue(fdir, doc):
    """Gaia and CatWISE stars with positions carried to the mean time of the observations."""
    import json
    p = Path(fdir) / "overlays.json"
    if not p.exists():
        return []
    ov = json.loads(p.read_text())
    t = sum(e["mjd"] for e in doc["exposures"]) / max(1, len(doc["exposures"]))
    out = []
    for cat in ("gaia", "catwise"):
        for s in ov.get(cat) or []:
            dt = (t - s.get("mjd0", t)) / 365.25
            out.append({"cat": cat, "x": s["x"] + s.get("pmx", 0) * dt, "y": s["y"] + s.get("pmy", 0) * dt, "m": s.get("m"),
                        "pm": (s.get("pmx", 0) ** 2 + s.get("pmy", 0) ** 2) ** 0.5})
    return out


@lru_cache(maxsize=16)
def _ref_fwhm(fdir, mtime):
    """The PSF width of this field's stack: the median fitted width of up to 25 isolated, unsaturated Gaia stars."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return _ref_fwhm_calc(fdir)


def _ref_fwhm_calc(fdir):
    import numpy as np
    _, doc, c = _paths(fdir)
    n = c["img"].shape[1]
    cat = [s for s in _catalogue(fdir, doc) if s["cat"] == "gaia" and R < s["x"] < n - R - 1 and R < s["y"] < n - R - 1]
    cat.sort(key=lambda s: s["m"] if s["m"] is not None else 99)
    cx = np.array([s["x"] for s in cat], float); cy = np.array([s["y"] for s in cat], float)
    cm = np.array([s["m"] or 99 for s in cat], float)
    widths = []
    for s in cat:
        if len(widths) >= N_REF:
            break
        d = np.hypot(cx - s["x"], cy - s["y"])
        if ((0 < d) & (d < 5) & (cm < (s["m"] or 99) + 3)).any():
            continue                                        # a neighbour bright enough to widen the fit
        x0, y0 = int(round(s["x"])), int(round(s["y"]))
        img, var, fl, xa, ya = _stamp(c, x0, y0)
        if ((fl[:, y0 - ya, x0 - xa] & FL_SAT) != 0).mean() > 0.05:
            continue
        med = np.nanmedian(img, axis=0)
        b, sd = _bkg(med, x0 - xa, y0 - ya)
        if not np.isfinite(med[y0 - ya, x0 - xa]) or (med[y0 - ya, x0 - xa] - b) / sd < REF_MIN_SNR:
            continue
        f = _fit(med, x0 - xa, y0 - ya, b)
        if f and f[1] < 0.5:
            widths.append(f[0])
    return float(np.median(widths)) if len(widths) >= 3 else None, len(widths)


def check(fdir, x, y):
    """(HTTP status, rendered JSON bytes) of the star check at field pixel (x, y)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # all-NaN columns in the median are expected (bad pixels)
        return _check(fdir, x, y)


def _check(fdir, x, y):
    import numpy as np
    fdir, doc, c = _paths(fdir)
    n = c["img"].shape[1]
    if not (0 <= x < n and 0 <= y < n):
        return 422, "outside"
    x0, y0 = int(round(x)), int(round(y))
    img, var, fl, xa, ya = _stamp(c, x0, y0)
    med = np.nanmedian(img, axis=0)
    # snap to the brightest pixel within 2 px of the click
    cx, cy = x0 - xa, y0 - ya
    best = None
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            qx, qy = cx + dx, cy + dy
            if 0 <= qy < med.shape[0] and 0 <= qx < med.shape[1] and dx * dx + dy * dy <= 4:
                sat = ((fl[:, qy, qx] & FL_SAT) != 0).mean()
                v = np.inf if sat > SAT_SKIP else med[qy, qx]
                if np.isfinite(v) or v == np.inf:
                    if best is None or v > best[0]:
                        best = (v, qx, qy)
    if best is None:
        return 200, _render({"x": x, "y": y, "verdict": "none", "tests": {}})
    _, cx, cy = best
    sx, sy = cx + xa, cy + ya
    b, sd = _bkg(med, cx, cy)
    flc = fl[:, cy, cx]
    sat_frac = float(((flc & FL_SAT) != 0).mean())
    usable = (flc & FL_BAD) == 0
    tests = {"n_exp": int(len(flc)), "sat_frac": round(sat_frac, 3),
             "ghost_frac": round(float(((flc & FL_GHOST) != 0).mean()), 3),
             "persist_frac": round(float(((flc & FL_PERSIST) != 0).mean()), 3)}

    # catalogue match within 1.5 px
    cat = _catalogue(str(fdir), doc)
    dist = np.hypot(np.array([s["x"] for s in cat], float) - sx, np.array([s["y"] for s in cat], float) - sy)
    m = [cat[i] for i in np.argsort(dist, kind="stable") if dist[i] < MATCH_PX]
    gaia = next((s for s in m if s["cat"] == "gaia"), None)
    cw = next((s for s in m if s["cat"] == "catwise"), None)
    cd = abs(doc["wcs"]["cdelt"][1]) * 3600
    tests["gaia"] = None if not gaia else {"m": round(gaia["m"], 2) if gaia["m"] is not None else None, "pm": round(gaia["pm"] * cd, 3)}
    tests["catwise"] = None if not cw else {"m": round(cw["m"], 2) if cw["m"] is not None else None}

    # the AI (real/bogus CNN): it scores what is left after the reference sky is subtracted, so it only sees things
    # that move or change. Detections within 2 px of this spot in any exposure, with its probability.
    p_link = doc.get("p_link") or 0.5
    dets = [cd_ for cd_ in doc.get("candidates", []) if (cd_["x"] - sx) ** 2 + (cd_["y"] - sy) ** 2 <= 4]
    ai = {"p": [round(d["p"], 3) for d in dets][:60], "n": len(dets), "n_real": sum(1 for d in dets if d["p"] >= p_link), "p_max": round(max((d["p"] for d in dets), default=0), 3), "p_link": p_link}
    trk = next((d["track"] for d in dets if d.get("track") is not None), None)
    if trk is not None and trk < len(doc.get("tracks", [])):
        t = doc["tracks"][trk]
        ai["track"] = {k: t.get(k) for k in ("id", "kind", "known", "d_au", "rate_arcsec_h")}
    tests["ai"] = ai

    if sat_frac > SAT_SKIP:
        return 200, _render({"x": sx, "y": sy, "verdict": "saturated", "tests": tests})

    peak = float(med[cy, cx] - b)
    tests["snr"] = round(peak / sd, 1)
    if not np.isfinite(peak) or peak / sd < 5:
        return 200, _render({"x": sx, "y": sy, "verdict": "none", "tests": tests})

    # present in each exposure on its own: 3x3 sum minus sky, against its noise
    ys, xs = slice(max(0, cy - 1), cy + 2), slice(max(0, cx - 1), cx + 2)
    flux = np.nansum(img[:, ys, xs], axis=(1, 2)) - b * 9
    noise = np.sqrt(np.nansum(var[:, ys, xs], axis=(1, 2))) + 1e-9
    use = usable & np.isfinite(img[:, cy, cx])
    det = (flux / noise > 3) & use
    tests["present"] = int(det.sum()); tests["usable"] = int(use.sum())
    tests["seq"] = "".join("1" if d else ("0" if u else "-") for d, u in zip(det, use))     # each exposure, in time order

    f = _fit(med, cx, cy, b)
    ref, nref = _ref_fwhm(str(fdir), _mtime(fdir / "field.json"))
    # the light against distance from the centre, every pixel within 5 px, scaled to the peak: drawn against the model
    yy, xx = np.mgrid[:med.shape[0], :med.shape[1]]
    rr = np.hypot(xx - cx, yy - cy)
    m5 = (rr <= 5) & np.isfinite(med)
    tests["profile"] = [[round(float(r_), 2), round(float(v), 3)] for r_, v in zip(rr[m5], (med[m5] - b) / max(peak, 1e-9))]
    tests["fwhm"] = None if f is None else round(f[0], 2)
    tests["fwhm_ref"] = None if ref is None else round(ref, 2)
    tests["n_ref"] = nref
    tests["resid"] = None if f is None else round(f[1], 2)

    frac = tests["present"] / max(1, tests["usable"])
    ratio = None if (f is None or ref is None) else f[0] / ref
    tests["width_ratio"] = None if ratio is None else round(ratio, 2)
    if tests["usable"] >= 5 and frac < 0.5:
        verdict = "transient"                 # there only now and then: not a fixed point on the sky
    elif ratio is not None and ratio > 1.6:
        verdict = "extended"
    elif ratio is not None and ratio < 0.55:
        verdict = "sharp"
    elif ratio is None:
        verdict = "unfit"
    else:
        verdict = "star"
    if verdict in ("star", "extended", "unfit"):
        tests["spectrum"] = _spectrum(c, doc, sx, sy)
    return 200, _render({"x": sx, "y": sy, "verdict": verdict, "tests": tests})


def _spectrum(c, doc, x, y):
    """The model's prediction from the light: forced photometry at (x, y) in every exposure (each exposure sees its
    own wavelength), then a blackbody / power-law fit (star with a temperature, or galaxy-like) and the brown-dwarf
    spectral classifier."""
    import numpy as np
    from .specclass import phot_stamp
    from .specfit import bin_spectrum, fit_star
    ds = doc.get("products", {}).get("lam_ds", 5)
    ly, lx = min(int(y) // ds, c["lam"].shape[1] - 1), min(int(x) // ds, c["lam"].shape[2] - 1)
    L, F, E = [], [], []
    for i in range(c["img"].shape[0]):
        # only a stamp around (x, y) is read from the memory-mapped cube, not the whole exposure
        p = phot_stamp(c["img"][i], c["var"][i], c["flag"][i], x, y)
        if p is None:
            continue
        lam = float(c["lam"][i, ly, lx])
        L.append(lam if np.isfinite(lam) else doc["exposures"][i]["lam_um"]); F.append(p[0]); E.append(p[1])
    spec = bin_spectrum(L, F, E)
    fit = fit_star(spec)
    out = None if fit is None else {"kind": fit["kind"], "T": round(fit["T"]), "distance_pc": round(fit["distance_pc"], 1) if fit.get("distance_pc") else None,
                                    "bins": [[round(a, 3), round(b_, 2), round(e, 2)] for a, b_, e in spec]}
    try:
        from .specclass import score_points
        bd = score_points(L, F, E)
        if out is not None and bd is not None:
            out["bd"] = round(bd, 3)
    except Exception:  # noqa: BLE001 - the classifier is optional
        pass
    return out
