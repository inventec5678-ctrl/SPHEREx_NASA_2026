"""Before/after table for the switch from QR2+QR3 to DR1+QR3: python scripts/release_compare.py

Reads the snapshot written by scripts/rebuild_release.py (outputs/release_compare/qr2qr3/) and the fields as they
are now (web/data/fields/) and writes web/data/validation/dr1.json for the validation page: per field the exposures
and what the analysis found; per named target the measured motion, the photometry and the scores; the 45-star
proper-motion validation (outputs/release_compare/dr1qr3/pm_validation.json, re-testing the same stars) and the
cross-epoch and variable-star summaries. A field not rebuilt yet is reported as such, never mixed in.
"""
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, OUTPUTS, VALIDATION, read_json, write_json  # noqa: E402

BEFORE = OUTPUTS / "release_compare" / "qr2qr3"
AFTER_V = OUTPUTS / "release_compare" / "dr1qr3"
OUT = VALIDATION / "dr1.json"
TARGETS = ("barnard", "epsindi", "wise0855", "rwaur", "rdra")
BAD_FLAGS = 5
MIN_SNR_PSF = 10              # aperture S/N above which a point enters the PSF/aperture ratio
MIN_PSF_POINTS = 5
XEPOCH_KEYS = ("created", "n_measured", "n_with_gaia", "scatter_per_axis_mas_yr", "isolated_fraction")
MOTION_KEYS = ("measured_arcsec", "predicted_arcsec", "err_arcsec", "days", "band")


def _load(p):
    try:
        return read_json(p)
    except (OSError, ValueError):
        return None


def _releases(doc):
    return dict(Counter(e.get("release") or "QR2/QR3" for e in doc.get("exposures", [])))


def field_row(doc, summ):
    ex = doc["exposures"]
    return {"n": len(ex), "first": ex[0]["iso"][:10], "last": ex[-1]["iso"][:10],
            "releases": _releases(doc), "n_candidates": len(doc.get("candidates", [])), "n_tracks": summ.get("n_tracks"),
            "n_known": summ.get("n_known"), "n_unknown": summ.get("n_unknown"), "n_known_bodies": summ.get("n_known_bodies")}


def target_row(doc):
    t = doc.get("target") or {}
    pts = t.get("points", [])
    good = [p for p in pts if p.get("f") is not None and not ((p.get("flag") or 0) & BAD_FLAGS)]
    ratio = [p["psf"] / p["f"] for p in good
             if p.get("psf") and not p.get("psf_sat") and p["f"] > 0 and p.get("e") and p["f"] > MIN_SNR_PSF * p["e"]]
    snr = [p["f"] / p["e"] for p in good if p.get("e")]
    m = t.get("motion") or None
    return {"n_points": len(pts), "n_phot": len(good), "median_snr": round(float(np.median(snr)), 1) if snr else None,
            "psf_over_aperture": round(float(np.median(ratio)), 3) if len(ratio) >= MIN_PSF_POINTS else None,
            "n_psf_ratio": len(ratio),
            "motion": m and {k: m[k] for k in MOTION_KEYS},
            "pass_ratio": t.get("pass_ratio"), "bd_score": t.get("bd_score")}


def pm_summary(p):
    if not p:
        return None
    done = [r for r in p["stars"] if "result" in r and not r["result"].get("skip")]
    found = [r for r in done if r["result"].get("found")]
    res = [r["result"]["direct"]["resid_arcsec"] for r in done if r["result"].get("direct")]
    return {"n_stars": len(p["stars"]), "n_tested": len(done), "n_found": len(found),
            "median_resid_arcsec": round(float(np.median(res)), 3) if res else None,
            "per_star": {r["star"]["id"]: {"found": bool(r["result"].get("found")), "pm": round(r["star"]["pm"], 3),
                                           "g": round(r["star"]["g"], 2),
                                           "resid": (r["result"].get("direct") or {}).get("resid_arcsec")}
                         for r in done}}


def _var_summary(v):
    return v and {"updated": v.get("updated"),
                  "n_candidates": sum(f.get("n_candidates", 0) for f in v["fields"].values()),
                  "n_measured": sum(f.get("n_measured", 0) for f in v["fields"].values())}


def main():
    out = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "before": "QR2 + QR3", "after": "DR1 + QR3",
           "psf_before": "optical PSF (QR2 files)", "psf_after": "effective PSF (ePSF tables in the DR1/QR3 files)",
           "fields": [], "targets": []}
    for d in sorted((BEFORE / "fields").iterdir()):
        b, bs = _load(d / "field.json"), _load(d / "summary.json") or {}
        a, as_ = _load(FIELDS / d.name / "field.json"), _load(FIELDS / d.name / "summary.json") or {}
        if not b or not a:
            continue
        rebuilt = any(e.get("release") for e in a["exposures"])
        out["fields"].append({"id": d.name, "name": b["name"], "rebuilt": rebuilt, "before": field_row(b, bs),
                              "after": field_row(a, as_) if rebuilt else None})
        if d.name in TARGETS:
            out["targets"].append({"id": d.name, "name": b["target"]["name"], "kind": b["target"]["kind"],
                                   "rebuilt": rebuilt, "before": target_row(b),
                                   "after": target_row(a) if rebuilt else None})
    out["pm_validation"] = {"before": pm_summary(_load(BEFORE / "pm_validation.json")),
                            "after": pm_summary(_load(AFTER_V / "pm_validation.json"))}
    xb, xa = _load(BEFORE / "xepoch_validation.json"), _load(OUTPUTS / "xepoch_validation.json")
    out["xepoch"] = {"before": xb and {k: xb.get(k) for k in XEPOCH_KEYS},
                     "after": xa and xa.get("created", "") > (xb or {}).get("created", "")
                     and {k: xa.get(k) for k in XEPOCH_KEYS} or None}
    vb, va = _load(BEFORE / "var_search.json"), _load(OUTPUTS / "var_search.json")
    out["variables"] = {"before": _var_summary(vb),
                        "after": _var_summary(va) if va and va.get("updated", "") > (vb or {}).get("updated", "") else None}
    write_json(OUT, out)
    print(f"{OUT}: {sum(f['rebuilt'] for f in out['fields'])}/{len(out['fields'])} fields rebuilt; "
          f"pm validation after: {(out['pm_validation']['after'] or {}).get('n_tested')} tested")


if __name__ == "__main__":
    main()
