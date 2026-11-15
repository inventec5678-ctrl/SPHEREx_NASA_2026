"""Null test for the shift-and-stack survey: how many tracks does chance alone produce?

For every survey field: stack each pass once, then link the stacked peaks (a) with their true times and
(b) after cyclically relabelling which pass each set of peaks came from (the peaks keep their positions and
S/N, but the parallax + orbit model now predicts the wrong motion, so anything that still links is a chance
alignment). Both go through the same confirmation step. If (a) is not clearly above (b), the candidates are
consistent with chance.

  python scripts/stack_null.py <field_id>   -> outputs/survey/<id>/null.json
  python scripts/stack_null.py summary      -> paper_evidence/stack_null.json
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, PAPER_EVIDENCE, read_json, write_json  # noqa: E402

OUT = OUTPUTS / "survey"
THRESH = 7.0
MIN_PASS_EXPOSURES = 8
D_TRIALS = np.geomspace(40, 3000, 36)        # trial distances of the stacking search (au)


def run(fid):
    from sxlib import link, shiftstack
    fdir = OUT / fid
    doc, snr = shiftstack.load_field(fdir)
    mjd = np.array([e["mjd"] for e in doc["exposures"]])
    P = shiftstack.passes_of(mjd)
    used = [k for k, idx in enumerate(P) if len(idx) >= MIN_PASS_EXPOSURES]
    groups = []
    for k in used:
        for p in shiftstack.stack_pass(doc, snr, P[k], D_TRIALS, THRESH):
            groups.append({"pass": k, "ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "peak": p})
    mask, _ = shiftstack.star_mask(fdir, doc)
    groups = [g for g in groups if not mask[int(round(g["peak"]["y"])), int(round(g["peak"]["x"]))]]
    dets = []
    for k, g in enumerate(groups):
        p = g["peak"]
        dets.append({"ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "p": p["snr"]})
        g["members"] = [k]
    groups, dets = shiftstack.drop_static(groups, dets, log=lambda s: None)
    peaks = [g["peak"] | {"pass": g["pass"]} for g in groups]
    mids = {k: float(np.median(mjd[P[k]])) for k in used}
    res = {"id": fid, "n_peaks": len(peaks), "passes": len(used)}
    perms = {"true": {k: k for k in used}}
    if len(used) >= 3:
        for s in (1, 2):
            perms[f"shift{s}"] = {k: used[(i + s) % len(used)] for i, k in enumerate(used)}
    for name, pm in perms.items():
        G = [dict(g, mjd=mids[pm[g["pass"]]]) for g in groups]
        D = [dict(d, mjd=mids[pm[g["pass"]]]) for d, g in zip(dets, groups)]
        tr = link.link_groups(G, D, tol_arcsec=shiftstack.LINK_TOL) if G else []
        ok = shiftstack.confirm(doc, snr, P, tr, peaks, THRESH)
        res[name] = {"linked": len(tr), "confirmed": len(ok)}
    print(json.dumps(res), flush=True)
    write_json(fdir / "null.json", res, indent=None)


def summary():
    rows = [read_json(p) for p in sorted(OUT.glob("*/null.json"))]
    tot = {k: sum(r[k]["confirmed"] for r in rows if k in r) for k in ("true", "shift1", "shift2")}
    out = {"fields": rows, "total_true": tot["true"], "total_null_mean": (tot["shift1"] + tot["shift2"]) / 2,
           "total_null": [tot["shift1"], tot["shift2"]],
           "note": "confirmed stacked tracks with true pass times vs. cyclically relabelled pass times (chance alignments)"}
    write_json(PAPER_EVIDENCE / "stack_null.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "fields"}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    summary() if sys.argv[1] == "summary" else run(sys.argv[1])
