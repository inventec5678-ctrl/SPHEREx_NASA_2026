"""PSF-fit photometry on the field grid, using SPHEREx's own PSF model.

DR1 and QR3 files carry the effective PSF (ePSF: 21 x 21 zones per detector, 5x oversampled). It is already
convolved with the pixel, so a model pixel is the ePSF *sampled* at that pixel's centre, as in IRSA's PSF tutorial.
Older QR2 files carried an optical PSF (121 zones x 101 x 101 at 10x per detector and week), which is *integrated*
over each pixel; it is used only when no ePSF of the detector is cached. sxlib.archive.load_psf puts both on the same
10x grid. For photometry on the resampled field grid we use one symmetrised PSF per detector (mean of all zones,
averaged over the 8 rotations/flips, because the field grid is rotated with respect to the detector) and shift it
to the star's sub-pixel position. Flux and local background are fitted by weighted least squares to the
pixels within R_FIT, leaving out flagged pixels and, for a saturated star, the whole core (r < R_CORE). For a fixed
PSF the fitted amplitude is the total flux, whether or not the core was usable.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.ndimage import shift as nd_shift

from .archive import CACHE
from .products import PIX_SR

OS = 10                      # oversampling of the L2 PSF
HALF = 5                     # model window: (2*HALF+1)^2 field pixels
R_FIT, R_CORE = 5.0, 2.0
BLUR = 0.4                   # extra Gaussian blur (field px) from resampling onto the field grid; calibrated on
                             # isolated unsaturated Gaia stars (it minimises the scatter of PSF / large-aperture flux)
MIN_PIX = 12                 # fewest usable pixels for a fit
N_WEEKS = 6                  # optical PSF: average this many weekly cubes (the PSF is stable)
SAT_R = 1.5                  # a flagged pixel within this radius marks the core saturated
POS_STEPS = np.arange(-0.6, 0.61, 0.15)    # position refinement grid (px)


@lru_cache(maxsize=16)
def psf_kind(det, cache=str(CACHE)):
    """'epsf' when an effective PSF of this detector is cached (DR1/QR3), 'optical' for the older QR2 cubes."""
    return "epsf" if any(Path(cache, "psf").glob(f"E{det}_*.npz")) else "optical"


@lru_cache(maxsize=16)
def psf_for(det, cache=str(CACHE)):
    from .archive import load_psf
    if psf_kind(det, cache) == "epsf":
        cube, _ = load_psf(None, int(det), Path(cache))
        if cube is None:
            return None
        acc = cube.astype(np.float64).mean(axis=0)
    else:
        files = sorted(Path(cache, "psf").glob(f"D{det}_*.npz"))
        if not files:
            return None
        acc = None
        for f in files[:N_WEEKS]:                    # a few weeks are plenty; the PSF is stable
            with np.load(f) as z:
                p = z["psf"].astype(np.float64).mean(axis=0)
            acc = p if acc is None else acc + p
    p = np.clip(acc, 0, None)
    sym = sum(np.rot90(q, k) for q in (p, p.T) for k in range(4)) / 8
    if BLUR:
        from scipy.ndimage import gaussian_filter
        sym = gaussian_filter(sym, BLUR * OS)
    return sym / sym.sum()


def _embed(psf):
    """The PSF on the (2*HALF+1)*OS model canvas, its centre (index 50) on the central pixel's centre (index 55)."""
    n = (2 * HALF + 1) * OS
    big = np.zeros((n, n))
    c0 = n // 2 - psf.shape[0] // 2
    big[c0:c0 + psf.shape[0], c0:c0 + psf.shape[1]] = psf
    return big


def model(psf, dx, dy, sample=False, _big=None):
    """(2*HALF+1)^2 image of a unit-flux star at sub-pixel offset (dx, dy) from the window's central pixel.
    sample=True for an ePSF (value at each pixel centre), False for an optical PSF (integral over each pixel).
    _big: the PSF already embedded by _embed (fit() reuses it for every trial position)."""
    big = nd_shift(_embed(psf) if _big is None else _big, (dy * OS, dx * OS), order=1, mode="constant")
    blocks = big.reshape(2 * HALF + 1, OS, 2 * HALF + 1, OS)
    if not sample:
        return blocks.sum(axis=(1, 3))
    m = blocks[:, OS // 2, :, OS // 2]
    s = m.sum()
    return m / s if s > 0 else m


def fit(img, var, bad, x, y, det):
    """Total flux (µJy), its error, and the number of pixels used; None if the star cannot be fitted."""
    psf = psf_for(int(det))
    if psf is None:
        return None
    sample = psf_kind(int(det)) == "epsf"
    n0, n1 = img.shape
    xi, yi = int(round(x)), int(round(y))
    if not (HALF <= xi < n1 - HALF and HALF <= yi < n0 - HALF):
        return None
    sl = (slice(yi - HALF, yi + HALF + 1), slice(xi - HALF, xi + HALF + 1))
    im, va, bd = img[sl].astype(np.float64), var[sl].astype(np.float64), bad[sl].astype(bool)
    yy, xx = np.mgrid[-HALF:HALF + 1, -HALF:HALF + 1]
    r = np.hypot(xx - (x - xi), yy - (y - yi))
    sat = bool((bd & (r < SAT_R)).any())
    use = np.isfinite(im) & np.isfinite(va) & (va > 0) & ~bd & (r <= R_FIT)
    if sat:
        use &= r >= R_CORE                           # a saturated core: fit the wings only
    nuse = int(use.sum())
    if nuse < MIN_PIX:
        return None
    w = 1.0 / va[use]
    big = _embed(psf)
    ones = np.ones(nuse)

    def solve(px, py):
        m = model(psf, px - xi, py - yi, sample, _big=big)
        A = np.vstack([m[use], ones]).T
        Aw = A * w[:, None]
        try:
            cov = np.linalg.inv(A.T @ Aw)
        except np.linalg.LinAlgError:
            return None
        coef = cov @ (Aw.T @ im[use])
        chi2 = float(np.sum(w * (im[use] - A @ coef) ** 2))
        return chi2, coef, cov
    # the position is refined on a small grid (registration and catalogue positions are good to a few tenths of a pixel)
    best = None
    for ddx in POS_STEPS:
        for ddy in POS_STEPS:
            r_ = solve(x + ddx, y + ddy)
            if r_ is not None and (best is None or r_[0] < best[0]):
                best = r_
    if best is None:
        return None
    _, (a, b), cov = best
    k = PIX_SR * 1e12                                 # image units (MJy/sr) summed over pixels -> µJy
    return float(a * k), float(np.sqrt(cov[0, 0]) * k), nuse, sat
