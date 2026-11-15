"""External checks of the variable-star light curves: python scripts/external_checks.py

R Draconis: the period and epoch of maximum from the AAVSO International Variable Star Index (VSX, read through the
VizieR mirror at CfA because AAVSO's own site does not allow scripted access) predict the pulsation phase at each
SPHEREx pass. We compare the order of the passes' brightness (from the PSF-wing light curve) with the phase, and fit
a 246-day sinusoid to the SPHEREx points to get the phase of the infrared maximum and the amplitude per detector.
Also stores, for every target, the brightest/faintest pass ratio from the PSF-wing ring and from a PSF fit (the
Barnard's Star control says which method is stable for a saturated star)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, read_json  # noqa: E402

VIZIER = "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"
TARGETS = ("barnard", "epsindi", "wise0855", "rwaur", "rdra")
VARIABLES = ("rdra", "rwaur")
DETECTORS = range(1, 7)
MIN_DET_POINTS = 6            # points a detector needs for its median
MIN_PASS_POINTS = 3           # points a pass needs for its median
MIN_FIT_POINTS = 10           # points a detector needs for the sinusoid fit
EDGE = 1e-6                   # days: pass boundaries are inclusive
MJD_JD = 2400000.5


def vsx(ra, dec):
    import requests
    r = requests.get(VIZIER, params={"-source": "B/vsx/vsx", "-c": f"{ra} {dec}", "-c.rs": 10,
                                     "-out": "Name,Type,max,min,Period,Epoch"}, timeout=60)
    r.raise_for_status()
    rows = [ln.split("\t") for ln in r.text.splitlines() if ln and not ln.startswith("#")]
    rows = [x for x in rows[3:] if len(x) >= 6]
    if not rows:
        return None
    n, ty, mx, mn, per, ep = [v.strip() for v in rows[0][:6]]
    num = lambda s: float(s) if s else None  # noqa: E731
    return {"name": n, "type": ty, "max_mag": num(mx), "min_mag": num(mn), "period_d": num(per), "epoch_max_jd": num(ep)}


def _in_pass(p, q):
    return q["mjd0"] - EDGE <= p["mjd"] <= q["mjd1"] + EDGE


def _per_detector(pts):
    """{det: (points, median of key)} for detectors with enough points; key is applied by the caller."""
    by = {}
    for p in pts:
        by.setdefault(p["det"], []).append(p)
    return {d: by[d] for d in DETECTORS if len(by.get(d, ())) >= MIN_DET_POINTS}


def pass_ratios(t, passes, key):
    pts = [p for p in t["points"] if p.get(key) and p[key] > 0]
    out = {}
    for det, v in _per_detector(pts).items():
        med = np.median([p[key] for p in v])
        pm = []
        for q in passes:
            s = [p[key] / med for p in v if _in_pass(p, q)]
            if len(s) >= MIN_PASS_POINTS:
                pm.append(float(np.median(s)))
        if len(pm) >= 2:
            out[f"D{det}"] = round(max(pm) / min(pm), 2)
    return out


def mira_check(t, passes, info):
    P, E = info["period_d"], info["epoch_max_jd"] - MJD_JD
    pts = [p for p in t["points"] if p.get("w") and p["w"] > 0]
    dets = _per_detector(pts)
    meds = {d: np.median([p["w"] for p in v]) for d, v in dets.items()}
    rows = []
    for k, q in enumerate(passes):
        m = (q["mjd0"] + q["mjd1"]) / 2
        rel = []
        for det, v in dets.items():
            s = [p["w"] / meds[det] for p in v if _in_pass(p, q)]
            if len(s) >= MIN_PASS_POINTS:
                rel.append(np.median(s))
        rows.append({"pass": k, "mjd": round(m, 1), "phase": round(((m - E) / P) % 1, 2),
                     "rel_brightness": round(float(np.median(rel)), 2) if rel else None})
    fits = {}
    for det in DETECTORS:
        v = np.array([(((p["mjd"] - E) / P) % 1, p["w"]) for p in pts if p["det"] == det])
        if len(v) < MIN_FIT_POINTS:
            continue
        y = v[:, 1] / np.median(v[:, 1])
        X = np.vstack([np.cos(2 * np.pi * v[:, 0]), np.sin(2 * np.pi * v[:, 0]), np.ones(len(v))]).T
        a, b, c = np.linalg.lstsq(X, y, rcond=None)[0]
        fits[f"D{det}"] = {"phase_of_max": round(float(np.arctan2(b, a) / (2 * np.pi)) % 1, 2),
                           "amplitude": round(float(np.hypot(a, b) / c), 2)}
    # the prediction: brightest near phase 0 (IR maximum lags the visual one by ~0.1), faintest near 0.5
    pred = [abs(((r["phase"] + 0.5) % 1) - 0.5) for r in rows]          # distance from maximum in phase
    obs = [r["rel_brightness"] for r in rows]
    agree = bool(np.argsort(pred).tolist() == np.argsort([-o for o in obs]).tolist()) if None not in obs else None
    return {"source": "AAVSO VSX via VizieR (CfA mirror)", "vsx": info, "passes": rows, "sinusoid": fits,
            "order_agrees": agree}


def main():
    from sxlib.analyze import write_doc
    for tid in TARGETS:
        out = FIELDS / tid
        doc = read_json(out / "field.json")
        t, passes = doc["target"], doc["products"]["passes"]
        t["pass_ratio"] = {"ring": pass_ratios(t, passes, "w"), "psf": pass_ratios(t, passes, "psf")}
        if tid in VARIABLES:
            try:
                info = vsx(t["ra"], t["dec"])
            except Exception as e:  # noqa: BLE001
                info = None
                print(tid, "VSX unavailable:", e)
            if info:
                t["vsx"] = info
                if info.get("period_d") and info.get("epoch_max_jd") and tid == "rdra":
                    t["external_check"] = mira_check(t, passes, info)
        write_doc(out, doc)
        print(tid, json.dumps({k: t.get(k) for k in ("pass_ratio", "vsx", "external_check")})[:900])


if __name__ == "__main__":
    main()
