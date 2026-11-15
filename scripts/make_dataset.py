"""Build the real/bogus training set.

For each field: fetch all SPHEREx exposures (all survey passes), inject synthetic movers
with the exposure PSF, difference every exposure against wavelength-matched references,
detect candidates, and label them:
  1 / "inj"    - within 1.5 px of an injected mover in that exposure
  1 / "known"  - within 1.5 px of a known asteroid/comet (JPL sb_ident, propagated)
  0 / "bogus"  - everything else (star residuals, artifacts, noise)
Also stores the per-exposure injection truth with a "detected by stage-1" flag, which
feeds the injection-recovery analysis.

  python scripts/make_dataset.py --fields fields.json --out data/ds --procs 4

process_field() is reused by scripts/known_benchmark.py.
"""
import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, read_json, write_json  # noqa: E402
from sxlib import detect, pipeline  # noqa: E402
from sxlib.inject import random_movers  # noqa: E402

REF_KW = {"lam_tol": 0.03, "eps": 0.1}
KNOWN_VMAX = 18.5               # known objects fainter than this are not labelled real in one exposure
MATCH_PX = 1.5
EDGE_PX = 11                    # injections closer than this to the edge have no full stamp
MIN_EXPOSURES = 20
INJ_MAG_RANGE = (14.0, 21.5)
INJ_RATE_RANGE = (1.0, 150.0)
SRC_CODE = {"inj": 0, "known": 1, "bogus": 2}
META_DTYPE = [("exp", "i4"), ("x", "f4"), ("y", "f4"), ("snr", "f4"), ("mjd", "f8"), ("det", "i2"), ("lam", "f4"),
              ("src", "i1"), ("mag", "f4"), ("rate", "f4"), ("mover", "i4")]


def default_fields():
    """Ecliptic belt every 30 deg in longitude (+ a few at |beta|~12 deg)."""
    import astropy.units as u
    from astropy.coordinates import GeocentricTrueEcliptic, SkyCoord
    out = [(lon, 0.0 if k % 2 == 0 else 3.0) for k, lon in enumerate(range(0, 360, 30))]
    out += [(45, 12.0), (165, -12.0), (225, 12.0), (315, -12.0)]
    fields = []
    for lon, lat in out:
        c = SkyCoord(lon * u.deg, lat * u.deg, frame=GeocentricTrueEcliptic).icrs
        fields.append({"name": f"ecl{lon:03d}{'+' if lat >= 0 else '-'}{abs(int(lat)):02d}",
                       "ra": round(float(c.ra.deg), 4), "dec": round(float(c.dec.deg), 4)})
    return fields


def known_positions(field, half_width):
    from sxlib.known import known_for_field
    pos, bodies = known_for_field(field, half_width, kinds=("a",), log=lambda m: None)
    return {i: [(n, ra, dec, bodies[n]["V"]) for n, ra, dec in v] for i, v in pos.items()}, \
        {n: b["V"] for n, b in bodies.items()}


def _pix(f, ras, decs):
    """Field pixel positions of many sky positions in one WCS call (empty-safe)."""
    if not len(ras):
        return np.zeros(0), np.zeros(0)
    x, y = f.world_to_pix(np.asarray(ras, float), np.asarray(decs, float))
    return np.atleast_1d(np.asarray(x, float)), np.atleast_1d(np.asarray(y, float))


