"""Variable-star search on synthetic data (no network, a few seconds): pytest tests/test_varsearch.py"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sxlib import varsearch as V  # noqa: E402

DET_RANGE = {1: (0.75, 1.11), 2: (1.10, 1.64), 3: (1.63, 2.42), 4: (2.40, 3.82), 5: (3.81, 4.42), 6: (4.41, 5.00)}


def synthetic_field(seed=3, n=128, per=12):
    """Three passes x six detectors x `per` exposures of a field with constant stars, one unsaturated variable
    (x1.4 fainter in the last pass), one saturated constant star and one saturated variable (x1.6 brighter in the
    first pass). Every star has its own spectral slope; each pass has its own zero point per detector."""
    rng = np.random.default_rng(seed)
    n_pass = 3
    det = np.tile(np.repeat(np.arange(1, 7), per), n_pass)
    pk = np.repeat(np.arange(n_pass), 6 * per)
    N = len(det)
    mjd = 60800 + pk * 180 + rng.uniform(0, 12, N)
    lam = np.array([rng.uniform(*DET_RANGE[d]) for d in det])
    zp = 1 + 0.04 * rng.standard_normal((n_pass, 7))                     # calibration drift, the same for every star
    grid = [(x, y) for x in range(16, 113, 16) for y in range(16, 113, 16)]
    sat = [(32.3, 95.6), (95.7, 32.4)]                                   # constant, variable
    grid = [g for g in grid if all(np.hypot(g[0] - s[0], g[1] - s[1]) > 24 for s in sat)]
    stars = [{"x": x + rng.uniform(-.4, .4), "y": y + rng.uniform(-.4, .4), "flux": 10 ** rng.uniform(2.6, 3.6),
              "alpha": rng.uniform(-2, 1), "L": [1, 1, 1], "sat": False} for x, y in grid]
    stars[5]["L"] = [1.0, 1.0, 1 / 1.4]; stars[5]["flux"] = 1500.0
    stars += [{"x": sat[0][0], "y": sat[0][1], "flux": 4e5, "alpha": -1.0, "L": [1, 1, 1], "sat": True},
              {"x": sat[1][0], "y": sat[1][1], "flux": 4e5, "alpha": 0.5, "L": [1.6, 1.0, 1.0], "sat": True}]
    yy, xx = np.mgrid[0:n, 0:n]
    img = rng.standard_normal((N, n, n)).astype(np.float32)
    flag = np.zeros((N, n, n), np.uint8)
    for s in stars:
        r2 = (xx - s["x"]) ** 2 + (yy - s["y"]) ** 2
        psf = 0.88 * np.exp(-r2 / (2 * 0.85 ** 2)) / (2 * np.pi * 0.85 ** 2) + 0.12 * np.exp(-r2 / (2 * 3.5 ** 2)) / (2 * np.pi * 3.5 ** 2)
        amp = s["flux"] * (lam / 2.0) ** s["alpha"] * np.array([s["L"][p] for p in pk]) * zp[pk, det] * (1 + 0.03 * rng.standard_normal(N))
        img += (amp[:, None, None] * psf[None]).astype(np.float32)
        if s["sat"]:
            core = r2 <= 2.6 ** 2
            img[:, core] = np.nan; flag[:, core] = 1
    stacks = np.zeros((n_pass, 7, n, n), np.float32)
    for p in range(n_pass):
        stacks[p, 0] = np.median(img[pk == p], axis=0)
    F = {"img": img, "var": np.ones_like(img), "flag": flag, "lam": np.repeat(lam.astype(np.float32), 4).reshape(N, 2, 2), "ds": 64,
         "stacks": stacks, "mjd": mjd, "pass": pk, "det": det, "lam_um": lam, "pass_mjd": [60806 + 180 * p for p in range(n_pass)]}
    return F, stars


def test_finds_the_injected_variables_and_nothing_else():
    F, stars = synthetic_field()
    res = V.search_cube(F, log=lambda m: None)
    assert res["stats"]["n_sources"] >= len(stars) - 1
    var_unsat, var_sat = stars[5], stars[-1]
    hits = {id(s): V.nearest(res["candidates"], s["x"], s["y"], 1.0) for s in stars}
    assert hits[id(var_unsat)] is not None, "the unsaturated variable was missed"
    assert hits[id(var_sat)] is not None, "the saturated variable was missed"
    assert len(res["candidates"]) == 2, [(c["x"], c["y"], c["amp"]) for c in res["candidates"]]     # no constant star
    a, b = hits[id(var_unsat)], hits[id(var_sat)]
    assert not a["saturated"] and abs(a["amp"] / 1.4 - 1) < 0.15 and a["pair"][1] == 2
    assert b["saturated"] and abs(b["amp"] / 1.6 - 1) < 0.2 and b["pair"][0] == 0
    assert a["n_dets_agree"] >= V.MIN_DETS and b["n_dets_agree"] >= V.MIN_DETS
    # the saturated constant star is measured (ring photometry) and stays below the threshold
    row = V.nearest(res["all"], stars[-2]["x"], stars[-2]["y"], 1.0)
    assert row is not None and row["saturated"] and not row["candidate"]


def test_fit_recovers_pass_factors():
    rng = np.random.default_rng(1)
    n = 90
    pk = np.repeat([0, 1, 2], n // 3)
    lam = rng.uniform(1.1, 1.64, n)
    L = np.array([1.0, 1.3, 0.8])
    flux = 1000 * (lam / 1.3) ** -1.5 * L[pk] * (1 + 0.05 * rng.standard_normal(n))
    l, C, used, rms = V.fit_detector(lam, flux, pk, 3)
    truth = np.log(L) - np.log(L).mean()
    assert used >= n - 3 and 0.03 < rms < 0.08
    assert np.all(np.abs(l - truth) < 4 * np.sqrt(np.diag(C)) + 1e-3)
    assert np.all(np.sqrt(np.diag(C)) < 0.03)


def test_no_bias_for_a_faint_star_with_a_noisier_pass():
    """A constant faint star observed at S/N 3 in one pass and 6 in another must not look variable (a log fit or a
    cut on single-point S/N puts the noisy pass ~10% too high)."""
    rng = np.random.default_rng(7)
    n = 400
    pk = np.repeat([0, 1], n)
    lam = rng.uniform(2.4, 3.8, 2 * n)
    flux = 100 * (lam / 3.0) ** 0.5 + np.where(pk == 0, 100 / 3, 100 / 6) * rng.standard_normal(2 * n)
    l, C, used, rms = V.fit_detector(lam, flux, pk, 2)
    d, e = l[0] - l[1], np.sqrt(C[0, 0] + C[1, 1] - 2 * C[0, 1])
    assert abs(d) < 3 * e and e < 0.03


def test_blended_sources_are_not_searched():
    F, stars = synthetic_field(seed=5)
    srcs = V.find_sources(F["stacks"])
    assert not any(s["blended"] for s in srcs if not s["hole"])        # isolated stars on a grid
    # put a second star 3 px from one of them
    s = stars[2]
    yy, xx = np.mgrid[0:F["img"].shape[1], 0:F["img"].shape[2]]
    r2 = (xx - s["x"] - 3) ** 2 + (yy - s["y"]) ** 2
    F["img"] += (0.6 * s["flux"] * np.exp(-r2 / (2 * 0.85 ** 2)) / (2 * np.pi * 0.85 ** 2)).astype(np.float32)[None]
    for p in range(3):
        F["stacks"][p, 0] = np.median(F["img"][F["pass"] == p], axis=0)
    srcs = V.find_sources(F["stacks"])
    near = [q for q in srcs if np.hypot(q["x"] - s["x"], q["y"] - s["y"]) < 4]
    assert near and all(q["blended"] for q in near)
