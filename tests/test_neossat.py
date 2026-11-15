"""Offline tests for sxlib.neossat (NEOSSat preprocessing, astrometric calibration) and web/api_neossat (coverage)."""
import math

import numpy as np
import pytest
from astropy.io import fits

from sxlib import neossat as N


def _fake_sky(seed=3, n_stars=160, ra0=200.0, dec0=10.0, radius=0.35):
    rng = np.random.default_rng(seed)
    r = radius * np.sqrt(rng.uniform(0, 1, n_stars))
    th = rng.uniform(0, 2 * np.pi, n_stars)
    ra = ra0 + r * np.cos(th) / math.cos(math.radians(dec0))
    dec = dec0 + r * np.sin(th)
    g = rng.uniform(9, 15.5, n_stars)
    return [{"ra": float(a), "dec": float(d), "phot_g_mean_mag": float(m), "pmra": 0.0, "pmdec": 0.0, "parallax": 0.0}
            for a, d, m in zip(ra, dec, g)]


def _true_wcs(ra0, dec0, shape, angle_deg, parity, scale_arcsec=3.02, offset_px=(17.0, -11.0)):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra0, dec0]
    w.wcs.crpix = [shape[1] / 2 + offset_px[0], shape[0] / 2 + offset_px[1]]
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    w.wcs.cd = (scale_arcsec / 3600) * np.array([[c, -s], [s, c]]) @ np.diag([parity, 1.0])
    return w


def _render(w, stars, shape, fwhm=2.6, seed=5):
    rng = np.random.default_rng(seed)
    img = rng.normal(100.0, 5.0, shape)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    sig = fwhm / 2.355
    x, y = w.all_world2pix([s["ra"] for s in stars], [s["dec"] for s in stars], 0)
    for xi, yi, s in zip(x, y, stars):
        if -10 < xi < shape[1] + 10 and -10 < yi < shape[0] + 10:
            amp = 30000 * 10 ** (-0.4 * (s["phot_g_mean_mag"] - 9))
            box = (abs(xx - xi) < 8) & (abs(yy - yi) < 8)
            img[box] += amp * np.exp(-((xx[box] - xi) ** 2 + (yy[box] - yi) ** 2) / (2 * sig ** 2))
    return img.astype(np.float32)


@pytest.mark.parametrize("angle,parity,shape", [(215.0, 1, (256, 256)), (101.0, -1, (400, 420))])
def test_solve_recovers_wcs(angle, parity, shape):
    ra0, dec0 = 200.0, 10.0
    stars = _fake_sky(ra0=ra0, dec0=dec0)
    w = _true_wcs(ra0 + 0.01, dec0 - 0.008, shape, angle, parity)
    img = _render(w, stars, shape)
    hdr = fits.Header({"DATE-OBS": "2019-11-01T00:00:00", "EXPOSURE": 1.0})
    # the pointing given to the solver is ~1' off, as NEOSSat's attitude estimate is
    sol = N.solve(img, hdr, gaia_rows=stars, ra0=ra0, dec0=dec0)
    assert sol is not None
    assert sol["rms_arcsec"] < 0.3
    assert sol["n_match"] >= 8
    # every pixel maps to the same sky position within 0.3"
    px = np.array([[10, 10], [shape[1] - 10, 20], [shape[1] / 2, shape[0] / 2], [30, shape[0] - 15]], float)
    a = np.array(w.all_pix2world(px[:, 0], px[:, 1], 0)).T
    b = np.array(sol["wcs"].all_pix2world(px[:, 0], px[:, 1], 0)).T
    sep = np.hypot((a[:, 0] - b[:, 0]) * math.cos(math.radians(dec0)), a[:, 1] - b[:, 1]) * 3600
    assert sep.max() < 0.3


def test_solve_excludes_target():
    ra0, dec0 = 200.0, 10.0
    stars = _fake_sky(ra0=ra0, dec0=dec0)
    shape = (256, 256)
    w = _true_wcs(ra0, dec0, shape, 30.0, 1)
    img = _render(w, stars, shape)
    hdr = fits.Header({"DATE-OBS": "2019-11-01T00:00:00", "EXPOSURE": 1.0})
    x, y = w.all_world2pix([s["ra"] for s in stars], [s["dec"] for s in stars], 0)
    j = int(np.argmin(np.hypot(x - 128, y - 128)))
    sol_all = N.solve(img, hdr, gaia_rows=stars, ra0=ra0, dec0=dec0)
    sol_ex = N.solve(img, hdr, gaia_rows=stars, ra0=ra0, dec0=dec0, exclude=[(stars[j]["ra"], stars[j]["dec"])])
    assert sol_ex["n_match"] <= sol_all["n_match"]


