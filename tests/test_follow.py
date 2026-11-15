"""Follow an asteroid (sxlib/follow.py, web/api_follow.py, scripts/follow_build.py): parsing IRSA MOST and JPL SBDB
answers, sampling, forced photometry on a synthetic cutout, the light-curve period search, the job endpoints and the
MOST-vs-pipeline comparison. No network."""
import importlib.util
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from fastapi import FastAPI

from asgi_client import get, request
from sxlib import follow as F

ROOT = Path(__file__).resolve().parent.parent

# the head of a real MOST "Brief" answer (65 Cybele, 2025-12), cut to three rows and the columns we read
MOST_TXT = r"""\output_url = "https://irsa.ipac.caltech.edu/workspace/TMP_x/MOST/pid1"
\catalog = "spherex"
\object_name = "65 Cybele (A861 EB)"
\eccentricity = " 0.127740433498258"
\fixlen = T
|    ra_obj|   dec_obj|sun_dist|geo_dist|   phase|  vmag|      observationid|productid|               mjd_start|                 mjd_end|uri|
|    double|    double|  double|  double|  double|double|               char|     char|                  double|                  double|char|
 177.027460   1.627777   3.4212   3.4399  16.5010  13.25   2025W50_1A_0348_2        D1          61018.497835903          61018.499168281 ibe/data/spherex/dr1/level2/2025W50_1A/l2b-v27-2026-209/1/level2_2025W50_1A_0348_2D1_spx_l2b-v27-2026-209.fits
 177.027460   1.627777   3.4212   3.4399  16.5010  13.25   2025W50_1A_0348_2        D4          61018.497835903          61018.499168281 ibe/data/spherex/dr1/level2/2025W50_1A/l2b-v27-2026-209/4/level2_2025W50_1A_0348_2D4_spx_l2b-v27-2026-209.fits
 178.333262   1.153326   3.4123   3.3213  16.7345  13.18   2025W51_1A_0427_1        D4          61025.970141887          61025.971474265 ibe/data/spherex/qr3/level2/2025W51_1A/l2b-v27-2026-210/4/level2_2025W51_1A_0427_1D4_spx_l2b-v27-2026-210.fits
"""


def test_parse_most_brief():
    meta, rows = F.parse_ipac(MOST_TXT)
    assert meta["object_name"] == "65 Cybele (A861 EB)"
    assert len(rows) == 3 and rows[0]["productid"] == "D1"
    ims = F.most_images(rows)
    assert [i["detector"] for i in ims] == [1, 4, 4]
    a = ims[0]
    assert a["url"].startswith("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/")
    assert a["obs_id"] == "2025W50_1A_0348_2" and a["release"] == "dr1" and ims[2]["release"] == "qr3"
    assert a["mjd"] == pytest.approx((61018.497835903 + 61018.499168281) / 2)
    assert (a["ra"], a["dec"], a["vmag"], a["r_au"], a["d_au"]) == (177.02746, 1.627777, 13.25, 3.4212, 3.4399)


def test_most_errors():
    amb = ("Object Name Error:\n\nUser Input String=Vesta\n\nMultiple matches to the input string in the list from Horizons.\n\n"
           "Vesta, Object Type=Asteroid, NAIF ID=2000004, Designation=NO_VALUE \n"
           "4 Vesta, Object Type=Asteroid, NAIF ID=20000004, Designation=A807 FA \n")
    e = F.parse_most_error(amb)
    assert e.code == "ambiguous" and e.choices == ["Vesta", "4 Vesta"]
    assert F.parse_most_error("Object Name Error:\nUser Input String=xyz\nHORIZONS name lookup failed\n").code == "unknown"
    assert F.parse_most_error("MOST: *** Error connecting to HORIZONS").code == "most_down"


