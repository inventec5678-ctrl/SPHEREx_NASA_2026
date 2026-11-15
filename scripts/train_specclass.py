"""Train the brown-dwarf spectral classifier on synthetic spectra; test it on real SPHEREx spectra.

  python scripts/train_specclass.py            train, then measure on real data
  python scripts/train_specclass.py --eval     re-measure the real-data numbers of the stored model only

Real test set (never used in training):
  positives: Epsilon Indi B (T1+T6 binary) and WISE 0855-0714 (Y4), from their tracked forced photometry;
  negatives: Gaia DR3 stars (G 8.5-16) in every analysed field, forced photometry at their positions in every exposure.
Writes models/bd_spec.npz (numpy weights) and models/bd_spec_metrics.json.

scripts/export_validation_detail.py imports this module, replaces FIELDS (a filtered view of the field directory)
and calls real_negatives() / real_positives(); both therefore read the module-level FIELDS at call time.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, dumps, read_json, write_json  # noqa: E402,F401  (FIELDS: module global, see above)

BAD_BITS = 5                    # flag bits that exclude a pixel (1 bad | 4 ghost)
G_RANGE = (8.5, 16.0)           # Gaia G of the negative stars
EDGE_PX = 8
TARGET_EXCLUDE_PX = 4           # Gaia stars this close to a named target are not negatives
MIN_BINS = 5
FP_THRESHOLDS = (0.5, 0.8, 0.9)
THRESHOLD = 0.8
POSITIVE_IDS = ("epsindi", "wise0855")
N_TRAIN, N_VAL = 60000, 8000
EPOCHS, BATCH, LR, WEIGHT_DECAY = 40, 512, 2e-3, 1e-4


def real_negatives(per_field=60, rng=None):
    from sxlib.products import phot
    from sxlib.specclass import bin_spectrum
    out = []
    for fd in sorted(FIELDS.iterdir()):
        if "." in fd.name or not (fd / "cube" / "img.npy").exists() or not (fd / "overlays.json").exists():
            continue
        doc = read_json(fd / "field.json")
        img = np.load(fd / "cube" / "img.npy", mmap_mode="r"); var = np.load(fd / "cube" / "var.npy", mmap_mode="r")
        fl = np.load(fd / "cube" / "flag.npy", mmap_mode="r"); lam = np.load(fd / "cube" / "lam.npy", mmap_mode="r")
        ds = doc["products"].get("lam_ds", 5)
        n = img.shape[1]
        tg = doc.get("target")
        gaia = [s for s in read_json(fd / "overlays.json")["gaia"]
                if s["m"] and G_RANGE[0] < s["m"] < G_RANGE[1] and EDGE_PX < s["x"] < n - EDGE_PX and EDGE_PX < s["y"] < n - EDGE_PX
                and not (tg and np.hypot(s["x"] - tg["passes"][0]["x"], s["y"] - tg["passes"][0]["y"]) < TARGET_EXCLUDE_PX)]
        rng.shuffle(gaia)
        stars = gaia[:per_field]
        if not stars:
            continue
        exps = [(e["i"], e["mjd"]) for e in doc["exposures"] if e["i"] < img.shape[0]]
        bad = {}                                    # bad-pixel mask per exposure, computed once for all stars
        for s in stars:
            L, F, E = [], [], []
            for i, mjd in exps:
                dt = (mjd - s["mjd0"]) / 365.25
                x, y = s["x"] + s["pmx"] * dt, s["y"] + s["pmy"] * dt
                if i not in bad:
                    bad[i] = (fl[i] & BAD_BITS).astype(bool)
                p = phot(img[i], var[i], bad[i], x, y)
                if p is None:
                    continue
                L.append(float(lam[i, min(int(y) // ds, lam.shape[1] - 1), min(int(x) // ds, lam.shape[2] - 1)]))
                F.append(p[0]); E.append(p[1])
            xb, mb = bin_spectrum(L, F, E)
            if mb.sum() >= MIN_BINS:
                out.append({"field": fd.name, "g": s["m"], "x": xb, "m": mb})
    return out


def real_positives():
    from sxlib.specclass import bin_spectrum
    out = []
    for tid in POSITIVE_IDS:
        t = read_json(FIELDS / tid / "field.json")["target"]
        pts = [p for p in t["points"] if p.get("f") is not None and p.get("e") and not ((p.get("flag") or 0) & BAD_BITS)]
        xb, mb = bin_spectrum([p["lam"] for p in pts], [p["f"] for p in pts], [p["e"] for p in pts])
        out.append({"id": tid, "x": xb, "m": mb})
    return out


def _real_metrics(score):
    """Scores of the stored model on the real positives and negatives: (positive scores, negatives summary)."""
    pos = real_positives()
    neg = real_negatives(rng=np.random.default_rng(1))
    ps = {p["id"]: score(p["x"], p["m"]) for p in pos}
    ns = np.array([score(n["x"], n["m"]) for n in neg])
    fp = {thr: float(np.mean(ns >= thr)) for thr in FP_THRESHOLDS}
    worst = sorted(zip(ns, neg), key=lambda t: -t[0])[:5]
    return ({k: round(v, 3) for k, v in ps.items()},
            {"n": len(neg), "median_score": round(float(np.median(ns)), 4), "false_positive_rate": fp,
             "highest": [{"field": n["field"], "g": n["g"], "score": round(float(s), 3)} for s, n in worst]})


def main():
    import torch
    from sklearn.metrics import roc_auc_score
    from torch import nn

    import sxlib.specclass as sc
    from sxlib.specclass import MODEL, NB, score, synth
    rng = np.random.default_rng(7)
    X, M, Y = synth(N_TRAIN, rng)
    Xv, Mv, Yv = synth(N_VAL, np.random.default_rng(8))

    def t(a, b):
        return torch.tensor(np.concatenate([a, b], 1), dtype=torch.float32)
    xt, yt, xv = t(X, M), torch.tensor(Y, dtype=torch.float32), t(Xv, Mv)
    torch.manual_seed(0)
    net = nn.Sequential(nn.Linear(2 * NB, 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))
    opt = torch.optim.Adam(net.parameters(), LR, weight_decay=WEIGHT_DECAY)
    lossf = nn.BCEWithLogitsLoss()

    def val_prob():
        with torch.no_grad():
            return torch.sigmoid(net(xv).squeeze(1)).numpy()
    for ep in range(EPOCHS):
        perm = torch.randperm(len(xt))
        for k in range(0, len(xt), BATCH):
            b = perm[k:k + BATCH]
            opt.zero_grad(); loss = lossf(net(xt[b]).squeeze(1), yt[b]); loss.backward(); opt.step()
        if ep % 10 == 9:
            print(f"epoch {ep + 1}: synthetic validation accuracy {np.mean((val_prob() > .5) == Yv):.4f}", flush=True)
    lin = [m for m in net if isinstance(m, nn.Linear)]
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    np.savez(MODEL, **{f"w{k}": l.weight.detach().numpy().T for k, l in enumerate(lin)},
             **{f"b{k}": l.bias.detach().numpy() for k, l in enumerate(lin)})
    sc._W = None                                    # make score() reload the weights just written
    pv = val_prob()
    syn_auc = float(roc_auc_score(Yv, pv))
    pos_scores, neg_summary = _real_metrics(score)
    met = {"synthetic_val_accuracy": float(np.mean((pv > .5) == Yv)), "synthetic_val_auc": syn_auc,
           "real_positive_scores": pos_scores, "real_negatives": neg_summary,
           "threshold": THRESHOLD, "bins_um": [round(float(c), 3) for c in sc.CENTRES],
           "training": "60000 synthetic spectra (50% T/Y dwarfs; stars, M giants/Miras, L dwarfs, YSOs, galaxies), no real data"}
    write_json(MODEL.parent / "bd_spec_metrics.json", met)
    print(dumps(met))


def evaluate():
    """--eval: re-measure the real-data numbers of the stored model on the fields as they are now (e.g. after a new
    data release), without retraining. The synthetic-validation numbers and the weights are kept; the previous
    real-data numbers are kept under "previous" so the change can be shown."""
    from sxlib.specclass import MODEL, score
    path = MODEL.parent / "bd_spec_metrics.json"
    met = read_json(path)
    pos_scores, neg_summary = _real_metrics(score)
    met["previous"] = {k: met[k] for k in ("real_positive_scores", "real_negatives")}
    met["real_positive_scores"] = pos_scores
    met["real_negatives"] = neg_summary
    met["evaluated"] = time.strftime("%Y-%m-%dT%H:%M:%S") + " (real-data numbers re-measured on the current fields; weights unchanged)"
    write_json(path, met)
    print(dumps({k: met[k] for k in ("real_positive_scores", "real_negatives", "previous")}))


if __name__ == "__main__":
    evaluate() if "--eval" in sys.argv else main()
