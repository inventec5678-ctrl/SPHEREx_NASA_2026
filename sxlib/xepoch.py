"""Cross-epoch proper motion and a joint proper-motion + parallax fit.

SPHEREx alone spans about one year, so a star has to move ~0.75"/yr before the pass-to-pass search (pmsearch.py) can
see it. CatWISE2020 measured the same sources around 2015.4 at a similar angular resolution, so comparing where a
source is in the SPHEREx pass stacks with where CatWISE put it gives a ~11 year baseline and a ~10x smaller limit.

Cross-epoch stage (candidates):
1. sources are detected and fitted in every pass stack (pmsearch._sources), in the all-band stack and in D5 / D6;
2. each pass is registered to Gaia DR3 stars moved to that pass's epoch (affine fit, sigma clipped). Gaia fixes the
   frame only: it never chooses a candidate;
3. each source is paired with the CatWISE2020 entry at its position (CatWISE's own motion is used for the pairing
   only); its motion is (SPHEREx position - CatWISE position) / baseline, averaged over the passes;
4. the error is the fit error plus a floor measured from the bulk of isolated sources in the same field (most stars
   do not move measurably in 11 years);
5. a candidate is significant (>= 5 sigma, >= 0.08"/yr), seen in at least two passes that agree, away from the
   border, not saturated, shows the same offset in at least two detector arrays and none that contradicts it, and
   is isolated: no comparable catalogue source within 3 px (18"). CatWISE lists the two members of a blend
   separately while SPHEREx measures their common centroid, which fakes an offset; this cut removes every false
   alarm on the eight fields analysed on 2026-11-12 but also half of the real stars;
6. only then is Gaia consulted for the label (known / static / mismatch / new), as in pmsearch._label.

Joint fit (joint): position, proper motion and parallax (5 parameters) through all passes, in the frame of the first
pass (rel_frames: every star two passes share, not only the Gaia ones). Parallax factors are averaged over the
exposures of each pass and band. Cross-epoch candidates are also anchored on the CatWISE position, which carries no
parallax. The same fit on the field's static stars (plx_null) calibrates the error; a parallax is reported only at
>= 3 sigma with an acceptable fit, and never for a saturated star with a single degree of freedom.

Measured on the eight fields (scripts/pm_search.py --validate, 2026-11-12): motion scatter against Gaia 14 mas/yr
per axis for isolated stars; 0 of 1270 stars Gaia calls static were flagged; half of the sources are isolated; the
significance cut keeps 48% of isolated stars at 0.10"/yr, 79% at 0.15"/yr and 91% at 0.30"/yr. Static stars scatter
by 70-135 mas in parallax, so only objects within about 3 pc could show one.
"""
import numpy as np

from .pmsearch import DET_ARRAYS, DUP_PX, PIX, _match, _Near, _robust_sigma, _sources, fit_position

MJD_CATWISE = 57170.0          # the epoch products.overlays() assigns to CatWISE2020 positions
R_REG = 1.0                    # px: source <-> Gaia pairing for the frame
R_CW = 1.5                     # px: source <-> CatWISE pairing (9"; ~0.8"/yr over 11 yr without CatWISE's own motion)
ISO_PX = 3.0                   # px: a comparable catalogue neighbour inside this radius makes a source "not isolated"
ISO_DMAG = 2.5                 # ... comparable = at most this much fainter (10% of the flux)
NB_PX = 4.5                    # neighbours are recorded out to here
MIN_SIG = 5.0
MIN_PM = 0.08                  # arcsec/yr: below this the frame systematics (blends, colour terms) dominate
BANDS = (0, 5, 6)              # all bands; D5 and D6 for sources that are only bright at 4-5 um
REG_MIN_SNR = 10               # sources used to register a pass (on Gaia, or on pass 0)
FLOOR_SNR = 20                 # well-measured stars that set the noise floors
MIN_AFFINE = 12                # fewer frame stars than this: translation only (or a borrowed all-band map)


# ---- frame -------------------------------------------------------------------------------------------------------
def affine(src, dst, clip=3.0, iters=5):
    """dst ~ [x, y, 1] @ C with sigma clipping. Returns (C[3,2], keep mask, rms px); a shift only when few points."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    keep = np.ones(len(src), bool)
    if len(src) < 4:
        return None, keep, np.nan
    C = None
    for _ in range(iters):
        n = int(keep.sum())
        if n < 4:
            return None, keep, np.nan
        if n >= 12:
            A = np.c_[src[keep], np.ones(n)]
            C, *_ = np.linalg.lstsq(A, dst[keep], rcond=None)
        else:                                               # too few stars for six parameters: translation
            C = np.vstack([np.eye(2), np.median(dst[keep] - src[keep], axis=0)])
        res = np.hypot(*(np.c_[src, np.ones(len(src))] @ C - dst).T)
        s = max(1.4826 * float(np.median(res[keep])), 0.03)
        new = res <= clip * s
        if (new == keep).all():
            break
        keep = new
    rms = float(np.sqrt(np.mean(res[keep] ** 2))) if keep.any() else np.nan
    return C, keep, rms


def apply(C, x, y):
    v = np.c_[np.atleast_1d(x), np.atleast_1d(y), np.ones(np.size(x))] @ C
    return v[:, 0], v[:, 1]


def _at(cat, mjd):
    """Catalogue positions moved to mjd with the catalogue's own motion. Returns x, y, mag arrays."""
    if not cat:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    t = (mjd - np.array([s["mjd0"] for s in cat], float)) / 365.25
    x = np.array([s["x"] for s in cat], float) + np.array([s["pmx"] for s in cat], float) * t
    y = np.array([s["y"] for s in cat], float) + np.array([s["pmy"] for s in cat], float) * t
    m = np.array([np.nan if s.get("m") is None else s["m"] for s in cat], float)
    return x, y, m


