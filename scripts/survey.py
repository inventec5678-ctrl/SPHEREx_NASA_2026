"""A targeted search for distant planets in SPHEREx data.

  python scripts/survey.py plan            # choose fields, keep those with >= 3 survey passes -> outputs/survey/plan.json
  python scripts/survey.py run <field_id>  # full pipeline + blind distant search + shift-and-stack search
  python scripts/survey.py summary         # merge results, vet candidates, write paper_evidence/survey.json

Regions: A = Planet Nine predicted path where it crosses the northern galactic plane (RA 75-105 deg),
B = near the predicted aphelion (RA 45-75 deg), D = the 2025 IRAS/AKARI candidate (Phan et al. 2025) extrapolated
to 2025-26. The fields sample the predicted path (a 0.5 deg strip along it), they do not tile the whole +-12 deg
probability band; limits are stated for the area actually searched.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, OUTPUTS, PAPER_EVIDENCE, read_json, write_json  # noqa: E402

OUT = OUTPUTS / "survey"
SIZE = 0.5
# Brown & Batygin 2021 median orbit projected on the sky
PATH_RA = [26, 40, 53, 67, 82, 97, 114]
PATH_DEC = [-5, 1, 8, 14, 19, 23, 26]
REGIONS = (("A", (75.0, 105.0)), ("B", (45.0, 74.0)))
RA_STEP = 1.5
# Phan et al. 2025: IRAS (1983.6) and AKARI (2006.7) positions; the motion is extrapolated 19 yr to 2025.7
IRAS, AKARI = (35.74075, -48.5125), (35.18379, -49.2135)
IRAS_AKARI_YR, EXTRAP_YR = 23.1, 19.0
PASS_GAP_DAYS = 40            # a gap longer than this between images starts a new pass
MIN_PASSES = 3
THRESH = 7.0
WORKERS = 6
FIELD_KEYS = ("id", "region", "ra", "dec", "n_exposures", "n_passes", "masked_fraction")


def plan():
    from sxlib import archive
    fields = []
    for region, (r0, r1) in REGIONS:
        for ra in np.arange(r0, r1 + 0.01, RA_STEP):
            fields.append({"region": region, "ra": float(ra), "dec": float(np.interp(ra, PATH_RA, PATH_DEC))})
    rate = ((AKARI[0] - IRAS[0]) / IRAS_AKARI_YR, (AKARI[1] - IRAS[1]) / IRAS_AKARI_YR)
    c_ra, c_dec = AKARI[0] + rate[0] * EXTRAP_YR, AKARI[1] + rate[1] * EXTRAP_YR
    for dx in (-0.5, 0, 0.5):
        for dy in (-0.5, 0, 0.5):
            fields.append({"region": "D", "ra": float(c_ra + dx / np.cos(np.radians(c_dec))), "dec": float(c_dec + dy)})
    keep, dropped = [], []
    for f in fields:
        f["id"] = f"sv{f['region']}_{f['ra']:07.3f}{f['dec']:+07.3f}".replace(".", "p")
        m = np.sort([im["mjd"] for im in archive.search_images(f["ra"], f["dec"], 0.001)])
        f["n_images"] = int(len(m))
        f["n_passes"] = int(1 + (np.diff(m) > PASS_GAP_DAYS).sum()) if len(m) else 0
        print(f["id"], f["n_images"], "images", f["n_passes"], "passes", flush=True)
        (keep if f["n_passes"] >= MIN_PASSES else dropped).append(f)
    write_json(OUT / "plan.json", {"fields": keep, "dropped": dropped, "phan_2025_extrapolated": [c_ra, c_dec]})
    print(f"{len(keep)} of {len(fields)} fields have >= 3 passes")


def run(fid):
    from sxlib import shiftstack
    from sxlib.analyze import analyze_field
    from sxlib.rbnet import Scorer
    f = next(x for x in read_json(OUT / "plan.json")["fields"] if x["id"] == fid)
    if not (OUT / fid / "field.json").exists():
        analyze_field(fid, fid, f["ra"], f["dec"], SIZE, OUT, Scorer(MODELS / "rb_cnn.pt"), log=print, workers=WORKERS)
    st = shiftstack.search(OUT / fid, thresh=THRESH, log=print)
    doc = read_json(OUT / fid / "field.json")
    single = [t for t in doc["tracks"] if t["kind"] == "distant"]
    res = {"id": fid, "region": f["region"], "ra": f["ra"], "dec": f["dec"], "n_exposures": len(doc["exposures"]),
           "n_passes": st["n_passes"], "masked_fraction": st["masked_fraction"],
           "single_distant": [{k: t.get(k) for k in ("id", "d_au", "pm_arcsec_yr", "rms_arcsec", "n_passes", "mean_p")}
                              | {"n": len(t["members"])} for t in single],
           "stack_tracks": [{"d_au": t["d_au"], "pm_arcsec_yr": t.get("pm_arcsec_yr"), "rms_arcsec": t["rms_arcsec"],
                             "n_passes": t["n_passes"], "peaks": [st["peaks"][m] for m in t["members"]]}
                            for t in st["tracks"]],
           "distant_search": doc.get("distant_search"), "known_lookup": doc.get("known_lookup")}
    write_json(OUT / fid / "search.json", res, default=float)
    print(f"{fid}: {len(single)} single-exposure distant tracks, {len(st['tracks'])} stacked tracks")


def summary():
    plan_ = read_json(OUT / "plan.json")
    rows, cands = [], []
    for f in plan_["fields"]:
        p = OUT / f["id"] / "search.json"
        if not p.exists():
            continue
        r = read_json(p)
        rows.append(r)
        for t in r["single_distant"]:
            cands.append({"field": r["id"], "region": r["region"], "method": "single", **t})
        for t in r["stack_tracks"]:
            cands.append({"field": r["id"], "region": r["region"], "method": "stack", "d_au": t["d_au"],
                          "pm_arcsec_yr": t["pm_arcsec_yr"], "rms_arcsec": t["rms_arcsec"], "n_passes": t["n_passes"],
                          "peaks": t["peaks"]})
    area = sum(SIZE * SIZE * (1 - r["masked_fraction"]) for r in rows)
    out = {"n_fields": len(rows), "area_deg2": round(area, 2),
           "by_region": {g: sum(1 for r in rows if r["region"] == g) for g in "ABD"},
           "candidates": cands, "fields": [{k: r[k] for k in FIELD_KEYS} for r in rows],
           "phan_2025_extrapolated": plan_.get("phan_2025_extrapolated")}
    write_json(PAPER_EVIDENCE / "survey.json", out, default=float)
    print(f"{len(rows)} fields, {out['area_deg2']} deg2 searched, {len(cands)} raw candidates")


if __name__ == "__main__":
    cmds = {"plan": plan, "run": lambda: run(sys.argv[2]), "summary": summary}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
