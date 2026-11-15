"""Streak (trail) detection on SPHEREx difference images.

An asteroid passing close to Earth moves far enough during one SPHEREx exposure (XPOSURE = 113.58 s in the L2
header) to leave a short line instead of a dot. Our CNN (sxlib/rbnet.py) was trained on point-like movers only, so
this is a separate, classical pass in the spirit of the line-segment detection in the CSA NEOSSat tutorial:

  1. matched filter: the difference image (in noise units) is correlated with unit-norm line kernels (a segment of a
     Gaussian PSF) at several lengths and every orientation; masked pixels (bad, ghosts, bright-star cores) get zero
     weight and the response is renormalised for them. Each kernel's response is divided by its own robust scatter,
     so the correlated noise of the resampled grid is calibrated on the image itself.
  2. candidates: local maxima of the best response above a threshold.
  3. fit: a trailed-PSF model (uniform segment convolved with a Gaussian) is fitted to the difference image for the
     segment's centre, length, angle and flux; a point model is fitted too.
  4. vetoes: too short (point-like, the CNN's job), uneven brightness along the line (a single blob picked up by a
     long kernel), a negative twin beside it (a mis-subtracted star), too much of the line masked.

Trail length L = rate * XPOSURE / 6.15": a trail longer than 2 px needs a rate above ~390"/h (6.5"/min); our minimum
length of 3 px (18") needs ~580"/h.
"""
from functools import lru_cache

import numpy as np
from scipy import fft as sfft
from scipy.ndimage import binary_dilation, maximum_filter
from scipy.optimize import least_squares
from scipy.special import erf

PIX_ARCSEC = 6.15
EXPTIME_S = 113.5826                 # L2 header XPOSURE (s); TELAPSE (start to stop) is 118.19 s
PIX_SR = (PIX_ARCSEC / 206264.806) ** 2
LENGTHS = (3, 5, 7, 10, 14, 20, 28, 40, 56, 80)   # px, roughly x1.4 apart
SIGMA = 0.75                         # px: SPHEREx PSF (FWHM ~5-7") after bilinear resampling onto the field grid
L_MIN = 3.0                          # px: shorter is point-like (the CNN's job)
THR = 7.0                            # matched-filter S/N (kernel-normalised) for a candidate
PROFILE = "flat"                      # brightness along a trail; see _along
ZCLIP = 20.0                         # per-pixel S/N is clipped at this before filtering (SUR_ERROR pixels can be 1000)
SIGMA_STEP = 3                       # robust scatter of a response map from every 3rd pixel in each direction
MIN_VALID = 100                      # fewest usable pixels for a search
SNR_MIN = 5.0                        # vetoes (see _reject_reason)
DCHI2_MIN = 9.0
SQRT_2PI = np.sqrt(2 * np.pi)


def trail_px(rate_arcsec_h, exptime_s=EXPTIME_S, pix=PIX_ARCSEC):
    """Trail length in pixels for a sky rate in arcsec per hour."""
    return np.asarray(rate_arcsec_h) * exptime_s / 3600.0 / pix


def rate_for(length_px, exptime_s=EXPTIME_S, pix=PIX_ARCSEC):
    """Sky rate (arcsec per hour) that makes a trail of length_px."""
    return np.asarray(length_px) * pix * 3600.0 / exptime_s


def ujy_to_ab(f_ujy):
    f = np.asarray(f_ujy, float)
    with np.errstate(all="ignore"):
        return np.where(f > 0, -2.5 * np.log10(f * 1e-6 / 3631.0), np.nan)


def ab_to_ujy(mag):
    return 3631.0e6 * 10 ** (-0.4 * np.asarray(mag, float))