def register(S, gaia, mjd):
    """Affine map from stack pixels to the catalogue frame, from clean Gaia stars at this pass's epoch."""
    from scipy.spatial import cKDTree
    gx, gy, gm = _at(gaia, mjd)
    if len(gx) < 4 or len(S) < 4:
        return None, {"n": 0}
    tree = cKDTree(np.c_[gx, gy])
    sx, sy = np.array([s["x"] for s in S]), np.array([s["y"] for s in S])
    d, j = tree.query(np.c_[sx, sy])
    use = [k for k in range(len(S)) if d[k] <= R_REG and S[k]["snr"] >= REG_MIN_SNR]
    nbs = tree.query_ball_point(np.c_[gx[j[use]], gy[j[use]]], ISO_PX) if use else []
    src, dst = [], []
    for k, nb in zip(use, nbs):
        jk = j[k]
        if any(q != jk and (not np.isfinite(gm[q]) or gm[q] < gm[jk] + ISO_DMAG) for q in nb):
            continue                                        # a comparable neighbour pulls the SPHEREx centroid
        src.append([sx[k], sy[k]]); dst.append([gx[jk], gy[jk]])
    C, keep, rms = affine(src, dst)
    return C, {"n": int(keep.sum()) if C is not None else 0, "n_paired": len(src), "rms_px": None if C is None else round(rms, 4)}


# ---- parallax ----------------------------------------------------------------------------------------------------
def parallax_factors(ra_deg, dec_deg, mjd):
    """Offsets (east, north) in arcsec per arcsec of parallax at the given times (Earth's barycentric position)."""
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time
    e = get_body_barycentric("earth", Time(np.atleast_1d(mjd), format="mjd"), ephemeris="builtin").xyz.to_value("au")
    a, d = np.radians(ra_deg), np.radians(dec_deg)
    east = e[0] * np.sin(a) - e[1] * np.cos(a)
    north = e[0] * np.cos(a) * np.sin(d) + e[1] * np.sin(a) * np.sin(d) - e[2] * np.cos(d)
    return east, north


def pass_factors(ra_deg, dec_deg, pass_mjd, pass_times=None):
    """Parallax factors of each pass stack: the mean over its exposures when their times are known."""
    ts = [np.atleast_1d(np.asarray(pass_times[k] if pass_times is not None and len(pass_times[k]) else [m], float))
          for k, m in enumerate(pass_mjd)]
    if not ts:
        return []
    e, n = parallax_factors(ra_deg, dec_deg, np.concatenate(ts))           # one ephemeris call for every pass
    cut = np.cumsum([len(t) for t in ts])[:-1]
    return [(float(np.mean(a)), float(np.mean(b))) for a, b in zip(np.split(e, cut), np.split(n, cut))]


def fit_motion(t_yr, east, north, err, pf=None):
    """Weighted least squares for position + proper motion (+ parallax when pf, the (east, north) parallax factors,
    is given). Everything in arcsec and years. Returns a dict with the parameters, their covariance and chi2."""
    t_yr, east, north, err = (np.asarray(v, float) for v in (t_yr, east, north, err))
    n = len(t_yr)
    t0 = float(np.average(t_yr, weights=1 / err ** 2))
    cols = 5 if pf is not None else 4
    A = np.zeros((2 * n, cols)); b = np.r_[east, north]; w = np.r_[1 / err, 1 / err]
    A[:n, 0] = 1; A[:n, 2] = t_yr - t0
    A[n:, 1] = 1; A[n:, 3] = t_yr - t0
    if pf is not None:
        A[:n, 4] = [p[0] for p in pf]; A[n:, 4] = [p[1] for p in pf]
    Aw = A * w[:, None]
    p, *_ = np.linalg.lstsq(Aw, b * w, rcond=None)
    try:
        cov = np.linalg.inv(Aw.T @ Aw)
    except np.linalg.LinAlgError:
        return None
    res = (A @ p - b) * w
    chi2, dof = float(res @ res), 2 * n - cols
    return {"p": p, "cov": cov, "chi2": chi2, "dof": dof, "t0": t0,
            "pm": (float(p[2]), float(p[3])), "pm_err": (float(np.sqrt(cov[2, 2])), float(np.sqrt(cov[3, 3]))),
            "plx": float(p[4]) if pf is not None else None, "plx_err": float(np.sqrt(cov[4, 4])) if pf is not None else None}


# ---- cross-epoch measurement -------------------------------------------------------------------------------------
def cw_pm_sigma(w2):
    """Per-axis error of CatWISE2020's own motion (arcsec/yr) by W2 magnitude. Measured on these fields against Gaia
    DR3 (2026-11-12, 2252 isolated stars): 10 mas/yr to W2 = 13, 13 at 13-14, 17 at 14-15, 24 at 15-16, 37 at 16-17."""
    w2 = 13.0 if w2 is None or not np.isfinite(w2) else float(w2)
    return 0.010 * 10 ** (0.14 * max(0.0, w2 - 13.0))


