"""Automatic proper-motion search on per-pass stacks (no catalogue in the detection step).

For each survey pass the field has a median stack of every exposure (band 0) and of each detector array (1-6).
1. detect sources in the first and last pass stacks (band 0) and fit each with a Gaussian (a saturated core is NaN
   in the stacks, so a saturated star is fitted on its wings);
2. register the two passes on the bulk of the stars (median offset) and measure every source's shift;
3. significance = shift / (fit errors + the systematic floor measured from bright stars in the same field);
4. a shift must also show up, in the same direction, in at least two detector arrays separately: a blend of two
   stars of different colour moves its centroid when the band mix changes, a real mover moves in every band;
5. only then are Gaia DR3 / CatWISE2020 consulted, to label each candidate as a known mover (catalogue motion
   agrees), a likely artefact (catalogue says the star is static) or new.

search() is this pass-to-pass search. search_all() adds the cross-epoch stage against CatWISE2020 positions (stars
down to ~0.1"/yr) and a joint proper-motion + parallax fit of every candidate; both live in xepoch.py.
"""
import hashlib
import math
import threading
from collections import OrderedDict

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

PIX = 6.15                     # arcsec per field pixel
MIN_SIG = 5.0                  # significance of the shift
MIN_SHIFT_PX = 0.12            # ~0.75 arcsec: below this the PSF-undersampling systematics dominate
MATCH_PX = 3.5                 # a source moving up to ~20"/yr is still matched across one year
DUP_PX = 1.5                   # two fitted sources closer than this are one star (several peaks of a saturated ring)
LABEL_PX = 2.0                 # a catalogue source this close to a candidate labels it
STATIC_PM = 0.15               # arcsec/yr: a catalogue motion below this is "static"
DET_ARRAYS = range(1, 7)       # the six detector-array stacks (band 1-6)