# ------------------------------------------------------------------------------------------------- model
def _along(u, L, sigma, profile):
    """Along-trail profile (integral 1) convolved with a Gaussian of sigma, at offsets u from the centre.
    flat: uniform; sur: 6 t (T - t) / T^3 in time, what a least-squares slope over an up-the-ramp exposure (SPHEREx
    fits the slope on board) gives for a source that crosses each pixel at a different time: bright middle, faint ends."""
    r2s = np.sqrt(2.0) * sigma
    s1, s2 = -L / 2 - u, L / 2 - u                  # integration limits in s = t - u
    I0 = 0.5 * (erf(s2 / r2s) - erf(s1 / r2s))
    if profile == "flat":
        return I0 / L
    phi = lambda s: np.exp(-0.5 * (s / sigma) ** 2) / (SQRT_2PI * sigma)  # noqa: E731
    p1, p2 = phi(s1), phi(s2)
    I1 = sigma ** 2 * (p1 - p2)                      # int s phi
    I2 = sigma ** 2 * I0 + sigma ** 2 * (s1 * p1 - s2 * p2)   # int s^2 phi
    A, C = 1.5 / L, -6.0 / L ** 3                    # p(t) = 6/L^3 (L^2/4 - t^2)
    return (A + C * u * u) * I0 + 2 * C * u * I1 + C * I2


def trail_model(shape, xc, yc, length, theta, flux=1.0, sigma=SIGMA, box=None, profile=None):
    """Trail of total `flux` (summed over pixels) centred at (xc, yc), `length` px from start to end at angle theta
    (radians, from +x towards +y), convolved with a circular Gaussian of `sigma` px; exact for a Gaussian PSF.
    profile: 'sur' (default, SPHEREx's on-board slope fit, see _along) or 'flat'.
    box = (y0, y1, x0, x1) evaluates only that sub-array (returned at that size)."""
    if box is None:
        y0, y1, x0, x1 = 0, shape[0], 0, shape[1]
    else:
        y0, y1, x0, x1 = box
    yy, xx = np.ogrid[y0:y1, x0:x1]
    yy, xx = yy.astype(float), xx.astype(float)
    c, s = np.cos(theta), np.sin(theta)
    dx, dy = xx - xc, yy - yc
    u = dx * c + dy * s                # along the trail
    v = -dx * s + dy * c               # across
    L = max(float(length), 1e-3)
    along = _along(u, L, sigma, profile or PROFILE)
    across = np.exp(-0.5 * (v / sigma) ** 2) / (SQRT_2PI * sigma)
    return flux * along * across


def line_kernel(length, theta, sigma=SIGMA):
    """Unit-norm (sum k^2 = 1) matched-filter kernel on an odd square grid, centred."""
    hx = int(np.ceil(abs(np.cos(theta)) * length / 2 + 3 * sigma + 1))
    hy = int(np.ceil(abs(np.sin(theta)) * length / 2 + 3 * sigma + 1))
    k = trail_model((2 * hy + 1, 2 * hx + 1), hx, hy, length, theta, 1.0, sigma)
    return k / np.sqrt((k ** 2).sum())


@lru_cache(maxsize=1024)
def _kernel(length, theta, sigma):
    """line_kernel, cached (read-only): the same few hundred kernels serve every exposure."""
    k = line_kernel(length, theta, sigma)
    k.setflags(write=False)
    return k


def angles_for(length, step=1.5):
    """Orientations in [0, pi): the segment's ends move by <= step/2 px between neighbours."""
    n = max(6, int(np.ceil(np.pi * max(length, 2.0) / step)))
    return np.arange(n) * np.pi / n


# ------------------------------------------------------------------------------------------------- filter
def _robust_sigma(a, step=SIGMA_STEP, valid=None):
    """1.4826 x MAD of every step-th pixel (finite ones; with `valid`, only those too); NaN under 50 samples."""
    v = a[::step, ::step]
    v = v[np.isfinite(v) if valid is None else (valid[::step, ::step] & np.isfinite(v))]
    if v.size < 50:
        return np.nan
    med = np.median(v)
    return 1.4826 * np.median(np.abs(v - med))