def _east_north(dx_px, dy_px, cdelt):
    """Pixel offsets -> (east, north) arcsec. x grows to the west when cdelt1 < 0."""
    return (-dx_px if cdelt[0] < 0 else dx_px) * PIX, dy_px * PIX


def frames(stacks, pass_mjd, ov, bands=BANDS):
    """Sources and the affine map to the catalogue frame for every (band, pass).
    A detector band with too few Gaia stars of its own borrows the all-band map of the same pass."""
    P = stacks.shape[0]
    out = {}
    for b in bands:
        for k in range(P):
            S = _sources(stacks[k, b])
            C, info = register(S, ov.get("gaia", []), pass_mjd[k])
            if (C is None or info["n"] < MIN_AFFINE) and b != 0 and out.get((0, k), {}).get("C") is not None:
                C, info = out[(0, k)]["C"], dict(info, borrowed=True)
            if C is not None and S:
                X, Y = apply(C, [s["x"] for s in S], [s["y"] for s in S])
                for s, x_, y_ in zip(S, X, Y):
                    s["X"], s["Y"] = float(x_), float(y_)
            out[(b, k)] = {"S": S, "C": C, "info": info}
    return out


def pass_floor(fr, b, P):
    """Positional noise of one pass stack beyond the fit error (px, per axis): scatter of the registered positions
    of well-measured stars between pairs of passes."""
    v = []
    for k in range(1, P):
        A, Z = fr[(b, 0)], fr[(b, k)]
        if A["C"] is None or Z["C"] is None:
            continue
        for s, t in zip(A["S"], _match_reg(A["S"], Z["S"], 1.0)):
            if t is not None and min(s["snr"], t["snr"]) >= FLOOR_SNR:
                v.append((t["X"] - s["X"], t["Y"] - s["Y"], s["err"] ** 2 + t["err"] ** 2))
    if len(v) < 8:
        return 0.05
    v = np.array(v)
    tot2 = _robust_sigma(v[:, 0]) ** 2 + _robust_sigma(v[:, 1]) ** 2          # two axes x two passes
    return float(np.sqrt(max((tot2 - np.median(v[:, 2])) / 4, 0.015 ** 2)))


def _match_reg(a, b, r):
    """Nearest source of b to each source of a in the registered frame (None beyond r px)."""
    return _match(a, b, r, "X", "Y")


