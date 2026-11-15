"""Train the real/bogus CNN on data/ds/*.npz (split by FIELD, never by candidate).

Reports on held-out test fields:
  * AUROC, recall at FPR=1% - all reals (injected + known) vs bogus
  * the same for KNOWN asteroids only (real sky, no injection involved)
  * baseline: difference-image S/N alone as the score
Saves models/rb_cnn.pt, models/metrics.json, models/roc.png, models/test_scores.npz

TEST, VAL and predict() are imported by scripts/build_paper_evidence.py and scripts/injection_recovery.py; torch,
sklearn and matplotlib are imported lazily so importing the split lists stays cheap.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, ROOT, write_json  # noqa: E402

TEST = ["ecl180+00", "ecl060+00"]
VAL = ["ecl120+00", "ecl315-12"]

MAX_BOGUS_PER_FIELD = 50000   # crowded galactic-plane fields would otherwise dominate
KNOWN_MAG_MAX = 18.5          # known asteroids used for the sim-to-real test
MAX_POS_WEIGHT = 20.0
FPR_TARGET = 0.01
WEIGHT_DECAY = 1e-4
PREDICT_BS = 4096


def load(ds_dir, names, cap_bogus=True):
    S, Y, M, F_ = [], [], [], []
    rng = np.random.default_rng(0)
    for n in names:
        p = Path(ds_dir) / f"{n}.npz"
        if not p.exists():
            continue
        z = np.load(p)
        y = z["y"]
        keep = np.arange(len(y))
        bog = np.flatnonzero(y == 0)
        if cap_bogus and len(bog) > MAX_BOGUS_PER_FIELD:
            keep = np.sort(np.r_[np.flatnonzero(y == 1), rng.choice(bog, MAX_BOGUS_PER_FIELD, replace=False)])
        S.append(z["stamps"][keep]); Y.append(y[keep]); M.append(z["meta"][keep]); F_ += [n] * len(keep)
    if not S:
        return None
    return {"x": np.concatenate(S), "y": np.concatenate(Y).astype(np.float32),
            "meta": np.concatenate(M), "field": np.array(F_)}


def augment(x):
    """Random 90-degree rotation and horizontal flip of a batch [B, C, H, W]."""
    import torch
    k = np.random.randint(4)
    x = torch.rot90(x, k, (2, 3))
    if np.random.rand() < 0.5:
        x = torch.flip(x, (3,))
    return x


def predict(model, x, dev, bs=PREDICT_BS):
    """Logits of ``model`` for stamps ``x`` (numpy), in batches, without gradients."""
    import torch
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), bs):
            out.append(model(torch.from_numpy(x[i:i + bs].astype(np.float32)).to(dev)).float().cpu())
    return torch.cat(out).numpy()


def recall_at_fpr(y, s, fpr_target=FPR_TARGET):
    from sklearn.metrics import roc_curve
    fpr, tpr, thr = roc_curve(y, s)
    k = max(np.searchsorted(fpr, fpr_target, side="right") - 1, 0)
    return float(tpr[k]), float(thr[k])


def report(y, s, src, tag):
    from sklearn.metrics import roc_auc_score
    r = {"auroc_all": float(roc_auc_score(y, s))}
    r["recall_at_fpr1_all"], _ = recall_at_fpr(y, s)
    known = (src == 1) | (y == 0)
    if (src == 1).sum() > 5:
        r["auroc_known"] = float(roc_auc_score(y[known], s[known]))
        r["recall_at_fpr1_known"], _ = recall_at_fpr(y[known], s[known])
        r["n_known"] = int((src == 1).sum())
    r["n_inj"], r["n_bogus"] = int((src == 0).sum()), int((y == 0).sum())
    print(f"  [{tag}] " + ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in r.items()))
    return r


def fit_temperature(logits, y):
    """Temperature scaling on the validation logits (LBFGS on log T)."""
    import torch
    import torch.nn.functional as F
    t = torch.zeros(1, requires_grad=True)
    lg, yt = torch.tensor(logits), torch.tensor(y)
    opt = torch.optim.LBFGS([t], lr=0.1, max_iter=100)

    def step():
        opt.zero_grad()
        loss = F.binary_cross_entropy_with_logits(lg / t.exp(), yt)
        loss.backward()
        return loss
    opt.step(step)
    return float(t.exp())


def plot_roc(path, panels):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_auc_score, roc_curve
    fig, ax = plt.subplots(1, 2, figsize=(9, 4))
    for k, (yy, sc, sn, title) in enumerate(panels):
        for s_, lab in ((sc, "CNN"), (sn, "S/N only")):
            f, t, _ = roc_curve(yy, s_)
            ax[k].plot(f, t, label=f"{lab} AUC={roc_auc_score(yy, s_):.3f}")
        ax[k].set_xscale("log"); ax[k].set_xlim(1e-4, 1); ax[k].axvline(FPR_TARGET, ls=":", c="gray")
        ax[k].set_xlabel("false positive rate"); ax[k].set_ylabel("recall"); ax[k].set_title(title, fontsize=9)
        ax[k].legend()
    fig.tight_layout(); fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Train the real/bogus CNN (split by field)")
    ap.add_argument("--ds", default=str(ROOT / "data" / "ds"))
    ap.add_argument("--out", default=str(MODELS))
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--bs", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--test", help="comma list of test fields (default: TEST)")
    ap.add_argument("--val", help="comma list of validation fields (default: VAL)")
    ap.add_argument("--eval-only", action="store_true", help="load OUT/rb_cnn.pt and only evaluate")
    a = ap.parse_args()
    import torch
    import torch.nn.functional as F
    from sklearn.metrics import roc_auc_score
    from sxlib.rbnet import RBNet
    global TEST, VAL
    TEST = a.test.split(",") if a.test else TEST
    VAL = a.val.split(",") if a.val else VAL
    torch.manual_seed(0); np.random.seed(0)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    names = sorted(p.stem for p in Path(a.ds).glob("*.npz"))
    # kb_* fields (bright known-asteroid benchmark) are evaluation-only
    train_names = [n for n in names if n not in TEST + VAL and not n.startswith("kb_")]
    tr, va, te = load(a.ds, train_names), load(a.ds, VAL), load(a.ds, TEST)
    # Real known asteroids are NEVER used for training: they form a sim-to-real test set
    # (known detections from every field vs bogus from the held-out test fields).
    allk = load(a.ds, names)
    km = (allk["meta"]["src"] == 1) & (allk["meta"]["mag"] <= KNOWN_MAG_MAX)
    known_set = {k: v[km] for k, v in allk.items()}
    keep = tr["meta"]["src"] != 1
    tr = {k: v[keep] for k, v in tr.items()}
    del allk
    for tag, d in (("train", tr), ("val", va), ("test", te)):
        print(f"{tag}: {len(d['y'])} cands, {int(d['y'].sum())} real "
              f"({int((d['meta']['src'] == 1).sum())} known asteroids), fields={sorted(set(d['field']))}")

    model = RBNet().to(dev)
    print("params", sum(p.numel() for p in model.parameters()))
    pos_w = torch.tensor(min(MAX_POS_WEIGHT, (1 - tr["y"].mean()) / tr["y"].mean()), device=dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.epochs * (len(tr["y"]) // a.bs + 1))
    X, Yt = torch.from_numpy(tr["x"]), torch.from_numpy(tr["y"])
    best, best_state = -1, None
    if a.eval_only:
        best_state = torch.load(Path(a.out) / "rb_cnn.pt", map_location=dev)["state"]
    for ep in range(0 if a.eval_only else a.epochs):
        model.train()
        perm = torch.randperm(len(Yt))
        tot = 0.0
        for i in range(0, len(perm), a.bs):
            idx = perm[i:i + a.bs]
            xb = augment(X[idx].float()).to(dev)
            yb = Yt[idx].to(dev)
            loss = F.binary_cross_entropy_with_logits(model(xb), yb, pos_weight=pos_w)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += loss.item() * len(idx)
        sv = predict(model, va["x"], dev)
        auc = roc_auc_score(va["y"], sv)
        rec, _ = recall_at_fpr(va["y"], sv)
        print(f"epoch {ep:2d} loss {tot / len(Yt):.4f} val AUROC {auc:.4f} recall@FPR1% {rec:.3f}", flush=True)
        if auc > best:
            best, best_state = auc, {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)

    lv = predict(model, va["x"], dev)
    T = fit_temperature(lv, va["y"])
    _, thr_val = recall_at_fpr(va["y"], lv / T)          # operating point fixed on VAL
    lt = predict(model, te["x"], dev) / T
    src = te["meta"]["src"]
    print("TEST (held-out fields):")
    res = {"temperature": T, "threshold_logit_fpr1_val": thr_val,
           "cnn": report(te["y"], lt, src, "CNN"),
           "baseline_snr": report(te["y"], te["meta"]["snr"].astype(float), src, "S/N only")}
    # sim-to-real: all known asteroids (all fields) vs test-field bogus
    lk = predict(model, known_set["x"], dev) / T
    bog = te["y"] == 0
    yk = np.r_[np.ones(len(lk)), np.zeros(bog.sum())]
    sk = np.r_[lk, lt[bog]]
    snr_k = np.r_[known_set["meta"]["snr"], te["meta"]["snr"][bog]].astype(float)
    res["known_all_fields"] = {"n_known": int(len(lk)), "n_fields": int(len(set(known_set["field"]))),
                               "auroc_cnn": float(roc_auc_score(yk, sk)),
                               "auroc_snr": float(roc_auc_score(yk, snr_k)),
                               "recall_at_val_threshold": float((lk >= thr_val).mean()),
                               "recall_at_fpr1_cnn": recall_at_fpr(yk, sk)[0],
                               "recall_at_fpr1_snr": recall_at_fpr(yk, snr_k)[0]}
    for kk, sfx in (("cnn", "cnn"), ("baseline_snr", "snr")):
        res[kk]["auroc_known"] = res["known_all_fields"]["auroc_" + sfx]
        res[kk]["recall_at_fpr1_known"] = res["known_all_fields"]["recall_at_fpr1_" + sfx]
    print("  [sim-to-real, known asteroids never seen in training]", res["known_all_fields"])
    p = 1 / (1 + np.exp(-lt))
    passed = lt >= thr_val
    fp = (passed & bog).sum() / max(1, bog.sum())
    tp = (passed & (te["y"] == 1)).sum() / max(1, te["y"].sum())
    res["test_at_val_threshold"] = {"recall": float(tp), "fpr": float(fp)}
    print(f"  at VAL-fixed threshold: test recall {tp:.3f}, test FPR {fp:.4f}")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "temperature": T, "threshold_logit": thr_val}, out / "rb_cnn.pt")
    write_json(out / "metrics.json", res)
    np.savez(out / "test_scores.npz", logit=lt, prob=p, y=te["y"], field=te["field"], meta=te["meta"])
    plot_roc(out / "roc.png", [(te["y"], lt, te["meta"]["snr"].astype(float), "held-out fields: injected movers vs bogus"),
                               (yk, sk, snr_k, f"real known asteroids ({len(lk)}, never trained on)")])
    print("saved", out)


if __name__ == "__main__":
    main()
