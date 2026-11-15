"""The interstellar comet page's products (scripts/comet_build.py) and its NEOSSat status endpoint (web/api_comet.py).
No network.

    .venv/bin/python -m pytest tests/test_comet.py -q
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("comet_build", ROOT / "scripts" / "comet_build.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def test_band_of_uses_the_wavelength_at_the_comet():
    assert C.band_of(4.26) == "co2" and C.band_of(4.20) == "co2" and C.band_of(4.32) == "co2"
    assert C.band_of(4.0) == "blue" and C.band_of(4.5) == "red"
    assert C.band_of(4.15) is None and C.band_of(4.38) is None and C.band_of(1.2) is None


def test_continuum_is_interpolated_linearly_in_wavelength():
    assert C.interp_continuum(10.0, 4.0, 20.0, 4.5, 4.25) == pytest.approx(15.0)
    img = C.interp_continuum(np.full((3, 3), 2.0), 4.0, np.full((3, 3), 4.0), 4.5, 4.4)
    assert np.allclose(img, 3.6)


def gauss(n, amp, sig, bg=0.0, noise=0.0, seed=0):
    yy, xx = np.mgrid[:n, :n]
    c = (n - 1) / 2
    img = bg + amp * np.exp(-((xx - c) ** 2 + (yy - c) ** 2) / (2 * sig ** 2))
    return img + np.random.default_rng(seed).normal(0, noise, img.shape) if noise else img


def test_aperture_flux_recovers_a_gaussian_over_a_flat_background():
    n, amp, sig = 101, 5.0, 1.5
    img = gauss(n, amp, sig, bg=0.3, noise=0.01)
    f, e, cov = C.aperture_flux(img, np.full(img.shape, 0.01 ** 2), 6, 20, 30)
    assert cov == 1.0
    assert f == pytest.approx(2 * np.pi * sig ** 2 * amp, rel=0.02)
    assert 0 < e < 0.1 * f
    img[48:53, 48:53] = np.nan                       # the core missing: refused, not guessed
    assert np.isnan(C.aperture_flux(img, None, 4, 20, 30)[0])


def test_weighted_mean_scales_errors_up_only():
    m, e, n = C.weighted_mean([1.0, 1.0, 1.0], [0.1, 0.1, 0.1])
    assert m == 1.0 and e == pytest.approx(0.1 / np.sqrt(3)) and n == 3
    m2, e2, _ = C.weighted_mean([0.0, 2.0], [0.1, 0.1])
    assert m2 == pytest.approx(1.0) and e2 > 0.1 / np.sqrt(2) * 5


def test_stack_drops_a_star_that_crosses_one_frame():
    frames = [np.zeros((9, 9)) for _ in range(5)]
    frames[2][4, 4] = 100.0
    out = C.stack(frames, [1.0] * 5)
    assert out[4, 4] == 0.0
    nan = [np.full((3, 3), np.nan), np.ones((3, 3)), np.ones((3, 3)) * 3]
    assert np.allclose(C.stack(nan, [1, 1, 1]), 2.0)          # a missing frame is ignored


def test_fill_holes_fills_islands_but_not_the_edge():
    img = gauss(41, 1.0, 6.0, bg=1.0)
    img[19:22, 19:22] = np.nan                 # a flagged star core inside the image
    img[:, :5] = np.nan                        # off the detector
    out, filled = C.fill_holes(img)
    assert filled[20, 20] and not filled[20, 2]
    assert np.isfinite(out[20, 20]) and abs(out[20, 20] - 2.0) < 0.15
    assert np.isnan(out[20, 2])


def test_resample_puts_the_comet_at_the_grid_centre_north_up():
    from astropy.wcs import WCS
    n = 117
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [170.0, 3.0]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    th = np.radians(30)                         # a rotated detector frame
    s = C.PIX / 3600
    w.wcs.cd = [[-s * np.cos(th), s * np.sin(th)], [s * np.sin(th), s * np.cos(th)]]
    ra, dec = 170.03, 3.02                      # the comet, off the cutout centre
    x, y = w.world_to_pixel_values(ra, dec)
    yy, xx = np.mgrid[:n, :n]
    img = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.2 ** 2))
    g = C.resample(img, w, ra, dec, n=41)
    assert np.unravel_index(np.nanargmax(g), g.shape) == (20, 20)
    # a source 5 pixels north of the comet lands 5 rows up (+y) on the north-up grid
    x2, y2 = w.world_to_pixel_values(ra, dec + 5 * s)
    img2 = np.exp(-((xx - x2) ** 2 + (yy - y2) ** 2) / (2 * 1.2 ** 2))
    g2 = C.resample(img2, w, ra, dec, n=41)
    assert np.unravel_index(np.nanargmax(g2), g2.shape) == (25, 20)


def test_band_integral_recovers_the_area_of_a_sampled_band():
    # a straight continuum plus a Gaussian band (the band as one exposure's ~0.1 um filter would see it), sampled
    # every 0.035 um like SPHEREx's D5 steps
    lam = np.arange(3.90, 4.62, 0.035)
    cont = 10 + 20 * (lam - 3.9)
    band_mjy = 600 * np.exp(-0.5 * ((lam - 4.26) / 0.04) ** 2)
    mjy = cont + band_mjy
    F, eF, coef, nb, nc = C.band_integral(lam, mjy, np.full(lam.size, 0.5))
    fine = np.linspace(4.0, 4.5, 5001)
    flam = 600 * np.exp(-0.5 * ((fine - 4.26) / 0.04) ** 2) * 1e-29 * 2.99792458e14 / fine ** 2
    truth = float(np.sum((fine[1:] - fine[:-1]) * (flam[1:] + flam[:-1]) / 2))
    assert F == pytest.approx(truth, rel=0.03)
    assert coef[0] == pytest.approx(20, abs=0.5) and nb >= 5 and nc >= 8
    assert 0 < eF < 0.01 * F
    # no band: the integral is consistent with zero
    F0, e0, *_ = C.band_integral(lam, cont + np.random.default_rng(3).normal(0, 0.5, lam.size), np.full(lam.size, 0.5))
    assert abs(F0) < 4 * e0


def test_parse_horizons_observer_table():
    txt = """header
 Date__(UT)__HR:MN, , , R.A._(ICRF), DEC_(ICRF), T-mag, N-mag, r, rdot, delta, deldot, S-O-T,/r, S-T-O,