def _robust_sigma(v):
    v = v[np.isfinite(v)]
    return 1.4826 * float(np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def fit_position(img, x0, y0, r=5.0):
    """Gaussian + background fit around (x0, y0). Returns (x, y, err_px, amp) or None."""
    from scipy.optimize import curve_fit
    n0, n1 = img.shape
    ya, yb, xa, xb = max(0, int(y0 - r)), min(n0, int(y0 + r) + 1), max(0, int(x0 - r)), min(n1, int(x0 + r) + 1)
    ys, xs = np.mgrid[ya:yb, xa:xb]
    v = img[ya:yb, xa:xb]
    ok = np.isfinite(v) & (np.hypot(xs - x0, ys - y0) <= r)
    if ok.sum() < 12:
        return None
    X, Y, V = xs[ok].astype(float), ys[ok].astype(float), v[ok].astype(float)

    def g(c, a, xc, yc, sg, b):
        return a * np.exp(-((c[0] - xc) ** 2 + (c[1] - yc) ** 2) / (2 * sg * sg)) + b
    b0 = float(np.percentile(V, 10))
    try:
        p, cov = curve_fit(g, (X, Y), V, p0=[max(float(V.max()) - b0, 1e-3), x0, y0, 1.0, b0],
                           bounds=([0, x0 - 2.5, y0 - 2.5, 0.4, -np.inf], [np.inf, x0 + 2.5, y0 + 2.5, 3.0, np.inf]), maxfev=3000)
    except Exception:  # noqa: BLE001
        return None
    e = np.sqrt(np.clip(np.diag(cov), 0, None))
    if not np.all(np.isfinite(e[1:3])) or e[1] > 0.7 or e[2] > 0.7:
        return None
    return float(p[1]), float(p[2]), float(np.hypot(e[1], e[2])), float(p[0])


def detect(img, nsig=6.0, edge=6):
    """Peaks of the lightly smoothed image above nsig x its robust noise. Returns [(x, y, snr)]."""
    good = np.isfinite(img)
    if good.sum() < 100:
        return []
    bg = float(np.nanmedian(img))
    sm = gaussian_filter(np.where(good, img - bg, 0.0), 0.8)
    sig = _robust_sigma(sm[good])
    if not np.isfinite(sig) or sig <= 0:
        return []
    # a saturated core is NaN: fill holes with a high value so the star still gives one peak
    hole = ~good & (gaussian_filter(good.astype(float), 1.5) > 0.5)
    sm = np.where(hole, np.nanmax(sm) if np.isfinite(sm).any() else 0, sm)
    pk = (sm == maximum_filter(sm, 3)) & (sm > nsig * sig)
    pk[:edge] = pk[-edge:] = False
    pk[:, :edge] = pk[:, -edge:] = False
    ys, xs = np.nonzero(pk)
    return [(float(x), float(y), float(sm[y, x] / sig)) for x, y in zip(xs, ys)]


class _Near:
    """Points added so far on a grid of cell size r: near(x, y) is True when one lies closer than r (constant time
    per query instead of a scan of every earlier point)."""

    def __init__(self, r):
        self.r, self.cells = r, {}

    def _cell(self, x, y):
        return math.floor(x / self.r), math.floor(y / self.r)

    def near(self, x, y):
        cx, cy = self._cell(x, y)
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for px, py in self.cells.get((i, j), ()):
                    if math.hypot(x - px, y - py) < self.r:
                        return True
        return False

    def add(self, x, y):
        self.cells.setdefault(self._cell(x, y), []).append((x, y))


# Fitted sources per stack image, keyed by its content: the pass-to-pass search and the cross-epoch stage
# (xepoch.frames) fit the same stacks, and the Gaussian fits are the slow part of both.
_SRC_CACHE, _SRC_CACHE_MAX, _SRC_LOCK = OrderedDict(), 48, threading.Lock()


def _img_key(img):
    a = np.ascontiguousarray(img)
    return a.shape, a.dtype.str, hashlib.blake2b(a.view(np.uint8).reshape(-1), digest_size=16).digest()


def _sources(img):
    """Detected and Gaussian-fitted sources of one stack, brightest first: [{x, y, err, snr}] (fresh dicts)."""
    key = _img_key(img)
    with _SRC_LOCK:
        hit = _SRC_CACHE.get(key)
        if hit is not None:
            _SRC_CACHE.move_to_end(key)
    if hit is None:
        hit, seen = [], _Near(DUP_PX)
        for x, y, snr in sorted(detect(img), key=lambda t: -t[2]):
            f = fit_position(img, x, y)
            if f is None or seen.near(f[0], f[1]):
                continue                                     # one star, several peaks (saturated ring)
            seen.add(f[0], f[1])
            hit.append({"x": f[0], "y": f[1], "err": f[2], "snr": snr})
        with _SRC_LOCK:
            _SRC_CACHE[key] = hit
            while len(_SRC_CACHE) > _SRC_CACHE_MAX:
                _SRC_CACHE.popitem(last=False)
    return [dict(s) for s in hit]


def _match(a, b, r=MATCH_PX, kx="x", ky="y"):
    """Nearest source of b to each source of a (None beyond r px), on the coordinates kx, ky."""
    if not b:
        return [None] * len(a)
    if not a:
        return []
    from scipy.spatial import cKDTree
    d, k = cKDTree(np.c_[[s[kx] for s in b], [s[ky] for s in b]]).query(np.c_[[s[kx] for s in a], [s[ky] for s in a]])
    return [b[j] if dj <= r else None for dj, j in zip(d, k)]


def _floor(dx, dy, err, snr):
    """Systematic positional noise between two passes, beyond the fit errors, from the best-measured stars."""
    still = np.hypot(dx, dy) < 1.0                     # real movers and mismatched pairs must not set the floor
    order = np.argsort(-snr)
    ref = order[still[order]][: max(8, int((snr[still] >= 20).sum()))]
    if ref.size < 5:
        return 0.2
    sx, sy = _robust_sigma(dx[ref]), _robust_sigma(dy[ref])
    tot2 = (sx * sx + sy * sy) / 2
    return float(np.sqrt(max(tot2 - np.median(err[ref] ** 2), 0.02 ** 2)))


def _vacated(img_later, img_first, s, t):
    """For a shift of a pixel or more: the star must have left its first position (and not have been at the second
    one before). Otherwise two different stars were paired."""
    if np.hypot(t["x"] - s["x"], t["y"] - s["y"]) < 1.0:
        return True
    for img, here, other in ((img_later, s, t), (img_first, t, s)):
        f = fit_position(img, here["x"], here["y"], r=2.5)
        if f is not None and np.hypot(f[0] - here["x"], f[1] - here["y"]) < 0.6 and np.hypot(f[0] - other["x"], f[1] - other["y"]) > 1.0:
            return False
    return True


def linear_ok(track, pass_mjd, shift, err):
    """Proper motion is a straight line in time (parallax is small at SPHEREx's pass spacing for anything not
    extremely close): every intermediate pass must sit near the line from the first to the last position.
    A pair matched across two different stars, or a variable blend, jumps instead."""
    if len(track) < 3:
        return True
    a, z = track[0], track[-1]
    ta, tz = pass_mjd[a["k"]] if "mjd" not in a else a["mjd"], pass_mjd[z["k"]] if "mjd" not in z else z["mjd"]
    for q in track[1:-1]:
        tq = q.get("mjd", pass_mjd[q["k"]])
        u = (tq - ta) / max(tz - ta, 1e-6)
        off = np.hypot(q["x"] - (a["x"] + u * (z["x"] - a["x"])), q["y"] - (a["y"] + u * (z["y"] - a["y"])))
        if off > max(0.35 * shift, 3 * err, 0.3):
            return False
    return True


def _search_band(stacks, pass_mjd, b, cdelt):
    P = stacks.shape[0]
    a_k, z_k = 0, P - 1
    dt_yr = (pass_mjd[z_k] - pass_mjd[a_k]) / 365.25
    A, Z = _sources(stacks[a_k, b]), _sources(stacks[z_k, b])
    mz = _match(A, Z)
    pairs = [(s, t) for s, t in zip(A, mz) if t is not None]
    if len(pairs) < 10:
        return [], {"band": b, "reason": "too_few_sources", "n_a": len(A), "n_z": len(Z)}
    dx = np.array([t["x"] - s["x"] for s, t in pairs]); dy = np.array([t["y"] - s["y"] for s, t in pairs])
    snr = np.array([min(s["snr"], t["snr"]) for s, t in pairs])
    ferr = np.array([np.hypot(s["err"], t["err"]) for s, t in pairs])
    order = np.argsort(-snr)[: max(8, int((snr >= 20).sum()))]
    ox, oy = float(np.median(dx[order])), float(np.median(dy[order]))      # frame registration between passes
    floor = _floor(dx - ox, dy - oy, ferr, snr)
    stats = {"band": b, "n_a": len(A), "n_z": len(Z), "n_pairs": len(pairs), "offset_px": [round(ox, 3), round(oy, 3)],
             "floor_px": round(floor, 4), "dt_yr": round(dt_yr, 3)}
    cands = []
    for (s, t), ddx, ddy in zip(pairs, dx - ox, dy - oy):
        shift = float(np.hypot(ddx, ddy))
        err = float(np.sqrt(s["err"] ** 2 + t["err"] ** 2 + floor ** 2))
        sig = shift / err
        if sig < MIN_SIG or shift < MIN_SHIFT_PX:
            continue
        if not _vacated(stacks[z_k, b], stacks[a_k, b], s, t):
            continue
        # the same shift in the detector arrays separately (seeded at the detection positions)
        bands = []
        for d in DET_ARRAYS:
            fa = fit_position(stacks[a_k, d], s["x"], s["y"])
            fz = fit_position(stacks[z_k, d], t["x"], t["y"])
            if fa is None or fz is None:
                continue
            bx, by = fz[0] - fa[0] - ox, fz[1] - fa[1] - oy
            be = float(np.sqrt(fa[2] ** 2 + fz[2] ** 2 + floor ** 2))
            ok = np.hypot(bx - ddx, by - ddy) <= max(0.5 * shift, 2.5 * be) and np.hypot(bx, by) / be >= 2
            bands.append({"d": d, "dx": round(float(bx), 3), "dy": round(float(by), 3), "err": round(be, 3), "agree": bool(ok)})
        n_fit, n_agree = len(bands), sum(bb["agree"] for bb in bands)
        if n_agree < 2:
            continue
        track = [{"k": a_k, "x": round(s["x"], 3), "y": round(s["y"], 3)}]
        for k in range(1, P - 1):
            f = (pass_mjd[k] - pass_mjd[a_k]) / max(pass_mjd[z_k] - pass_mjd[a_k], 1e-6)
            fp = fit_position(stacks[k, b], s["x"] + f * (t["x"] - s["x"]), s["y"] + f * (t["y"] - s["y"]))
            if fp is not None:
                track.append({"k": k, "x": round(fp[0], 3), "y": round(fp[1], 3)})
        track.append({"k": z_k, "x": round(t["x"], 3), "y": round(t["y"], 3)})
        if not linear_ok(track, pass_mjd, shift, err):
            continue
        sx, sy = ddx * PIX / dt_yr, ddy * PIX / dt_yr
        pmra = -sx if cdelt[0] < 0 else sx                                    # x grows to the west when cdelt1 < 0
        cands.append({"x": round(s["x"], 2), "y": round(s["y"], 2), "snr": round(float(min(s["snr"], t["snr"])), 1), "det_band": b,
                      "dx": round(float(ddx), 3), "dy": round(float(ddy), 3), "shift_px": round(shift, 3), "sig": round(sig, 1),
                      "err_px": round(err, 3), "pm_arcsec_yr": round(float(np.hypot(sx, sy)), 3), "pmra": round(float(pmra), 3),
                      "pmdec": round(float(sy), 3), "n_bands_fit": n_fit, "n_bands_agree": n_agree, "bands": bands, "track": track})
    return cands, stats


DETECT_BANDS = (0, 5, 6)       # all bands, and D5/D6 (3.8-5.0 um) where cold brown dwarfs are brightest


def search(stacks, pass_mjd, overlays=None, cdelt=(-PIX / 3600, PIX / 3600), log=print):
    """stacks: float array [P, 7, n, n]; pass_mjd: mid-time of each pass. Returns {"candidates": [...], "stats": {...}}."""
    P = stacks.shape[0]
    if P < 2:
        return {"candidates": [], "stats": {"reason": "one_pass"}}
    found, per = [], []
    for b in DETECT_BANDS:
        c, st = _search_band(stacks, pass_mjd, b, cdelt)
        per.append(st)
        found += c
    cands, seen = [], _Near(DUP_PX)                    # one entry per star: its most significant detection band
    for x in sorted(found, key=lambda q: -q["sig"]):
        if not seen.near(x["x"], x["y"]):
            seen.add(x["x"], x["y"])
            cands.append(x)
    dt_yr = (pass_mjd[-1] - pass_mjd[0]) / 365.25
    for c in cands:                                    # the motion: median of the detection and every agreeing detector
        v = np.array([[c["dx"], c["dy"]]] + [[b["dx"], b["dy"]] for b in c["bands"] if b["agree"]])
        mx, my = np.median(v, axis=0)
        sx, sy = mx * PIX / dt_yr, my * PIX / dt_yr
        c.update(dx=round(float(mx), 3), dy=round(float(my), 3), pm_arcsec_yr=round(float(np.hypot(sx, sy)), 3),
                 pmra=round(float(-sx if cdelt[0] < 0 else sx), 3), pmdec=round(float(sy), 3))
    _label(cands, overlays, pass_mjd[0], dt_yr)
    # an unexplained mover must be seen on its line in every intermediate pass: when the fit at the predicted
    # position fails, linear_ok() had nothing to test, and a pair of different stars can pass for a mover
    # (Kapteyn's Star field, D5: a 3.3 px "shift" between a star and a neighbour, middle pass not found)
    unverified = [c for c in cands if P >= 3 and len(c["track"]) < P and c["status"] in ("new", "mismatch")]
    drop = {id(u) for u in unverified}
    cands = [c for c in cands if id(c) not in drop]
    cands.sort(key=lambda c: -c["sig"])
    for i, c in enumerate(cands):
        c["id"] = i
    stats = {"per_band": per, "dt_yr": round(dt_yr, 3), "n_candidates": len(cands), "n_new": sum(c["status"] == "new" for c in cands),
             "floor_px": per[0].get("floor_px"), "n_pairs": per[0].get("n_pairs"), "n_unverified": len(unverified)}
    log(f"  pm search: {', '.join(f'band {s_["band"]}: {s_.get("n_pairs", 0)} matched, floor {s_.get("floor_px", "-")} px' for s_ in per)}; "
        f"{len(cands)} movers ({stats['n_new']} new)")
    return {"candidates": cands, "stats": stats}


def search_all(stacks, pass_mjd, overlays=None, cdelt=(-PIX / 3600, PIX / 3600), ra=None, dec=None, pass_times=None, log=print):
    """search() plus two things that need the catalogues' positions (sxlib/xepoch.py):
    - a cross-epoch stage: SPHEREx against CatWISE2020 (2015.4), which reaches ~0.1"/yr for isolated stars;
    - a joint proper-motion + parallax fit of every candidate over all passes (needs the field centre ra, dec;
      pass_times = exposure MJDs of each pass, for the parallax factors).
    Candidates gain: method ("spherex" | "xepoch"), baseline_yr, pm_err_arcsec_yr, plx_mas, plx_err_mas, dist_pc."""
    res = search(stacks, pass_mjd, overlays, cdelt=cdelt, log=log)
    if stacks.shape[0] < 2:
        return res
    from .xepoch import extend
    try:
        return extend(res, stacks, pass_mjd, overlays, cdelt, ra, dec, pass_times, log)
    except Exception as e:  # noqa: BLE001 - the pass-to-pass result stands on its own
        log(f"  cross-epoch stage skipped: {e}")
        return res


def _label(cands, ov, mjd_a, dt_yr):
    """known: a catalogue source within 2 px whose own motion agrees; static: the catalogue says it does not move
    (so the measured shift is probably a blend or artefact); new: nothing in the catalogues explains it."""
    for c in cands:
        c["status"], c["match"] = "new", None
    if not ov:
        return
    srcs = [("Gaia DR3", s) for s in ov.get("gaia", [])] + [("CatWISE2020", s) for s in ov.get("catwise", [])]
    if not srcs or not cands:
        return
    pmx = np.array([s["pmx"] for _, s in srcs], float); pmy = np.array([s["pmy"] for _, s in srcs], float)
    t = (mjd_a - np.array([s["mjd0"] for _, s in srcs], float)) / 365.25
    sx = np.array([s["x"] for _, s in srcs], float) + pmx * t
    sy = np.array([s["y"] for _, s in srcs], float) + pmy * t
    dt = max(dt_yr, 1e-6)
    for c in cands:
        d = np.hypot(sx - c["x"], sy - c["y"])
        d[~np.isfinite(d)] = np.inf
        i = int(np.argmin(d))                                                 # first of equals, as a strict "<" scan
        if not d[i] <= LABEL_PX:
            continue
        cat, s = srcs[i]
        pm_cat = float(np.hypot(s["pmx"], s["pmy"])) * PIX                    # arcsec/yr
        c["match"] = {"cat": cat, "sep_px": round(float(d[i]), 2), "mag": s.get("m"), "pm_cat": round(pm_cat, 3)}
        # compare vectors in pixels per year
        mv = np.array([c["dx"], c["dy"]]) / dt                                # registered shift, px/yr
        cv = np.array([s["pmx"], s["pmy"]])
        if pm_cat >= STATIC_PM and np.linalg.norm(mv - cv) <= max(0.35 * np.linalg.norm(cv), 0.12 / dt):
            c["status"] = "known"
        elif pm_cat < STATIC_PM:
            c["status"] = "static"
        else:
            c["status"] = "mismatch"
