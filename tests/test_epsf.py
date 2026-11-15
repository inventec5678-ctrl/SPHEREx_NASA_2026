"""The DR1/QR3 effective PSF: resampled onto the 10x grid and *sampled* at pixel centres, it must reproduce the
pixel values of a star (the ePSF already includes the pixel), as IRSA's PSF tutorial uses it."""
import numpy as np
from scipy.special import erf

from sxlib.archive import epsf_to_grid
from sxlib.inject import psf_stamp
from sxlib.psfphot import model


def _pixel_gauss(dx, dy, sigma, n=11):
    """Exact fraction of a unit Gaussian star (centre offset dx, dy from the central pixel's centre) in each pixel."""
    e = np.arange(n + 1) - n / 2
    fx = np.diff(0.5 * (1 + erf((e - dx) / (np.sqrt(2) * sigma))))
    fy = np.diff(0.5 * (1 + erf((e - dy) / (np.sqrt(2) * sigma))))
    return np.outer(fy, fx)


def _epsf(sigma, ovs=5, m=33):
    """An ePSF table entry: the pixel-integrated star at sub-pixel offsets, sampled every 1/ovs pixel."""
    u = (np.arange(m) - (m - 1) / 2) / ovs
    c = (_pixel_gauss(0, 0, sigma, 1)).sum()               # normalisation below makes the absolute scale irrelevant
    g = np.array([[_pixel_gauss(x, y, sigma, 1)[0, 0] for x in u] for y in u]) / c
    return g / g.sum()


def test_epsf_sampled_matches_pixel_values():
    sigma = 0.6
    grid = epsf_to_grid(_epsf(sigma), 5)[0]
    assert grid.shape == (101, 101) and abs(grid.sum() - 1) < 1e-5
    for dx, dy in ((0, 0), (0.3, -0.2), (-0.45, 0.4)):
        want = _pixel_gauss(dx, dy, sigma)
        want = want / want.sum()
        got = model(grid, dx, dy, sample=True)
        assert np.abs(got - want).max() < 0.01 * want.max()
        st = psf_stamp(grid, dx, dy, sample=True)
        assert np.abs(st - want).max() < 0.01 * want.max()
    # integrating an ePSF would blur it by one more pixel: the peak drops noticeably
    assert model(grid, 0, 0, sample=False).max() < 0.9 * model(grid, 0, 0, sample=True).max()
