"""Run the automatic proper-motion search on analysed fields: python scripts/pm_search.py [field ids...]

Writes web/data/fields/<id>/pm_candidates.json (served to the field lab and the candidate queue). Two stages
(sxlib/pmsearch.py, sxlib/xepoch.py): the pass-to-pass search inside SPHEREx's own year, and the cross-epoch search
against CatWISE2020 positions from 2015; every candidate then gets a joint proper-motion + parallax fit.

    python scripts/pm_search.py --validate      measure the cross-epoch stage against Gaia DR3 on every field
                                                (writes outputs/xepoch_validation.json; changes no field).

score_candidates() is also used by sxlib/products.py and sxlib/quicklook.py (``from scripts.pm_search import ...``).
"""
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, OUTPUTS, dumps, field_ids, read_json, write_json  # noqa: E402

MJD_TOL = 1e-6                  # pass window slack (days)
N_BANDS = 7                     # band 0 = all detectors, 1..6 = detector
STATIC_PM = 0.03                # arcsec/yr: Gaia stars treated as static for the injection test
STATIC_FLAG_PM = 0.05           # arcsec/yr: "static" bin for the false-alarm count
INJ_PM = (0.05, 0.08, 0.10, 0.15, 0.20, 0.30)
RECALL_BINS = [(0.15, 99.0), (0.10, 0.15), (0.05, 0.10)]


def load(fid):
    """(doc, stacks[P,7,n,n], pass mid-times, overlays, exposure times of each pass per band) of an analysed field."""
    out = FIELDS / fid
    doc = read_json(out / "field.json")
    pr = doc.get("products")
    if not pr or not (out / "pass" / "stacks.bin").exists():
        return None
    raw = (out / "pass" / "stacks.bin").read_bytes()
    P, B, n, _ = struct.unpack("<4i", raw[:16])
    st = np.frombuffer(raw[16:], np.float16).astype(np.float32).reshape(P, B, n, n)
    st[~np.isfinite(st)] = np.nan
    mjd = [(q["mjd0"] + q["mjd1"]) / 2 for q in pr["passes"]]
    ov = read_json(out / "overlays.json") if (out / "overlays.json").exists() else None
    e_mjd = np.array([e["mjd"] for e in doc["exposures"]], float)
    e_det = np.array([e["detector"] for e in doc["exposures"]])
    in_pass = [(e_mjd >= q["mjd0"] - MJD_TOL) & (e_mjd <= q["mjd1"] + MJD_TOL) for q in pr["passes"]]
    times = {b: [e_mjd[m if b == 0 else m & (e_det == b)].tolist() for m in in_pass] for b in range(N_BANDS)}
    return doc, st, mjd, ov, times


def run(fid, log=print):
    from sxlib.pmsearch import search_all
    out = FIELDS / fid
    got = load(fid)
    if got is None:
        log(f"{fid}: no pass stacks"); return None
    doc, st, mjd, ov, times = got
    t0 = time.time()
    res = search_all(st, mjd, ov, cdelt=doc["wcs"]["cdelt"], ra=doc["ra"], dec=doc["dec"], pass_times=times,
                     log=lambda m: log(f"{fid}{m}"))
    cands = res["candidates"]
    if cands:
        rd = _pix2world(doc["wcs"], [c["x"] for c in cands], [c["y"] for c in cands])
        for c, (ra, dec) in zip(cands, rd):
            c["ra"], c["dec"] = round(float(ra), 6), round(float(dec), 6)
    score_candidates(out, doc, cands, mjd)
    res.update(field=fid, created=time.strftime("%Y-%m-%dT%H:%M:%S"), seconds=round(time.time() - t0, 1),
               pass_mjd=[round(m, 3) for m in mjd])
    write_json(out / "pm_candidates.json", res, indent=None)
    return res


def score_candidates(out, doc, cands, pass_mjd):
    """Brown-dwarf spectral score along each candidate's track (sxlib/specclass.py)."""
    from sxlib.specclass import track_score
    cube = Path(out) / "cube"
    if not cands or not (cube / "img.npy").exists():
        return
    img, var, fl, lam = (np.load(cube / f"{k}.npy", mmap_mode="r") for k in ("img", "var", "flag", "lam"))
    lam_ds = doc["products"].get("lam_ds", 5)
    for c in cands:
        try:
            sc, n = track_score(img, var, fl, lam, lam_ds, doc["exposures"], c, pass_mjd)
        except Exception:  # noqa: BLE001
            sc, n = None, 0
        c["bd_score"] = None if sc is None else round(sc, 3)
        c["bd_points"] = n


def _pix2world(w, x, y):
    """Pixel -> (ra, dec) rows for arrays of positions, through the field's TAN WCS (one WCS for all points)."""
    from astropy.wcs import WCS
    wc = WCS(naxis=2)
    wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]; wc.wcs.crval = w["crval"]; wc.wcs.crpix = w["crpix"]; wc.wcs.cdelt = w["cdelt"]
    return wc.wcs_pix2world(np.column_stack([x, y]).astype(float), 0)