def measure(stacks, pass_mjd, ov, cdelt, bands=BANDS, fr=None):
    """Cross-epoch motion of every source paired with a CatWISE entry. Returns (stars, stats, frames).
    Each star: ref position, per-pass positions, motion (east, north arcsec/yr), isolation flag, catalogue indices."""
    from scipy.spatial import cKDTree
    P = stacks.shape[0]
    fr = fr or frames(stacks, pass_mjd, ov, bands)
    cat = ov.get("catwise", [])
    stats = {"n_catwise": len(cat), "n_gaia": len(ov.get("gaia", [])), "reg": {f"{b}:{k}": fr[(b, k)]["info"] for b, k in fr}}
    if len(cat) < 10:
        return [], dict(stats, reason="no_catwise"), fr
    cx = np.array([s["x"] for s in cat]); cy = np.array([s["y"] for s in cat])
    cm = np.array([99.0 if s.get("m") is None else s["m"] for s in cat])
    cpx = np.array([s["pmx"] for s in cat]); cpy = np.array([s["pmy"] for s in cat])
    tree_c = cKDTree(np.c_[cx, cy])
    stars, seen = [], _Near(DUP_PX)
    for b in bands:
        ks = [k for k in range(P) if fr[(b, k)]["C"] is not None]
        if not ks:
            continue
        z = ks[-1]
        gx, gy, gm = _at(ov.get("gaia", []), pass_mjd[z])
        tree_g = cKDTree(np.c_[gx, gy]) if len(gx) else None
        dtz = (pass_mjd[z] - MJD_CATWISE) / 365.25
        tree_p = cKDTree(np.c_[cx + cpx * dtz, cy + cpy * dtz])
        Sz = fr[(b, z)]["S"]
        # each source of the last pass, paired with its counterpart in every other pass (one tree per pass)
        pair = {k: _match_reg(Sz, fr[(b, k)]["S"], 1.5) for k in ks if k != z}
        for i_s, s in enumerate(Sz):
            if seen.near(s["x"], s["y"]):
                continue                                    # already measured in an earlier band
            # CatWISE pairing: where CatWISE's own motion puts each entry now, or where it was
            near = set(tree_p.query_ball_point([s["X"], s["Y"]], R_CW)) | set(tree_c.query_ball_point([s["X"], s["Y"]], R_CW))
            if not near:
                continue
            dist = {j: min(np.hypot(cx[j] + cpx[j] * dtz - s["X"], cy[j] + cpy[j] * dtz - s["Y"]), np.hypot(cx[j] - s["X"], cy[j] - s["Y"])) for j in near}
            j = min(dist, key=dist.get)
            # neighbours that could be blended into the centroid or paired by mistake: (separation px, how much fainter)
            nb = [(float(np.hypot(cx[q] - cx[j], cy[q] - cy[j])), float(cm[q] - cm[j]), "c")
                  for q in set(tree_c.query_ball_point([cx[j], cy[j]], NB_PX)) | near if q != j]
            jg = None
            if tree_g is not None:
                dg, jq = tree_g.query([s["X"], s["Y"]])
                jg = int(jq) if dg <= R_REG else None
                g0 = gm[jg] if jg is not None and np.isfinite(gm[jg]) else 17.5 - ISO_DMAG
                nb += [(float(np.hypot(gx[q] - s["X"], gy[q] - s["Y"])), float(gm[q] - g0) if np.isfinite(gm[q]) else 0.0, "g")
                       for q in tree_g.query_ball_point([s["X"], s["Y"]], NB_PX) if q != jg]
            iso = not any(d_ <= ISO_PX and dm < ISO_DMAG for d_, dm, _ in nb)
            ep = []
            for k in ks:
                t = s if k == z else pair[k][i_s]
                if t is None:
                    continue
                dt = (pass_mjd[k] - MJD_CATWISE) / 365.25
                ep.append({"k": k, "x": t["x"], "y": t["y"], "X": t["X"], "Y": t["Y"], "err": t["err"], "snr": t["snr"], "dt": dt,
                           "vx": (t["X"] - cx[j]) / dt, "vy": (t["Y"] - cy[j]) / dt})          # px/yr
            w = np.array([1 / max(e["err"], 0.01) ** 2 for e in ep])
            vx = float(np.sum(w * [e["vx"] for e in ep]) / w.sum()); vy = float(np.sum(w * [e["vy"] for e in ep]) / w.sum())
            dtm = float(np.mean([e["dt"] for e in ep]))
            seen.add(s["x"], s["y"])
            stars.append({"band": b, "x": s["x"], "y": s["y"], "X": s["X"], "Y": s["Y"], "snr": s["snr"], "ep": ep, "j": int(j), "jg": jg,
                          "iso": bool(iso), "nb": nb, "w2": float(cm[j]), "vx": vx, "vy": vy, "baseline_yr": dtm,
                          "fit_err": float(1 / np.sqrt(w.sum())) / dtm / np.sqrt(2)})          # per axis, px/yr
    # error floor per axis from the bulk: most stars do not move measurably in 11 years
    bulk = [q for q in stars if q["iso"] and q["snr"] >= FLOOR_SNR] or [q for q in stars if q["iso"]]
    if len(bulk) >= 15:
        v = np.array([[q["vx"], q["vy"]] for q in bulk])
        tot2 = (_robust_sigma(v[:, 0]) ** 2 + _robust_sigma(v[:, 1]) ** 2) / 2
        floor = float(np.sqrt(max(tot2 - np.median([q["fit_err"] ** 2 for q in bulk]), (0.010 / PIX) ** 2)))
    else:
        floor = 0.025 / PIX                                 # typical of the fields with enough stars to measure it
    for q in stars:
        q["err"] = float(np.hypot(q["fit_err"], floor))     # per axis, px/yr
        q["pm"] = float(np.hypot(q["vx"], q["vy"]) * PIX)
        q["sig"] = float(np.hypot(q["vx"], q["vy"]) / q["err"])
    stats.update(n_measured=len(stars), n_isolated=sum(q["iso"] for q in stars), floor_arcsec_yr=round(floor * PIX, 4), n_bulk=len(bulk))
    return stars, stats, fr


def detectors(q, stacks, fr, cat, floor):
    """The same cross-epoch motion measured in each detector array separately (px/yr), seeded at the star's
    positions in the detection band. A blend of two stars of different colour has a centroid that depends on the
    band, so its apparent offset from CatWISE changes from detector to detector; a real mover's does not."""
    c = cat[q["j"]]
    out = []
    # the all-band map of each pass when there is one, else the detection band's
    maps = {e["k"]: (fr[(0, e["k"])]["C"] if (0, e["k"]) in fr and fr[(0, e["k"])]["C"] is not None
                     else fr[(q["band"], e["k"])]["C"]) for e in q["ep"]}
    for d in DET_ARRAYS:
        v, w = [], []
        for e in q["ep"]:
            C = maps[e["k"]]
            f = fit_position(stacks[e["k"], d], e["x"], e["y"])
            if f is None or C is None:
                continue
            X, Y = apply(C, f[0], f[1])
            v.append(((X[0] - c["x"]) / e["dt"], (Y[0] - c["y"]) / e["dt"])); w.append(1 / max(f[2], 0.01) ** 2)
        if not v:
            continue
        v, w = np.array(v), np.array(w)
        vx, vy = float(np.sum(w * v[:, 0]) / w.sum()), float(np.sum(w * v[:, 1]) / w.sum())
        err = float(np.hypot(1 / np.sqrt(w.sum()) / q["baseline_yr"] / np.sqrt(2), floor))
        diff, pm = float(np.hypot(vx - q["vx"], vy - q["vy"])), float(np.hypot(q["vx"], q["vy"]))
        out.append({"d": d, "vx": vx, "vy": vy, "err": err, "n": len(v),
                    "agree": bool(diff <= max(0.5 * pm, 2.5 * err) and np.hypot(vx, vy) / err >= 2),
                    "against": bool(diff > max(0.5 * pm, 4 * err))})
    return out