def response_maps(z, valid, lengths=LENGTHS, sigma=SIGMA, angle_step=1.5):
    """Best matched-filter response per pixel over all orientations, for each length, in units of its own robust
    scatter over the image (so the correlated noise of the resampled grid needs no model). Masked pixels count as
    zero, which only lowers the response of lines that cross them. FFT correlation in float32 with zero padding.
    Returns R [nL, ny, nx], the argmax angle index TH [nL, ny, nx] and the angle list per length."""
    z = np.clip(np.where(valid, np.nan_to_num(z), 0.0), -ZCLIP, ZCLIP).astype(np.float32)
    ny, nx = z.shape
    pad = int(max(lengths) / 2 + 4 * sigma + 2)
    fshape = tuple(sfft.next_fast_len(n + 2 * pad, real=True) for n in z.shape)
    Fz = sfft.rfft2(z, fshape, workers=-1)
    R = np.full((len(lengths), ny, nx), -np.inf, np.float32)
    TH = np.zeros((len(lengths), ny, nx), np.int16)
    angs, sds = [], []
    for j, L in enumerate(lengths):
        a = angles_for(L, angle_step)
        angs.append(a)
        sds.append(np.full(len(a), np.nan))
        Rj, THj = R[j], TH[j]
        for t, th in enumerate(a):
            k = _kernel(float(L), float(th), float(sigma)).astype(np.float32)
            cy, cx = k.shape[0] // 2, k.shape[1] // 2
            r = sfft.irfft2(Fz * np.conj(sfft.rfft2(k, fshape, workers=-1)), fshape, workers=-1)
            # the kernel centre back onto its pixel: the first ny x nx samples of np.roll(r, (cy, cx))
            r = r[np.ix_((np.arange(ny) - cy) % fshape[0], (np.arange(nx) - cx) % fshape[1])]
            sd = _robust_sigma(r, valid=valid)
            if not np.isfinite(sd) or sd <= 0:
                continue
            sds[j][t] = sd
            r = np.where(valid, r / sd, -np.inf)
            better = r > Rj
            Rj[better] = r[better]
            THj[better] = t
    return R, TH, angs, sds


def _point_response(z, x, y, L, th, sigma):
    """One kernel's (unnormalised) response at pixel (x, y) of z (NaN counts as zero)."""
    k = _kernel(float(L), float(th), float(sigma))
    hy, hx = k.shape[0] // 2, k.shape[1] // 2
    y0, y1, x0, x1 = y - hy, y + hy + 1, x - hx, x + hx + 1
    sy0, sx0 = max(0, -y0), max(0, -x0)
    sy1, sx1 = k.shape[0] - max(0, y1 - z.shape[0]), k.shape[1] - max(0, x1 - z.shape[1])
    sub = np.nan_to_num(z[max(0, y0):min(z.shape[0], y1), max(0, x0):min(z.shape[1], x1)])
    return float((sub * k[sy0:sy1, sx0:sx1]).sum())


# ------------------------------------------------------------------------------------------------- fit
def _fit_box(shape, xc, yc, L, theta, margin=4):
    hx = abs(np.cos(theta)) * L / 2 + margin
    hy = abs(np.sin(theta)) * L / 2 + margin
    y0, y1 = max(0, int(yc - hy)), min(shape[0], int(np.ceil(yc + hy)) + 1)
    x0, x1 = max(0, int(xc - hx)), min(shape[1], int(np.ceil(xc + hx)) + 1)
    return y0, max(y0, y1), x0, max(x0, x1)


