"""Automatic variable-star search on the stored cube of an analysed field (no position is given in advance).

SPHEREx observes each source through a linear variable filter, so every exposure of a source is at a different
wavelength: comparing raw fluxes mixes the spectrum's shape into the "light curve". Per detector we therefore fit

    F(lambda, t) = S(lambda) * L(pass)

with S a smooth spectrum (a low-order polynomial in log lambda) and L one brightness factor per survey pass.

Steps
  1. Sources: peaks of the all-pass, all-band stack (blind; catalogues only label the result afterwards). A source
     that clearly moved between passes is followed pass by pass, so a high-proper-motion star does not fake a
     dimming. Sources with a close neighbour or a profile wider than a star's are not searched: the undersampled
     PSF turns by 180 degrees between passes and moves the neighbour's light in and out of the aperture.
  2. Forced photometry in every exposure: a 2-pixel aperture, or, in a detector where the core is saturated in
     >= 40% of the exposures, the light in a 3-pixel-wide ring outside the saturated region (the PSF wings scale
     with the total brightness). Points on flagged pixels are dropped, as in the field lab; points are NOT cut on
     their own S/N, because that biases the noisier pass upwards and fakes variability in faint stars.
  3. The fit above, per detector, in flux, sigma-clipped about the model; errors come from the residuals themselves
     (sandwich estimate), not from the pipeline variance.
  4. Ensemble zero points: the median change of the field's own unsaturated, unblended stars between each pair of
     passes is removed per detector (the field calibrates itself; the same correction is applied to ring fluxes).
  5. Error model from the same stars: a systematic floor is added to the fit errors and the result is scaled until
     their differences follow a unit normal. A detector "sees" a change between two passes when it is >= MIN_SIG
     effective sigma AND larger than the amplitude threshold of its method: aperture, MIN_SIG x the pass-to-pass
     scatter of the field's bright stars; ring, RING_MIN_AMP. A candidate needs at least MIN_DETS detectors that see
     the same pair of passes change in the same direction; "sig" is the second-highest detector significance, so
     one detector alone can never make a candidate.
  6. Labels: Gaia DR3 phot_variable_flag and the AAVSO VSX (through the VizieR mirror at CfA).

Run: python scripts/var_search.py [field ids]
"""
import json
import struct
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.ndimage import find_objects, gaussian_filter, maximum_filter
from scipy.ndimage import label as ndlabel

PIX = 6.15
PIX_SR = (PIX / 206264.806) ** 2
R_AP, R_IN, R_OUT = 2.0, 5.0, 9.0                    # the field lab's aperture and sky annulus (sxlib/products.py)
W_IN, W_OUT, W_SKY0, W_SKY1 = 4.5, 7.5, 10.0, 14.0   # the PSF-wing ring (scripts/build_targets.py)
SAT_FRAC = 0.4          # a detector uses the ring when the core is on saturated/bad pixels in this share of exposures
MIN_SIG = 5.0           # effective sigma a detector needs to "see" a change
MIN_DETS = 2            # detectors that must agree on the pair of passes and on the direction
MIN_PTS_PASS = 4        # usable points per pass and detector
MIN_PTS_DET = 12        # usable points per detector
MIN_SNR = 5.0           # median S/N of a detector's points
# Ring photometry of saturated stars has too few examples per field to calibrate there. Fixed values from the eight
# web fields (2026-11-12; scripts/var_search.py prints them again): 190 ring differences of 21 saturated stars that
# are not the two variable targets have a robust scatter of 0.059 in ln flux; 95% are below x1.21 and 99% below x1.27.
RING_SYS = 0.06         # ln units: systematic floor of a ring pass-to-pass difference (that robust scatter)
RING_MIN_AMP = 1.30     # above the 99th percentile; the steady, saturated Barnard's Star reaches x0.94-1.15 per detector
RING_R_MAX = 11.0       # a ring starting further out than this is too faint to use
BLEND_PX = 5.0          # a neighbour peak this close (aperture radius + ~2 PSF widths) ...
BLEND_RATIO = 0.15      # ... and at least this fraction of the source's peak makes the source "blended"
TRACK_PX = 0.5          # a source that moved this much between the first and last pass is followed pass by pass
NEAR_SAT_PX = 12.0      # an unsaturated source this close to a saturated star sits on its wings: not searched
DETECTORS = range(1, 7)


# ---- data ------------------------------------------------------------------------------------------------------
def load_field(field_dir):
    """Everything the search needs from a field directory, in memory."""
    d = Path(field_dir)
    doc = json.loads((d / "field.json").read_text())
    cube = {k: np.load(d / "cube" / f"{k}.npy", mmap_mode="r") for k in ("img", "var", "flag", "lam")}
    with open(d / "pass" / "stacks.bin", "rb") as fh:
        P, B, n, _ = struct.unpack("<4i", fh.read(16))
        stacks = np.frombuffer(fh.read(), np.float16).reshape(P, B, n, n).astype(np.float32)
    N = cube["img"].shape[0]
    ex = doc["exposures"][:N]
    passes = doc["products"]["passes"]
    mjd = np.array([e["mjd"] for e in ex])
    pk = np.full(N, -1)
    for q in passes:
        pk[(mjd >= q["mjd0"] - 1e-6) & (mjd <= q["mjd1"] + 1e-6)] = q["k"]
    return {"doc": doc, "img": np.asarray(cube["img"], np.float32), "var": np.asarray(cube["var"], np.float32),
            "flag": np.asarray(cube["flag"]), "lam": np.asarray(cube["lam"], np.float32),
            "ds": doc["products"].get("lam_ds", 5), "stacks": stacks, "mjd": mjd, "pass": pk,
            "det": np.array([e["detector"] for e in ex]), "lam_um": np.array([e["lam_um"] for e in ex]),
            "pass_mjd": [(q["mjd0"] + q["mjd1"]) / 2 for q in passes]}


