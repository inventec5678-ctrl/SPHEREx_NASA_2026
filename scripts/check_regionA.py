"""Monte Carlo check of the effective stacked limit in region A (Galactic-plane crossing), for the referee.
Injects distant bodies of AB 17.5-20 at 500 and 1500 au (circular-orbit drift) into the three region-A survey fields,
runs the same stack + link + confirm search, and records each recovered body's stacked significance (mean over its
stacked peaks, the statistic used for chance tracks). Completeness is reported for the nominal threshold (7) and for
the region's largest chance-track significance. Also reports the fraction of pixels where eps*R exceeds the exposure
noise in these crowded fields.  python scripts/check_regionA.py   -> paper_aas/regionA_mc.json"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PAPER_AAS, write_json  # noqa: E402
import stack_grid as sg  # noqa: E402

MAG_GRID = [17.5, 18.0, 18.5, 19.0, 19.5, 20.0]
D_GRID = [500.0, 1500.0]
FIELDS = [("svA_075", 75.0, 16.666666666666668), ("svA_076", 76.5, 17.166666666666668),
          ("svA_078", 78.0, 17.666666666666668)]
SEEDS = (11, 12, 13)
S_MAX = 14.1                # the region's largest chance-track significance
EPS = 0.1
EPS_STRIDE = 10             # every 10th raw exposure for the eps*R statistic
MIN_PIXELS = 1000
PROCS = 3


def eps_fraction(exps):
    """eps*R > sigma from the raw cutouts (single exposures as a proxy for the reference)."""
    fr = []
    for e in exps[::EPS_STRIDE]:
        ok = np.isfinite(e.img) & np.isfinite(e.var) & (e.var > 0)
        if ok.sum() > MIN_PIXELS:
            im = e.img[ok]
            fr.append(float(np.mean(EPS * (im - np.nanmedian(im)) > np.sqrt(e.var[ok]))))
    return fr


def run(name, ra0, dec0, seed):
    from sxlib import pipeline
    rng = np.random.default_rng(seed)
    exps = pipeline.load_exposures(ra0, dec0, sg.SIZE, workers=sg.LOAD_WORKERS, log=sg._quiet)
    fr = eps_fraction(exps)
    bodies = sg.place(rng, ra0, dec0, np.array([e.mjd for e in exps]), d_grid=D_GRID, mag_grid=MAG_GRID)
    f = sg.injected_field(exps, ra0, dec0, bodies)
    del exps
    r = sg.search_field(f)
    mean_snr = lambda t: float(np.mean([r["peaks"][m]["snr"] for m in t["members"]]))  # noqa: E731
    out, used = [], set()
    for b in bodies:
        best = sg.best_track(r, b)
        s = None
        if best:
            used.add(best[0])
            s = mean_snr(r["tracks"][best[0]])
        out.append({"d_au": b.d, "mag": b.mag, "recovered": bool(best), "s_stack": s})
    others = [mean_snr(t) for k, t in enumerate(r["tracks"]) if k not in used]
    print(f"[{name} seed {seed}] {sum(o['recovered'] for o in out)}/{len(out)} recovered, {len(others)} other tracks "
          f"(max S {max(others) if others else 0:.1f}), eps*R>sigma {100 * np.median(fr):.1f}%", flush=True)
    return {"field": name, "seed": seed, "bodies": out, "other_tracks_s": others, "epsR_frac": fr}


def main():
    jobs = [(n, r, d, s) for (n, r, d) in FIELDS for s in SEEDS]
    with ProcessPoolExecutor(PROCS) as ex:
        res = list(ex.map(run, *zip(*jobs)))
    write_json(PAPER_AAS / "regionA_mc.json", res)
    B = [b for r in res for b in r["bodies"]]
    for mag in MAG_GRID:
        bb = [b for b in B if b["mag"] == mag]
        c7 = np.mean([b["recovered"] for b in bb])
        cs = np.mean([b["recovered"] and b["s_stack"] > S_MAX for b in bb])
        print(f"AB {mag}: n={len(bb)} completeness {c7:.2f} (S>=7), {cs:.2f} (S>{S_MAX})")
    print("eps*R>sigma, region A: median %.1f%%" % (100 * np.median([x for r in res for x in r["epsR_frac"]])))


if __name__ == "__main__":
    main()