def fit_trail(diff, noise, valid, xc, yc, L, theta, sigma=SIGMA, profile=None):
    """Least-squares trailed-PSF fit. Returns dict with xc, yc, length, theta, flux (sum, diff units), errors,
    chi2 and the point-model chi2 on the same pixels."""
    box = _fit_box(diff.shape, xc, yc, max(L, 3) * 1.6 + 4, theta, margin=5)
    y0, y1, x0, x1 = box
    d = diff[y0:y1, x0:x1]
    n = noise[y0:y1, x0:x1]
    m = valid[y0:y1, x0:x1] & np.isfinite(d) & np.isfinite(n) & (n > 0)
    if m.sum() < 12:
        return None
    dd, ww = d[m], 1.0 / n[m]

    def resid(p, fixed_len=None):
        xc_, yc_, L_, th_, f_, b_ = p if fixed_len is None else (p[0], p[1], fixed_len, 0.0, p[2], p[3])
        mod = trail_model(None, xc_, yc_, L_, th_, f_, sigma, box, profile)[m] + b_
        return (dd - mod) * ww

    # initial flux from the matched-filter geometry
    k = trail_model(None, xc, yc, max(L, 1.0), theta, 1.0, sigma, box, profile)[m]
    f0 = float(np.sum(dd * k * ww ** 2) / max(np.sum(k * k * ww ** 2), 1e-12))
    p0 = [xc, yc, max(L, 1.0), theta, max(f0, 1e-6), 0.0]
    lo = [x0, y0, 0.0, theta - np.pi / 2, 0.0, -np.inf]
    hi = [x1 - 1, y1 - 1, 2.5 * max(L, 4) + 10, theta + np.pi / 2, np.inf, np.inf]
    p0 = list(np.clip(p0, np.array(lo) + 1e-6, np.array(hi) - 1e-6))
    # robust loss: SPHEREx's on-board ramp fit leaves a few trail pixels (SUR_ERROR) hundreds of sigma high
    try:
        r = least_squares(resid, p0, bounds=(lo, hi), x_scale=[0.5, 0.5, 1.0, 0.05, max(abs(f0), 1e-3), 1e-3],
                          loss="soft_l1", f_scale=3.0)
        rp = least_squares(lambda q: resid(q, fixed_len=1e-3), [xc, yc, max(f0, 1e-6), 0.0],
                           bounds=([x0, y0, 0.0, -np.inf], [x1 - 1, y1 - 1, np.inf, np.inf]), loss="soft_l1", f_scale=3.0)
    except (ValueError, np.linalg.LinAlgError):
        return None
    xc_, yc_, L_, th_, f_, b_ = r.x
    err = np.full(6, np.nan)
    try:
        J = r.jac
        cov = np.linalg.pinv(J.T @ J)
        err = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        pass
    th_ = float(np.mod(th_, np.pi))
    return {"xc": float(xc_), "yc": float(yc_), "length": float(L_), "theta": th_, "flux": float(f_),
            "flux_err": float(err[4]), "length_err": float(err[2]), "theta_err": float(err[3]),
            "chi2": float(2 * r.cost), "chi2_point": float(2 * rp.cost), "npix": int(m.sum()),
            "bg": float(b_)}


def _segment_stats(snr, valid, xc, yc, L, theta, sigma=SIGMA):
    """S/N of the thirds of a segment, of the whole, of two parallel strips beside it (negative twin test) and the
    masked share of the line."""
    out = {}
    c, s = np.cos(theta), np.sin(theta)
    z = np.clip(np.where(valid, np.nan_to_num(snr), 0.0), -ZCLIP, ZCLIP)
    shape = snr.shape

    def mf(cx, cy, Lp, off=0.0):
        cx2, cy2 = cx - s * off, cy + c * off
        box = _fit_box(shape, cx2, cy2, Lp, theta, margin=3)
        if box[1] - box[0] < 2 or box[3] - box[2] < 2:
            return np.nan, 0.0
        k = trail_model(None, cx2, cy2, max(Lp, 0.5), theta, 1.0, sigma, box)
        v = valid[box[0]:box[1], box[2]:box[3]]
        kk = k * v
        n2 = (kk * kk).sum()
        tot2 = (k * k).sum()
        if n2 <= 0:
            return np.nan, 0.0
        return float((kk * z[box[0]:box[1], box[2]:box[3]]).sum() / np.sqrt(n2)), float(n2 / tot2)

    thirds = []
    for q in (-1, 0, 1):
        thirds.append(mf(xc + c * q * L / 3, yc + s * q * L / 3, L / 3)[0])
    out["thirds"] = thirds
    out["snr"], out["cov"] = mf(xc, yc, L)
    side = [mf(xc, yc, L, off)[0] for off in (-2.0, 2.0)]
    out["side_min"] = float(np.nanmin(side)) if np.isfinite(side).any() else np.nan
    return out


def _endpoints(xc, yc, L, theta):
    c, s = np.cos(theta), np.sin(theta)
    return (xc - c * L / 2, yc - s * L / 2), (xc + c * L / 2, yc + s * L / 2)