def test_detect_drops_hot_pixels():
    img = np.random.default_rng(1).normal(0, 1, (120, 120)).astype(np.float32)
    yy, xx = np.mgrid[0:120, 0:120]
    img += 800 * np.exp(-((xx - 40.3) ** 2 + (yy - 60.7) ** 2) / (2 * 1.1 ** 2))
    img[90, 90] += 3000                     # a hot pixel
    det = N.detect(img)
    assert len(det) == 1
    assert abs(det[0, 0] - 40.3) < 0.1 and abs(det[0, 1] - 60.7) < 0.1


def test_overscan_trim_and_bias():
    d = np.zeros((256, 728), np.float32) + 1700.0
    d[:, 472:] += 50.0                       # sky in the science area
    d[10, :64] += 20.0                       # one row with a higher bias level
    d[10, 472:] += 20.0
    hdr = fits.Header({"OVERSCAN": 1, "BIASSEC": "[1:64,1:256]", "TRIMSEC": "[473:728,1:256]"})
    out = N.overscan_correct(d, hdr)
    assert out.shape == (256, 256)
    assert np.allclose(out, 50.0)


def test_fit_gauss_ignores_saturated_core():
    yy, xx = np.mgrid[0:21, 0:21]
    img = 1000 * np.exp(-((xx - 10.3) ** 2 + (yy - 9.6) ** 2) / (2 * 1.5 ** 2)) + 5
    img[9:11, 10:12] = np.nan
    x, y, ex, ey, fwhm, amp = N.fit_gauss(img, 10, 10, hw=5)
    assert abs(x - 10.3) < 0.02 and abs(y - 9.6) < 0.02
    assert abs(fwhm - 2.355 * 1.5) < 0.05


def test_north_up_grid_and_resample():
    w, n = N.north_up_wcs(100.0, 20.0, 60.0, 1.0)
    assert n == 60
    ra_e, _ = w.all_pix2world(0, n / 2, 0)
    ra_w, _ = w.all_pix2world(n - 1, n / 2, 0)
    assert ra_e > ra_w                       # east is on the left
    img = np.zeros((n, n))
    img[30, 20] = 1.0
    out = N.resample(img, w, w, (n, n))
    assert out[30, 20] == pytest.approx(1.0)


def test_coverage_summary_counts_exposures_once():
    rows = []
    for oid, mjd, prods in (("2019286012648", 58769.06, ["raw"]), ("2019286012848", 58769.07, ["raw"]),
                            ("2020170173036", 59018.73, ["raw", "clean"])):
        for p in prods:
            rows.append({"obs_publisher_did": f"ivo://cadc.nrc.ca/NEOSSAT?{oid}/{p}", "obs_id": oid, "t_min": mjd,
                         "t_exptime": 1.1 if p == "raw" else 100.0, "target_name": "X", "product": p})
    s = N.coverage_summary(rows)
    assert [d["date"] for d in s] == ["2019-10-13", "2020-06-18"]
    assert [d["n"] for d in s] == [2, 1]
    assert s[1]["calibrated"] and s[1]["product"] == "clean"
    assert s[1]["thumb"].endswith("2020170173036_clean_prev_256.png")
    assert N.file_name("2019286012648", "raw") == "NEOS_SCI_2019286012648.fits"
    assert N.file_name("2020170173036", "clean") == "NEOS_SCI_2020170173036_clean.fits"


def test_api_coverage_key_and_document():
    from web import api_neossat as A
    assert A.key_of(359.999, 4.741) == (0.0, 4.74, "0.00_+4.74")
    rr, dd, k = A.key_of(-0.5, -90.3)
    assert rr == pytest.approx(359.5) and dd == -90.0
    rows = [{"obs_publisher_did": "ivo://cadc.nrc.ca/NEOSSAT?2025336212125/cor", "obs_id": "2025336212125",
             "t_min": 61011.89, "t_exptime": 15.0, "target_name": "3I", "product": "cor"}]
    doc = A.summarise(rows, 178.74, 1.06)
    assert doc["status"] == "ok" and doc["n"] == 1 and doc["years"] == {"2025": 1}
    assert doc["thumb"]["url"].startswith(N.RAVEN)
    empty = A.summarise([], 10.0, 10.0)
    assert empty["n"] == 0 and empty["thumb"] is None
