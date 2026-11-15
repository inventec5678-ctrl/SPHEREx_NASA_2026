"""Validate the automatic proper-motion search on known high-proper-motion stars.

  python scripts/validate_pm.py [--n 60] [--per-pass 18]

Draws Gaia DR3 stars (9 < G < 16) at random over the sky in three proper-motion strata, and for each one:
  - downloads a small subset of SPHEREx cutouts (a few per detector per survey pass) of a 0.15 deg field,
  - builds per-pass, per-detector median stacks exactly as the field lab does,
  - runs sxlib.pmsearch.search blind (catalogues only label the result afterwards): is the star recovered?
  - fits the star directly at its predicted positions: measured vs predicted displacement (proper motion + parallax).
Results go to outputs/pm_validation.json (rewritten after every star, so the run can be watched or resumed).

stacks_of() and _safe() are reused by scripts/byw_validate.py.
"""
import argparse
import shutil
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, ROOT, read_json, write_json  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)
OUT = OUTPUTS / "pm_validation.json"
TMP = ROOT / "var" / "valcache"
SIZE = 0.15                     # field side (deg)
PIX_ARCSEC = 6.15               # SPHEREx pixel scale
N_DET = 6
MATCH_PX = 2.0                  # a candidate within this of the predicted first-pass position is the star
FIT_BANDS = (0, 5, 6)           # bands tried in turn for the direct position fit
MIN_EXPOSURES = 6
DOWNLOAD_THREADS = 8