def _near_edge(valid, x, y, r=3):
    iy, ix = int(round(y)), int(round(x))
    if not (0 <= iy < valid.shape[0] and 0 <= ix < valid.shape[1]):
        return True
    y0, y1, x0, x1 = max(0, iy - r), min(valid.shape[0], iy + r + 1), max(0, ix - r), min(valid.shape[1], ix + r + 1)
    sub = valid[y0:y1, x0:x1]
    return bool(sub.size < (2 * r + 1) ** 2 or sub.mean() < 0.5)


# ------------------------------------------------------------------------------------------------- detect
def veto_mask(shape, bad=None, ghost=None, ref_snr=None, star_snr=30.0, grow=1):
    """Pixels to ignore: bad/uncovered, ghosts, and the cores of bright reference stars (residuals live there)."""
    m = np.zeros(shape, bool)
    if bad is not None:
        m |= bad
    if ghost is not None:
        m |= ghost
    if ref_snr is not None:
        star = np.nan_to_num(ref_snr) > star_snr
        if grow:
            star = binary_dilation(star, iterations=grow)
        m |= star
    return m


def detect(snr, diff=None, mask=None, lengths=LENGTHS, thr=THR, sigma=SIGMA, l_min=L_MIN, max_cand=40, max_fit=80,
           min_cov=0.6, angle_step=1.5, keep_rejected=False):
    """Find line segments in a difference image.

    snr   difference in noise units (NaN = no data)
    diff  difference in flux units (MJy/sr); if None, the fit runs on snr and fluxes are in noise units
    mask  True = ignore (see veto_mask)
    Returns a list of dicts sorted by matched-filter S/N: x0, y0, x1, y1 (ends, field pixels), xc, yc, length (px),
    angle_deg (0-180, from +x towards +y), flux (diff units summed over pixels), snr, and flags. Rejected candidates
    carry 'reject' (only returned with keep_rejected)."""
    snr = np.asarray(snr, float)
    valid = np.isfinite(snr)
    if mask is not None:
        valid &= ~mask
    if valid.sum() < MIN_VALID:
        return []
    if diff is None:
        diff, noise = snr, np.ones_like(snr)
    else:
        diff = np.asarray(diff, float)
        with np.errstate(all="ignore"):
            noise = np.abs(diff / snr)
        # where snr ~ 0 the ratio is unstable: fill with the local median noise
        bad_n = ~np.isfinite(noise) | (np.abs(snr) < 0.3)
        if (~bad_n & valid).any():
            noise = np.where(bad_n, np.nanmedian(noise[~bad_n & valid]), noise)
    R, TH, angs, sds = response_maps(snr, valid, lengths, sigma, angle_step)
    best = np.max(R, 0)
    jbest = np.argmax(R, 0)
    best = np.where(np.isfinite(best), best, -np.inf)
    peak = (best == maximum_filter(best, size=5)) & (best >= thr)
    ys, xs = np.nonzero(peak)
    order = np.argsort(-best[ys, xs])[:max_cand * 3]
    found = []
    dres, zres = diff.copy(), np.where(valid, snr, np.nan)     # accepted trails are subtracted (no side lobes)
    nfit = 0
    for k in order:
        y, x = ys[k], xs[k]
        j = jbest[y, x]
        L = float(lengths[j])
        th = float(angs[j][TH[j, y, x]])
        # skip peaks that lie on an already measured segment, or vanish once accepted trails are subtracted
        if any(_on_segment(f, x, y) for f in found if not f.get("reject")):
            continue
        if any(f["reject"] is None for f in found) and \
                _point_response(zres, x, y, L, th, sigma) / sds[j][TH[j, y, x]] < thr:
            continue
        nfit += 1
        if nfit > max_fit:
            break
        fit = fit_trail(dres, noise, valid, float(x), float(y), L, th, sigma)
        if fit is None:
            continue
        st = _segment_stats(zres, valid, fit["xc"], fit["yc"], max(fit["length"], 1.0), fit["theta"], sigma)
        (ax, ay), (bx, by) = _endpoints(fit["xc"], fit["yc"], fit["length"], fit["theta"])
        rec = {"x0": round(ax, 2), "y0": round(ay, 2), "x1": round(bx, 2), "y1": round(by, 2),
               "xc": round(fit["xc"], 2), "yc": round(fit["yc"], 2), "length": round(fit["length"], 2),
               "length_err": round(fit["length_err"], 2) if np.isfinite(fit["length_err"]) else None,
               "angle_deg": round(float(np.degrees(fit["theta"])) % 180.0, 2),
               "flux": float(fit["flux"]), "flux_err": float(fit["flux_err"]) if np.isfinite(fit["flux_err"]) else None,
               "snr": round(float(st["snr"]), 2) if np.isfinite(st["snr"]) else None,
               "mf": round(float(best[y, x]), 2), "kernel_len": L,
               "thirds": [round(float(t), 2) if np.isfinite(t) else None for t in st["thirds"]],
               "dchi2": round(fit["chi2_point"] - fit["chi2"], 1), "cov": round(st["cov"], 2),
               "edges": int(_near_edge(valid, ax, ay)) + int(_near_edge(valid, bx, by))}
        rec["reject"] = _reject_reason(rec, st, l_min, min_cov)
        found.append(rec)
        if rec["reject"] is None:
            box = _fit_box(diff.shape, fit["xc"], fit["yc"], fit["length"], fit["theta"], margin=5)
            m = trail_model(None, fit["xc"], fit["yc"], fit["length"], fit["theta"], fit["flux"], sigma, box)
            sl = (slice(box[0], box[1]), slice(box[2], box[3]))
            dres[sl] -= m
            zres[sl] -= m / noise[sl]
        if len([f for f in found if not f["reject"]]) >= max_cand:
            break
    found = _merge(found)
    if not keep_rejected:
        found = [f for f in found if not f["reject"]]
    found.sort(key=lambda f: -(f["snr"] or 0))
    return found


