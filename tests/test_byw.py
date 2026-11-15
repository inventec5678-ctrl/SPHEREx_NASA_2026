"""Backyard Worlds validation (scripts/byw_validate.py): the catalogue parsing, the selection rule, the choice of
exposures and the summary. No network.

    .venv/bin/python -m pytest tests/test_byw.py -q
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import byw_validate as B  # noqa: E402

TSV = "\n".join([
    "#", "#   VizieR Astronomical Server", "#Table\tJ_ApJS_253_7_table1:", "#Column\tCWISE\t(A19)",
    "", "recno\tCWISE\tDisc\tPName",
    " \t \t \t ",                                   # VizieR's units line: blank for these columns
    "--------\t---\t---\t---",
    "       1\tJ163041.79-064338.3\tA, D, G, U   \t1630-0643",
    "       2\tJ000000.00+000000.0\tF, J, K\t0000+0000",
    "",
])


def test_parse_tsv_skips_comments_units_and_dashes():
    rows = B.parse_tsv(TSV)
    assert [r["recno"] for r in rows] == ["1", "2"]
    assert rows[0]["Disc"] == "A, D, G, U" and rows[0]["PName"] == "1630-0643"
    assert B.parse_tsv("#only comments\n") == []


def _a1(pname, ra, dec, pmra, pmde, w2, plx="", spad="15.0"):
    return {"PName": pname, "RACdeg": str(ra), "DECdeg": str(dec), "pmRA": str(pmra), "pmDE": str(pmde),
            "W2mag": str(w2), "W2magC2": "", "plx": plx, "SpAd": spad}


def test_select_applies_the_rule():
    t1 = [{"PName": "1630-0643", "CWISE": "J163041.79-064338.3", "Disc": "A, D, G, U"},   # volunteers
          {"PName": "0100+0100", "CWISE": "J010000.00+010000.0", "Disc": "F, J, K"},      # CatWISE team only
          {"PName": "0200+0200", "CWISE": "J020000.00+020000.0", "Disc": "S"},            # too faint
          {"PName": "0300+0300", "CWISE": "J030000.00+030000.0", "Disc": "G"},            # too slow
          {"PName": "0400+0400", "CWISE": "J040000.00+040000.0", "Disc": "R"}]            # volunteer (Rothermich)
    a1 = [_a1("1630-0643", 247.674, -6.727, -200, -545, 13.98),
          _a1("0100+0100", 15.0, 1.0, 900, 0, 13.0),
          _a1("0200+0200", 30.0, 2.0, 900, 0, 15.6),
          _a1("0300+0300", 45.0, 3.0, 100, 100, 14.0),
          _a1("0400+0400", 60.0, 4.0, 0, -1200, 14.8, plx="70.0")]
    # Meisner 2020: one new object and one duplicate of 0400+0400 (same star at another epoch)
    m2 = [{"Source": "WISEA J211456.86-180519.0", "Motion": "yes", "W2mag": "14.97"},
          {"Source": "WISEA J040000.00+040000.0", "Motion": "yes", "W2mag": "14.80"},
          {"Source": "WISEA J050000.00+050000.0", "Motion": "no", "W2mag": "14.00"}]
    m6 = [{"Source": "WISEA J211456.86-180519.0", "RA_ICRS": "318.7357753", "DE_ICRS": "-18.0897946", "MJD": "58518.15", "pmRA": "500", "pmDE": "-430"},
          {"Source": "WISEA J040000.00+040000.0", "RA_ICRS": "60.0", "DE_ICRS": str(4.0 - 1.2 * 3.6 / 3600), "MJD": str(57170 + 3.6 * 365.25), "pmRA": "0", "pmDE": "-1200"},
          {"Source": "WISEA J050000.00+050000.0", "RA_ICRS": "75.0", "DE_ICRS": "5.0", "MJD": "58500", "pmRA": "900", "pmDE": "0"}]
    m9 = [{"Source": "WISEA J211456.86-180519.0", "Dist": "18.3"}]
    objs, counts = B.select(t1, a1, m2, m6, m9)
    assert [o["id"] for o in objs] == ["1630-0643", "0400+0400", "2114-1805"]           # sorted by W2
    k = {o["id"]: o for o in objs}
    assert k["1630-0643"]["plx_src"] == "assumed" and k["1630-0643"]["plx"] == B.PLX_ASSUMED
    assert k["0400+0400"]["ref"] == "K21" and k["0400+0400"]["plx"] == 70.0           # duplicate: K21 entry kept
    assert abs(k["2114-1805"]["plx"] - 1000 / 18.3) < 0.01 and k["2114-1805"]["ref"] == "M20"
    assert abs(k["1630-0643"]["epoch"] - 2015.405) < 0.01                                 # CatWISE epoch MJD 57170
    assert counts["k21_volunteer"] == 4 and counts["m20_motion_confirmed"] == 2 and counts["selected"] == 3
    assert k["1630-0643"]["sptype"] == "T5"


def test_sptype_codes():
    assert B._sptype(15.0) == "T5" and B._sptype(6.5) == "L6.5" and B._sptype(20.0) == "Y0" and B._sptype(-1) == "M9"


def test_pick_exposures_spreads_per_pass_and_detector():
    metas, lab = [], []
    for p, t0 in enumerate((60800, 60990, 61180)):
        for d in range(1, 7):
            for j in range(15):
                metas.append({"detector": d, "mjd": t0 + j * 0.5 + d * 0.01, "obs_id": f"{p}_{d}_{j}"})
                lab.append(p)
    pick = B.pick_exposures(metas, np.array(lab), {4: 2, 5: 7, 6: 7})
    assert len(pick) == 3 * 16
    for p in range(3):
        for d, k in ((4, 2), (5, 7), (6, 7)):
            g = sorted(m["mjd"] for m, q in pick if q == p and m["detector"] == d)
            assert len(g) == k
            assert g[-1] - g[0] > 6.5                       # first and last of the pass: spread over its wavelengths
    assert not any(m["detector"] in (1, 2, 3) for m, _ in pick)
    # fewer available than asked: take them all, once
    few = B.pick_exposures(metas[:3], np.zeros(3, int), {1: 7})
    assert len(few) == 3 and len({m["obs_id"] for m, _ in few}) == 3


def test_detection_uses_empirical_noise():
    rng = np.random.default_rng(1)
    noise = [(float(v), 2.0) for v in rng.normal(10.0, 5.0, 48)]           # sky bias 10, scatter 5
    d = B.detection({5: [(60.0, 2.0)] + noise, 6: [(None, None)] + noise})
    assert d[6] is None
    assert 3.0 < d[5]["sigma_emp"] < 7.0 and abs(d[5]["flux_ujy"] - 50) < 4
    assert 6 < d[5]["snr"] < 17                                             # against the scatter, not the formal 2.0 (25)


def test_weighted_mean():
    m, e = B.weighted([1.0, 3.0, np.nan], [1.0, 1.0, 1.0])
    assert m == 2.0 and abs(e - 1 / np.sqrt(2)) < 1e-12
    assert B.weighted([np.nan], [1.0]) == (None, None)


def test_summary_and_limit():
    rows = [{"w2": w, "covered": True, "snr_best": 10 ** (-0.4 * (w - 14.0)) * 8, "detected": w < 14.5, "found": w < 14.2}
            for w in (13.95, 14.1, 14.3, 14.45, 14.6, 14.8, 14.95)]
    rows.append({"w2": 14.0, "covered": False})
    s = B.summarise(rows)
    assert s["n_selected"] == 8 and s["n_covered"] == 7 and s["n_detected"] == 4 and s["n_found"] == 2
    assert [b["n"] for b in s["bins"]] == [2, 2, 1, 2]
    w5, slope = B.limit_w2(rows)
    assert abs(slope + 0.4) < 1e-6 and abs(w5 - (14.0 + 2.5 * np.log10(8 / 5))) < 0.01
    assert B.limit_w2(rows[:2]) is None
