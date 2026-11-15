"""/api/validation: the per-star rows behind the guide's charts (web/server.py, scripts/export_validation_detail.py).
The summaries that were there before must still be there, and the new rows must agree with them."""
import json
import math
from pathlib import Path

import pytest

from asgi_client import get
from web import server

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def val():
    r = get(server.app, "/api/validation")
    assert r.status_code == 200
    return r.json()


def test_min_shift_is_the_search_threshold():
    from sxlib import pmsearch
    assert server._MIN_SHIFT_ARCSEC == pytest.approx(pmsearch.MIN_SHIFT_PX * pmsearch.PIX, abs=1e-3)


def test_known_star_row_from_a_result():
    s = {"star": {"id": 5363990535794423680, "ra": 159.56109739, "dec": -49.56488041, "pm": 0.6484042, "g": 13.497718},
         "result": {"dt_yr": 0.976, "pred_arcsec": 0.641, "found": False, "meas_pm": None, "sig": None,
                    "direct": {"meas_px": [0.038, -0.1], "resid_arcsec": 0.093}}}
    row = server._known_star_row(s)
    assert row == {"id": "5363990535794423680", "ra": 159.5611, "dec": -49.56488, "g": 13.5, "pm": 0.648, "dt_yr": 0.976,
                   "pred": 0.641, "meas": round(math.hypot(0.038, 0.1) * 6.15, 3), "resid": 0.093, "found": False,
                   "meas_pm": None, "sig": None}
    s["result"]["direct"] = None                       # the direct fit failed: nothing to plot, but the row is still there
    row = server._known_star_row(s)
    assert row["meas"] is None and row["resid"] is None and row["pred"] == 0.641


def test_known_stars_rows_agree_with_the_summary(val):
    if not (ROOT / "outputs" / "pm_validation.json").exists():
        pytest.skip("no known-star test on this machine")
    ks = val["known_stars"]
    for k in ("n_total", "n_done", "n_usable", "strata", "astrometry_resid_arcsec", "pm_ratio_median", "false_new_candidates"):
        assert k in ks                                  # the keys the site already used
    stars = ks["stars"]
    assert len(stars) == ks["n_usable"]
    assert set(stars[0]) == {"id", "ra", "dec", "g", "pm", "dt_yr", "pred", "meas", "resid", "found", "meas_pm", "sig"}
    assert all(isinstance(s["id"], str) and s["id"].isdigit() for s in stars)      # 19 digits: not safe as a JS number
    assert sum(s["found"] for s in stars) == sum(g["found"] for g in ks["strata"])
    for g in ks["strata"]:
        inside = [s for s in stars if g["pm_lo"] <= s["pm"] < g["pm_hi"]]
        assert (len(inside), sum(s["found"] for s in inside)) == (g["n"], g["found"])
    assert sum(s["meas"] is not None for s in stars) == ks["astrometry_resid_arcsec"]["n"]
    assert all((s["meas_pm"] is not None) == s["found"] for s in stars)
    assert 0.5 < ks["min_shift_arcsec"] < 1.0
    assert len(json.dumps(stars)) < 12000               # compact: about 200 bytes a star


def test_spectral_scores_agree_with_the_summary(val):
    if not (ROOT / "models" / "bd_spec_scores.json").exists():
        pytest.skip("scripts/export_validation_detail.py has not been run on this machine")
    sp = val["spectral"]
    for k in ("real_positive_scores", "real_negatives", "threshold", "training"):
        assert k in sp
    sc = sp["scores"]
    neg, pos = sc["negatives"], sc["positives"]
    assert set(neg[0]) == {"field", "g", "score", "z"}
    assert len(neg) == sp["real_negatives"]["n"]
    for thr, rate in sp["real_negatives"]["false_positive_rate"].items():
        assert sum(r["score"] >= float(thr) for r in neg) / len(neg) == pytest.approx(rate)
    assert {p["id"]: round(p["score"], 3) for p in pos} == sp["real_positive_scores"]
    # z is the log-odds of the score
    for r in neg + pos:
        assert r["score"] == pytest.approx(1 / (1 + math.exp(-r["z"])), abs=6e-4)
    assert sc["matches_metrics"] is True


def test_variable_targets_have_per_pass_brightness(val):
    if not (ROOT / "outputs" / "var_targets.json").exists() or "variables" not in val:
        pytest.skip("scripts/export_validation_detail.py has not been run on this machine")
    v = val["variables"]
    for k in ("fields", "n_searched", "n_candidates", "by_status", "targets", "catalogued"):
        assert k in v
    for tid in ("rdra", "rwaur", "barnard"):
        t = v["targets"][tid]
        ps = t["passes"]
        assert len(ps) >= 2 and set(ps[0]) == {"k", "mjd", "rel", "err"}
        # relative to the star's own mean, so the passes straddle 1; the stored amplitude is the largest ratio
        assert min(p["rel"] for p in ps) <= 1 <= max(p["rel"] for p in ps)
        assert max(p["rel"] for p in ps) / min(p["rel"] for p in ps) == pytest.approx(t["amp"], rel=2e-3)
    assert sum(f["n_searched"] for f in v["by_field"].values()) == v["n_searched"]
    assert sum(f["n_candidates"] for f in v["by_field"].values()) == v["n_candidates"]
    assert sum(f["catalogued_constant"] for f in v["by_field"].values()) == v["by_status"]["catalogued_constant"]


def test_false_movers_by_field_adds_up(val):
    assert sum(val["false_movers_by_field"].values()) == val["false_movers_in_fields"]
    assert len(val["false_movers_by_field"]) == val["fields_searched"]