def _reject_reason(rec, st, l_min, min_cov=0.6):
    if rec["snr"] is None or rec["snr"] < SNR_MIN:
        return "faint"
    if rec["length"] < l_min:
        return "point"
    if rec["dchi2"] < DCHI2_MIN:
        return "not_line"            # a point model fits as well
    th = [t if t is not None else -np.inf for t in rec["thirds"]]
    expect = rec["snr"] / np.sqrt(3.0)
    if min(th) < max(1.5, 0.3 * expect):
        return "uneven"              # one bright blob, or a line that stops short of the fit
    if np.isfinite(st["side_min"]) and st["side_min"] < -0.5 * rec["snr"]:
        return "dipole"              # negative twin beside it: a shifted/mis-subtracted source
    if rec["cov"] < min_cov:
        return "masked"
    return None


def _on_segment(f, x, y, tol=2.5):
    ax, ay, bx, by = f["x0"], f["y0"], f["x1"], f["y1"]
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else np.clip(((x - ax) * vx + (y - ay) * vy) / L2, 0, 1)
    return np.hypot(ax + t * vx - x, ay + t * vy - y) <= tol


def _merge(found):
    """Drop a detection that lies on a stronger one (collinear pieces of one long trail)."""
    keep = []
    for f in sorted(found, key=lambda f: (f["reject"] is not None, -(f["snr"] or 0))):
        dup = False
        for g in keep:
            if g["reject"] is None and _on_segment(g, f["xc"], f["yc"], tol=3.0):
                da = abs((f["angle_deg"] - g["angle_deg"] + 90) % 180 - 90)
                if da < 15 or f["length"] < 6:
                    dup = True
                    break
        if not dup:
            keep.append(f)
    return keep


def classify(det):
    """'trail' (both ends inside the image: a finite trail, what a fast asteroid makes) or 'crossing' (runs off the
    usable area at both ends: satellites and very fast objects cross the whole image)."""
    return "crossing" if det.get("edges", 0) >= 2 else "trail"


def flux_ujy(flux_mjysr_pix, pix_arcsec=PIX_ARCSEC):
    """Summed difference flux (MJy/sr x pixels) to microjansky."""
    return float(flux_mjysr_pix) * (pix_arcsec / 206264.806) ** 2 * 1e12   # (MJy/sr) x sr -> uJy


