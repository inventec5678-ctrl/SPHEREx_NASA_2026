"""Sensitivity of single-exposure detection to the systematic term eps of equation (2), for the referee.
Field RA 183.2, Dec -1.4 (0.3 deg; never used to train or calibrate the classifier). Synthetic movers are injected
once; the field is differenced with eps = 0.05, 0.10, 0.20 and scored by the classifier at its fixed operating
threshold. Reports, per eps and per detector, the completeness of injected detections and the number of other
sources passing the classifier per exposure (artifacts plus real moving objects).
    python scripts/check_eps.py   -> paper_aas/eps_sensitivity.json   (any working directory)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, PAPER_AAS, write_json  # noqa: E402

RA, DEC, SIZE = 183.2, -1.4, 0.3
EPS_VALUES = (0.05, 0.10, 0.20)
N_MOVERS = 150
MAG_RANGE, RATE_RANGE = (15.0, 18.5), (2.0, 60.0)
MATCH_PIX = 1.5
LAM_TOL = 0.03
DETECTORS = range(1, 7)


def injected_keys(f, truth, movers):
    """Per exposure index, the (x, y, mag) of injected detections that land on a good pixel."""
    where = {(e["obs_id"], e["detector"]): k for k, e in reversed(list(enumerate(f.exps)))}   # first match wins
    key = {}
    for t in truth:
        i = where.get((t["obs_id"], t["detector"]))
        if i is None:
            continue
        x, y = f.world_to_pix(t["ra"], t["dec"])
        ix, iy = int(round(float(x))), int(round(float(y)))
        if 0 <= ix < f.shape[1] and 0 <= iy < f.shape[0] and not f.bad[i, iy, ix]:
            key.setdefault(i, []).append((float(x), float(y), movers[t["mover"]].mag))
    return key


def main():
    from sxlib import pipeline
    from sxlib.inject import random_movers
    from sxlib.rbnet import Scorer
    from sxlib.stack import Field

    rng = np.random.default_rng(7)
    exps = pipeline.load_exposures(RA, DEC, SIZE)
    mjds = np.array([e.mjd for e in exps])
    movers = random_movers(rng, Field(RA, DEC, SIZE), mjds, N_MOVERS, mag_range=MAG_RANGE, rate_range=RATE_RANGE)
    truth = []
    f = pipeline.build_field(exps, RA, DEC, SIZE, movers=movers, truth_log=truth)
    sc = Scorer(MODELS / "rb_cnn.pt")
    thr = sc.thr_prob
    print(f"{len(f.exps)} exposures, {len(truth)} injected detections, threshold p={thr:.3f}", flush=True)
    key = injected_keys(f, truth, movers)
    out = {}
    for eps in EPS_VALUES:
        res = pipeline.detect_all(f, ref_kw={"lam_tol": LAM_TOL, "eps": eps})
        per = {d: {"inj": 0, "hit": 0, "other": 0, "nexp": 0} for d in DETECTORS}
        for r in res:
            i = r["i"]
            v = per[int(f.det[i])]
            v["nexp"] += 1
            c = r["cands"]
            p = sc(r["stamps"]) if c else np.zeros(0)
            used = np.zeros(len(c), bool)
            if c:
                cx = np.array([q["x"] for q in c]); cy = np.array([q["y"] for q in c])
            for x, y, _m in key.get(i, []):
                v["inj"] += 1
                if not c:
                    continue
                dd = np.hypot(cx - x, cy - y)
                j = int(np.argmin(dd))
                if dd[j] <= MATCH_PIX:
                    used[j] = True
                    v["hit"] += int(p[j] >= thr)
            v["other"] += int(((p >= thr) & ~used).sum())
        tot = {k: sum(v[k] for v in per.values()) for k in ("inj", "hit", "other", "nexp")}
        out[eps] = {"per_detector": per, "total": tot}
        print(f"eps={eps:.2f}: completeness {tot['hit'] / tot['inj']:.3f} ({tot['inj']} injected), "
              f"other sources passing per exposure {tot['other'] / tot['nexp']:.3f}", flush=True)
        for d in DETECTORS:
            v = per[d]
            if v["inj"]:
                print(f"   D{d}: completeness {v['hit'] / v['inj']:.3f} (n={v['inj']}), "
                      f"other/exposure {v['other'] / max(v['nexp'], 1):.3f}", flush=True)
    write_json(PAPER_AAS / "eps_sensitivity.json", out)


if __name__ == "__main__":
    main()