def test_parse_sbdb():
    ok = F.parse_sbdb({"object": {"fullname": "65 Cybele (A861 EB)", "spkid": "20000065", "kind": "an",
                                  "orbit_class": {"name": "Outer Main-belt Asteroid"}}})
    assert ok == {"status": "ok", "name": "65 Cybele (A861 EB)", "short": "65 Cybele", "spkid": "20000065",
                  "kind": "asteroid", "cls": "Outer Main-belt Asteroid"}
    c = F.parse_sbdb({"object": {"fullname": "C/2025 A6 (Lemmon)", "spkid": "1004054", "kind": "cu"}})
    assert c["kind"] == "comet" and c["short"] == "C/2025 A6 (Lemmon)"
    amb = F.parse_sbdb({"code": "300", "list": [{"name": "349P/Lemmon", "pdes": "349P"}, {"pdes": "2025 A6"}]})
    assert amb == {"status": "ambiguous", "choices": ["349P/Lemmon", "2025 A6"]}
    assert F.parse_sbdb({"code": "200", "message": "specified object was not found"}) == {"status": "unknown"}
    ph = F.parse_phys({"phys_par": [{"name": "rot_per", "value": "6.0814", "ref": "LCDB"}, {"name": "spec_T", "value": "P"},
                                    {"name": "diameter", "value": "237.26"}, {"name": "GM", "value": "1"}]})
    assert ph == {"rot_h": 6.0814, "rot_ref": "LCDB", "tholen": "P", "diam_km": 237.26}


def test_names_and_slugs():
    assert F.slugify("65 Cybele (A861 EB)") == "65-cybele-a861-eb"
    assert F.slugify("C/2025 A6 (Lemmon)", "2026-02-01", None) == "c-2025-a6-lemmon_2026-02-01_now"
    assert F.short_name("65 Cybele (A861 EB)") == "65 Cybele"
    assert F.short_name("(2024 YR4)") == "2024 YR4"
    assert F.short_name("29P/Schwassmann-Wachmann 1") == "29P/Schwassmann-Wachmann 1"


def _img(obs, det, mjd):
    return {"obs_id": obs, "detector": det, "mjd": mjd, "ra": 1.0, "dec": 2.0}


def test_sample_caps_and_keeps_detector_pairs():
    ims = [_img(f"o{k:03d}", d, 60000 + k * 0.1) for k in range(200) for d in (1, 4)]
    s = F.sample(ims, 150)
    assert 140 <= len(s) <= 152
    by = {}
    for im in s:
        by.setdefault(im["obs_id"], []).append(im["detector"])
    assert all(sorted(v) == [1, 4] for v in by.values())          # both wavelengths of one exposure together
    t = sorted(im["mjd"] for im in s)
    assert t[0] == 60000 and t[-1] == pytest.approx(60000 + 199 * 0.1)   # spread over the whole span
    few = ims[:20]
    assert F.sample(few, 150) == sorted(few, key=lambda i: i["mjd"])


class FakeExp:
    """Just what follow.measure / follow.render use of archive.Exposure."""

    def __init__(self, img, var, flags, wcs, lam=2.0):
        self.img, self.var, self.flags, self.wcs, self._lam = img, var, flags, wcs, lam

    def bad_mask(self):
        return ~np.isfinite(self.img)

    def wavelength_um(self, x, y):
        return np.full(np.shape(x), self._lam)


def _fake_exposure(ra, dec, n=70, flux_ujy=20000.0, dx=0.0, dy=0.0, rot=30.0):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra + 0.01, dec - 0.01]
    w.wcs.crpix = [n / 2, n / 2]
    s = 6.15 / 3600
    c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    w.wcs.cd = [[-s * c, s * sn], [s * sn, s * c]]
    x0, y0 = w.world_to_pixel_values(ra, dec)
    x0, y0 = float(x0) + dx, float(y0) + dy
    yy, xx = np.mgrid[:n, :n]
    from sxlib.products import PIX_SR
    sig = 0.9
    amp = flux_ujy / (PIX_SR * 1e12) / (2 * math.pi * sig ** 2)            # MJy/sr peak giving flux_ujy in total
    rng = np.random.default_rng(1)
    img = amp * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * sig ** 2)) + rng.normal(0, 0.01, (n, n))
    return FakeExp(img, np.full((n, n), 1e-4), np.zeros((n, n), np.int32), w)