def process_field(fd, out_dir, size, n_linear, n_distant, seed):
    t0 = time.time()
    name = fd["name"]
    dest = Path(out_dir) / f"{name}.npz"
    if dest.exists():
        return name, "exists"
    rng = np.random.default_rng(seed)
    exps = pipeline.load_exposures(fd["ra"], fd["dec"], size, workers=6, mjd_range=fd.get("mjd_range"),
                                   log=lambda s: print(f"[{name}] {s}", flush=True))
    if len(exps) < MIN_EXPOSURES:
        return name, f"too few exposures ({len(exps)})"
    from sxlib.stack import Field
    probe = Field(fd["ra"], fd["dec"], size)
    mjds = np.array([e.mjd for e in exps])
    movers = random_movers(rng, probe, mjds, n_linear, n_distant, mag_range=INJ_MAG_RANGE, rate_range=INJ_RATE_RANGE) \
        if n_linear + n_distant else []
    # keep linear movers inside the field for a sensible number of exposures
    for m in movers:
        if m.kind == "linear":
            m.active = float(min(4.0, 0.6 * size * 3600 / m.rate / 24))
    truth = []
    f = pipeline.build_field(exps, fd["ra"], fd["dec"], size, movers=movers or None, truth_log=truth)
    del exps
    print(f"[{name}] field built: {len(f.exps)} exposures, {len(truth)} injected placements", flush=True)
    known, bodies = known_positions(f, size / 2 + 0.02)
    print(f"[{name}] {len(bodies)} known small bodies (V<=21.5)", flush=True)

    truth_by_exp = {}
    for t in truth:
        truth_by_exp.setdefault((t["obs_id"], t["detector"]), []).append(t)

    ny, nx = f.shape[0], f.shape[1]
    S, Y, META, TRUTH = [], [], [], []
    for i, e in enumerate(f.exps):
        d = f.difference(i, **REF_KW)
        cands = detect.find_candidates(d)
        # injection truth in this exposure (only where the field grid is valid)
        tr = truth_by_exp.get((e["obs_id"], e["detector"]), [])
        xs, ys = _pix(f, [t["ra"] for t in tr], [t["dec"] for t in tr])
        tx, ty, tm = [], [], []
        for t, x, y in zip(tr, xs, ys):
            ix, iy = int(round(float(x))), int(round(float(y)))
            if EDGE_PX <= ix < nx - EDGE_PX and EDGE_PX <= iy < ny - EDGE_PX and d["valid"][iy, ix]:
                tx.append(float(x)); ty.append(float(y)); tm.append(t["mover"])
        kn = known[i]
        kx, ky = _pix(f, [k[1] for k in kn], [k[2] for k in kn])
        kv = [k[3] for k in kn]
        mi = detect.match(cands, tx, ty, MATCH_PX) if cands else np.array([], int)
        # only known objects bright enough for a single SPHEREx exposure count as real labels
        kok = [j for j, v in enumerate(kv) if np.isfinite(v) and v <= KNOWN_VMAX]
        mk = detect.match(cands, [float(kx[j]) for j in kok], [float(ky[j]) for j in kok], MATCH_PX) if cands else np.array([], int)
        mk = np.array([kok[j] if j >= 0 else -1 for j in mk], int)
        hit = {int(j) for j in mi if j >= 0}
        for j, (x, y, mv) in enumerate(zip(tx, ty, tm)):
            m = movers[mv]
            ix, iy = int(round(x)), int(round(y))
            TRUTH.append({"exp": i, "mover": mv, "kind": m.kind, "mag": m.mag,
                          "rate": getattr(m, "rate", 0.0), "d_au": getattr(m, "d", 0.0),
                          "snr_peak": float(np.nanmax(d["snr"][iy - 1:iy + 2, ix - 1:ix + 2])),
                          "detected": j in hit, "cand": int(np.flatnonzero(mi == j)[0]) if j in hit else -1,
                          "lam_um": e["lam_um"], "detector": e["detector"]})
        if not cands:
            continue
        st = detect.stamps(f, i, d, cands)
        for k, c in enumerate(cands):
            if mi[k] >= 0:
                m = movers[tm[mi[k]]]
                y, src, mag, rate = 1, "inj", m.mag, getattr(m, "rate", 0.0)
            elif mk[k] >= 0:
                y, src, mag, rate = 1, "known", kv[mk[k]], 0.0
            else:
                y, src, mag, rate = 0, "bogus", np.nan, 0.0
            Y.append(y)
            META.append((i, c["x"], c["y"], c["snr"], e["mjd"], e["detector"], e["lam_um"],
                         SRC_CODE[src], mag, rate, tm[mi[k]] if mi[k] >= 0 else -1))
        S.append(st.astype(np.float16))
    S = np.concatenate(S) if S else np.zeros((0, len(detect.CHANNELS), detect.STAMP, detect.STAMP), np.float16)
    meta = np.array(META, dtype=META_DTYPE)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dest, stamps=S, y=np.array(Y, np.int8), meta=meta,
                        truth=json.dumps(TRUTH), movers=json.dumps([m.describe() for m in movers]),
                        exps=json.dumps(f.exps), field=json.dumps({**fd, "size": size, "known": bodies}))
    n_pos = int(np.sum(Y)); n_known = int(np.sum(meta["src"] == 1)) if len(meta) else 0
    msg = (f"{len(Y)} cands ({n_pos} real: {n_pos - n_known} inj, {n_known} known), "
           f"stage-1 recall {np.mean([t['detected'] for t in TRUTH]) if TRUTH else float('nan'):.2f}, "
           f"{time.time() - t0:.0f}s")
    print(f"[{name}] DONE {msg}", flush=True)
    return name, msg


def main():
    ap = argparse.ArgumentParser(description="Build the real/bogus training set")
    ap.add_argument("--fields", help="JSON list of {name, ra, dec}; default ecliptic belt")
    ap.add_argument("--out", default=str(ROOT / "data" / "ds"))
    ap.add_argument("--size", type=float, default=0.5)
    ap.add_argument("--n-linear", type=int, default=60)
    ap.add_argument("--n-distant", type=int, default=3)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    fields = read_json(a.fields) if a.fields else default_fields()
    write_json(Path(a.out) / "fields.json", fields)
    with ProcessPoolExecutor(a.procs) as ex:
        futs = {ex.submit(process_field, fd, a.out, a.size, a.n_linear, a.n_distant, 1000 + k): fd["name"]
                for k, fd in enumerate(fields)}
        for fu in futs:
            try:
                print("RESULT", *fu.result(), flush=True)
            except Exception:  # noqa: BLE001
                print("FAILED", futs[fu], traceback.format_exc(), flush=True)


if __name__ == "__main__":
    main()