def passes_consistent(q, floor_px):
    """The SPHEREx passes must agree with each other: over one year a cross-epoch candidate moves far less than a
    pixel, so its registered position may only change by its own motion plus the noise."""
    if len(q["ep"]) < 2:
        return False
    for e in q["ep"]:
        px, py = q["ep"][-1]["X"] - (q["ep"][-1]["dt"] - e["dt"]) * q["vx"], q["ep"][-1]["Y"] - (q["ep"][-1]["dt"] - e["dt"]) * q["vy"]
        tol = max(3 * np.sqrt(e["err"] ** 2 + q["ep"][-1]["err"] ** 2 + 4 * floor_px ** 2), 0.2)
        if np.hypot(e["X"] - px, e["Y"] - py) > tol:
            return False
    return True


def saturated(img, x, y, r=2):
    n0, n1 = img.shape
    v = img[max(0, int(round(y)) - r):min(n0, int(round(y)) + r + 1), max(0, int(round(x)) - r):min(n1, int(round(x)) + r + 1)]
    return bool((~np.isfinite(v)).any())


# ---- candidates --------------------------------------------------------------------------------------------------
EDGE_PX = 8                    # stacks are shallow and distorted at the border
MIN_W2 = 6.0                   # brighter than this CatWISE itself saturates


def label(c, q, ov, mjd):
    """known: a catalogue already lists this motion; static: Gaia says the star does not move (so the offset is an
    artefact); mismatch: the catalogue motion is different; new: no Gaia entry, and CatWISE's own motion was too
    uncertain to show it. Same statuses and match record as pmsearch._label."""
    v = np.array([q["vx"], q["vy"]]) * PIX
    err = q["err"] * PIX
    if q["jg"] is not None:
        g = ov["gaia"][q["jg"]]
        gv = np.array([g["pmx"], g["pmy"]]) * PIX
        pm_cat = float(np.hypot(*gv))
        c["match"] = {"cat": "Gaia DR3", "sep_px": round(float(np.hypot(g["x"] + g["pmx"] * (mjd - g["mjd0"]) / 365.25 - q["X"],
                                                                         g["y"] + g["pmy"] * (mjd - g["mjd0"]) / 365.25 - q["Y"])), 2),
                      "mag": g.get("m"), "pm_cat": round(pm_cat, 3)}
        if pm_cat >= 0.05 and np.hypot(*(v - gv)) <= max(0.35 * pm_cat, 4.2 * err, 0.03):
            c["status"] = "known"
        elif pm_cat < 0.05:
            c["status"] = "static"
        else:
            c["status"] = "mismatch"
        return
    w = ov["catwise"][q["j"]]
    wv = np.array([w["pmx"], w["pmy"]]) * PIX
    pm_cat, se = float(np.hypot(*wv)), cw_pm_sigma(w.get("m"))
    c["match"] = {"cat": "CatWISE2020", "sep_px": round(float(np.hypot(w["x"] + w["pmx"] * q["baseline_yr"] - q["X"], w["y"] + w["pmy"] * q["baseline_yr"] - q["Y"])), 2),
                  "mag": w.get("m"), "pm_cat": round(pm_cat, 3)}
    agree = np.hypot(*(v - wv)) <= max(0.35 * pm_cat, 3 * np.sqrt(2) * np.hypot(err, se))
    if not agree:
        c["status"] = "mismatch"
    elif pm_cat >= 3 * np.sqrt(2) * se:
        c["status"] = "known"                               # CatWISE2020 measured this motion by itself
    else:
        c["status"] = "new"