def test_measure_and_render_on_synthetic_cutout():
    ra, dec = 178.4, 1.1
    e = _fake_exposure(ra, dec)
    m = F.measure(e, ra, dec)
    assert m["lam"] == 2.0 and not m["sat"] and not m["star"]
    # a 2-pixel aperture holds 1 - exp(-2^2 / (2 * 0.9^2)) = 91% of a sigma 0.9 px star (no aperture correction)
    assert m["flux"] == pytest.approx(20000 * 0.915, rel=0.06)
    assert abs(m["dra"]) < 0.3 and abs(m["ddec"]) < 0.3
    # an object 1 pixel east of the prediction: the centroid says so (east = +RA)
    m2 = F.measure(_fake_exposure(ra, dec, dx=0.0, dy=0.0, rot=0.0), ra + 6.15 / 3600 / math.cos(math.radians(dec)), dec)
    assert m2["dra"] == pytest.approx(-6.15, abs=0.8)
    img, noise, cov = F.render(e, ra, dec)
    assert img.shape == (F.NPIX, F.NPIX) and cov > 0.95
    c = F.NPIX // 2
    assert np.nanargmax(img) == c * F.NPIX + c                        # the object is in the middle of the frame
    a8 = F.to8(F.fill_holes(img), noise)
    assert a8.dtype == np.uint8 and a8[c, c] > 200
    assert F.measure(e, ra + 1.0, dec) is None                       # off the cutout


def test_lightcurve_finds_a_spin_and_skips_comets():
    rng = np.random.default_rng(3)
    P = 6.0                                                         # hours; two maxima per turn
    t = np.sort(60000 + rng.uniform(0, 6, 160))
    lam = rng.uniform(0.75, 5.0, len(t))
    spec = 30000 * (lam / 1.0) ** -1.2
    var = 0.08 * np.sin(2 * math.pi * (t * 24) / (P / 2))
    fl = spec * 10 ** (-0.4 * var) * (1 + rng.normal(0, 0.005, len(t)))
    fr = [{"mjd": float(a), "lam": float(b), "flux": float(c), "err": float(c) * 0.005, "r_au": 3.4, "d_au": 3.3}
          for a, b, c in zip(t, lam, fl)]
    res = F.lightcurve(fr, known_h=P)
    assert res["period_h"] == pytest.approx(P, rel=0.02)
    assert res["known"]["fap"] < 1e-6
    assert sum("rel" in f for f in fr) == len(fr)
    assert F.lightcurve([dict(f) for f in fr], periodic=False)["period_h"] is None
    flat = [{**f, "flux": float(s) * (1 + rng.normal(0, 0.005))} for f, s in zip(fr, spec)]
    assert F.lightcurve(flat)["period_h"] is None                    # noise alone: no period claimed


def test_sun_shape():
    s = F.sun_fnu(np.array([0.8, 0.88, 0.97, 2.0, 5.0]))
    assert s[1] > s[0] and s[1] > s[2] and s[3] > s[4]               # F_nu of sunlight peaks near 0.88 µm, then falls
    r = F.sun_fnu(np.array([20.0, 40.0]))
    assert r[0] / r[1] == pytest.approx(4.0, rel=0.05)              # Rayleigh-Jeans side: F_nu ~ lambda^-2


