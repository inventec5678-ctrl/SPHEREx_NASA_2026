"""Injection-recovery completeness on held-out test fields.

Every injected placement (exposure x mover inside the valid field) counts once.
  stage-1  : a difference-image candidate (S/N>=5) within 1.5 px
  pipeline : stage-1 AND CNN logit >= threshold fixed on the validation fields (FPR 1%)
Outputs models/recovery.json and models/recovery.png

  python scripts/injection_recovery.py [--ds data/ds] [--models models]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write_json  # noqa: E402
from train_cnn import TEST, predict  # noqa: E402

MAG_BINS = np.arange(14.0, 22.01, 0.5)
MIN_PER_BIN = 5
MIN_PER_DETECTOR = 50
DETECTORS = range(1, 7)
RATE_BINS = np.array([1, 3, 10, 30, 100, 160])     # arcsec/h
MIN_PER_RATE_BIN = 10
BRIGHT_MAG = 18
DISTANT_BRIGHT_MAG = 19


def mag50(mags, rec, bins):
    """Magnitude where completeness crosses 50% (linear interpolation)."""
    c = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (mags >= lo) & (mags < hi)
        c.append(rec[m].mean() if m.sum() >= MIN_PER_BIN else np.nan)
    c = np.array(c)
    mid = 0.5 * (bins[:-1] + bins[1:])
    for k in range(len(c) - 1):
        if c[k] >= 0.5 > c[k + 1]:
            return float(mid[k] + (c[k] - 0.5) / (c[k] - c[k + 1]) * (mid[k + 1] - mid[k])), mid, c
    return float("nan"), mid, c


def load_rows(ds, model, dev, T, thr):
    rows = []
    for name in TEST:
        with np.load(Path(ds) / f"{name}.npz") as z:
            stamps, meta, truth = z["stamps"], z["meta"], json.loads(str(z["truth"]))
        logit = predict(model, stamps, dev) / T
        first = {}
        for r, e in enumerate(meta["exp"]):
            first.setdefault(int(e), r)
        for t in truth:
            score = float(logit[first[t["exp"]] + t["cand"]]) if t["detected"] else -np.inf
            rows.append({**t, "field": name, "logit": score, "found": bool(t["detected"] and score >= thr)})
    return rows


def main():
    import torch
    from sxlib.rbnet import RBNet
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default="data/ds")
    ap.add_argument("--models", default="models")
    a = ap.parse_args()
    models = Path(a.models)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(models / "rb_cnn.pt", map_location=dev)
    model = RBNet().to(dev)
    model.load_state_dict(ck["state"])
    rows = load_rows(a.ds, model, dev, ck["temperature"], ck["threshold_logit"])

    mags = np.array([r["mag"] for r in rows]); rates = np.array([r["rate"] for r in rows])
    st1 = np.array([r["detected"] for r in rows]); fin = np.array([r["found"] for r in rows])
    kind = np.array([r["kind"] for r in rows]); det = np.array([r["detector"] for r in rows])
    finf = fin.astype(float)
    res = {"n_placements": len(rows), "stage1_completeness": float(st1.mean()), "pipeline_completeness": float(fin.mean())}
    res["mag50_stage1"], mid, c1 = mag50(mags, st1.astype(float), MAG_BINS)
    res["mag50_pipeline"], _, c2 = mag50(mags, finf, MAG_BINS)
    by_det = {d: mag50(mags[det == d], finf[det == d], MAG_BINS) for d in DETECTORS
              if (det == d).sum() > MIN_PER_DETECTOR}
    res["mag50_pipeline_by_detector"] = {f"D{d}": v[0] for d, v in by_det.items()}
    dist = kind == "distant"
    if dist.any():
        bright = dist & (mags < DISTANT_BRIGHT_MAG)
        res["distant_bodies"] = {"placements": int(dist.sum()), "completeness": float(fin[dist].mean()),
                                 "completeness_brighter_than_19": float(fin[bright].mean()) if bright.any() else None}
    lin_bright = (kind == "linear") & (mags < BRIGHT_MAG)
    res["completeness_by_rate_mag_lt_18"] = {}
    for lo, hi in zip(RATE_BINS[:-1], RATE_BINS[1:]):
        m = lin_bright & (rates >= lo) & (rates < hi)
        if m.sum() > MIN_PER_RATE_BIN:
            res["completeness_by_rate_mag_lt_18"][f"{lo}-{hi}"] = float(fin[m].mean())
    print(json.dumps(res, indent=1))
    write_json(models / "recovery.json", res)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].plot(mid, c1, "o-", label="stage 1: difference S/N>=5")
    ax[0].plot(mid, c2, "s-", label="+ CNN (FPR 1% on val)")
    ax[0].axhline(0.5, ls=":", c="gray")
    ax[0].set_xlabel("injected AB magnitude"); ax[0].set_ylabel("completeness (per exposure)")
    ax[0].set_title(f"held-out fields, {len(rows)} placements"); ax[0].legend()
    for d, v in by_det.items():
        ax[1].plot(mid, v[2], label=f"D{d}")
    ax[1].axhline(0.5, ls=":", c="gray"); ax[1].set_xlabel("injected AB magnitude")
    ax[1].set_title("pipeline completeness by detector"); ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(models / "recovery.png", dpi=150)


if __name__ == "__main__":
    main()