*******
$$SOE
 2025-Aug-01 00:00, , , 252.89203, -17.51420, 18.118, n.a., 3.49193, -50.1, 2.81145, -20.5, 124.8343,/T, 13.8059,
 2025-Aug-02 00:00, , , 252.20000, -17.40000, 18.070, n.a., 3.46000, -50.0, 2.80000, -20.0, 123.0000,/T, 14.0000,
$$EOE
"""
    rows = C.parse_horizons(txt)
    assert len(rows) == 2 and rows[0]["date"] == "2025-Aug-01 00:00"
    assert rows[0]["ra"] == pytest.approx(252.89203) and rows[0]["dec"] == pytest.approx(-17.5142)
    assert rows[0]["r_au"] == pytest.approx(3.49193) and rows[0]["delta_au"] == pytest.approx(2.81145)
    assert rows[0]["T_mag"] == pytest.approx(18.118) and rows[0]["phase"] == pytest.approx(13.8059)


def test_v_infinity_of_a_hyperbolic_flyby():
    # straight-line motion at 0.03 au/day far from the Sun: v_inf -> v (52 km/s), minus a little for the Sun's pull
    vec = [{"jd": 2460000 + k, "x": 50 + 0.03 * k, "y": 50.0, "z": 0.0} for k in range(10)]
    v = C.v_infinity_kms(vec)
    assert v == pytest.approx(0.03 * 149597870.7 / 86400, rel=0.01)


def test_votable_reader(tmp_path):
    from astropy.table import Table
    t = Table({"obs_id": ["2025W50_2A_0813_4", "2025W31_2A_0156_1"], "spherex_detector": ["D3", "D6"],
               "comet_ra": [166.6, 252.66], "comet_dec": [5.36, -17.49], "t_min": [61022.1, 60888.333], "t_max": [61022.2, 60888.335]})
    f = tmp_path / "t.vot"
    t.write(str(f), format="votable")
    rows = C.read_obs_table(f)
    assert [r["obs_id"] for r in rows] == ["2025W31_2A_0156_1", "2025W50_2A_0813_4"]
    assert rows[0]["det"] == 6 and C.epoch_of(rows[0]["t_min"]) == "aug" and C.epoch_of(rows[1]["t_min"]) == "dec"


def test_rough_q_co2_is_of_a_sensible_size():
    # 1e-15 W/m^2 in a 25" aperture at r = 3.2 au, Delta = 2.7 au: of order 1e27 molecules/s
    q = C.rough_q_co2(1e-15, 3.2, 2.7, 24.6)
    assert 3e26 < q < 3e27


def test_clean_makes_valid_json():
    out = json.dumps(C.clean({"a": float("nan"), "b": [np.float32(1.5), np.int64(2)], "c": np.inf}), allow_nan=False)
    assert json.loads(out) == {"a": None, "b": [1.5, 2], "c": None}


def test_neossat_status(tmp_path):
    from web.api_comet import neossat_status
    assert neossat_status(tmp_path) == {"available": False}
    (tmp_path / "neossat.json").write_text("{not json", encoding="utf-8")
    assert neossat_status(tmp_path) == {"available": False}
    (tmp_path / "neossat.json").write_text(json.dumps({"date": "2025-12-02", "n_frames": 48, "detected": True}), encoding="utf-8")
    (tmp_path / "neossat.webp").write_bytes(b"x")
    s = neossat_status(tmp_path)
    assert s["available"] and s["n_frames"] == 48 and s["images"] == {"neossat.webp": True, "neossat_stars.webp": False}