# ---- the job endpoints -----------------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    from web import api_follow as A
    monkeypatch.setattr(A, "OUT", tmp_path / "follow")
    monkeypatch.setattr(A, "CACHE", tmp_path / "cache")
    (tmp_path / "follow").mkdir()
    A._ip_jobs.clear(); A._resolved.clear(); A._ip_resolve.clear()
    spawned = []
    monkeypatch.setattr(A, "_spawn", lambda *a: spawned.append(a))
    names = {"cybele": {"status": "ok", "name": "65 Cybele (A861 EB)", "short": "65 Cybele", "spkid": "20000065", "kind": "asteroid"},
             "lemmon": {"status": "ambiguous", "choices": ["349P/Lemmon", "C/2025 A6 (Lemmon)"]}}
    monkeypatch.setattr(A.F, "sbdb_resolve", lambda q, cache=None: names.get(q.lower().split()[-1], {"status": "unknown"}))
    app = FastAPI()
    app.include_router(A.router)
    return A, app, spawned


def _post(app, body, ip="127.0.0.1"):
    return request(app, "POST", "/api/follow", {"content-type": "application/json"}, body, client_ip=ip)


def test_follow_job_lifecycle(api):
    A, app, spawned = api
    r = _post(app, {"q": "Cybele", "t0": "2025-12-01", "t1": "2025-12-31"})
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert slug == "65-cybele-a861-eb_2025-12-01_2025-12-31" and len(spawned) == 1
    assert spawned[0][:2] == (slug, "20000065")
    j = get(app, f"/api/follow/job/{slug}").json()
    assert j["status"] == "searching" and "pid" not in j
    # a running job is reused, not started again
    assert _post(app, {"q": "cybele", "t0": "2025-12-01", "t1": "2025-12-31"}).json()["slug"] == slug
    assert len(spawned) == 1
    # a dead job (no heartbeat) reads as stalled
    p = A.OUT / slug / "doc.json"
    d = json.loads(p.read_text(encoding="utf-8")); d["heartbeat"] = time.time() - 600; p.write_text(json.dumps(d), encoding="utf-8")
    assert get(app, f"/api/follow/job/{slug}").json()["error"] == "stalled"
    # a finished one is listed
    d.update(status="done", frames=[{"f": 0, "mjd": 1}, {"f": 3, "mjd": 2}], stack=12); p.write_text(json.dumps(d), encoding="utf-8")
    (A.OUT / "showcases.json").write_text(json.dumps([{"slug": slug, "note": "cybele"}]), encoding="utf-8")
    lst = get(app, "/api/follow/list").json()
    assert lst["showcase"][0]["slug"] == slug and lst["showcase"][0]["thumb"].startswith(f"/data/follow/{slug}/f/0003.webp")
    assert lst["recent"] == []


def test_follow_answers_and_limits(api):
    A, app, spawned = api
    assert _post(app, {"q": "Lemmon"}).json() == {"status": "ambiguous", "choices": ["349P/Lemmon", "C/2025 A6 (Lemmon)"]}
    assert _post(app, {"q": "nothing"}).status_code == 404
    assert _post(app, {"q": "<script>"}).status_code == 422
    assert _post(app, {"q": "Cybele", "t0": "yesterday"}).status_code == 422
    assert get(app, "/api/follow/job/..%2Fetc").status_code in (400, 404)
    assert get(app, "/api/follow/resolve?q=Cybele").json()["spkid"] == "20000065"
    # at most MAX_RUNNING jobs at once
    for k in range(A.MAX_RUNNING):
        assert _post(app, {"q": "Cybele", "t0": f"2025-0{k + 1}-01"}, f"10.0.0.{k}").status_code == 200
    assert _post(app, {"q": "Cybele", "t0": "2025-09-01"}, "10.0.0.9").status_code == 429
    # per visitor per day
    for d in A.OUT.iterdir():
        if d.is_dir():
            j = json.loads((d / "doc.json").read_text(encoding="utf-8")); j["status"] = "done"; (d / "doc.json").write_text(json.dumps(j), encoding="utf-8")
    A._ip_jobs.clear()
    # the jobs started here stay running, so lift the global cap for this part: only the per-visitor limit is tested
    running, A.MAX_RUNNING = A.MAX_RUNNING, A.PER_IP_DAY + 2
    try:
        rs = [_post(app, {"q": "Cybele", "t1": f"2026-0{k + 1}-01"}, "10.1.1.1") for k in range(A.PER_IP_DAY + 1)]
    finally:
        A.MAX_RUNNING = running
    codes = [r.status_code for r in rs]
    assert codes[:A.PER_IP_DAY] == [200] * A.PER_IP_DAY and codes[-1] == 429
    assert rs[-1].json()["detail"] == "per_ip_limit"