# ---- sources ---------------------------------------------------------------------------------------------------
def _robust_sigma(v):
    v = v[np.isfinite(v)]
    return 1.4826 * float(np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def _holes(good):
    """Saturated cores in a stack: connected NaN regions that do not touch the border. [(x, y, radius)]"""
    lab, n = ndlabel(~good)
    out = []
    for k, sl in enumerate(find_objects(lab), 1):
        if sl is None or sl[0].start == 0 or sl[1].start == 0 or sl[0].stop == good.shape[0] or sl[1].stop == good.shape[1]:
            continue
        m = lab[sl] == k
        area = int(m.sum())
        if area < 2 or area > 900:
            continue
        yy, xx = np.nonzero(m)
        out.append((float(xx.mean() + sl[1].start), float(yy.mean() + sl[0].start), float(np.sqrt(area / np.pi))))
    return out


def detect(img, nsig=8.0, edge=int(R_OUT) + 2):
    """Sources of a stack, brightest first: [(x, y, snr, hole_radius, blended)]. A saturated core is a NaN hole in
    the stack: each hole is one source at the hole's centre (hole_radius > 0), and the peaks on its rim are dropped.
    blended: another peak at least BLEND_RATIO as high lies within BLEND_PX. SPHEREx's PSF is undersampled and turns
    by 180 degrees between passes, so the share of a close neighbour's light inside the aperture changes from pass to
    pass; such sources fake variability and are not searched."""
    good = np.isfinite(img)
    if good.sum() < 100:
        return []
    sm = gaussian_filter(np.where(good, img - np.nanmedian(img), 0.0), 0.8)
    sig = _robust_sigma(sm[good])
    if not np.isfinite(sig) or sig <= 0:
        return []
    n0, n1 = img.shape
    holes = [h for h in _holes(good) if edge <= h[0] < n1 - edge and edge <= h[1] < n0 - edge]
    pk = (sm == maximum_filter(sm, 3)) & (sm > 4 * sig) & good
    ys, xs = np.nonzero(pk)
    peaks = np.c_[xs, ys, sm[ys, xs] / sig].astype(float).reshape(-1, 3)
    out = [(x, y, float(np.nanmax(sm) / sig), r, False) for x, y, r in holes]
    if not len(peaks):
        return out
    from scipy.spatial import cKDTree
    from .pmsearch import _Near
    hx, hy, hr = (np.array([h[i] for h in holes], float) for i in range(3))
    taken = _Near(2.5)
    for o in out:
        taken.add(o[0], o[1])
    tree = cKDTree(peaks[:, :2])
    for i in np.argsort(-peaks[:, 2], kind="stable"):            # brightest first
        x, y, snr = peaks[i]
        if snr < nsig or not (edge <= x < n1 - edge and edge <= y < n0 - edge):
            continue
        if len(holes) and (np.hypot(x - hx, y - hy) < hr + 3.5).any():
            continue                                     # the rim of a saturated core
        if taken.near(x, y):
            continue
        nb = np.array(tree.query_ball_point([x, y], BLEND_PX), int)
        d = np.hypot(peaks[nb, 0] - x, peaks[nb, 1] - y)
        blended = bool(((d > 0.5) & (d < BLEND_PX) & (peaks[nb, 2] >= BLEND_RATIO * snr)).any())
        taken.add(x, y)
        out.append((float(x), float(y), float(snr), 0.0, blended))
    return out


def concentration(img, x, y):
    """Light within 1.5 px over light within 3.5 px (local sky removed): lower than a single star's when the source
    is two stars or a galaxy. NaN if it cannot be measured."""
    xi, yi, h = int(round(x)), int(round(y)), int(R_OUT) + 1
    if xi - h < 0 or yi - h < 0 or xi + h + 1 > img.shape[1] or yi + h + 1 > img.shape[0]:
        return np.nan
    st = img[yi - h:yi + h + 1, xi - h:xi + h + 1]
    yy, xx = np.mgrid[yi - h:yi + h + 1, xi - h:xi + h + 1]
    r = np.hypot(xx - x, yy - y)
    sky = st[(r >= R_IN) & (r <= R_OUT) & np.isfinite(st)]
    if sky.size < 20 or not np.isfinite(st[r <= 3.5]).all():
        return np.nan
    v = st - np.median(sky)
    tot = v[r <= 3.5].sum()
    return float(v[r <= 1.5].sum() / tot) if tot > 0 else np.nan


def centroid(img, x, y, r=2.5, max_shift=1.5):
    """Flux-weighted centre near (x, y); NaN pixels (a saturated core) count with the brightest finite value.
    Returns the start position when the centre wanders more than max_shift (a neighbour)."""
    n0, n1 = img.shape
    cx, cy = x, y
    for _ in range(4):
        x0, x1, y0, y1 = int(cx - r - 1), int(cx + r + 2), int(cy - r - 1), int(cy + r + 2)
        if x0 < 0 or y0 < 0 or x1 > n1 or y1 > n0:
            return x, y
        st = img[y0:y1, x0:x1]
        if not np.isfinite(st).any():
            return x, y
        yy, xx = np.mgrid[y0:y1, x0:x1]
        m = np.hypot(xx - cx, yy - cy) <= r
        v = np.where(np.isfinite(st), st, np.nanmax(st)) - np.nanpercentile(st, 10)
        w = np.clip(v, 0, None) * m
        if w.sum() <= 0:
            return x, y
        cx, cy = float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())
    return (cx, cy) if np.hypot(cx - x, cy - y) <= max_shift else (x, y)


