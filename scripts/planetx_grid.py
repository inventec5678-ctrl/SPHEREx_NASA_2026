"""Planet X injection grid (paper Table: recovery vs distance x magnitude).

Injects one simulated distant body per (distance, magnitude) cell into each of 5 fields the
CNN never trained on, runs the full pipeline (difference -> detect -> CNN -> distant-first linking)
and checks, per body, whether a distant-body track recovers it and how close the fitted distance is.

  python scripts/planetx_grid.py --out paper_evidence/planetx_grid.json
"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, PAPER_EVIDENCE, write_json  # noqa: E402
from sxlib import detect, pipeline  # noqa: E402
from sxlib.analyze import P_LINK, REF_KW, build_tracks  # noqa: E402
from sxlib.inject import DistantBody  # noqa: E402
from sxlib.link import circular_pm  # noqa: E402
from sxlib.stack import FEAT_OUTLIER  # noqa: E402

D_GRID = [500.0, 800.0, 1500.0, 3000.0]
MAG_GRID = [15.0, 16.0, 17.0]
SIZE = 0.5
P_KEEP = 0.05                   # candidates below this CNN probability are not kept for linking
MATCH_PX = 1.5                  # a candidate this close to an injected position belongs to that body
PASS_GAP_DAYS = 40              # a gap longer than this starts a new survey pass
FIELDS = [  # validation/test fields + the demo patch: none were used to train the CNN
    ("ecl180+00", 180.0026, -0.0011), ("ecl060+00", 57.8182, 20.1502), ("ecl120+00", 122.1796, 20.1507),
    ("ecl315-12", 321.4222, -27.7638), ("demo181.6", 181.6, -0.4)]


def place_bodies(rng, ra0, dec0, mjds, margin=0.03):
    """One body per grid cell, placed so its whole parallax path stays inside the field."""
    bodies = []
    half = SIZE / 2 - margin
    cosd = np.cos(np.radians(dec0))
    for d in D_GRID:
        for mag in MAG_GRID:
            # each body moves on a circular orbit in a random direction (its own motion is comparable to
            # the parallax at these distances, so leaving it out would make the test circular)
            pa = rng.uniform(0, 2 * np.pi)
            pm = (circular_pm(d) * np.sin(pa), circular_pm(d) * np.cos(pa))
            probe = DistantBody(ra0, dec0, d, mag, float(np.median(mjds)), pm_arcsec_yr=pm)
            ra, dec = probe.position(mjds)
            dx = (ra - ra0) * cosd; dy = dec - dec0
            lo_x, hi_x = -half - dx.min(), half - dx.max()
            lo_y, hi_y = -half - dy.min(), half - dy.max()
            if lo_x > hi_x or lo_y > hi_y:
                continue
            ox, oy = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
            bodies.append(DistantBody(ra0 + ox / cosd, dec0 + oy, d, mag, float(np.median(mjds)), pm_arcsec_yr=pm))
    return bodies


def run_field(name, ra0, dec0, seed, scorer_path):
    from sxlib.rbnet import Scorer
    scorer = Scorer(scorer_path)
    rng = np.random.default_rng(seed)
    exps = pipeline.load_exposures(ra0, dec0, SIZE, workers=6, log=lambda s: None)
    mjds = np.array([e.mjd for e in exps])
    bodies = place_bodies(rng, ra0, dec0, mjds)
    truth = []
    f = pipeline.build_field(exps, ra0, dec0, SIZE, movers=bodies, truth_log=truth)
    del exps
    cands = []
    for i in range(len(f.exps)):
        d = f.difference(i, **REF_KW)
        cs = detect.find_candidates(d)
        if not cs:
            continue
        p = scorer(detect.stamps(f, i, d, cs))
        for k, c in enumerate(cs):
            if p[k] < P_KEEP:
                continue
            cra, cdec = f.pix_to_world(c["x"], c["y"])
            cands.append({"id": len(cands), "i": i, "x": c["x"], "y": c["y"], "ra": float(cra), "dec": float(cdec),
                          "p": float(p[k]), "known": None, "track": None,
                          "l2": bool((f.feat[i, c["iy"] - 1:c["iy"] + 2, c["ix"] - 1:c["ix"] + 2] & FEAT_OUTLIER).any())})
    tracks = build_tracks(cands, f.mjd, log=lambda s: None)
    # truth per exposure index
    idx = {(e["obs_id"], e["detector"]): k for k, e in enumerate(f.exps)}
    tru = {}
    truth = [(t, idx[(t["obs_id"], t["detector"])]) for t in truth if (t["obs_id"], t["detector"]) in idx]
    if truth:
        xs, ys = f.world_to_pix(np.array([t["ra"] for t, _ in truth]), np.array([t["dec"] for t, _ in truth]))
        for (t, k), x, y in zip(truth, np.atleast_1d(xs), np.atleast_1d(ys)):
            x, y = float(x), float(y)
            if 0 <= x < f.shape[1] and 0 <= y < f.shape[0] and not f.bad[k, int(round(y)), int(round(x))]:
                tru.setdefault(k, []).append((t["mover"], x, y))
    owner = {}
    for c in cands:
        for mv, x, y in tru.get(c["i"], []):
            if np.hypot(c["x"] - x, c["y"] - y) <= MATCH_PX:
                owner[c["id"]] = mv
    out = []
    dist_tracks = [t for t in tracks if t["kind"] == "distant"]
    matched_tracks = set()
    for mv, b in enumerate(bodies):
        n_place = sum(1 for v in tru.values() for m, _, _ in v if m == mv)
        n_det = sum(1 for c in cands if owner.get(c["id"]) == mv and c["p"] >= P_LINK)
        best = None
        for t in dist_tracks:
            on = sum(1 for m in t["members"] if owner.get(m) == mv)
            if on >= 0.5 * len(t["members"]) and (best is None or on > best[1]):
                best = (t, on)
        rec = {"field": name, "d_au": b.d, "mag": b.mag, "placements": n_place, "detected_p_link": n_det,
               "recovered": bool(best), "d_fit": best[0]["d_au"] if best else None,
               "n_passes": best[0]["n_passes"] if best else 0, "members_on_body": best[1] if best else 0,
               "pm_true": [round(v, 1) for v in b.pm], "pm_fit": best[0].get("pm_arcsec_yr") if best else None}
        if best:
            matched_tracks.add(best[0]["id"])
            rec["d_err_frac"] = abs(best[0]["d_au"] - b.d) / b.d
        out.append(rec)
    false_tracks = [t for t in dist_tracks if t["id"] not in matched_tracks]
    print(f"[{name}] {sum(r['recovered'] for r in out)}/{len(out)} bodies recovered, "
          f"{len(false_tracks)} unmatched distant tracks", flush=True)
    n_passes = 1 + int((np.diff(np.sort(mjds)) > PASS_GAP_DAYS).sum())
    return {"field": name, "bodies": out, "n_distant_tracks": len(dist_tracks), "n_false_distant": len(false_tracks), "n_passes": n_passes}


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 3), round(c + h, 3)]


def main():
    ap = argparse.ArgumentParser(description="Planet X injection grid (recovery vs distance x magnitude)")
    ap.add_argument("--out", default=str(PAPER_EVIDENCE / "planetx_grid.json"))
    ap.add_argument("--procs", type=int, default=3)
    a = ap.parse_args()
    model = str(MODELS / "rb_cnn.pt")
    with ProcessPoolExecutor(a.procs) as ex:
        res = list(ex.map(run_field, *zip(*[(n, r, d, 7000 + k, model) for k, (n, r, d) in enumerate(FIELDS)])))
    bodies = [b for r in res for b in r["bodies"]]
    table = []
    for d in D_GRID:
        for m in MAG_GRID:
            cell = [b for b in bodies if b["d_au"] == d and b["mag"] == m]
            k = sum(b["recovered"] for b in cell)
            errs = [b["d_err_frac"] for b in cell if b["recovered"]]
            table.append({"d_au": d, "mag": m, "n": len(cell), "recovered": k, "rate": round(k / len(cell), 3) if cell else None,
                          "ci95": wilson(k, len(cell)), "median_d_err_pct": round(100 * float(np.median(errs)), 2) if errs else None,
                          "max_d_err_pct": round(100 * float(np.max(errs)), 2) if errs else None})
    doc = {"d_grid": D_GRID, "mag_grid": MAG_GRID, "fields": [f[0] for f in FIELDS], "field_size_deg": SIZE,
           "table": table, "per_field": res,
           "false_distant_tracks_total": sum(r["n_false_distant"] for r in res),
           "note": "One injected body per (distance, magnitude) cell per field; bodies placed so the whole "
                   "parallax path stays inside the 0.5 deg field. Recovery = a distant-body track whose members "
                   "are >=50% on that body. Fields were never used to train the CNN."}
    write_json(a.out, doc)
    for r in table:
        print(r)
    print("false distant tracks:", doc["false_distant_tracks_total"])


if __name__ == "__main__":
    main()