def sample(n):
    from sxlib import gaia                  # ESA's Gaia archive, MAST as the fallback
    strata = [(500, 1000, n // 3), (1000, 2000, n // 3), (2000, 12000, n - 2 * (n // 3))]
    rows = []
    for lo, hi, k in strata:
        q = (f"SELECT TOP {k} source_id, ra, dec, pmra, pmdec, parallax, pm, phot_g_mean_mag FROM gaiadr3.gaia_source "
             f"WHERE pm BETWEEN {lo} AND {hi} AND phot_g_mean_mag BETWEEN 9 AND 16 AND parallax > 0 "
             f"AND random_index < 1800000000 ORDER BY random_index")
        rows += gaia.query(q)
    return [{"id": r["source_id"], "ra": float(r["ra"]), "dec": float(r["dec"]), "pmra": float(r["pmra"]), "pmdec": float(r["pmdec"]),
             "plx": float(r["parallax"]), "pm": float(r["pm"]) / 1000, "g": float(r["phot_g_mean_mag"]), "epoch": 2016.0} for r in rows]


def stacks_of(f):
    """Per-pass median stacks [P, 7, n, n] (band 0 = all detectors, 1..6 = one detector) and pass mid-times."""
    from sxlib.products import passes_of
    lab = passes_of(f.mjd)
    P, n = int(lab.max()) + 1, f.shape[0]
    st = np.full((P, N_DET + 1, n, n), np.nan, np.float32)
    img = np.where(f.bad, np.nan, f.img)
    mid = []
    with np.errstate(all="ignore"):
        for p in range(P):
            sel = lab == p
            st[p, 0] = np.nanmedian(img[sel], axis=0)
            for d in range(1, N_DET + 1):
                s2 = sel & (f.det == d)
                if s2.any():
                    st[p, d] = np.nanmedian(img[s2], axis=0)
            mid.append(float(np.median(f.mjd[sel])))
    return st, mid


def _pick(metas, lab, per_pass):
    """Up to ``per_pass`` exposures per pass, round-robin over detectors (middle one first, then from both ends)."""
    pick = []
    for p in np.unique(lab):
        by = {}
        for m, l in zip(metas, lab):
            if l == p:
                by.setdefault(m["detector"], []).append(m)
        k = n_p = 0
        while n_p < per_pass and any(by.values()):
            for d in sorted(by):
                g = by[d]
                if g:
                    pick.append((g.pop(len(g) // 2 if k == 0 else (0 if k % 2 else -1)), p)); n_p += 1
            k += 1
    return pick


def one(star, per_pass, log):
    from sxlib import archive
    from sxlib.pmsearch import fit_position, search
    from sxlib.products import overlays, passes_of
    from sxlib.stack import Field
    from sxlib.targets import centre_2026, position_at
    ra0, dec0 = centre_2026(star)
    metas = archive.search_images(ra0, dec0)
    if not metas:
        return {"skip": "no_data"}
    pick = _pick(metas, passes_of(np.array([m["mjd"] for m in metas])), per_pass)
    if len({p for _, p in pick}) < 2:
        return {"skip": "one_pass"}
    tmp = TMP / str(star["id"])
    with ThreadPoolExecutor(DOWNLOAD_THREADS) as ex:
        exps = [e for e in ex.map(lambda m: _safe(archive.fetch_cutout, m[0], ra0, dec0, SIZE * 1.5, False, tmp), pick) if e is not None]
    shutil.rmtree(tmp, ignore_errors=True)
    f = Field(ra0, dec0, SIZE)
    for e in exps:
        f.add(e)
    if len(f.exps) < MIN_EXPOSURES:
        return {"skip": "too_few_exposures"}
    f.freeze()
    st, mid = stacks_of(f)
    if len(mid) < 2:
        return {"skip": "one_pass"}
    ov = overlays(f, log=lambda m: None)
    res = search(st, mid, ov, cdelt=list(map(float, f.wcs.wcs.cdelt)), log=lambda m: None)
    # where Gaia (+ parallax) says the star is in the first and last pass
    ra_p, dec_p = position_at(star, np.array([mid[0], mid[-1]]))
    (xa, xz), (ya, yz) = f.world_to_pix(ra_p, dec_p)
    pred = np.array([xz - xa, yz - ya])
    hit = min(res["candidates"], key=lambda c: np.hypot(c["x"] - xa, c["y"] - ya), default=None)
    found = hit is not None and np.hypot(hit["x"] - xa, hit["y"] - ya) <= MATCH_PX
    direct = None
    for b in FIT_BANDS:
        fa, fz = fit_position(st[0, b], xa, ya), fit_position(st[-1, b], xz, yz)
        if fa and fz:
            meas = np.array([fz[0] - fa[0], fz[1] - fa[1]]) - np.array(res["stats"]["per_band"][0].get("offset_px", [0, 0]))
            direct = {"band": b, "meas_px": [round(float(v), 3) for v in meas], "err_px": round(float(np.hypot(fa[2], fz[2])), 3),
                      "resid_arcsec": round(float(np.linalg.norm(meas - pred) * PIX_ARCSEC), 3)}
            break
    return {"n_exp": len(f.exps), "n_pass": len(mid), "dt_yr": round((mid[-1] - mid[0]) / 365.25, 3),
            "pred_px": [round(float(v), 3) for v in pred], "pred_arcsec": round(float(np.linalg.norm(pred) * PIX_ARCSEC), 3),
            "found": bool(found), "status": hit["status"] if found else None,
            "meas_pm": hit["pm_arcsec_yr"] if found else None, "sig": hit["sig"] if found else None,
            "n_other_candidates": len(res["candidates"]) - (1 if found else 0),
            "n_new_other": sum(1 for c in res["candidates"] if c["status"] == "new" and not (found and c is hit)),
            "floor_px": res["stats"].get("floor_px"), "direct": direct}


def _safe(fn, *a):
    """fn(*a), or None when it raises (one failed download must not stop a star)."""
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description="Validate the proper-motion search on random Gaia high-PM stars")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--per-pass", type=int, default=18)
    ap.add_argument("--out", default=str(OUT), help="result file (resumed if it exists)")
    ap.add_argument("--stars-from", help="re-test the stars of an earlier result file (e.g. on a new data release)")
    a = ap.parse_args()
    out = Path(a.out)
    done = read_json(out, {"stars": []})
    if not done["stars"]:
        src = read_json(a.stars_from)["stars"] if a.stars_from else None
        done["stars"] = [{"star": r["star"]} for r in src] if src else [{"star": s} for s in sample(a.n)]
    for k, rec in enumerate(done["stars"]):
        if "result" in rec:
            continue
        t0 = time.time()
        try:
            rec["result"] = one(rec["star"], a.per_pass, print)
        except Exception as e:  # noqa: BLE001
            rec["result"] = {"skip": f"error: {str(e)[:120]}"}
        rec["seconds"] = round(time.time() - t0, 1)
        r = rec["result"]
        verdict = r.get("skip") or ("FOUND " + str(r["status"]) if r["found"] else "missed")
        resid = "" if r.get("skip") or not r.get("direct") else f"resid {r['direct']['resid_arcsec']}\""
        print(f"{k + 1}/{len(done['stars'])} G={rec['star']['g']:.1f} pm={rec['star']['pm']:.2f}\"/yr -> "
              f"{verdict} {resid} ({rec['seconds']}s)", flush=True)
        done["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_json(out, done, atomic=True)
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
