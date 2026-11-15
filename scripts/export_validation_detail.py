"""Per-star numbers behind two summaries of /api/validation, so the guide can draw them as charts.

  python scripts/export_validation_detail.py [--scores] [--passes]      (both when no option is given)

Nothing is trained and nothing is downloaded; only the stored field cubes are read.

--scores  models/bd_spec_scores.json: the classifier score of every real ordinary star of the test set summarised in
          models/bd_spec_metrics.json and of the two real brown dwarfs. The stars are selected exactly as in
          scripts/train_specclass.py (same code, same seed) and scored with the stored weights (models/bd_spec.npz).
          The file records whether the recomputed summary equals the stored one ("matches_metrics").
--passes  outputs/var_targets.json: the brightness in each survey pass of R Draconis, RW Aurigae and the steady
          control Barnard's Star, as the blind variable search measures it (sxlib/varsearch.py; the stored
          var_candidates.json keeps these per-pass values only for flagged candidates, so the control has none).
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MODELS, OUTPUTS, read_json, write_json  # noqa: E402

THRESHOLD = 0.8               # the classifier's operating threshold (as in models/bd_spec_metrics.json)
NEG_SEED = 1                  # the seed scripts/train_specclass.py uses for the real negatives
FP_TOL, SCORE_TOL = 1e-9, 2e-3
PASS_TARGETS = ("rdra", "rwaur", "barnard")


class _Fields:
    """The fields directory, limited to some fields (stands in for train_specclass.FIELDS)."""

    def __init__(self, base, keep):
        self.base, self.keep = base, keep

    def iterdir(self):
        return (p for p in self.base.iterdir() if self.keep(p))

    def __truediv__(self, name):
        return self.base / name


def spec_scores():
    """Rows for models/bd_spec_scores.json (see the module docstring)."""
    import train_specclass as T
    from sxlib.specclass import logit, score
    met_path = MODELS / "bd_spec_metrics.json"
    # The stored summary was made from the fields analysed at that time. A field added later would change both the
    # number of stars and (through the shared random generator) which stars are drawn in the fields after it, so
    # only fields whose cube is older than the summary are used: the selection is then the one that was summarised.
    born = met_path.stat().st_mtime if met_path.exists() else float("inf")
    T.FIELDS = _Fields(FIELDS, lambda p: not (p / "cube" / "img.npy").exists() or (p / "cube" / "img.npy").stat().st_mtime <= born)
    neg = T.real_negatives(rng=np.random.default_rng(NEG_SEED))
    pos = T.real_positives()
    ns = np.array([score(n["x"], n["m"]) for n in neg])
    # z is the log-odds the network puts out (score = 1 / (1 + exp(-z))): it does not pile up at 0 and 1, so a
    # plot of the distribution uses it
    rows = [{"field": n["field"], "g": round(float(n["g"]), 2), "score": round(float(s), 4), "z": round(logit(n["x"], n["m"]), 2)}
            for n, s in zip(neg, ns)]
    out = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "threshold": THRESHOLD,
           "source": "recomputed from the stored field cubes with the stored weights (models/bd_spec.npz); no retraining",
           "positives": [{"id": p["id"], "score": round(float(score(p["x"], p["m"])), 4), "z": round(logit(p["x"], p["m"]), 2)} for p in pos],
           "negatives": rows}
    out["fields"] = sorted({r["field"] for r in rows})
    if met_path.exists():
        met = read_json(met_path)
        rn = met["real_negatives"]
        fp = {thr: float(np.mean(ns >= float(thr))) for thr in rn["false_positive_rate"]}
        top = sorted(rows, key=lambda r: -r["score"])[:len(rn["highest"])]
        out["matches_metrics"] = bool(
            len(rows) == rn["n"] and all(abs(fp[k] - v) < FP_TOL for k, v in rn["false_positive_rate"].items())
            and all(a["field"] == b["field"] and abs(a["score"] - b["score"]) < SCORE_TOL for a, b in zip(top, rn["highest"]))
            and all(abs(p["score"] - met["real_positive_scores"].get(p["id"], -1)) < SCORE_TOL for p in out["positives"]))
    return out


def pass_brightness(ids=PASS_TARGETS):
    """Rows for outputs/var_targets.json: per-pass brightness of the named target of each field, relative to its mean."""
    from sxlib import varsearch as V
    out = {}
    for fid in ids:
        F = V.load_field(FIELDS / fid)
        res = V.search_cube(F, log=lambda *_: None)
        tg = F["doc"]["target"]
        row = V.nearest(res["all"], tg["passes"][0]["x"], tg["passes"][0]["y"])
        if row is None:
            continue
        flagged = V.nearest(res["candidates"], tg["passes"][0]["x"], tg["passes"][0]["y"]) is not None
        out[fid] = {"flagged": flagged, "amp": row["amp"], "sig": row["sig"], "saturated": row["saturated"], "passes": row["L"]}
    return {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": out}


def main(argv):
    both = not any(a in argv for a in ("--scores", "--passes"))
    if both or "--scores" in argv:
        t0 = time.time()
        d = spec_scores()
        write_json(MODELS / "bd_spec_scores.json", d, compact=True)
        print(f"spectral scores: {len(d['negatives'])} ordinary stars, {len(d['positives'])} brown dwarfs, "
              f"same as the stored summary: {d.get('matches_metrics')} ({time.time() - t0:.0f} s)")
    if both or "--passes" in argv:
        t0 = time.time()
        d = pass_brightness()
        write_json(OUTPUTS / "var_targets.json", d)
        for k, v in d["targets"].items():
            print(f"{k}: flagged {v['flagged']}, x{v['amp']}, passes {[p['rel'] for p in v['passes']]}")
        print(f"  ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main(sys.argv[1:])