# ------------------------------------------------------------------------------------------------- inputs
# SPHEREx fits each pixel's slope on board. A fast asteroid crosses a pixel in a few seconds, a step in the ramp
# that the on-board transient check flags as TRANSIENT (often SUR_ERROR too) and the L2 pipeline grows a HALO
# around: measured on 2025 FA22 (2025-09-18, 40-px trail), 76-92% of the trail's pixels carry TRANSIENT and 94-100%
# HALO. These are hard-bad bits for the point-source pipeline, so the streak pass clears them (bit numbers from the
# FLAGS header: 0 TRANSIENT, 2 SUR_ERROR, 28 HALO).
TRAIL_BITS = (0, 2, 28)


def add_relaxed(field, exp, bits=TRAIL_BITS):
    """stack.Field.add with the trail bits cleared. Returns the cleared-bit mask on the field grid (what the
    standard processing would have thrown away), or None if the exposure was not added."""
    import copy

    from reproject import reproject_interp

    from .archive import bitmask
    m = bitmask(bits)
    cleared = ((exp.flags & m) != 0).astype(float)
    e2 = copy.copy(exp)
    e2.flags = exp.flags & ~m
    if not field.add(e2):
        return None
    cl, _ = reproject_interp((cleared, exp.wcs.celestial), field.wcs, field.shape, order="nearest-neighbor")
    return np.nan_to_num(cl) > 0.5


def field_from_cube(field_dir):
    """Rebuild a stack.Field (enough for Field.difference) from an analysed field's cube/*.npy and field.json."""
    import json
    from pathlib import Path

    from .products import FL_BAD, FL_GHOST, FL_OUTLIER, FL_SOURCE, LAM_DS
    from .stack import FEAT_GHOST, FEAT_OUTLIER, FEAT_SOURCE, Field, field_wcs
    d = Path(field_dir)
    doc = json.loads((d / "field.json").read_text())
    img = np.load(d / "cube" / "img.npy").astype(np.float32)
    var = np.load(d / "cube" / "var.npy").astype(np.float32)
    flag = np.load(d / "cube" / "flag.npy")
    lam = np.load(d / "cube" / "lam.npy").astype(np.float32)
    n = img.shape[1]
    lam = np.repeat(np.repeat(lam, LAM_DS, 1), LAM_DS, 2)[:, :n, :n]
    f = Field.__new__(Field)
    f.ra, f.dec, f.size = doc["ra"], doc["dec"], doc["size_deg"]
    f.wcs, f.shape = field_wcs(f.ra, f.dec, f.size)
    ex = doc["exposures"][: img.shape[0]]
    f.exps = [{"obs_id": e["obs_id"], "mjd": e["mjd"], "detector": e["detector"], "lam_um": e["lam_um"]} for e in ex]
    f.img, f.var = img, np.where(var > 0, var, np.nan).astype(np.float32)
    f.bad = (flag & FL_BAD) != 0
    f.feat = (((flag & FL_SOURCE) != 0) * FEAT_SOURCE | ((flag & FL_GHOST) != 0) * FEAT_GHOST
              | ((flag & FL_OUTLIER) != 0) * FEAT_OUTLIER).astype(np.uint8)
    f.lam = lam
    f.mjd = np.array([e["mjd"] for e in f.exps])
    f.det = np.array([e["detector"] for e in f.exps])
    return f, doc


def detect_in_field(f, i, ref_kw=None, **kw):
    """Difference exposure i of a stack.Field (same settings as the main pipeline) and run detect()."""
    from .stack import FEAT_GHOST
    d = f.difference(i, **(ref_kw or {"lam_tol": 0.03, "eps": 0.1}))
    with np.errstate(all="ignore"):
        ref_snr = d["ref"] / np.sqrt(d["var_ref"])
    mask = veto_mask(f.shape, bad=~d["valid"], ghost=(f.feat[i] & FEAT_GHOST) != 0, ref_snr=ref_snr)
    return detect(d["snr"], d["diff"], mask, **kw), d, mask
