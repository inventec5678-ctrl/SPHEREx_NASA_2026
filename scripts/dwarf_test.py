"""Real-data test of the distant-body method on known dwarf planets.

  python scripts/dwarf_test.py analyze Makemake 0   # analyse the field of one survey pass (0.6 deg, centred on JPL)
  python scripts/dwarf_test.py fit Makemake         # merge the passes, blind distant search, compare with JPL
  python scripts/dwarf_test.py stack Eris           # shift-and-stack each pass, link the stacked peaks, compare

A body this far sweeps ~1 deg between passes, more than one field, so each pass gets its own field centred
on the JPL position; candidates from all fields are merged in sky coordinates and linked blind (AI score only,
no catalogue help). The result is compared with JPL Horizons (observer = SPHEREx).
Needs outputs/dwarf_coverage.json (scripts/dwarf_coverage.py).
"""
import functools
import sys
import urllib.parse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, OUTPUTS, dumps, read_json, write_json  # noqa: E402

OUT = OUTPUTS / "dwarf"
SIZE = 0.6                      # field side (deg)
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
SPHEREX_CENTER = "'500@-163182'"
BODY_ID = {"Makemake": "136472", "Haumea": "136108", "Eris": "136199"}
HORIZONS_BATCH = 60             # epochs per Horizons request
PASS_SLACK_DAYS = 1
ON_BODY_ARCSEC = 8              # a single-exposure detection this close to JPL is the body
ON_BODY_STACK_ARCSEC = 12       # same for a stacked peak
STACK_DISTANCES = np.geomspace(40, 3000, 36)
STACK_MIN_SNR = 5.0


@functools.lru_cache(maxsize=None)
def coverage():
    return read_json(OUTPUTS / "dwarf_coverage.json")


def horizons(name, mjds, extra_prec=True, batch=None):
    """{mjd: (ra, dec, r_au)} of the body seen from SPHEREx at the given MJDs (JPL Horizons)."""
    from sxlib import archive
    mjds = list(mjds)
    batch = batch or max(len(mjds), 1)
    out = {}
    for a in range(0, len(mjds), batch):
        part = mjds[a:a + batch]
        q = {"format": "json", "COMMAND": f"'{BODY_ID[name]};'", "EPHEM_TYPE": "OBSERVER", "CENTER": SPHEREX_CENTER,
             "TLIST_TYPE": "JD", "QUANTITIES": "'1,19'", "ANG_FORMAT": "DEG"}
        if extra_prec:
            q["EXTRA_PREC"] = "YES"
        q.update({"CSV_FORMAT": "YES", "OBJ_DATA": "NO",
                  "TLIST": "'" + " ".join(f"{m + 2400000.5:.6f}" for m in part) + "'"})
        r = archive._get(HORIZONS + "?" + urllib.parse.urlencode(q), {}, timeout=120).json()["result"]
        rows = r[r.index("$$SOE") + 5:r.index("$$EOE")].strip().splitlines()
        for m, row in zip(part, rows):
            f = [x.strip() for x in row.split(",")]
            out[m] = (float(f[3]), float(f[4]), float(f[5]))
    return out


def _near(ra, dec, ra0, dec0, radius):
    from sxlib import link
    x, y = link._tangent(np.array([ra]), np.array([dec]), ra0, dec0)
    return np.hypot(x[0], y[0]) <= radius


def _err_pct(d, r_true):
    return round(100 * abs(d - r_true) / r_true, 2)


def analyze(name, k):
    from sxlib.analyze import analyze_field
    from sxlib.rbnet import Scorer
    p = coverage()[name]["passes"][k]
    analyze_field(f"dw_{name}_{k}", f"{name} pass {k}", p["ra"], p["dec"], SIZE, OUT, Scorer(MODELS / "rb_cnn.pt"),
                  description=f"{name}, survey pass {k}, centred on JPL Horizons", log=print)