def find_sources(stacks):
    """Blind source list from the mean of the passes' all-band stacks. Each source has one position per pass: the
    same for all passes, unless it clearly moved (>= TRACK_PX between the first and last pass, e.g. Barnard's
    Star), in which case each pass uses its own centre. "blended" marks sources with a close neighbour or a profile
    wider than the field's stars (two stars in one peak, or a galaxy)."""
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        allp = np.nanmean(stacks[:, 0], axis=0)
    out = []
    for x, y, snr, rh, blended in detect(allp):
        rc = rh + 2.5
        if not rh:
            x, y = centroid(allp, x, y, r=rc)
        pos = [centroid(stacks[p, 0], x, y, r=rc, max_shift=1.5 + rh / 2) if np.isfinite(stacks[p, 0]).any() else (x, y)
               for p in range(stacks.shape[0])]
        moved = np.hypot(pos[-1][0] - pos[0][0], pos[-1][1] - pos[0][1]) >= TRACK_PX
        out.append({"x": x, "y": y, "snr": snr, "hole": rh, "blended": blended, "moved": bool(moved),
                    "pos": pos if moved else [(x, y)] * len(pos), "conc": np.nan if rh else concentration(allp, x, y)})
    c = np.array([s["conc"] for s in out if not s["hole"] and not s["blended"] and np.isfinite(s["conc"])])
    if c.size >= 10:
        lo = np.median(c) - 4 * max(_robust_sigma(c), 0.01)
        for s in out:
            if not s["hole"] and not (s["conc"] >= lo):
                s["blended"] = True
    return out


