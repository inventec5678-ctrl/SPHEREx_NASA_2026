"""Numbers quoted in reply to the fifth referee report (runs from any working directory):
1) distance-grid mismatch (scalloping) loss of parallax-only stacking, from the actual exposure times of the survey
   fields: a body at the geometric midpoint between two trial distances, stacked at the nearer one;
2) the same trailing loss for eccentric orbits at perihelion (speed sqrt(1+e) x circular)."""
import sys
from pathlib import Path

import numpy as np
from scipy.special import erf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, read_json  # noqa: E402

PIX, SIG = 6.15, 5.0 / 2.355 / 6.15     # pixel (arcsec), PSF sigma (pixels)
PASS_DAYS = 14
GRID = np.geomspace(40, 3000, 36)       # trial distances of the stacking search (au)
MIN_DIST = 400                          # au: grid steps checked
FIELD_STRIDE = 6                        # every 6th survey field
OFFSET_STRIDE = 4                       # every 4th exposure of a pass
# stack pixel phase (11 x 11 sub-pixel centres) and the 3 x 3 neighbouring pixels: every peak candidate
_PHASE = (np.linspace(-0.5, 0.5, 11)[:, None] + np.array([-1, 0, 1])[None, :]).ravel()


def _pix_frac(c):
    """Fraction of a pixel-integrated 1-D Gaussian at offset c (pixels) falling in the central pixel."""
    return 0.5 * (erf((0.5 - c) / (np.sqrt(2) * SIG)) - erf((-0.5 - c) / (np.sqrt(2) * SIG)))


def pixel_psf(x, y):
    """Pixel-integrated Gaussian at offset (x, y) pixels: flux falling in the central pixel."""
    return _pix_frac(x) * _pix_frac(y)


def peak_of(offsets):
    """Peak of the stack of PSFs at the given (dx, dy) offsets, best over the stack pixel phase.
    The PSF separates in x and y, so the mean over offsets for every (x phase, y phase) pair is one matrix product."""
    off = np.asarray(offsets, float).reshape(-1, 2)
    fx = _pix_frac(off[None, :, 0] - _PHASE[:, None])          # (phases, N)
    fy = _pix_frac(off[None, :, 1] - _PHASE[:, None])
    return float((fx @ fy.T).max() / len(off))


def grid_mismatch(p0):
    from sxlib import link
    from sxlib.shiftstack import passes_of
    print(f"grid step: factor {GRID[1] / GRID[0]:.3f}")
    loss, span = {}, {}
    for fn in sorted((OUTPUTS / "survey").glob("*/field.json"))[::FIELD_STRIDE]:
        D = read_json(fn)
        mjd = np.array([e["mjd"] for e in D["exposures"]])
        cosd = np.cos(np.radians(D["dec"]))
        for idx in passes_of(mjd):
            t = mjd[idx]
            t0 = float(np.median(t))
            for g0, g1 in zip(GRID[:-1], GRID[1:]):
                if g0 < MIN_DIST:
                    continue
                dt = np.sqrt(g0 * g1)
                ra_t, de_t = link.predict_distant(D["ra"], D["dec"], t0, dt, t)
                pk = 0
                for g in (g0, g1):        # the search keeps the better of the two neighbouring trial distances
                    ra_g, de_g = link.predict_distant(D["ra"], D["dec"], t0, g, t)
                    off = np.c_[(ra_t - ra_g) * cosd, de_t - de_g] * 3600 / PIX
                    pk = max(pk, peak_of(off[::OFFSET_STRIDE] - off.mean(0)))
                loss.setdefault(round(dt), []).append(-2.5 * np.log10(pk / p0))
                span.setdefault(round(dt), []).append(t.max() - t.min())
    for lo, hi in ((400, 600), (600, 1000), (1000, 3000)):
        v = np.concatenate([loss[d] for d in loss if lo <= d < hi])
        print(f"grid-mismatch loss {lo}-{hi} au: median {np.median(v):.2f}, 90th pct {np.percentile(v, 90):.2f}, "
              f"max {v.max():.2f} mag")
    d0 = min(loss)
    k = int(np.argmax(loss[d0]))
    print(f"worst case at {d0} au: pass span {span[d0][k]:.0f} d")


def trail(L, p0):
    xs = np.linspace(-L / 2, L / 2, 41)
    return -2.5 * np.log10(peak_of(np.c_[xs, np.zeros_like(xs)]) / p0)


def main():
    p0 = peak_of([(0, 0)])
    grid_mismatch(p0)
    for d in (400, 500):
        for e in (0.0, 0.3, 0.6):
            L = np.sqrt(1 + e) * 2 * np.pi * d ** -1.5 * 206265 * PASS_DAYS / 365.25 / PIX
            print(f"trail {d} au, e={e} at perihelion: {L:.2f} px, loss {trail(L, p0):.2f} mag")


if __name__ == "__main__":
    main()