def fit(name):
    from sxlib import link
    from sxlib.analyze import P_LINK
    passes = coverage()[name]["passes"]
    pool, per_pass = [], []
    for k, p in enumerate(passes):
        doc = read_json(OUT / f"dw_{name}_{k}" / "field.json")
        ex = doc["exposures"]
        keep = [c for c in doc["candidates"]
                if p["mjd0"] - PASS_SLACK_DAYS <= ex[c["i"]]["mjd"] <= p["mjd1"] + PASS_SLACK_DAYS and c["p"] >= P_LINK]
        pool += [{**c, "mjd": ex[c["i"]]["mjd"], "pass": k} for c in keep]
        per_pass.append((k, len(keep)))
    # JPL positions of the body at every exposure time we have (observer = SPHEREx)
    jpl = horizons(name, sorted({c["mjd"] for c in pool}), extra_prec=True, batch=HORIZONS_BATCH)
    on = [idx for idx, c in enumerate(pool) if _near(c["ra"], c["dec"], *jpl[c["mjd"]][:2], ON_BODY_ARCSEC)]
    r_true = float(np.median([jpl[c["mjd"]][2] for c in pool]))
    res = {"name": name, "r_jpl_au": round(r_true, 2), "candidates_per_pass": per_pass, "detections_on_body": len(on),
           "passes_with_detections": sorted({pool[i]["pass"] for i in on})}
    # 1) blind search over everything (no catalogue help)
    found = link.search_distant(pool)
    on_set = set(on)
    best = None
    for t in found:
        hit = len(set(t["members"]) & on_set)
        if hit >= 0.5 * len(t["members"]) and (best is None or hit > best[1]):
            best = (t, hit)
    res["blind"] = ({"d_au": round(best[0]["d_au"], 2), "pm_arcsec_yr": best[0].get("pm_arcsec_yr"), "rms_arcsec": round(best[0]["rms_arcsec"], 2),
                     "n_passes": best[0]["n_passes"], "members": len(best[0]["members"]), "on_body": best[1],
                     "d_err_pct": _err_pct(best[0]["d_au"], r_true)} if best else None)
    res["blind_tracks_total"] = len(found)
    # 2) seeded check from the detections that are on the body (what the website's point check does)
    if on:
        pr = link.probe_distant(pool, on[len(on) // 2])
        res["seeded"] = {k: pr[k] for k in ("ok", "d_au", "pm_arcsec_yr", "rms_arcsec", "n_passes", "reason") if k in pr}
        if pr.get("ok"):
            res["seeded"]["d_err_pct"] = _err_pct(pr["d_au"], r_true)
        # 3) the fit on exactly the detections of the body
        d, rms, pm = link.fit_distant([pool[i] for i in on])
        res["fit_on_body"] = {"d_au": round(d, 2), "rms_arcsec": round(rms, 2), "pm_arcsec_yr": pm, "d_err_pct": _err_pct(d, r_true)}
    print(dumps(res))
    write_json(OUT / f"result_{name}.json", res)


def stack(name):
    """Shift-and-stack each pass inside its own field, merge the stacked peaks, link across passes,
    compare with JPL (the test for bodies too faint for single exposures, e.g. Eris)."""
    from sxlib import link, shiftstack
    passes = coverage()[name]["passes"]
    groups, dets = [], []
    for k, p in enumerate(passes):
        fdir = OUT / f"dw_{name}_{k}"
        doc, snr = shiftstack.load_field(fdir)
        mjd = np.array([e["mjd"] for e in doc["exposures"]])
        idx = np.flatnonzero((mjd >= p["mjd0"] - PASS_SLACK_DAYS) & (mjd <= p["mjd1"] + PASS_SLACK_DAYS))
        mask, frac = shiftstack.star_mask(fdir, doc)
        pk = [q for q in shiftstack.stack_pass(doc, snr, idx, STACK_DISTANCES, STACK_MIN_SNR)
              if not mask[int(round(q["y"])), int(round(q["x"]))]]
        print(f"pass {k}: {len(idx)} images, {len(pk)} stacked peaks >= 5")
        for q in pk:
            dets.append({"ra": q["ra"], "dec": q["dec"], "mjd": q["mjd"], "p": q["snr"]})
            groups.append({"pass": k, "members": [len(dets) - 1], "ra": q["ra"], "dec": q["dec"], "mjd": q["mjd"], "peak": q})
    groups, dets = shiftstack.drop_static(groups, dets)
    tracks = link.link_groups(groups, dets)
    # where JPL says the body is at each pass mid-time
    jpl = horizons(name, sorted({g["mjd"] for g in groups}), extra_prec=False)
    on_body = [k for k, g in enumerate(groups) if _near(g["ra"], g["dec"], *jpl[g["mjd"]][:2], ON_BODY_STACK_ARCSEC)]
    r_true = float(np.median([v[2] for v in jpl.values()]))
    on_set = set(on_body)
    res = {"name": name, "r_jpl_au": round(r_true, 2),
           "stacked_peaks_on_body": [(groups[k]["pass"], round(groups[k]["peak"]["snr"], 1)) for k in on_body],
           "tracks": [{"d_au": round(t["d_au"], 2), "rms": round(t["rms_arcsec"], 1), "n_passes": t["n_passes"],
                       "on_body": len(set(t["members"]) & on_set)} for t in tracks]}
    print(dumps(res))
    write_json(OUT / f"stack_{name}.json", res)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmds = {"analyze": lambda: analyze(argv[1], int(argv[2])), "fit": lambda: fit(argv[1]), "stack": lambda: stack(argv[1])}
    if not argv or argv[0] not in cmds:
        sys.exit(__doc__.split("\n\n")[1])
    OUT.mkdir(parents=True, exist_ok=True)
    cmds[argv[0]]()


if __name__ == "__main__":
    main()