def candidates(stacks, pass_mjd, ov, cdelt, fr=None):
    """Cross-epoch candidates in the pm_candidates.json schema. Returns (candidates, stats, stars, frames)."""
    P, n = stacks.shape[0], stacks.shape[-1]
    stars, stats, fr = measure(stacks, pass_mjd, ov, cdelt, fr=fr)
    if not stars:
        return [], stats, stars, fr
    cat = ov["catwise"]
    floor = stats["floor_arcsec_yr"] / PIX
    dt_yr = (pass_mjd[-1] - pass_mjd[0]) / 365.25
    out, why, pfl = [], {}, {}
    for q in stars:
        if q["sig"] < MIN_SIG or q["pm"] < MIN_PM:
            continue
        ref = q["ep"][-1]
        if q["band"] not in pfl:
            pfl[q["band"]] = pass_floor(fr, q["band"], P)
        bad = ("few_passes" if len(q["ep"]) < 2 else "edge" if min(q["x"], q["y"], n - 1 - q["x"], n - 1 - q["y"]) < EDGE_PX
               else "not_isolated" if not q["iso"] else "bright" if q["w2"] < MIN_W2
               else "saturated" if saturated(stacks[ref["k"], q["band"]], q["x"], q["y"])
               else "passes_disagree" if not passes_consistent(q, pfl[q["band"]]) else None)
        if bad is None:
            dd = detectors(q, stacks, fr, cat, floor)
            q["dets"] = dd
            if sum(d["agree"] for d in dd) < 2:
                bad = "detectors_disagree"
            elif any(d["against"] for d in dd):
                bad = "colour_dependent"
        if bad:
            why[bad] = why.get(bad, 0) + 1
            continue
        pe, pn = _east_north(q["vx"], q["vy"], cdelt)
        ep0 = q["ep"][0]
        w = cat[q["j"]]
        c = {"x": round(ep0["x"], 2), "y": round(ep0["y"], 2), "snr": round(float(q["snr"]), 1), "det_band": q["band"],
             "dx": round(q["vx"] * dt_yr, 4), "dy": round(q["vy"] * dt_yr, 4), "shift_px": round(float(np.hypot(q["vx"], q["vy"]) * dt_yr), 4),
             "sig": round(q["sig"], 1), "err_px": round(q["err"] * dt_yr, 4), "pm_arcsec_yr": round(q["pm"], 3),
             "pmra": round(float(pe), 3), "pmdec": round(float(pn), 3),
             "n_bands_fit": len(q["dets"]), "n_bands_agree": sum(d["agree"] for d in q["dets"]),
             "bands": [{"d": d["d"], "pm_x": round(d["vx"] * PIX, 3), "pm_y": round(d["vy"] * PIX, 3), "err": round(d["err"] * PIX, 3), "agree": d["agree"]} for d in q["dets"]],
             "track": [{"k": e["k"], "x": round(e["x"], 3), "y": round(e["y"], 3)} for e in q["ep"]],
             "method": "xepoch", "baseline_yr": round(q["baseline_yr"], 2), "pm_err_arcsec_yr": round(q["err"] * PIX, 4),
             "cw": {"x": w["x"], "y": w["y"], "mjd": w["mjd0"], "w2": w.get("m"), "pm_own": round(float(np.hypot(w["pmx"], w["pmy"]) * PIX), 3)}}
        label(c, q, ov, pass_mjd[ref["k"]])
        c["_q"] = q
        out.append(c)
    out.sort(key=lambda c: -c["sig"])
    stats.update(n_significant=len(out) + sum(why.values()), rejected=why, n_candidates=len(out),
                 limit_arcsec_yr=round(max(MIN_PM, MIN_SIG * float(np.median([q["err"] for q in stars if q["iso"]] or [floor])) * PIX), 3))
    return out, stats, stars, fr


# ---- joint proper motion + parallax ------------------------------------------------------------------------------
def rel_frames(fr, b, P):
    """Maps from each pass's stack pixels to those of pass 0, from every star the two passes share in band b (far
    more stars than the clean Gaia ones, so pass-to-pass positions are tighter than through the catalogue frame).
    Returns (C per pass or None, per-axis noise floor of each pass in px: the star-to-star scatter plus the
    uncertainty of that pass's map, which matters where a band has few stars)."""
    S0 = fr[(b, 0)]["S"]
    C, dif, reg = [np.vstack([np.eye(2), [0.0, 0.0]])], [], [0.0]
    for k in range(1, P):
        pairs = [(t, s) for t, s in zip(fr[(b, k)]["S"], _match(fr[(b, k)]["S"], S0, 1.0))
                 if s is not None and min(s["snr"], t["snr"]) >= REG_MIN_SNR]
        Ck, keep, rms = affine([[t["x"], t["y"]] for t, _ in pairs], [[s["x"], s["y"]] for _, s in pairs]) if len(pairs) >= 6 else (None, None, None)
        C.append(Ck)
        if Ck is None:
            reg.append(np.nan)
            continue
        n = int(keep.sum())
        reg.append(float(rms / np.sqrt(2) / np.sqrt(max(n - (3 if n >= MIN_AFFINE else 1), 1))))
        for (t, s_), ok in zip(pairs, keep):
            if ok and min(s_["snr"], t["snr"]) >= FLOOR_SNR:
                X, Y = apply(Ck, t["x"], t["y"])
                dif.append((X[0] - s_["x"], Y[0] - s_["y"], s_["err"] ** 2 + t["err"] ** 2))
    if len(dif) < 8:
        fl = 0.03
    else:
        dif = np.array(dif)
        tot2 = _robust_sigma(dif[:, 0]) ** 2 + _robust_sigma(dif[:, 1]) ** 2
        fl = float(np.sqrt(max((tot2 - np.median(dif[:, 2])) / 4, 0.01 ** 2)))
    return C, [float(np.hypot(fl, r)) if np.isfinite(r) else fl for r in reg]


