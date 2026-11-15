"""Pass-to-pass proper-motion search (sxlib/pmsearch.py) on synthetic pass stacks. No network, a few seconds.

    .venv/bin/python -m pytest tests/test_pmsearch.py -q
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sxlib.pmsearch import PIX, fit_position, search  # noqa: E402

MJD = [60800.0, 60982.6, 61165.25]          # three passes over exactly one year


def star_field(n=96, nstar=45, seed=0, min_sep=8.0, edge=10):
    """Well-separated star positions and amplitudes."""
    rng = np.random.default_rng(seed)
    pos = []
    while len(pos) < nstar:
        p = rng.uniform(edge, n - edge, 2)
        if all(np.hypot(*(p - q)) >= min_sep for q in pos):
            pos.append(p)
    return np.array(pos), 10 ** rng.uniform(0.0, 1.7, nstar)


def render(pos, amp, n=96, noise=0.02, seed=0, sigma=1.0):
    rng = np.random.default_rng(seed)
    img = rng.normal(0, noise, (n, n)).astype(np.float32)
    yy, xx = np.mgrid[0:n, 0:n]
    for (x, y), a in zip(pos, amp):
        x0, x1, y0, y1 = max(0, int(x) - 8), min(n, int(x) + 9), max(0, int(y) - 8), min(n, int(y) + 9)
        img[y0:y1, x0:x1] += a * np.exp(-((xx[y0:y1, x0:x1] - x) ** 2 + (yy[y0:y1, x0:x1] - y) ** 2) / (2 * sigma ** 2))
    return img


def make_stacks(pos, amp, shift_per_yr=None, mover=0, n=96, seed=0):
    """[P, 7, n, n]: band 0 and the six detector bands, independent noise in each; star `mover` moves linearly."""
    P = len(MJD)
    st = np.zeros((P, 7, n, n), np.float32)
    for k in range(P):
        p = pos.copy()
        if shift_per_yr is not None:
            p[mover] = p[mover] + np.asarray(shift_per_yr) * (MJD[k] - MJD[0]) / 365.25
        for b in range(7):
            st[k, b] = render(p, amp, n, seed=seed * 1000 + k * 10 + b)
    return st


def test_fit_position_is_subpixel_accurate():
    img = render(np.array([[40.37, 51.81]]), np.array([20.0]), seed=3)
    x, y, err, amp = fit_position(img, 40, 52)
    assert abs(x - 40.37) < 0.03 and abs(y - 51.81) < 0.03
    assert err < 0.05 and 15 < amp < 25


def test_static_field_gives_no_candidates():
    pos, amp = star_field(seed=1)
    res = search(make_stacks(pos, amp, seed=1), MJD, None, log=lambda m: None)
    assert res["candidates"] == []
    assert res["stats"]["floor_px"] <= 0.05


def test_injected_mover_is_recovered_with_its_motion():
    pos, amp = star_field(seed=2)
    amp[5] = 20.0
    shift = np.array([0.9, -0.8])                               # px per year: 1.204 px = 7.41 arcsec/yr
    res = search(make_stacks(pos, amp, shift_per_yr=shift, mover=5, seed=2), MJD, None, log=lambda m: None)
    assert len(res["candidates"]) == 1
    c = res["candidates"][0]
    assert np.hypot(c["x"] - pos[5][0], c["y"] - pos[5][1]) < 0.5
    assert abs(c["pm_arcsec_yr"] - np.hypot(*shift) * PIX) < 0.4
    assert abs(c["dx"] - shift[0]) < 0.08 and abs(c["dy"] - shift[1]) < 0.08
    assert c["status"] == "new" and c["n_bands_agree"] >= 2 and c["sig"] >= 5
    assert [t["k"] for t in c["track"]] == [0, 1, 2]


def test_catalogue_only_labels_the_result():
    pos, amp = star_field(seed=4)
    amp[7] = 20.0
    shift = np.array([-1.0, 0.6])
    st = make_stacks(pos, amp, shift_per_yr=shift, mover=7, seed=4)
    gaia = [{"x": float(x), "y": float(y), "m": 14.0, "pmx": 0.0, "pmy": 0.0, "mjd0": MJD[0]} for x, y in pos]
    gaia[7].update(pmx=float(shift[0]), pmy=float(shift[1]))
    res = search(st, MJD, {"gaia": gaia, "catwise": []}, log=lambda m: None)
    assert [c["status"] for c in res["candidates"]] == ["known"]
    gaia[7].update(pmx=0.0, pmy=0.0)                             # the catalogue says it does not move
    res = search(st, MJD, {"gaia": gaia, "catwise": []}, log=lambda m: None)
    assert [c["status"] for c in res["candidates"]] == ["static"]


def test_unexplained_mover_missing_its_middle_pass_is_not_reported():
    pos, amp = star_field(seed=2)
    amp[5] = 20.0
    shift = np.array([0.9, -0.8])
    st = make_stacks(pos, amp, shift_per_yr=shift, mover=5, seed=2)
    x, y = pos[5] + shift * (MJD[1] - MJD[0]) / 365.25           # blank the mover in the middle pass, every band
    st[1, :, int(y) - 4:int(y) + 5, int(x) - 4:int(x) + 5] = np.nan
    res = search(st, MJD, None, log=lambda m: None)
    assert res["candidates"] == [] and res["stats"]["n_unverified"] == 1
    # a catalogued mover is still reported: the catalogue confirms what the missing pass cannot
    gaia = [{"x": float(px), "y": float(py), "m": 14.0, "pmx": 0.0, "pmy": 0.0, "mjd0": MJD[0]} for px, py in pos]
    gaia[5].update(pmx=float(shift[0]), pmy=float(shift[1]))
    res = search(st, MJD, {"gaia": gaia, "catwise": []}, log=lambda m: None)
    assert [c["status"] for c in res["candidates"]] == ["known"]
