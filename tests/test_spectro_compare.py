"""scripts/irsa_spectro_compare.py, offline: parsing IRSA's result VOTable, pass windows, exposure matching, ratios."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("irsa_spectro_compare", ROOT / "scripts" / "irsa_spectro_compare.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


def votable(rows):
    """A result in the service's own layout: one TR per source, arrays as space-separated TDs, 'Nx*' char arrays."""
    did = "".join(f"ivo://irsa.ipac/spherex_{r['coll']}?{r['obs']}/D{r['det']}".ljust(54) for r in rows)
    col = "".join(r["coll"].ljust(4) for r in rows)
    j = lambda k: " ".join(str(r[k]) for r in rows)  # noqa: E731
    fields = [("source_id", "long", None), ("ra", "double", None), ("dec", "double", None), ("n_meas", "int", None),
              ("lambda", "float", "*"), ("lambda_width", "float", "*"), ("flux", "float", "*"), ("flux_err", "float", "*"),
              ("mjd", "double", "*"), ("data_collection", "char", "4x*"), ("det_id", "unsignedByte", "*"), ("flags", "long", "*"),
              ("fit_ql", "float", "*"), ("flux_bkg", "float", "*"), ("obs_publisher_did", "char", "54x*")]
    tds = ["1", "10.0", "-5.0", str(len(rows)), j("lam"), " ".join("0.02" for _ in rows), j("flux"), j("err"), j("mjd"), col,
           j("det"), j("flags"), " ".join("1.0" for _ in rows), " ".join("0.5" for _ in rows), did]
    head = "".join(f'<FIELD name="{n}" datatype="{t}"' + (f' arraysize="{a}"' if a else "") + "/>" for n, t, a in fields)
    body = "".join(f"<TD>{v}</TD>" for v in tds)
    return (f'<?xml version="1.0"?><VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4"><RESOURCE type="results">'
            f"<TABLE>{head}<DATA><TABLEDATA><TR>{body}</TR></TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>").encode()


ROWS = [  # IRSA measurements: five matched exposures (one flagged bad), one exposure we do not have
    {"obs": "2025W35_1A_0432_4", "det": 1, "coll": "dr1", "lam": 0.80, "flux": 1000.0, "err": 10.0, "mjd": 60914.2, "flags": 0},
    {"obs": "2025W35_1A_0433_1", "det": 2, "coll": "dr1", "lam": 1.20, "flux": 2000.0, "err": 20.0, "mjd": 60914.3, "flags": 2097152},
    {"obs": "2025W35_1A_0434_1", "det": 3, "coll": "dr1", "lam": 2.00, "flux": 3000.0, "err": 30.0, "mjd": 60914.4, "flags": 0},
    {"obs": "2026W10_1A_0001_1", "det": 4, "coll": "qr3", "lam": 3.00, "flux": 1500.0, "err": 15.0, "mjd": 61100.1, "flags": 0},
    {"obs": "2026W10_1A_0002_1", "det": 5, "coll": "qr3", "lam": 4.20, "flux": 800.0, "err": 8.0, "mjd": 61100.2, "flags": 1 << 32 | 3},
    {"obs": "2026W10_1A_0099_1", "det": 6, "coll": "qr3", "lam": 4.80, "flux": 600.0, "err": 6.0, "mjd": 61100.3, "flags": 0},
]


def test_parse_result_reads_arrays_and_fixed_width_strings():
    src = sc.parse_result(votable(ROWS))
    assert len(src) == 1 and src[0]["n_meas"] == 6
    rows = src[0]["rows"]
    assert [r["obs_id"] for r in rows] == [r["obs"] for r in ROWS]
    assert [r["coll"] for r in rows] == ["dr1", "dr1", "dr1", "qr3", "qr3", "qr3"]
    assert rows[4]["flags"] == (1 << 32 | 3) and rows[0]["det"] == 1 and rows[2]["flux"] == pytest.approx(3000.0)
    assert not sc.irsa_ok(rows[4]) and sc.irsa_ok(rows[1])          # bit 32 (bad pixel) out; bit 21 (known source) is nominal


