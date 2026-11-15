"""Diagnostics for one field: reference availability vs wavelength tolerance, candidate
counts, and a few difference-image previews (incl. one injected mover sanity check).

  python scripts/probe_field.py [--ra 178.6] [--dec 1.1] [--size 0.5] [--out outputs/probe]
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write_json  # noqa: E402

LAM_TOLS = (0.01, 0.02, 0.03, 0.05)
EPS_VALUES = (0.0, 0.05, 0.1, 0.15)
LAM_TOL = 0.03                 # the tolerance used for the difference previews and the injection check
MATCH_PIX = 1.5
MJD_UNIX0 = 40587              # MJD of 1970-01-01
# one bright injected mover so the injection path can be eyeballed end-to-end: offset, rate ("/h), PA, AB, days
INJ_OFFSET, INJ_RATE, INJ_PA, INJ_MAG, INJ_ACTIVE = 0.05, 5.0, 60.0, 16.0, 1.5


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sxlib import detect, pipeline
    from sxlib.inject import LinearMover

    ap = argparse.ArgumentParser()
    ap.add_argument("--ra", type=float, default=178.6)
    ap.add_argument("--dec", type=float, default=1.1)
    ap.add_argument("--size", type=float, default=0.5)
    ap.add_argument("--out", default="outputs/probe")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    exps = pipeline.load_exposures(a.ra, a.dec, a.size)
    mjds = np.array([e.mjd for e in exps])
    mjd0 = float(mjds[np.argmin(np.abs(mjds - np.median(mjds)))])
    m = LinearMover(a.ra + INJ_OFFSET, a.dec - INJ_OFFSET, mjd0, INJ_RATE, INJ_PA, INJ_MAG, active_days=INJ_ACTIVE)
    truth = []
    f = pipeline.build_field(exps, a.ra, a.dec, a.size, movers=[m], truth_log=truth)
    n_exp = len(f.exps)
    print(f"field {f.shape}, {n_exp} exposures, detectors {np.bincount(f.det)}")
    print(f"passes (month): {sorted(set(np.datetime_as_string(np.array(f.mjd - MJD_UNIX0, 'datetime64[D]'), 'M')))}")
    rep = {"n_exp": n_exp, "tol": {}}
    for tol in LAM_TOLS:
        n = np.array([float(np.median(f.reference(i, lam_tol=tol)[2])) for i in range(0, n_exp, 5)])
        rep["tol"][tol] = {"median_nref": float(np.median(n)), "frac_nref_ge2": float(np.mean(n >= 2))}
        print(f"lam_tol={tol:.2f}: median refs/pixel={np.median(n):.1f}, exposures with >=2 refs: {np.mean(n >= 2):.0%}")

    for eps in EPS_VALUES:
        res = pipeline.detect_all(f, with_stamps=False, ref_kw={"lam_tol": LAM_TOL, "eps": eps})
        nc = [len(r["cands"]) for r in res]
        rep[f"cands_per_exp_eps{eps}"] = float(np.median(nc))
        print(f"eps={eps}: candidates/exposure median {np.median(nc)}, total {sum(nc)}")

    diffs = {}                 # difference images reused by the injection check and the previews

    def diff(i):
        if i not in diffs:
            diffs[i] = f.difference(i, lam_tol=LAM_TOL)
        return diffs[i]

    alphas = [diff(i)["alpha"] for i in range(0, n_exp, 7)]
    print(f"alpha: median {np.median(alphas):.3f}, 5-95% {np.percentile(alphas, 5):.3f}-{np.percentile(alphas, 95):.3f}")
    # injected recovery
    index = {}
    for k, e in enumerate(f.exps):
        index.setdefault((e["obs_id"], e["detector"]), k)
    hit = n_in = 0
    for t in truth:
        i = index.get((t["obs_id"], t["detector"]))
        if i is None:
            continue
        x, y = f.world_to_pix(t["ra"], t["dec"])
        ix, iy = int(round(float(x))), int(round(float(y)))
        if not (0 <= ix < f.shape[1] and 0 <= iy < f.shape[0]) or f.bad[i, iy, ix]:
            continue
        n_in += 1
        d = diff(i)
        c = pipeline.detect.find_candidates(d)
        ok = bool((detect.match(c, [float(x)], [float(y)], MATCH_PIX) >= 0).any()) if c else False
        hit += ok
        print(f"   inj {t['obs_id']} D{t['detector']} snr_at_truth={np.nanmax(d['snr'][iy - 1:iy + 2, ix - 1:ix + 2]):.1f} found={ok}")
    rep["injected_exposures_in_field"], rep["injected_recovered"] = n_in, int(hit)
    print(f"injected mover (AB 16, 5\"/h): recovered in {hit}/{n_in} in-field exposures")
    write_json(out / "probe.json", rep)

    keys = {(t["obs_id"], t["detector"]) for t in truth}
    inj_idx = [k for k, e in enumerate(f.exps) if (e["obs_id"], e["detector"]) in keys]
    idx = inj_idx[:3] + list(range(0, n_exp, max(1, n_exp // 3)))[:3]
    fig, ax = plt.subplots(len(idx), 3, figsize=(9, 3 * len(idx)), squeeze=False)
    for r, i in enumerate(idx):
        d = diff(i)
        res_i = pipeline.detect.find_candidates(d)
        e = f.exps[i]
        for c, (im, title) in enumerate([(f.img[i], "science"), (d["ref"], f"ref (n~{np.median(d['nref']):.0f})"),
                                         (d["snr"], "S/N diff")]):
            v = np.nanpercentile(np.abs(im), 99.5) if c < 2 else 8
            ax[r, c].imshow(im, origin="lower", cmap="gray" if c < 2 else "RdBu_r",
                            vmin=-v * (0.1 if c < 2 else 1), vmax=v)
            ax[r, c].set_title(f"{title}  {e['obs_id']} D{e['detector']} {e['lam_um']:.2f}um", fontsize=6)
            ax[r, c].axis("off")
        for t in truth:
            if t["obs_id"] == e["obs_id"] and t["detector"] == e["detector"]:
                x, y = f.world_to_pix(t["ra"], t["dec"])
                ax[r, 2].add_patch(plt.Circle((float(x), float(y)), 9, fill=False, color="magenta", lw=1))
        for c in res_i:
            ax[r, 2].add_patch(plt.Circle((c["x"], c["y"]), 4, fill=False, color="lime", lw=0.5))
    fig.savefig(out / "diffs.png", dpi=140, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