def joint(epochs, cdelt, pf, tm, anchor=None, scale=1.0, trust_one_dof=True):
    """Five-parameter fit (position, proper motion, parallax) through pass positions [{k, X, Y, err, floor}] in one
    frame (err = 2-D fit error in px, floor = per-axis systematic in px) and, optionally, an anchor
    {X, Y, mjd, err_arcsec} that carries no parallax (a multi-year catalogue mean). pf = parallax factors and
    tm = mean time of each pass. The parallax is reported only when the fit is acceptable and it is >= 3 sigma; the
    error is the formal one scaled by this star's residuals and by `scale`, the spread of the same fit on the
    field's static stars (plx_null). Returns a dict; plx_mas is None when nothing can be claimed."""
    if len(epochs) < 3:
        return {"plx_mas": None, "reason": "fewer_than_3_passes", "n_pass": len(epochs)}
    X0, Y0, t0 = epochs[0]["X"], epochs[0]["Y"], tm[epochs[0]["k"]]
    t, E, N, S, F = [], [], [], [], []
    for e in epochs:
        de, dn = _east_north(e["X"] - X0, e["Y"] - Y0, cdelt)
        t.append((tm[e["k"]] - t0) / 365.25); E.append(de); N.append(dn); F.append(pf[e["k"]])
        S.append(np.sqrt(e["err"] ** 2 / 2 + e.get("floor", 0.03) ** 2) * PIX)
    if anchor is not None:
        de, dn = _east_north(anchor["X"] - X0, anchor["Y"] - Y0, cdelt)
        t.append((anchor["mjd"] - t0) / 365.25); E.append(de); N.append(dn); F.append((0.0, 0.0)); S.append(anchor["err_arcsec"])
    f = fit_motion(t, E, N, S, F)
    if f is None or f["dof"] < 1:
        return {"plx_mas": None, "reason": "no_degrees_of_freedom", "n_pass": len(epochs)}
    f0 = fit_motion(t, E, N, S)
    from scipy.stats import chi2 as _chi2
    k = float(max(1.0, np.sqrt(f["chi2"] / f["dof"]), scale))
    plx, err = f["plx"] * 1000, f["plx_err"] * 1000 * k
    out = {"n_pass": len(epochs), "anchor": anchor is not None, "chi2": round(f["chi2"], 2), "dof": f["dof"],
           "chi2_no_plx": round(f0["chi2"], 2) if f0 else None, "plx_raw_mas": round(plx, 1), "plx_raw_err_mas": round(err, 1),
           "err_scale": round(k, 2), "pm_fit_arcsec_yr": round(float(np.hypot(*f["pm"])), 3),
           "pmra_fit": round(f["pm"][0], 3), "pmdec_fit": round(f["pm"][1], 3)}
    why = ("poor_fit" if f["chi2"] > _chi2.ppf(0.99, f["dof"]) else "one_dof_unchecked" if f["dof"] < 2 and not trust_one_dof
           else "below_3_sigma" if not (plx > 0 and plx >= 3 * err) else None)
    if why:
        out.update(plx_mas=None, reason=why)
    else:
        out.update(plx_mas=round(plx, 1), plx_err_mas=round(err, 1), dist_pc=round(1000 / plx, 2))
    return out


def plx_null(tracks, cdelt, pf, tm, anchors=None):
    """The same fit on stars that should show no parallax. Returns {n, z_sigma, sigma_mas, frac_3sig}: the spread of
    parallax / error (1 if the errors are right) and of the parallax itself."""
    z, v = [], []
    for i, ep in enumerate(tracks):
        j = joint(ep, cdelt, pf, tm, anchor=anchors[i] if anchors else None)
        if "plx_raw_mas" in j and j["plx_raw_err_mas"] > 0:
            z.append(j["plx_raw_mas"] / j["plx_raw_err_mas"]); v.append(j["plx_raw_mas"])
    if len(z) < 15:
        return {"n": len(z), "z_sigma": None, "sigma_mas": None, "frac_3sig": None}
    z = np.array(z)
    return {"n": len(z), "z_sigma": round(_robust_sigma(z), 2), "sigma_mas": round(_robust_sigma(np.array(v)), 1),
            "frac_3sig": round(float(np.mean(np.abs(z) > 3)), 3)}


def _rel_tracks(fr, b, P, C, floor, min_snr=FLOOR_SNR):
    """Pass positions (frame of pass 0) of every star seen in all passes of band b: the null sample."""
    out = []
    if any(c is None for c in C):
        return out
    S0 = fr[(b, 0)]["S"]
    pair = {k: _match(S0, fr[(b, k)]["S"], 1.0) for k in range(1, P)}
    for i_s, s in enumerate(S0):
        if s["snr"] < min_snr:
            continue
        ep = [{"k": 0, "X": s["x"], "Y": s["y"], "err": s["err"], "floor": floor[0]}]
        for k in range(1, P):
            t = pair[k][i_s]
            if t is None or t["snr"] < min_snr:
                break
            X, Y = apply(C[k], t["x"], t["y"])
            ep.append({"k": k, "X": float(X[0]), "Y": float(Y[0]), "err": t["err"], "floor": floor[k]})
        if len(ep) == P and s["snr"] >= min_snr:
            out.append(ep)
    return out


