"""Every number in the paper and on the methods page comes from here (never typed by hand).

Reads data/ds/*.npz + models/rb_cnn.pt and writes paper_evidence/evidence.json with:
  * bootstrap 95% CIs (1000 resamples of candidates) for AUROC / recall / FPR
  * per-detector and per-magnitude tables (known asteroids and injected movers)
  * injection completeness per magnitude bin with Wilson CIs
  * dataset composition per field
plus paper_evidence/manifest.json with the SHA-256 of every evidence and model file.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, PAPER_EVIDENCE, ROOT, dumps, rel, write_json  # noqa: E402
from train_cnn import TEST, VAL  # noqa: E402

OUT = PAPER_EVIDENCE
DS = ROOT / "data" / "ds"
RNG = np.random.default_rng(20261021)
B = 1000                        # bootstrap resamples
V_MAX = 18.5                    # known asteroids bright enough for one exposure
MAX_CLEAN_BOGUS = 20000         # per field, in the clean comparison
KNOWN_MAG_BINS = ((0, 15), (15, 16), (16, 17), (17, 18.5))
COMPLETENESS_MAG = (14.0, 21.5, 0.5)
ROLES = ("train", "val", "test", "benchmark")


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(float(c - h), 4), round(float(c + h), 4)]


def boot(fn, *arrays):
    n = len(arrays[0])
    vals = []
    for _ in range(B):
        ix = RNG.integers(0, n, n)
        try:
            vals.append(fn(*[a[ix] for a in arrays]))
        except ValueError:
            continue
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rate(sel_p, thr, digits=4):
    """Fraction of scores >= thr, rounded; None for an empty selection."""
    return round(float((sel_p >= thr).mean()), digits) if len(sel_p) else None


def _auc_block(y, p, s, auc):
    return {"auroc": round(float(auc(y, p)), 4), "auroc_ci95": boot(auc, y, p),
            "auroc_snr": round(float(auc(y, s)), 4), "auroc_snr_ci95": boot(auc, y, s)}


def main():
    from sklearn.metrics import roc_auc_score, roc_curve
    from sxlib.rbnet import Scorer
    sc = Scorer(MODELS / "rb_cnn.pt")
    thr = sc.thr_prob
    names = sorted(p.stem for p in DS.glob("*.npz"))
    comp, test, known, truth_rows, clean_bog = [], [], [], [], []
    rng = np.random.default_rng(0)
    for n in names:
        z = np.load(DS / f"{n}.npz")
        m, y = z["meta"], z["y"]
        role = "test" if n in TEST else "val" if n in VAL else "benchmark" if n.startswith("kb_") else "train"
        km = (m["src"] == 1) & (m["mag"] <= V_MAX)
        comp.append({"field": n, "role": role, "candidates": int(len(y)), "injected": int((m["src"] == 0).sum()),
                     "known_v_le_18_5": int(km.sum()), "bogus": int((y == 0).sum())})
        need_test = n in TEST
        # clean comparison: fields never used in training contribute BOTH their known asteroids and
        # their own false signals (up to 20k per field), so positives and negatives share the same skies
        need_bog = role != "train" and km.any()
        if not (need_test or km.any()):
            continue
        st = z["stamps"]
        if need_test:
            p = sc(st)
            test.append({"p": p, "y": y, "src": m["src"], "det": m["det"], "snr": m["snr"], "mag": m["mag"]})
            ue, ui = np.unique(m["exp"], return_index=True)          # first candidate row of each exposure
            first = dict(zip(ue.tolist(), ui.tolist()))
            for t in json.loads(str(z["truth"])):
                pt = float(p[first[t["exp"]] + t["cand"]]) if t["detected"] else 0.0
                truth_rows.append((t["mag"], t["detector"], t["kind"], t["rate"], t["detected"], t["detected"] and pt >= thr))
        if km.any():
            known.append({"p": sc(st[km]), "det": m["det"][km], "mag": m["mag"][km], "snr": m["snr"][km], "field": n, "role": role})
        if need_bog:
            bi = np.flatnonzero(y == 0)
            if len(bi) > MAX_CLEAN_BOGUS:
                bi = np.sort(rng.choice(bi, MAX_CLEAN_BOGUS, replace=False))
            clean_bog.append({"p": p[bi] if need_test else sc(st[bi]), "snr": m["snr"][bi], "field": n})
        print("scored", n, flush=True)

    T = {k: np.concatenate([t[k] for t in test]) for k in test[0]}
    K = {k: np.concatenate([t[k] for t in known]) for k in ("p", "det", "mag", "snr")}
    bog = T["y"] == 0
    inj = T["src"] == 0
    ev = {"threshold_prob": round(thr, 4), "bootstrap_resamples": B,
          "bootstrap_unit": "candidate (fields are not resampled; CIs ignore between-field variance)"}

    # injected vs bogus on the held-out test fields
    yi = np.r_[np.ones(inj.sum()), np.zeros(bog.sum())]
    pi = np.r_[T["p"][inj], T["p"][bog]]
    si = np.r_[T["snr"][inj], T["snr"][bog]]
    ev["test_injected"] = {
        "n_injected": int(inj.sum()), "n_bogus": int(bog.sum()), "fields": TEST, **_auc_block(yi, pi, si, roc_auc_score),
        "recall": round(float((T["p"][inj] >= thr).mean()), 4), "recall_ci95": wilson(int((T["p"][inj] >= thr).sum()), int(inj.sum())),
        "fpr": round(float((T["p"][bog] >= thr).mean()), 5), "fpr_ci95": wilson(int((T["p"][bog] >= thr).sum()), int(bog.sum()))}

    # real known asteroids (never trained on) vs held-out bogus
    yk = np.r_[np.ones(len(K["p"])), np.zeros(bog.sum())]
    pk = np.r_[K["p"], T["p"][bog]]
    sk = np.r_[K["snr"], T["snr"][bog]]
    kh = int((K["p"] >= thr).sum())
    ev["known_asteroids"] = {
        "n_known": int(len(K["p"])), "n_fields": len(known), "v_max": V_MAX, **_auc_block(yk, pk, sk, roc_auc_score),
        "recall": round(kh / len(K["p"]), 4), "recall_ci95": wilson(kh, len(K["p"])),
        "note": "positives from 31 fields (199 detections in training-field images, asteroids themselves removed from training); negatives from the 2 test fields"}

    # the clean version: only fields the CNN never trained on, positives and negatives from the same fields
    kc = [k for k in known if k["role"] != "train"]
    if kc and clean_bog:
        cp = np.concatenate([k["p"] for k in kc]); cs = np.concatenate([k["snr"] for k in kc])
        bp = np.concatenate([b["p"] for b in clean_bog]); bs = np.concatenate([b["snr"] for b in clean_bog])
        yc = np.r_[np.ones(len(cp)), np.zeros(len(bp))]
        kh2 = int((cp >= thr).sum())
        ev["known_asteroids_clean"] = {
            "n_known": int(len(cp)), "n_fields": len(kc), "n_bogus": int(len(bp)), "v_max": V_MAX,
            **_auc_block(yc, np.r_[cp, bp], np.r_[cs, bs], roc_auc_score),
            "recall": round(kh2 / len(cp), 4), "recall_ci95": wilson(kh2, len(cp)),
            "fpr": round(float((bp >= thr).mean()), 5), "fpr_ci95": wilson(int((bp >= thr).sum()), int(len(bp))),
            "note": "validation, test and benchmark fields only (never used in training); bogus from the same fields"}

    # per detector
    ev["by_detector"] = []
    for d in range(1, 7):
        ki, ii, bi = K["det"] == d, inj & (T["det"] == d), bog & (T["det"] == d)
        ev["by_detector"].append({
            "detector": d, "known_n": int(ki.sum()), "known_recall": _rate(K["p"][ki], thr),
            "known_recall_ci95": wilson(int((K["p"][ki] >= thr).sum()), int(ki.sum())),
            "injected_n": int(ii.sum()), "injected_recall": _rate(T["p"][ii], thr),
            "bogus_n": int(bi.sum()), "fpr": _rate(T["p"][bi], thr, 5)})
    # known asteroids by V magnitude
    ev["known_by_mag"] = []
    for lo, hi in KNOWN_MAG_BINS:
        mm = (K["mag"] >= lo) & (K["mag"] < hi)
        k = int((K["p"][mm] >= thr).sum())
        ev["known_by_mag"].append({"v_lo": lo, "v_hi": hi, "n": int(mm.sum()),
                                   "recall": round(k / mm.sum(), 4) if mm.any() else None, "ci95": wilson(k, int(mm.sum()))})
    # injection completeness per AB magnitude (all placements in the test fields)
    mags = np.array([r[0] for r in truth_rows], float)
    st1 = np.array([r[4] for r in truth_rows], bool)
    fin = np.array([r[5] for r in truth_rows], bool)
    lo0, hi0, step = COMPLETENESS_MAG
    ev["completeness_by_mag"] = []
    for lo in np.arange(lo0, hi0, step):
        mm = (mags >= lo) & (mags < lo + step)
        ev["completeness_by_mag"].append({
            "ab_lo": float(lo), "ab_hi": float(lo + step), "n": int(mm.sum()),
            "stage1": round(float(st1[mm].mean()), 4) if mm.any() else None, "stage1_ci95": wilson(int(st1[mm].sum()), int(mm.sum())),
            "pipeline": round(float(fin[mm].mean()), 4) if mm.any() else None, "pipeline_ci95": wilson(int(fin[mm].sum()), int(mm.sum()))})
    # ROC curves (log-spaced FPR grid) for interactive figures
    grid = np.r_[0, np.logspace(-4, 0, 60)]

    def curve(y, s_):
        f, t, _ = roc_curve(y, s_)
        return [round(float(v), 4) for v in np.interp(grid, f, t)]
    ev["roc"] = {"fpr": [round(float(g), 6) for g in grid],
                 "injected_cnn": curve(yi, pi), "injected_snr": curve(yi, si),
                 "known_cnn": curve(yk, pk), "known_snr": curve(yk, sk)}
    ev["dataset"] = comp
    ev["dataset_totals"] = {r: {k: int(sum(c[k] for c in comp if c["role"] == r))
                                for k in ("candidates", "injected", "known_v_le_18_5", "bogus")}
                            | {"fields": sum(1 for c in comp if c["role"] == r)}
                            for r in ROLES}
    write_json(OUT / "evidence.json", ev)
    files = [OUT / "evidence.json", MODELS / "metrics.json", MODELS / "recovery.json", MODELS / "rb_cnn.pt"]
    if (OUT / "planetx_grid.json").exists():
        files.append(OUT / "planetx_grid.json")
    write_json(OUT / "manifest.json", {rel(p): sha(p) for p in files})
    print(dumps({k: ev.get(k) for k in ("test_injected", "known_asteroids", "known_asteroids_clean")}))


if __name__ == "__main__":
    main()