def test_prune_keeps_showcases_and_newest(api, monkeypatch):
    A, app, spawned = api
    monkeypatch.setattr(A, "KEEP", 2)
    for k in range(5):
        d = A.OUT / f"obj{k}"
        d.mkdir()
        (d / "doc.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
        t = time.time() - 1000 + k * 10
        import os
        os.utime(d, (t, t))
    (A.OUT / "obj0" / "keep").touch()
    A._prune()
    assert sorted(x.name for x in A.OUT.iterdir()) == ["obj0", "obj3", "obj4"]


# ---- the validation against our own pipeline ----------------------------------------------------------------------
def _build():
    spec = importlib.util.spec_from_file_location("follow_build", ROOT / "scripts" / "follow_build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_compare_most_with_field_detections():
    B = _build()
    wcs = {"crval": [178.6, 1.1], "crpix": [51.0, 51.0], "cdelt": [-6.15 / 3600, 6.15 / 3600]}
    doc = {"wcs": wcs, "shape": [101, 101], "cnn_threshold_prob": 0.6,
           "exposures": [{"i": 0, "obs_id": "A", "detector": 1, "nref": 4}, {"i": 1, "obs_id": "B", "detector": 4, "nref": 4}],
           "tracks": [{"id": 0, "known": "65 Cybele (A861 EB)"}],
           "candidates": [{"id": 5, "i": 0, "x": 50.0 + 0.5, "y": 50.0, "ra": 0, "dec": 0, "p": 0.9, "snr": 40, "track": 0,
                           "known": "65 Cybele (A861 EB)"}]}
    x, y = B.tan_xy(wcs, 178.6, 1.1)
    assert (x, y) == pytest.approx((50.0, 50.0))
    # put the candidate's sky position half a pixel east of the field centre, as its x says
    doc["candidates"][0]["ra"] = 178.6 - 0.5 * wcs["cdelt"][0] / math.cos(math.radians(1.1))
    doc["candidates"][0]["dec"] = 1.1
    ims = [{"obs_id": "A", "detector": 1, "mjd": 1.0, "ra": 178.6, "dec": 1.1, "vmag": 13.2},
           {"obs_id": "B", "detector": 4, "mjd": 1.1, "ra": 178.6, "dec": 1.1, "vmag": 13.2},     # in our data, not found
           {"obs_id": "C", "detector": 2, "mjd": 1.2, "ra": 178.6, "dec": 1.1, "vmag": 13.2},     # not in our exposures
           {"obs_id": "A", "detector": 1, "mjd": 1.0, "ra": 179.6, "dec": 1.1, "vmag": 13.2}]     # outside the field
    rec = B.compare(doc, "65 Cybele (A861 EB)", ims)
    assert len(rec) == 3
    a, b, c = rec
    assert a["found"] and a["nn"] and a["track"] and a["label"] == "65 Cybele (A861 EB)"
    assert a["dra"] == pytest.approx(-0.5 * wcs["cdelt"][0] * 3600, abs=0.05) and abs(a["ddec"]) < 0.01
    assert b["in_field"] and not b["found"]
    assert not c["in_field"]
    assert B.query_name("5591 Koyo (1990 VF2)") == "5591" and B.query_name("(2012 FU25)") == "2012 FU25"


def test_validation_file_shape():
    p = ROOT / "web" / "data" / "validation" / "follow.json"
    if not p.exists():
        pytest.skip("validation not built yet")
    v = json.loads(p.read_text(encoding="utf-8"))
    assert {"totals", "by_v", "offsets", "bodies"} <= set(v)
    assert v["totals"]["found"] <= v["totals"]["used"] <= v["totals"]["inside"]
