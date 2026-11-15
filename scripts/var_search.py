"""Automatic variable-star search on every analysed field that has a cube: python scripts/var_search.py [field ids]

Writes web/data/fields/<id>/var_candidates.json ({"candidates": [...], "stats": {...}}; see sxlib/varsearch.py) and
outputs/var_search.json, a summary across fields: candidates by catalogue status, whether the challenge's variable
targets were found without being told where they are, the steady saturated control (Barnard's Star), and the pooled
scatter of ring photometry on saturated stars that are not the targets (the numbers behind RING_SYS / RING_MIN_AMP).
Options: --no-catalogues (skip VSX and Gaia; status is then null).
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, OUTPUTS, field_ids, read_json, write_json  # noqa: E402

SUMMARY = OUTPUTS / "var_search.json"
TARGET_XY, TARGET_TOL = 88, 3          # a named target sits at the centre pixel of its field
STATUSES = ("known_variable", "catalogued_constant", "new")


def _is_target(q, tc):
    return (tc is not None and tc["kind"] == "var"
            and abs(q["x"] - TARGET_XY) < TARGET_TOL and abs(q["y"] - TARGET_XY) < TARGET_TOL)


def _control(results):
    """Barnard's Star, the steady saturated control, from this run or from its stored candidates file."""
    bar = results.get("barnard")
    if bar is None:
        p = FIELDS / "barnard" / "var_candidates.json"
        bar = read_json(p) if p.exists() else None
    if not bar:
        return None
    tc = bar["stats"].get("target_check") or bar["stats"].get("control", {}).get("barnard")
    return {k: tc.get(k) for k in ("measured", "flagged", "amp", "sig", "amp_det")} if tc else None


def _ring_pool(ring, V):
    if not ring:
        return None
    dl, err = np.array([q["dl"] for q in ring]), np.array([q["err"] for q in ring])
    z = np.abs(dl) / np.hypot(err, V.RING_SYS)
    adl = np.abs(dl)
    p95, p99 = np.percentile(adl, [95, 99])
    return {"n_differences": int(len(dl)), "robust_sigma_ln": round(V._robust_sigma(dl), 4),
            "median_fit_err_ln": round(float(np.median(err)), 4),
            "amp_p95": round(float(np.exp(p95)), 3), "amp_p99": round(float(np.exp(p99)), 3),
            "max_z": round(float(z.max()), 2), "n_z_ge_5": int((z >= 5).sum())}


def main(argv):
    from sxlib import varsearch as V
    with_cat = "--no-catalogues" not in argv
    ids = field_ids([a for a in argv if not a.startswith("--")], marker="cube/img.npy", skip_dotted=True)
    results, ring = {}, []
    for fid in ids:
        t0 = time.time()
        print(f"{fid}:")
        res = V.search(FIELDS / fid, with_catalogues=with_cat)
        results[fid] = res
        tc = res["stats"].get("target_check")
        ring += [q for q in res["ring"] if not _is_target(q, tc)]
        for c in res["candidates"]:
            m = c["match"]
            print(f"  #{c['id']} ({c['x']}, {c['y']}) x{c['amp']} sig {c['sig']} dets {c['dets_agree']} "
                  f"{'ring' if c['saturated'] else 'aperture'} -> {c['status']}"
                  f"{' ' + str(m['name']) + ' ' + str(m['type']) if m else ''}")
        print(f"  {time.time() - t0:.1f} s")
    control = _control(results)
    pool = _ring_pool(ring, V)
    summary = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "fields": {}, "control_barnard": control,
               "ring_pool_excluding_targets": pool}
    for fid, res in results.items():
        st = res["stats"]
        st["control"] = {"barnard": control, "ring_pool": pool}
        write_json(FIELDS / fid / "var_candidates.json", {"candidates": res["candidates"], "stats": st}, indent=None)
        cv = st.get("catalogued_variables")
        summary["fields"][fid] = {
            "n_sources": st["n_sources"], "n_measured": st["n_measured"], "n_candidates": len(res["candidates"]),
            "n_searched": st["n_searched"], "n_blended": st["n_blended"], "n_near_saturated": st["n_near_saturated"],
            "by_status": st["by_status"], "target_check": st.get("target_check"),
            "catalogued_variables": {k: v for k, v in cv.items() if k != "list"} if cv else None,
            "threshold_unsat": st["threshold_unsat"], "catalogue_errors": st["catalogue_errors"]}
    if len(ids) > 1 or not SUMMARY.exists():
        write_json(SUMMARY, summary)
    print("control (Barnard's Star):", control)
    print("ring pool (saturated stars other than the variable targets):", pool)
    tot = {k: sum(f["by_status"][k] for f in summary["fields"].values()) for k in STATUSES}
    print("candidates:", sum(f["n_candidates"] for f in summary["fields"].values()), tot)


if __name__ == "__main__":
    main(sys.argv[1:])