# ---- photometry ------------------------------------------------------------------------------------------------
def photometry(F, src):
    """Aperture and ring flux of one source in every exposure (at its position in that exposure's pass).

    Returns arrays over exposures: f, e (aperture, uJy), w, we (ring), core_sat (the centre pixel is saturated or
    bad), core_bad (that, or two bad pixels in the central 3x3), cover, flag, lam, and "dets":
    {det: {"sat": share of covered exposures with core_sat, "r_in": inner ring radius}}.
    The ring starts where fewer than 15% of that detector's exposures are saturated (never inside 4.5 px), so a very
    bright star is measured further out; ring fluxes are only compared within one source and one detector."""
    N, n0, n1 = F["img"].shape
    out = {k: np.full(N, np.nan) for k in ("f", "e", "w", "we", "lam")}
    out["core_bad"] = np.zeros(N, bool); out["core_sat"] = np.zeros(N, bool)
    out["cover"] = np.zeros(N, bool); out["flag"] = np.zeros(N, np.uint8)
    out["dets"] = {}
    edge = min(src["x"], src["y"], n1 - 1 - src["x"], n0 - 1 - src["y"])
    H = int(min(RING_R_MAX + W_SKY1 - W_IN + 1, edge - 2))
    if H < R_OUT + 1:
        return out
    nb = H + 1                                           # annuli 0..H for the saturation profile
    stamps = {}
    for p in np.unique(F["pass"]):
        if p < 0:
            continue
        x, y = src["pos"][p] if p < len(src["pos"]) else (src["x"], src["y"])
        xi, yi = int(round(x)), int(round(y))
        x0, x1, y0, y1 = xi - H, xi + H + 1, yi - H, yi + H + 1
        if x0 < 0 or y0 < 0 or x1 > n1 or y1 > n0:
            continue
        sel = np.flatnonzero(F["pass"] == p)
        im = F["img"][sel, y0:y1, x0:x1]; va = F["var"][sel, y0:y1, x0:x1]
        bad = (F["flag"][sel, y0:y1, x0:x1] & 1).astype(bool)
        ok = np.isfinite(im) & ~bad
        yy, xx = np.mgrid[y0:y1, x0:x1]
        r = np.hypot(xx - x, yy - y)
        flat = lambda a: a.reshape(len(sel), -1)         # noqa: E731
        cover = flat(np.isfinite(im)).mean(axis=1) > 0.4
        # aperture, exactly as the field lab's phot()
        ap, sky = (r <= R_AP).ravel(), ((r >= R_IN) & (r <= R_OUT)).ravel()
        okf, imf, vaf = flat(ok), flat(im), flat(va)
        vok = okf & np.isfinite(vaf)
        g_ap = (vok & ap).sum(axis=1)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = np.nanmedian(np.where(okf & sky, imf, np.nan), axis=1)
            sc = ap.sum() / np.maximum(g_ap, 1)
            f = (np.where(vok & ap, imf, 0.0).sum(axis=1) - s * g_ap) * sc * PIX_SR * 1e12
            e = np.sqrt(np.where(vok & ap, vaf, 0.0).sum(axis=1)) * sc * PIX_SR * 1e12
        good = (g_ap >= 0.75 * ap.sum()) & ((okf & sky).sum(axis=1) >= 20)
        out["f"][sel] = np.where(good, f, np.nan); out["e"][sel] = np.where(good, e, np.nan)
        cpix = (yi - y0) * (x1 - x0) + (xi - x0)           # the pixel under the source
        c3 = ((np.abs(xx - xi) <= 1) & (np.abs(yy - yi) <= 1)).ravel()
        out["core_sat"][sel] = ~okf[:, cpix] & cover
        out["core_bad"][sel] = (~okf[:, cpix] | ((~okf & c3).sum(axis=1) >= 2)) & cover
        out["cover"][sel] = cover
        out["flag"][sel] = F["flag"][sel, yi, xi]
        lam = F["lam"][sel, min(yi // F["ds"], F["lam"].shape[1] - 1), min(xi // F["ds"], F["lam"].shape[2] - 1)]
        out["lam"][sel] = np.where(np.isfinite(lam) & (lam > 0), lam, F["lam_um"][sel])
        stamps[p] = (sel, okf, imf, vaf, r.ravel())
    for d in DETECTORS:
        # where does this detector stop saturating? (share of bad pixels per 1-px annulus, over covered exposures)
        nbad, ntot = np.zeros(nb), np.zeros(nb)
        for sel, okf, imf, vaf, r in stamps.values():
            m = (F["det"][sel] == d) & out["cover"][sel]
            if not m.any():
                continue
            k = np.minimum(r.astype(int), nb - 1)
            nbad += np.bincount(k, (~okf[m]).sum(axis=0), nb); ntot += np.bincount(k, np.full(r.size, m.sum()), nb)
        if ntot[0] == 0:
            continue
        prof = nbad / np.maximum(ntot, 1)
        md = (F["det"] == d) & out["cover"]
        sat = float(out["core_sat"][md].mean()) if md.any() else 0.0    # as the lab: the centre pixel is flagged
        clear = [k for k in range(1, nb - 1) if prof[k] < 0.15 and prof[k + 1] < 0.15]
        r_in = max(W_IN, clear[0] + 1.0) if clear else None
        ring_fits = r_in is not None and r_in <= RING_R_MAX and r_in + (W_SKY1 - W_IN) <= H
        out["dets"][d] = {"sat": sat, "r_in": r_in if ring_fits else None}
        if sat < SAT_FRAC or not ring_fits:
            continue
        for sel, okf, imf, vaf, r in stamps.values():
            m = np.flatnonzero((F["det"][sel] == d) & out["cover"][sel])
            if not len(m):
                continue
            ring = (r >= r_in) & (r < r_in + W_OUT - W_IN)
            rsky = (r >= r_in + W_SKY0 - W_IN) & (r < r_in + W_SKY1 - W_IN)
            o, im, va = okf[m], imf[m], vaf[m]
            g_r = (o & ring).sum(axis=1)
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rs = np.nanmedian(np.where(o & rsky, im, np.nan), axis=1)
                rsc = ring.sum() / np.maximum(g_r, 1)
                w = (np.where(o & ring, im, 0.0).sum(axis=1) - rs * g_r) * rsc * PIX_SR * 1e12
                we = np.sqrt(np.where(o & ring & np.isfinite(va), va, 0.0).sum(axis=1)) * rsc * PIX_SR * 1e12
            rgood = (g_r >= 0.7 * ring.sum()) & ((o & rsky).sum(axis=1) >= 30)
            out["w"][sel[m]] = np.where(rgood, w, np.nan); out["we"][sel[m]] = np.where(rgood, we, np.nan)
    return out


# ---- F(lambda, t) = S(lambda) L(pass) --------------------------------------------------------------------------
def fit_detector(lam, flux, pk, n_pass):
    """Fit F = poly(ln lambda) * L[pass] to one detector's points, in flux (not log flux) and without any cut on the
    S/N of single points: a log fit or a "flux > 3 sigma" cut biases the noisier pass upwards, which on faint stars
    looks exactly like variability. Gauss-Newton with 4-sigma clipping about the model.

    Returns (l, C, n_used, rms): l = ln L relative to the mean of the passes present (NaN where a pass has too few
    points), C its covariance from the residuals themselves (heteroscedasticity-consistent "sandwich" estimate, so a
    noisier pass gets a larger error), rms the fractional scatter about the model. None if it cannot be fitted."""
    lam, flux, pk = np.asarray(lam, float), np.asarray(flux, float), np.asarray(pk, int)
    ok = np.isfinite(lam) & np.isfinite(flux) & (pk >= 0)
    present = [p for p in range(n_pass) if (ok & (pk == p)).sum() >= MIN_PTS_PASS]
    ok &= np.isin(pk, present)
    if len(present) < 2 or ok.sum() < MIN_PTS_DET:
        return None
    u = np.log(np.where(ok, lam, 1.0))
    lo, hi = u[ok].min(), u[ok].max()
    u = (2 * u - lo - hi) / max(hi - lo, 1e-6)
    deg = 3 if ok.sum() >= 24 else 2
    P = np.vstack([u ** k for k in range(deg + 1)]).T
    onehot = np.vstack([(pk == p).astype(float) for p in present[1:]]).T          # [n, k-1]
    y = np.where(ok, flux, 0.0)
    med = np.median(y[ok])
    keep = ok & (np.abs(y - med) <= 8 * max(1.4826 * np.median(np.abs(y[ok] - med)), 1e-12))     # gross outliers only
    c = np.linalg.lstsq(P[keep], y[keep], rcond=None)[0]
    ell = np.zeros(len(present) - 1)
    for _ in range(4):                                       # clipping rounds
        for _ in range(15):                                  # Gauss-Newton
            Lj = np.exp(onehot @ ell)
            m = (P @ c) * Lj
            J = np.hstack([P * Lj[:, None], m[:, None] * onehot])
            d = np.linalg.lstsq(J[keep], (y - m)[keep], rcond=None)[0]
            dl = np.clip(d[deg + 1:], -0.5, 0.5)
            c, ell = c + d[:deg + 1], ell + dl
            if np.abs(dl).max(initial=0) < 1e-6:
                break
        Lj = np.exp(onehot @ ell)
        m = (P @ c) * Lj
        res = y - m
        sg = 1.4826 * np.median(np.abs(res[keep] - np.median(res[keep])))
        new = ok & (np.abs(res) <= 4 * max(sg, 1e-12))
        if any((new & (pk == p)).sum() < MIN_PTS_PASS for p in present) or new.sum() < MIN_PTS_DET:
            return None
        if (new == keep).all():
            break
        keep = new
    if not np.isfinite(c).all() or (m[keep] <= 0).any():
        return None                                          # the fitted spectrum is not positive: too faint to say
    J = np.hstack([P * Lj[:, None], m[:, None] * onehot])[keep]
    r = res[keep]
    n, k = J.shape
    if n - k < 3:
        return None
    try:
        B = np.linalg.inv(J.T @ J)
    except np.linalg.LinAlgError:
        return None
    cov = B @ (J.T @ (J * (r ** 2)[:, None])) @ B * n / (n - k)
    q = len(present)
    lp = np.zeros(q); Cp = np.zeros((q, q))
    lp[1:] = ell; Cp[1:, 1:] = cov[deg + 1:, deg + 1:]
    T = np.eye(q) - 1.0 / q                                  # relative to the mean of the passes present
    lp, Cp = T @ lp, T @ Cp @ T.T
    l = np.full(n_pass, np.nan); C = np.full((n_pass, n_pass), np.nan)
    l[present] = lp; C[np.ix_(present, present)] = Cp
    return l, C, int(n), float(np.sqrt(np.mean((r / m[keep]) ** 2)))


def measure(ph, pk, det, n_pass):
    """Per-detector pass factors of one source: {det: {l, C, method, n, rms, snr, sat, r_in}}."""
    out = {}
    for d, info in ph["dets"].items():
        m = (det == d) & (pk >= 0) & ph["cover"]
        if m.sum() < MIN_PTS_DET:
            continue
        if info["sat"] >= SAT_FRAC:
            if info["r_in"] is None:
                continue                                    # saturated too far out for a ring inside the field
            v, e, method = ph["w"], ph["we"], "ring"
            use = m & np.isfinite(v) & (e > 0)
        else:
            v, e, method = ph["f"], ph["e"], "aperture"
            use = m & np.isfinite(v) & (e > 0) & ~ph["core_bad"] & ((ph["flag"] & 5) == 0)
        # the detector is chosen on its median S/N; single points are never cut on S/N (see fit_detector)
        if use.sum() < MIN_PTS_DET or np.median(v[use] / e[use]) < MIN_SNR:
            continue
        r = fit_detector(ph["lam"][use], v[use], pk[use], n_pass)
        if r is None:
            continue
        out[d] = {"l": r[0], "C": r[1], "n": r[2], "rms": r[3], "method": method, "snr": float(np.median(v[use] / e[use])),
                  "sat": info["sat"], "r_in": info["r_in"] if method == "ring" else None}
    return out


@lru_cache(maxsize=None)
def _pairs(n_pass):
    return tuple((a, b) for a in range(n_pass) for b in range(a + 1, n_pass))


def _dvar(C, a, b):
    return C[a, a] + C[b, b] - 2 * C[a, b]


def calibrate(meas, n_pass):
    """Zero points and error model from the field's own unsaturated stars (aperture photometry).

    zpair[(det, a, b)]: median of l[a] - l[b] over the stars measured in both passes (the field's own calibration
    change between two passes; removed from every source). bright_scatter: robust scatter of the corrected
    differences of the third of measurements with the smallest fit errors. sys: what is left of that after the fit
    errors (the floor added in quadrature). scale: width of the resulting z distribution (>= 1)."""
    zpair, n_ref, diffs, errs = {}, 0, [], []
    pairs = _pairs(n_pass)
    for d in DETECTORS:
        for a, b in pairs:
            v = [(m[d]["l"][a] - m[d]["l"][b], _dvar(m[d]["C"], a, b)) for m in meas if d in m and m[d]["method"] == "aperture"]
            v = [(x, e) for x, e in v if np.isfinite(x) and e > 0]
            z = float(np.median([x for x, _ in v])) if len(v) >= 8 else 0.0
            zpair[(d, a, b)] = z
            n_ref = max(n_ref, len(v))
            diffs += [x - z for x, _ in v]; errs += [np.sqrt(e) for _, e in v]
    # per-pass zero points for the displayed curve: least squares on the pair zero points (mean zero)
    zp = {}
    A = np.zeros((len(pairs), n_pass))                    # the same design matrix for every detector
    for k, (a, b) in enumerate(pairs):
        A[k, a], A[k, b] = 1, -1
    for d in DETECTORS:
        y = np.array([zpair[(d, a, b)] for a, b in pairs], float)
        zp[d] = np.linalg.lstsq(A, y, rcond=None)[0]
    diffs, errs = np.array(diffs), np.array(errs)
    if len(diffs) < 30:                                   # too few stars to calibrate on: conservative defaults
        return {"zpair": zpair, "zp": zp, "sys": 0.03, "scale": 1.5, "bright_scatter": 0.04, "n_ref": n_ref, "n_diff": int(len(diffs))}
    bright = errs <= np.percentile(errs, 33)
    s = _robust_sigma(diffs[bright])
    sys = float(np.sqrt(max(s ** 2 - np.median(errs[bright]) ** 2, 0.0)))
    z = diffs / np.hypot(errs, sys)
    return {"zpair": zpair, "zp": zp, "sys": sys, "scale": float(max(1.0, _robust_sigma(z))), "bright_scatter": float(s),
            "n_ref": n_ref, "n_diff": int(len(diffs))}


def evaluate(m, cal, n_pass, pass_mjd):
    """Variability of one source from its per-detector fits. Returns a dict (always), with "candidate": bool."""
    thr_ap = float(np.exp(MIN_SIG * cal["bright_scatter"]))
    per = {}
    for d, r in m.items():
        ring = r["method"] == "ring"
        per[d] = {"l": r["l"], "C": r["C"], "sys": RING_SYS if ring else cal["sys"], "scale": cal["scale"],
                  "thr": RING_MIN_AMP if ring else thr_ap, "method": r["method"]}
    best = None
    for a, b in _pairs(n_pass):
        for sign in (1, -1):
            zs = []
            for d, q in per.items():
                dl = sign * (q["l"][a] - q["l"][b] - cal["zpair"][(d, a, b)])
                v = _dvar(q["C"], a, b)
                if not np.isfinite(dl) or not v > 0:
                    continue
                zs.append((float(dl / np.hypot(np.sqrt(v), q["sys"]) / q["scale"]), d, float(dl)))
            agree = sorted((t for t in zs if t[0] >= MIN_SIG and np.exp(t[2]) >= per[t[1]]["thr"]), reverse=True)
            zz = sorted((t[0] for t in zs), reverse=True)
            key = (len(agree), zz[1] if len(zz) > 1 else -np.inf)
            if best is None or key > best["key"]:
                best = {"key": key, "pair": (a, b) if sign > 0 else (b, a), "agree": [t[1] for t in agree],
                        "sig": zz[1] if len(zz) > 1 else None, "n_fit": len(zs),
                        "amp_det": {f"D{d}": round(float(np.exp(dl)), 3) for _, d, dl in sorted(zs, key=lambda t: t[1])}}
    # one brightness per pass: detectors combined with inverse-variance weights (fit error and floor)
    L = []
    for p in range(n_pass):
        v = [(q["l"][p] - cal["zp"][d][p], q["C"][p, p] * q["scale"] ** 2 + (q["sys"] * q["scale"]) ** 2 / 2)
             for d, q in per.items() if np.isfinite(q["l"][p]) and q["C"][p, p] >= 0]
        if not v:
            L.append(None); continue
        w = np.array([1 / max(e, 1e-8) for _, e in v]); x = np.array([l for l, _ in v])
        L.append((float((w * x).sum() / w.sum()), float(np.sqrt(1 / w.sum()))))
    ok = [p for p in range(n_pass) if L[p] is not None]
    mean = float(np.mean([L[p][0] for p in ok])) if ok else 0.0
    amp = float(np.exp(max(L[p][0] for p in ok) - min(L[p][0] for p in ok))) if len(ok) >= 2 else None
    n_ring = sum(1 for q in per.values() if q["method"] == "ring")
    cand = bool(best and len(best["agree"]) >= MIN_DETS)
    return {"candidate": cand, "amp": None if amp is None else round(amp, 3),
            "sig": None if not best or best["sig"] is None else round(best["sig"], 2),
            "n_dets_agree": len(best["agree"]) if best else 0, "n_dets_fit": best["n_fit"] if best else 0,
            "dets_agree": sorted(best["agree"]) if best else [], "pair": list(best["pair"]) if best else None,
            "amp_det": best["amp_det"] if best else {}, "saturated": bool(per and n_ring * 2 >= len(per)),
            "L": [{"k": p, "mjd": round(float(pass_mjd[p]), 1), "rel": round(float(np.exp(L[p][0] - mean)), 4),
                   "err": round(float(np.exp(L[p][0] - mean) * L[p][1]), 4)} for p in ok]}


CAND_KEYS = ("x", "y", "amp", "sig", "n_dets_agree", "n_dets_fit", "dets_agree", "pair", "amp_det", "saturated", "L")


def search_cube(F, log=print):
    """The whole search on a loaded field (load_field or a synthetic one). No catalogues.
    Returns {"candidates": [...], "stats": {...}, "all": [one row per measured source], "cal", "meas", "sources"}."""
    n_pass = F["stacks"].shape[0]
    srcs = find_sources(F["stacks"])
    meas = [measure(photometry(F, s), F["pass"], F["det"], n_pass) for s in srcs]
    is_sat = [bool(m) and sum(1 for r in m.values() if r["method"] == "ring") * 2 >= len(m) for m in meas]
    sat_xy = np.array([(s["x"], s["y"]) for s, t in zip(srcs, is_sat) if t], float).reshape(-1, 2)
    near = [not t and bool(len(sat_xy)) and bool((np.hypot(s["x"] - sat_xy[:, 0], s["y"] - sat_xy[:, 1]) < NEAR_SAT_PX).any())
            for s, t in zip(srcs, is_sat)]
    cal = calibrate([m for s, m, nr in zip(srcs, meas, near) if not nr and not s["blended"]], n_pass)
    rows = []
    for s, m, nr in zip(srcs, meas, near):
        if not m:
            continue
        ev = evaluate(m, cal, n_pass, F["pass_mjd"])
        ev.update(x=round(s["x"], 2), y=round(s["y"], 2), near_saturated=nr, blended=bool(s["blended"] and not ev["saturated"]),
                  moved=s["moved"])
        rows.append(ev)
    cands = sorted((r for r in rows if r["candidate"] and not r["near_saturated"] and not r["blended"]), key=lambda c: -(c["sig"] or 0))
    cands = [{"id": k, **{key: c[key] for key in CAND_KEYS}} for k, c in enumerate(cands)]
    stats = {"n_sources": len(srcs), "n_measured": len(rows), "n_saturated": sum(1 for r in rows if r["saturated"]),
             "n_near_saturated": sum(1 for r in rows if r["near_saturated"]), "n_blended": sum(1 for r in rows if r["blended"]),
             "n_searched": sum(1 for r in rows if not r["near_saturated"] and not r["blended"]),
             "threshold_unsat": round(float(np.exp(MIN_SIG * cal["bright_scatter"])), 3), "threshold_sat": RING_MIN_AMP,
             "bright_scatter": round(cal["bright_scatter"], 4), "sys_unsat": round(cal["sys"], 4), "sys_sat": RING_SYS,
             "error_scale": round(cal["scale"], 3), "n_reference_stars": cal["n_ref"], "min_sig": MIN_SIG, "min_dets": MIN_DETS,
             "n_passes": n_pass}
    log(f"  variables: {len(srcs)} sources, {len(rows)} measured, {len(cands)} candidates "
        f"(bright-star scatter {cal['bright_scatter']:.3f}, floor {cal['sys']:.3f}, scale {cal['scale']:.2f})")
    return {"candidates": cands, "stats": stats, "all": rows, "cal": cal, "meas": meas, "sources": srcs}


# ---- catalogue labels ------------------------------------------------------------------------------------------
VIZIER = "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"   # first of the services sxlib.gaia tries (MAST is its fallback)


def _sep_arcsec(ra, dec, ra2, dec2):
    c = np.cos(np.radians(dec))
    return float(np.hypot((ra - ra2) * c, dec - dec2) * 3600)


def _seps(ra, dec, ra2, dec2):
    """_sep_arcsec with array arguments (elementwise, the same arithmetic)."""
    return np.hypot((ra - ra2) * np.cos(np.radians(dec)), dec - dec2) * 3600


def _radec(rows):
    return (np.array([r["ra"] for r in rows], float).reshape(-1), np.array([r["dec"] for r in rows], float).reshape(-1))


def catalogues(ra, dec, radius_deg):
    """VSX and Gaia DR3 sources around a field centre. Returns {"vsx": [...] | None, "gaia": [...] | None, "errors": {}}."""
    import requests
    import urllib3
    urllib3.disable_warnings()
    out = {"vsx": None, "gaia": None, "errors": {}}
    try:
        r = requests.get(VIZIER, params={"-source": "B/vsx/vsx", "-c": f"{ra} {dec}", "-c.rm": round(radius_deg * 60, 2),
                                         "-out": "Name,Type,Period,RAJ2000,DEJ2000", "-out.max": "unlimited"}, timeout=90)
        r.raise_for_status()
        rows = [ln.split("\t") for ln in r.text.splitlines() if ln and not ln.startswith("#")]
        vs = []
        for x in rows[3:]:
            if len(x) < 5:
                continue
            try:
                vs.append({"name": x[0].strip(), "type": x[1].strip() or None, "period_d": float(x[2]) if x[2].strip() else None,
                           "ra": float(x[3]), "dec": float(x[4])})
            except ValueError:
                continue
        if "#INFO" not in r.text and not rows:
            raise RuntimeError("empty VizieR reply")
        out["vsx"] = vs
    except Exception as e:  # noqa: BLE001 - labels are optional
        out["errors"]["vsx"] = str(e)[:200]
    try:
        from . import gaia                  # ESA's Gaia archive, MAST as the fallback
        rows = gaia.cone(ra, dec, radius_deg, ["source_id", "ra", "dec", "phot_g_mean_mag", "phot_variable_flag"], max_g=19.5, top=6000)
        gs = []
        for v in rows:
            try:
                gs.append({"id": v["source_id"], "ra": float(v["ra"]), "dec": float(v["dec"]),
                           "g": float(v["phot_g_mean_mag"]) if v["phot_g_mean_mag"] else None, "flag": v["phot_variable_flag"].strip('"')})
            except (ValueError, KeyError):
                continue
        out["gaia"] = gs
    except Exception as e:  # noqa: BLE001
        out["errors"]["gaia"] = str(e)[:200]
    return out


def label(cands, cats, ov_xy=None):
    """status and match for each candidate (needs ra/dec). Catalogues only label; they never select."""
    vsx, gaia = cats["vsx"] or [], cats["gaia"] or []
    vra, vdec = _radec(vsx)
    gra, gdec = _radec(gaia)
    ov = np.array(ov_xy, float).reshape(-1, 2) if ov_xy is not None else None
    for c in cands:
        c["status"], c["match"] = None, None
        if cats["vsx"] is None and cats["gaia"] is None:
            continue
        v = None
        if vsx:
            sv = _seps(c["ra"], c["dec"], vra, vdec)
            i = int(np.argmin(sv))
            v = (float(sv[i]), vsx[i])
        sg = _seps(c["ra"], c["dec"], gra, gdec)
        g = sorted(((float(sg[i]), gaia[i]) for i in np.flatnonzero(sg <= 1.5 * PIX)),
                   key=lambda t: (t[1]["g"] is None, t[1]["g"]))                                    # brightest within 1.5 px
        if v and v[0] <= 1.5 * PIX:
            c["status"] = "known_variable"
            c["match"] = {"cat": "VSX", "name": v[1]["name"], "type": v[1]["type"], "period_d": v[1]["period_d"], "sep_arcsec": round(v[0], 1)}
        elif g and g[0][1]["flag"] == "VARIABLE":
            c["status"] = "known_variable"
            c["match"] = {"cat": "Gaia DR3", "name": f"Gaia DR3 {g[0][1]['id']}", "type": "VARIABLE", "period_d": None, "sep_arcsec": round(g[0][0], 1)}
        elif cats["vsx"] is None or cats["gaia"] is None:
            c["status"] = None                             # one catalogue could not be asked: do not call it constant
            if g:
                c["match"] = {"cat": "Gaia DR3", "name": f"Gaia DR3 {g[0][1]['id']}", "type": None, "period_d": None, "sep_arcsec": round(g[0][0], 1)}
        elif g:
            c["status"] = "catalogued_constant"
            c["match"] = {"cat": "Gaia DR3", "name": f"Gaia DR3 {g[0][1]['id']}", "type": None, "period_d": None, "sep_arcsec": round(g[0][0], 1)}
        elif ov is not None and bool((np.hypot(c["x"] - ov[:, 0], c["y"] - ov[:, 1]) <= 1.5).any()):
            c["status"] = "catalogued_constant"
            c["match"] = {"cat": "CatWISE2020", "name": None, "type": None, "period_d": None, "sep_arcsec": None}
        else:
            c["status"] = "new"
    return cands


def pix2world(wcs, x, y):
    """Field pixel -> RA, Dec (the same gnomonic grid as the web app's pix2world)."""
    d2r = np.pi / 180
    xi, eta = (x + 1 - wcs["crpix"][0]) * wcs["cdelt"][0] * d2r, (y + 1 - wcs["crpix"][1]) * wcs["cdelt"][1] * d2r
    a0, d0 = wcs["crval"][0] * d2r, wcs["crval"][1] * d2r
    den = np.cos(d0) - eta * np.sin(d0)
    return float(((a0 + np.arctan2(xi, den)) / d2r) % 360), float(np.arctan2(np.sin(d0) + eta * np.cos(d0), np.hypot(xi, den)) / d2r)


def nearest(rows, x, y, r=3.0):
    """The measured source nearest to (x, y), or None. Only used to report on named targets and the control star."""
    best = min(rows, key=lambda q: np.hypot(q["x"] - x, q["y"] - y), default=None)
    return best if best is not None and np.hypot(best["x"] - x, best["y"] - y) <= r else None


def search(field_dir, with_catalogues=True, log=print):
    """Search one analysed field. Returns {"candidates", "stats"} as written to var_candidates.json, plus "all"
    (every measured source) and "ring" (ring differences of saturated sources, for the pooled calibration)."""
    d = Path(field_dir)
    F = load_field(d)
    res = search_cube(F, log)
    doc = F["doc"]
    for c in res["candidates"] + res["all"]:
        c["ra"], c["dec"] = (round(v, 6) for v in pix2world(doc["wcs"], c["x"], c["y"]))
    cats = {"vsx": None, "gaia": None, "errors": {"all": "skipped"}}
    if with_catalogues:
        cats = catalogues(doc["ra"], doc["dec"], doc["size_deg"] * 0.75)
    ov_xy = None
    try:
        ov = json.loads((d / "overlays.json").read_text())
        ov_xy = [(s["x"], s["y"]) for s in ov.get("gaia", []) + ov.get("catwise", [])]
    except Exception:  # noqa: BLE001 - labels are optional
        pass
    label(res["candidates"], cats, ov_xy)
    st = res["stats"]
    st["catalogue_errors"] = cats["errors"]
    st["n_vsx_in_field"] = None if cats["vsx"] is None else len(cats["vsx"])
    st["n_gaia_variable_in_field"] = None if cats["gaia"] is None else sum(1 for g in cats["gaia"] if g["flag"] == "VARIABLE")
    st["by_status"] = {k: sum(1 for c in res["candidates"] if c["status"] == k) for k in ("known_variable", "catalogued_constant", "new")}
    # completeness against the catalogues: catalogued variables that coincide (within 1 px) with a measured source
    known = [{"cat": "VSX", **v} for v in cats["vsx"] or []]
    vra, vdec = _radec(known)
    known += [{"cat": "Gaia DR3", "name": f"Gaia DR3 {g['id']}", "type": "VARIABLE", "period_d": None, "ra": g["ra"], "dec": g["dec"]}
              for g in cats["gaia"] or [] if g["flag"] == "VARIABLE" and not (_seps(g["ra"], g["dec"], vra, vdec) < 2).any()]
    ara, adec = _radec(res["all"])
    kv = []
    for v in known:
        if not res["all"]:
            continue
        d = _seps(ara, adec, v["ra"], v["dec"])
        i = int(np.argmin(d))
        row = res["all"][i]
        if d[i] > PIX:
            continue
        kv.append({"cat": v["cat"], "name": v["name"], "type": v["type"], "period_d": v["period_d"], "x": row["x"], "y": row["y"],
                   "searched": not row["blended"] and not row["near_saturated"], "flagged": nearest(res["candidates"], row["x"], row["y"], 0.5) is not None,
                   "amp": row["amp"], "sig": row["sig"], "n_dets_agree": row["n_dets_agree"], "saturated": row["saturated"]})
    st["catalogued_variables"] = None if cats["vsx"] is None and cats["gaia"] is None else {
        "n_in_field": len(known), "n_on_a_measured_source": len(kv), "n_searched": sum(1 for q in kv if q["searched"]),
        "n_flagged": sum(1 for q in kv if q["flagged"]), "list": kv}
    # a named target (scripts/build_targets.py): did the blind search flag it? Reported only; never used to select.
    tg = doc.get("target")
    if tg and tg.get("passes"):
        row = nearest(res["all"], tg["passes"][0]["x"], tg["passes"][0]["y"])
        cand = nearest(res["candidates"], tg["passes"][0]["x"], tg["passes"][0]["y"])
        st["target_check"] = {"id": tg["id"], "kind": tg.get("kind"), "measured": row is not None, "flagged": cand is not None,
                              "cand_id": None if cand is None else cand["id"],
                              **({k: row[k] for k in ("amp", "sig", "n_dets_agree", "amp_det", "saturated")} if row else {})}
    n_pass = F["stacks"].shape[0]
    ring = []
    for s, m in zip(res["sources"], res["meas"]):
        for dd, r in m.items():
            if r["method"] != "ring":
                continue
            for a, b in _pairs(n_pass):
                dl, v = r["l"][a] - r["l"][b] - res["cal"]["zpair"][(dd, a, b)], _dvar(r["C"], a, b)
                if np.isfinite(dl) and v > 0:
                    ring.append({"x": round(s["x"], 1), "y": round(s["y"], 1), "det": dd, "dl": float(dl), "err": float(np.sqrt(v))})
    return {"candidates": res["candidates"], "stats": st, "all": res["all"], "ring": ring}