def test_split_passes_and_job_key():
    assert sc.split_passes([3.0, 1.0, 2.0, 50.0, 51.0, 200.0]) == [(1.0, 3.0), (50.0, 51.0), (200.0, 200.0)]
    assert sc.split_passes([]) == []
    k = sc.job_key((269.4462097, 4.7672292), (60902.365, 60923.608))
    assert k == sc.job_key((269.446209701, 4.767229199), (60902.365, 60923.608)) and len(k) == 12
    assert k != sc.job_key((269.4462097, 4.7672292), (60902.365, 60923.708))


def test_robust():
    r = sc.robust([1.0, 1.1, 0.9, None, float("nan"), 1.0])
    assert r["median"] == pytest.approx(1.0) and r["n"] == 4 and r["scatter"] == pytest.approx(1.4826 * 0.05, abs=1e-3)
    assert sc.robust([]) is None


def test_compare_target_matches_by_exposure(tmp_path):
    fields, cache = tmp_path / "fields", tmp_path / "cache"
    (fields / "rwaur").mkdir(parents=True)
    (cache / "rwaur").mkdir(parents=True)
    obs = [r["obs"] for r in ROWS[:5]] + ["2025W40_9Z_0001_1"]       # our last exposure is not in IRSA's result
    exps = [{"i": i, "obs_id": o, "mjd": ROWS[i]["mjd"] if i < 5 else 60950.0, "release": "DR1" if i < 3 else "QR3"} for i, o in enumerate(obs)]
    # ours = 0.9 x IRSA (aperture) and 1.02 x IRSA (PSF); the second point carries our own ghost flag
    pts = []
    for i in range(6):
        f = ROWS[i]["flux"] if i < 5 else 500.0
        pts.append({"i": i, "mjd": exps[i]["mjd"], "det": ROWS[i]["det"] if i < 5 else 6, "lam": ROWS[i]["lam"] - 0.003 if i < 5 else 4.9,
                    "f": 0.9 * f, "e": 0.01 * f, "flag": 4 if i == 1 else 0, "psf": 1.02 * f, "psf_e": 0.01 * f, "psf_sat": False})
    doc = {"created": "2026-11-13 12:00:00", "exposures": exps,
           "products": {"passes": [{"k": 0, "mjd0": 60914.0, "mjd1": 60951.0}, {"k": 1, "mjd0": 61100.0, "mjd1": 61101.0}]},
           "target": {"name": "RW Aurigae", "kind": "var", "points": pts, "aperture_px": 2.0}}
    (fields / "rwaur" / "field.json").write_text(json.dumps(doc), encoding="utf-8")
    (cache / "rwaur" / "abc.vot").write_bytes(votable(ROWS))
    (cache / "rwaur" / "abc.json").write_text(json.dumps({"k": 0, "point": [76.95, 30.40], "window": [60900, 61200], "result": "abc.vot"}), encoding="utf-8")
    c = sc.compare_target("rwaur", field_dir=fields / "rwaur", cache=cache)
    assert c["n_matched"] == 5 and c["irsa_only"] == 1 and c["ours_only"] == 1
    # aperture: our flagged point (i=1) and IRSA's bad point (i=4) are out -> 3 ratios of 0.9
    assert c["ratio_aperture"] == {"median": 0.9, "scatter": 0.0, "n": 3}
    # PSF: our own flag does not apply to the PSF fit (it fits around flagged pixels); IRSA's bad point is still out
    assert c["ratio_psf"]["median"] == pytest.approx(1.02) and c["ratio_psf"]["n"] == 4
    assert c["dlam_um"]["median"] == pytest.approx(-0.003, abs=1e-6)
    assert {d["pass"]: d["n"] for d in c["ratio_aperture_by_pass"]} == {0: 2, 1: 1}
    assert c["irsa"]["collections"] == {"dr1": 3, "qr3": 3} and c["ours"]["releases"] == {"DR1": 3, "QR3": 3}
    assert c["caveat"] == "variable" and c["meaningful"] is True
    lam, irsa, irsa_e, ap, psf, k, det, bits = c["points"][0]
    assert (lam, irsa, k, det) == (0.8, 1000.0, 0, 1) and ap == pytest.approx(900.0) and bits & 4 and bits & 8