def extend(res, stacks, pass_mjd, ov, cdelt, ra=None, dec=None, pass_times=None, log=print):
    """Add the cross-epoch stage and the joint fit to a pmsearch.search() result (in place; existing ids are kept)."""
    P = stacks.shape[0]
    dt_yr = (pass_mjd[-1] - pass_mjd[0]) / 365.25
    cands = res["candidates"]
    for c in cands:
        c.update(method="spherex", baseline_yr=round(dt_yr, 2), pm_err_arcsec_yr=round(c["pm_arcsec_yr"] / max(c["sig"], 1e-6), 3),
                 plx_mas=None, plx_err_mas=None, dist_pc=None)
    ov = ov or {"gaia": [], "catwise": []}                    # without catalogues only the joint fit runs
    fr = frames(stacks, pass_mjd, ov)
    xc, xs, stars, fr = candidates(stacks, pass_mjd, ov, cdelt, fr=fr)
    fl_pm = xs.get("floor_arcsec_yr", 0.025)
    null = {}
    if ra is not None and P >= 3:
        # when each pass's stack was taken: the mean over the exposures of that band (a pass can last two months)
        pf, tm, pf_of = {}, {}, {}
        for b in BANDS:
            pt = pass_times.get(b, pass_times.get(0)) if isinstance(pass_times, dict) else pass_times
            if id(pt) not in pf_of:                         # bands sharing exposure times share the factors
                pf_of[id(pt)] = pass_factors(ra, dec, pass_mjd, pt)
            pf[b] = pf_of[id(pt)]
            tm[b] = [float(np.mean(pt[k])) if pt is not None and len(pt[k]) else pass_mjd[k] for k in range(P)]
        rel = {b: rel_frames(fr, b, P) for b in BANDS}
        for b in BANDS:
            null[b] = plx_null(_rel_tracks(fr, b, P, *rel[b]), cdelt, pf[b], tm[b])
        # 1. pass-to-pass movers: SPHEREx passes alone, in the frame of the first pass of their detection band
        for c in cands:
            b = c["det_band"] if c["det_band"] in rel else 0
            C, fl = rel[b]
            ep, sat = [], False
            for t in c["track"]:
                f = fit_position(stacks[t["k"], b], t["x"], t["y"])
                if f is None or C[t["k"]] is None:
                    continue
                X, Y = apply(C[t["k"]], f[0], f[1])
                ep.append({"k": t["k"], "X": float(X[0]), "Y": float(Y[0]), "err": f[2], "floor": fl[t["k"]]})
                sat = sat or saturated(stacks[t["k"], b], f[0], f[1])
            # a saturated star is fitted on its wings; its errors cannot be checked against the (unsaturated) null
            # sample, so with a single degree of freedom nothing is claimed
            j = joint(ep, cdelt, pf[b], tm[b], scale=max(1.0, null[b]["z_sigma"] or 1.25), trust_one_dof=not sat)
            j.update(saturated=sat, null=null[b])
            c["plx_fit"] = j
            c.update(plx_mas=j["plx_mas"], plx_err_mas=j.get("plx_err_mas"), dist_pc=j.get("dist_pc"))
        # 2. cross-epoch movers: the same passes (frame of pass 0, mapped to the catalogue frame) anchored on CatWISE
        def anchored(q):
            C, fl = rel[q["band"]]
            C0 = fr[(q["band"], 0)]["C"]
            if C0 is None or any(C[e["k"]] is None for e in q["ep"]):
                return None, None
            ep = []
            for e in q["ep"]:
                x0, y0 = apply(C[e["k"]], e["x"], e["y"])
                X, Y = apply(C0, x0[0], y0[0])
                ep.append({"k": e["k"], "X": float(X[0]), "Y": float(Y[0]), "err": e["err"], "floor": fl[e["k"]]})
            w = ov["catwise"][q["j"]]
            return ep, {"X": w["x"], "Y": w["y"], "mjd": MJD_CATWISE, "err_arcsec": fl_pm * q["baseline_yr"]}
        bulk = [anchored(q) for q in stars if q["iso"] and q["snr"] >= FLOOR_SNR and len(q["ep"]) == P and q["band"] == 0]
        bulk = [x for x in bulk if x[0] is not None]
        null["anchored"] = plx_null([x[0] for x in bulk], cdelt, pf[0], tm[0], anchors=[x[1] for x in bulk])
        for c in xc:
            ep, an = anchored(c["_q"])
            if ep is None:
                continue
            b = c["_q"]["band"]
            j = joint(ep, cdelt, pf[b], tm[b], anchor=an, scale=max(1.0, null["anchored"]["z_sigma"] or 1.25))
            j["null"] = null["anchored"]
            c["plx_fit"] = j
            c.update(plx_mas=j["plx_mas"], plx_err_mas=j.get("plx_err_mas"), dist_pc=j.get("dist_pc"))
    new = []
    for c in xc:
        c.pop("_q")
        for k in ("plx_mas", "plx_err_mas", "dist_pc"):
            c.setdefault(k, None)
        same = next((o for o in cands if min(np.hypot(o["track"][k]["x"] - c["track"][-1]["x"], o["track"][k]["y"] - c["track"][-1]["y"]) for k in (0, -1)) < 2.0), None)
        if same is not None:                                # the pass-to-pass search already has this star: keep its entry
            same["xepoch"] = {k: c[k] for k in ("pm_arcsec_yr", "pmra", "pmdec", "pm_err_arcsec_yr", "sig", "baseline_yr", "status", "match")}
        else:
            new.append(c)
    for i, c in enumerate(new):
        c["id"] = len(cands) + i
    res["candidates"] = cands + new
    res["stats"]["xepoch"] = dict({k: v for k, v in xs.items() if k != "reg"}, n_added=len(new), plx_null={str(k): v for k, v in null.items()})
    res["stats"]["n_candidates"] = len(res["candidates"])
    res["stats"]["n_new"] = sum(c["status"] == "new" for c in res["candidates"])
    log(f"  cross-epoch: {xs.get('n_measured', 0)} sources paired with CatWISE ({xs.get('n_isolated', 0)} isolated), "
        f"floor {xs.get('floor_arcsec_yr', 0) * 1000:.0f} mas/yr; {len(new)} more movers, rejected {xs.get('rejected', {})}")
    return res