def _rstd(v):
    """Robust standard deviation (1.4826 MAD); None for an empty list."""
    if not len(v):
        return None
    v = np.asarray(v)
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def validate(ids, log=print):
    """The cross-epoch stage against Gaia DR3 (the truth it never sees when choosing candidates):
    scatter of the measured motion, recall of Gaia's movers, false alarms among Gaia's static stars, and how
    complete the significance cut is for isolated stars (their CatWISE position displaced by a known motion)."""
    from sxlib import xepoch as X
    from sxlib.pmsearch import PIX
    rng = np.random.default_rng(1)
    rows, per, inj = [], {}, {m: [0, 0] for m in INJ_PM}
    for fid in ids:
        got = load(fid)
        if got is None or not got[3] or not got[3].get("catwise"):
            continue
        doc, st, mjd, ov, _ = got
        cands, stats, stars, _ = X.candidates(st, mjd, ov, doc["wcs"]["cdelt"])
        picked = {id(c["_q"]) for c in cands}
        iso_g = []
        for q in stars:
            g = ov["gaia"][q["jg"]] if q["jg"] is not None else None
            r = {"field": fid, "iso": q["iso"], "snr": q["snr"], "pm": q["pm"], "sig": q["sig"], "cand": id(q) in picked,
                 "gaia_pm": None if g is None else float(np.hypot(g["pmx"], g["pmy"]) * PIX),
                 "res": None if g is None else ((q["vx"] - g["pmx"]) * PIX, (q["vy"] - g["pmy"]) * PIX)}
            rows.append(r)
            if g is not None and q["iso"]:
                iso_g.append(r)
                if r["gaia_pm"] < STATIC_PM:                 # a static star given a known motion in a random direction
                    for m in inj:
                        a = rng.uniform(0, 2 * np.pi)
                        v = np.hypot(q["vx"] + m / PIX * np.cos(a), q["vy"] + m / PIX * np.sin(a))
                        inj[m][0] += 1; inj[m][1] += int(v / q["err"] >= X.MIN_SIG and v * PIX >= X.MIN_PM)
        ex = [v for r in iso_g for v in r["res"]]
        per[fid] = {"n_measured": len(stars), "n_isolated": stats.get("n_isolated"), "floor_mas_yr": round(stats.get("floor_arcsec_yr", 0) * 1000, 1),
                    "scatter_per_axis_mas_yr": None if len(ex) < 10 else round(_rstd(ex) * 1000, 1), "n_candidates": len(cands),
                    "limit_arcsec_yr": stats.get("limit_arcsec_yr"), "rejected": stats.get("rejected")}
        log(f"{fid}: {per[fid]}")
    g = [r for r in rows if r["gaia_pm"] is not None]
    static = [r for r in g if r["gaia_pm"] < STATIC_FLAG_PM]
    nog = [r for r in rows if r["gaia_pm"] is None]

    def _bin(lo, hi):
        sel = [r for r in g if lo <= r["gaia_pm"] < hi]
        return {"gaia_pm_lo": lo, "gaia_pm_hi": hi, "n": len(sel), "n_isolated": sum(r["iso"] for r in sel),
                "found": sum(r["cand"] for r in sel)}
    out = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "fields": per, "n_measured": len(rows), "n_with_gaia": len(g),
           "scatter_per_axis_mas_yr": round(_rstd([v for r in g if r["iso"] for v in r["res"]]) * 1000, 1),
           "recall": [_bin(lo, hi) for lo, hi in RECALL_BINS],
           "static": {"n": len(static), "n_isolated": sum(r["iso"] for r in static), "flagged": sum(r["cand"] for r in static)},
           "no_gaia": {"n": len(nog), "n_isolated": sum(r["iso"] for r in nog), "flagged": sum(r["cand"] for r in nog)},
           "injected_isolated": [{"pm": m, "n": n, "found": k, "frac": round(k / n, 3) if n else None} for m, (n, k) in inj.items()],
           "isolated_fraction": round(float(np.mean([r["iso"] for r in rows])), 3) if rows else None}
    write_json(OUTPUTS / "xepoch_validation.json", out)
    return out


def _print_candidate(c):
    plx = f" plx {c['plx_mas']}±{c['plx_err_mas']} mas" if c.get("plx_mas") else ""
    match = c["match"]["cat"] + " pm " + str(c["match"]["pm_cat"]) if c["match"] else ""
    print(f"   #{c['id']} [{c.get('method', 'spherex')}] ({c['x']:.0f},{c['y']:.0f}) {c['pm_arcsec_yr']:.3f}\"/yr "
          f"sig {c['sig']} snr {c['snr']} bands {c['n_bands_agree']}/{c['n_bands_fit']} {c['status']} {match}{plx}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ids = field_ids([a for a in argv if not a.startswith("--")], marker="pass/stacks.bin", skip_dotted=True)
    if "--validate" in argv:
        v = validate(ids)
        print(dumps({k: v[k] for k in v if k != "fields"}))
        return
    for fid in ids:
        r = run(fid)
        if r:
            for c in r["candidates"][:12]:
                _print_candidate(c)


if __name__ == "__main__":
    main()
