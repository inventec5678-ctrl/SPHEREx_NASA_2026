"""Depth of the shift-and-stack search: inject faint distant bodies (with orbital motion) into real fields
the CNN never trained on, stack, link, and count recoveries and false tracks.

  python scripts/stack_grid.py --out paper_evidence/stack_grid.json

Also the engine of scripts/check_regionA.py (place, injected_field, search_field, best_track).
"""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write_json  # noqa: E402
from sxlib import pipeline, shiftstack  # noqa: E402
from sxlib.analyze import REF_KW  # noqa: E402
from sxlib.inject import DistantBody  # noqa: E402
from sxlib.link import _tangent, circular_pm  # noqa: E402

D_GRID = [150.0, 500.0, 1500.0]
MAG_GRID = [18.0, 18.5, 19.0, 19.5, 20.0, 20.5]
SIZE = 0.5
FIELDS = [("ecl180+00", 180.0026, -0.0011), ("ecl060+00", 57.8182, 20.1502),
          ("ecl315-12", 321.4222, -27.7638)]   # three passes each
SEED0 = 9000
THRESH = 7.0                # stacked S/N threshold
MATCH_ARCSEC = 10.0         # a track member is the body's if within 10" of it at the member's time
MIN_HITS = 2
LOAD_WORKERS = 6
SKY_STRIDE = 8              # every 8th exposure for the median sky image
_quiet = lambda s: None     # noqa: E731


def place(rng, ra0, dec0, mjds, margin=0.04, d_grid=None, mag_grid=None):
    """One body per (distance, magnitude), placed at random so its whole path stays inside the field."""
    out, cosd, half = [], np.cos(np.radians(dec0)), SIZE / 2 - margin
    t0 = float(np.median(mjds))
    for d in d_grid or D_GRID:
        for mag in mag_grid or MAG_GRID:
            pa = rng.uniform(0, 2 * np.pi)
            pm = (circular_pm(d) * np.sin(pa), circular_pm(d) * np.cos(pa))
            ra, dec = DistantBody(ra0, dec0, d, mag, t0, pm_arcsec_yr=pm).position(mjds)
            dx, dy = (ra - ra0) * cosd, dec - dec0
            lo_x, hi_x, lo_y, hi_y = -half - dx.min(), half - dx.max(), -half - dy.min(), half - dy.max()
            if lo_x > hi_x or lo_y > hi_y:
                continue
            ox, oy = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
            out.append(DistantBody(ra0 + ox / cosd, dec0 + oy, d, mag, t0, pm_arcsec_yr=pm))
    return out


def injected_field(exps, ra0, dec0, bodies):
    return pipeline.build_field(exps, ra0, dec0, SIZE, movers=bodies, truth_log=[])


def search_field(f, thresh=THRESH):
    """Difference every exposure, then run the stack + link + confirm search on the S/N cube."""
    snr = np.stack([np.nan_to_num(f.difference(i, **REF_KW)["snr"]).astype(np.float32) for i in range(len(f.exps))])
    sci_med = np.nanmedian(f.img[::SKY_STRIDE], 0)
    sci_med = np.nan_to_num(np.arcsinh(sci_med / (3 * np.nanmedian(np.sqrt(f.var[::SKY_STRIDE]))))
                            / np.arcsinh(300) * 255)
    w = f.wcs.wcs
    return shiftstack.search_arrays([{"mjd": float(m)} for m in f.mjd],
                                    {"crval": list(w.crval), "crpix": list(w.crpix), "cdelt": list(w.cdelt)},
                                    snr, sci_med, thresh=thresh, log=_quiet)


def best_track(r, b):
    """(track index, hits) of the track with the most members within MATCH_ARCSEC of body b (at least MIN_HITS),
    or None. The body's ephemeris is evaluated once for all peaks (one astropy call instead of one per member)."""
    peaks = r["peaks"]
    if not peaks or not r["tracks"]:
        return None
    mjd = np.array([p["mjd"] for p in peaks])
    bra, bdec = (np.atleast_1d(v) for v in b.position(mjd))
    x, y = _tangent(np.array([p["ra"] for p in peaks]), np.array([p["dec"] for p in peaks]), bra, bdec)
    near = np.hypot(x, y) <= MATCH_ARCSEC
    best = None
    for k, t in enumerate(r["tracks"]):
        hits = int(sum(near[m] for m in t["members"] if m < len(peaks)))
        if hits >= MIN_HITS and (best is None or hits > best[1]):
            best = (k, hits)
    return best


def run(name, ra0, dec0, seed):
    rng = np.random.default_rng(seed)
    exps = pipeline.load_exposures(ra0, dec0, SIZE, workers=LOAD_WORKERS, log=_quiet)
    bodies = place(rng, ra0, dec0, np.array([e.mjd for e in exps]))
    f = injected_field(exps, ra0, dec0, bodies)
    del exps
    r = search_field(f)
    out, used = [], set()
    for b in bodies:
        best = best_track(r, b)
        if best:
            used.add(best[0])
        t = r["tracks"][best[0]] if best else None
        out.append({"d_au": b.d, "mag": b.mag, "recovered": bool(best), "d_fit": t["d_au"] if t else None,
                    "d_err_pct": round(100 * abs(t["d_au"] - b.d) / b.d, 2) if t else None})
    nf = len(r["tracks"]) - len(used)
    print(f"[{name}] {sum(o['recovered'] for o in out)}/{len(out)} recovered by stacking, {nf} false tracks, "
          f"mask {r['masked_fraction']:.3f}", flush=True)
    return {"field": name, "bodies": out, "false_tracks": nf, "n_tracks": len(r["tracks"]),
            "masked_fraction": r["masked_fraction"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="paper_evidence/stack_grid.json")
    ap.add_argument("--procs", type=int, default=3)
    a = ap.parse_args()
    jobs = [(n, r, d, SEED0 + k) for k, (n, r, d) in enumerate(FIELDS)]
    with ProcessPoolExecutor(a.procs) as ex:
        res = list(ex.map(run, *zip(*jobs)))
    bodies = [b for r in res for b in r["bodies"]]
    table = []
    for mag in MAG_GRID:
        bb = [b for b in bodies if b["mag"] == mag]
        rec = [b["d_err_pct"] for b in bb if b["recovered"]]
        table.append({"mag": mag, "n": len(bb), "recovered": len(rec),
                      "median_d_err_pct": float(np.median(rec)) if rec else None})
    out = {"fields": [f[0] for f in FIELDS], "d_grid": D_GRID, "mag_grid": MAG_GRID, "table": table, "per_field": res,
           "false_tracks_total": sum(r["false_tracks"] for r in res),
           "note": "faint distant bodies with circular-orbit motion injected into 3-pass fields; "
                   "shift-and-stack per pass + parallax/orbit linking"}
    write_json(a.out, out)
    print(json.dumps(table, indent=1))


if __name__ == "__main__":
    main()
