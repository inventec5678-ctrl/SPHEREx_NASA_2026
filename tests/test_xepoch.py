"""Cross-epoch proper motion and the joint proper-motion + parallax fit (sxlib/xepoch.py). No network.

    .venv/bin/python -m pytest tests/test_xepoch.py -q
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sxlib import xepoch as X  # noqa: E402
from sxlib.pmsearch import PIX, search_all  # noqa: E402
from tests.test_pmsearch import MJD, make_stacks, star_field  # noqa: E402

CDELT = (-PIX / 3600, PIX / 3600)
BASE = (MJD[-1] - X.MJD_CATWISE) / 365.25                        # ~10.9 yr


def catalogues(pos, mover=None, pm_px=(0.0, 0.0), gaia_has_mover=False, cw_own_pm=False):
    """Gaia and CatWISE entries at the stars' positions; the mover's CatWISE entry is where it was in 2015.4."""
    gaia, cw = [], []
    for i, (x, y) in enumerate(pos):
        is_m = i == mover
        if not is_m or gaia_has_mover:
            t = (MJD[-1] - 57388.0) / 365.25
            gaia.append({"x": float(x - (pm_px[0] * t if is_m else 0)), "y": float(y - (pm_px[1] * t if is_m else 0)), "m": 14.0,
                         "pmx": float(pm_px[0]) if is_m else 0.0, "pmy": float(pm_px[1]) if is_m else 0.0, "mjd0": 57388.0})
        cw.append({"x": float(x - (pm_px[0] * BASE if is_m else 0)), "y": float(y - (pm_px[1] * BASE if is_m else 0)), "m": 12.0,
                   "pmx": float(pm_px[0]) if is_m and cw_own_pm else 0.0, "pmy": float(pm_px[1]) if is_m and cw_own_pm else 0.0,
                   "mjd0": X.MJD_CATWISE})
    return {"gaia": gaia, "catwise": cw}


def test_affine_recovers_a_known_map():
    rng = np.random.default_rng(0)
    src = rng.uniform(0, 100, (60, 2))
    C = np.array([[1.0003, 0.0002], [-0.0001, 0.9998], [0.04, -0.03]])
    dst = np.c_[src, np.ones(60)] @ C + rng.normal(0, 0.01, (60, 2))
    dst[:3] += 2.0                                               # three outliers
    got, keep, rms = X.affine(src, dst)
    assert np.allclose(got, C, atol=0.01) and keep.sum() == 57 and rms < 0.03


def test_parallax_factors_have_unit_amplitude_at_the_ecliptic_pole():
    e, n = X.parallax_factors(270.0, 66.56, np.linspace(60000, 60365, 25))
    r = np.hypot(e, n)
    assert 0.97 < r.min() and r.max() < 1.03
    e, n = X.parallax_factors(120.0, 20.0, np.linspace(60000, 60365, 25))   # near the ecliptic: mostly east-west
    assert np.abs(e).max() > 0.95 and np.hypot(e, n).max() < 1.03


def test_fit_motion_recovers_motion_and_parallax():
    rng = np.random.default_rng(1)
    t = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    pf = [(0.9, 0.3), (-0.95, -0.2), (0.92, 0.28), (-0.9, -0.25), (0.93, 0.3)]
    pm, plx, sig = (0.8, -0.4), 0.35, 0.02
    east = 1.0 + pm[0] * t + plx * np.array([p[0] for p in pf]) + rng.normal(0, sig, 5)
    north = -2.0 + pm[1] * t + plx * np.array([p[1] for p in pf]) + rng.normal(0, sig, 5)
    f = X.fit_motion(t, east, north, np.full(5, sig), pf)
    assert abs(f["plx"] - plx) < 4 * f["plx_err"] and f["plx_err"] < 0.03
    assert abs(f["pm"][0] - pm[0]) < 0.05 and abs(f["pm"][1] - pm[1]) < 0.05
    assert f["dof"] == 5 and f["chi2"] < 20


def _epochs(plx_arcsec, pm=(1.5, -0.7), sig_px=0.008, seed=0):
    rng = np.random.default_rng(seed)
    mjd = [60800.0, 60982.0, 61165.0, 61347.0]
    pf = X.pass_factors(120.0, 20.0, mjd)
    ep = []
    for k, m in enumerate(mjd):
        t = (m - mjd[0]) / 365.25
        east, north = pm[0] * t + plx_arcsec * pf[k][0], pm[1] * t + plx_arcsec * pf[k][1]
        ep.append({"k": k, "X": 50.0 - east / PIX + rng.normal(0, sig_px), "Y": 50.0 + north / PIX + rng.normal(0, sig_px),
                   "err": sig_px * np.sqrt(2), "floor": 0.0})
    return ep, pf, mjd


def test_joint_fit_reports_an_injected_parallax_and_nothing_for_a_distant_star():
    ep, pf, mjd = _epochs(0.5)
    j = X.joint(ep, CDELT, pf, mjd)
    assert j["plx_mas"] is not None and abs(j["plx_mas"] - 500) < 4 * j["plx_err_mas"] and j["plx_err_mas"] < 100
    assert abs(j["dist_pc"] - 1000 / j["plx_mas"]) < 0.02
    assert abs(j["pm_fit_arcsec_yr"] - np.hypot(1.5, 0.7)) < 0.15
    ep, pf, mjd = _epochs(0.0)
    j = X.joint(ep, CDELT, pf, mjd)
    assert j["plx_mas"] is None and j["reason"] == "below_3_sigma"
    assert X.joint(ep[:2], CDELT, pf, mjd)["plx_mas"] is None               # two passes: nothing to fit
    j = X.joint(_epochs(0.5)[0][:3], CDELT, pf, mjd, trust_one_dof=False)     # three passes of a saturated star
    assert j["plx_mas"] is None and j["reason"] == "one_dof_unchecked"


def test_static_field_gives_no_cross_epoch_candidates():
    pos, amp = star_field(seed=11)
    st = make_stacks(pos, amp, seed=11)
    c, stats, stars, _ = X.candidates(st, MJD, catalogues(pos), CDELT)
    assert c == [] and stats["n_measured"] >= 35
    assert stats["floor_arcsec_yr"] <= 0.011                      # synthetic stars: only the built-in minimum is left


def test_slow_mover_is_found_across_epochs_and_labelled():
    pos, amp = star_field(seed=12)
    amp[3] = 15.0
    pm = np.array([0.20, -0.15]) / PIX                            # px/yr: 0.25 arcsec/yr, far below the one-year limit
    st = make_stacks(pos, amp, shift_per_yr=pm, mover=3, seed=12)
    res = search_all(st, MJD, catalogues(pos, 3, pm, cw_own_pm=True), cdelt=CDELT, ra=120.0, dec=20.0, log=lambda m: None)
    assert len(res["candidates"]) == 1
    c = res["candidates"][0]
    assert c["method"] == "xepoch" and c["id"] == 0 and 10 < c["baseline_yr"] < 11.5
    assert abs(c["pm_arcsec_yr"] - 0.25) < max(4 * c["pm_err_arcsec_yr"], 0.02) and c["sig"] >= 5
    assert abs(c["pmra"] - (-0.20)) < 0.03 and abs(c["pmdec"] - (-0.15)) < 0.03     # x grows to the west
    assert c["status"] == "known" and c["match"]["cat"] == "CatWISE2020"
    assert c["track"][0]["k"] == 0 and c["track"][-1]["k"] == 2 and c["n_bands_agree"] >= 2
    assert c["plx_mas"] is None and "plx_fit" in c                # no parallax was injected
    # Gaia knows the star: the label comes from Gaia
    res = search_all(st, MJD, catalogues(pos, 3, pm, gaia_has_mover=True), cdelt=CDELT, ra=120.0, dec=20.0, log=lambda m: None)
    assert [(c["status"], c["match"]["cat"]) for c in res["candidates"]] == [("known", "Gaia DR3")]
    # CatWISE's own motion says it is static: reported, but as a disagreement to be reviewed
    res = search_all(st, MJD, catalogues(pos, 3, pm), cdelt=CDELT, ra=120.0, dec=20.0, log=lambda m: None)
    assert [c["status"] for c in res["candidates"]] == ["mismatch"]


def test_a_comparable_neighbour_vetoes_the_candidate():
    pos, amp = star_field(seed=12)
    amp[3] = 15.0
    pm = np.array([0.20, -0.15]) / PIX
    st = make_stacks(pos, amp, shift_per_yr=pm, mover=3, seed=12)
    ov = catalogues(pos, 3, pm, cw_own_pm=True)
    ov["catwise"].append({"x": ov["catwise"][3]["x"] + 2.0, "y": ov["catwise"][3]["y"], "m": 12.5, "pmx": 0.0, "pmy": 0.0, "mjd0": X.MJD_CATWISE})
    c, stats, _, _ = X.candidates(st, MJD, ov, CDELT)
    assert c == [] and stats["rejected"].get("not_isolated") == 1


def test_search_all_without_catalogues_keeps_the_fast_mover_and_fits_it():
    pos, amp = star_field(seed=2)
    amp[5] = 20.0
    st = make_stacks(pos, amp, shift_per_yr=np.array([0.9, -0.8]), mover=5, seed=2)
    res = search_all(st, MJD, None, cdelt=CDELT, ra=120.0, dec=20.0, log=lambda m: None)
    assert len(res["candidates"]) == 1
    c = res["candidates"][0]
    assert c["method"] == "spherex" and c["id"] == 0 and abs(c["baseline_yr"] - 1.0) < 0.01
    assert abs(c["pm_err_arcsec_yr"] - c["pm_arcsec_yr"] / c["sig"]) < 0.01
    assert c["plx_mas"] is None and c["plx_fit"]["n_pass"] == 3 and c["plx_fit"]["saturated"] is False
    assert abs(c["plx_fit"]["pm_fit_arcsec_yr"] - np.hypot(0.9, 0.8) * PIX) < 0.5
