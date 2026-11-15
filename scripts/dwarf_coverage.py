"""Where were the dwarf planets when SPHEREx looked? JPL Horizons ephemeris (observer = SPHEREx) + IRSA
image search along the path -> survey passes with the images that contain each body.

  python scripts/dwarf_coverage.py   -> outputs/dwarf_coverage.json
"""
import sys
import urllib.parse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, write_json  # noqa: E402

TARGETS = {"Makemake": "136472", "Haumea": "136108", "Eris": "136199"}
START, STOP = "2025-05-01", "2026-10-15"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
SPHEREX = "'500@-163182'"       # Horizons observer code of SPHEREx
EPH_STEP = 3                    # days between image searches along the path
SEARCH_HALF_DAYS = 2            # images within +-2 days containing the body
PASS_GAP_DAYS = 30              # a gap longer than this starts a new survey pass
MJD_JD = 2400000.5


def ephem(cmd, step="1d"):
    from sxlib import archive
    q = {"format": "json", "COMMAND": f"'{cmd};'", "EPHEM_TYPE": "OBSERVER", "CENTER": SPHEREX,
         "START_TIME": f"'{START}'", "STOP_TIME": f"'{STOP}'", "STEP_SIZE": f"'{step}'", "QUANTITIES": "'1,9,19,20'",
         "ANG_FORMAT": "DEG", "CSV_FORMAT": "YES", "OBJ_DATA": "NO", "CAL_FORMAT": "JD"}
    r = archive._get(HORIZONS + "?" + urllib.parse.urlencode(q), {}, timeout=120).json()["result"]
    out = []
    for row in r[r.index("$$SOE") + 5:r.index("$$EOE")].strip().splitlines():
        p = [x.strip() for x in row.split(",")]
        # JD, flag, flag, RA, DEC, APmag, S-brt, r, rdot, delta, deldot
        out.append({"mjd": float(p[0]) - MJD_JD, "ra": float(p[3]), "dec": float(p[4]), "V": float(p[5]),
                    "r_au": float(p[7]), "delta_au": float(p[9])})
    return out


def group_passes(mjds):
    passes = []
    for m in mjds:
        if passes and m - passes[-1][-1] < PASS_GAP_DAYS:
            passes[-1].append(m)
        else:
            passes.append([m])
    return passes


def coverage(cmd):
    from sxlib import archive
    eph = ephem(cmd)
    emjd = np.array([e["mjd"] for e in eph])
    nearest = lambda m: eph[int(np.argmin(np.abs(emjd - m)))]  # noqa: E731
    hits = set()
    for e in eph[::EPH_STEP]:
        imgs = archive.search_images(e["ra"], e["dec"], 0.001,
                                     mjd_range=(e["mjd"] - SEARCH_HALF_DAYS, e["mjd"] + SEARCH_HALF_DAYS))
        hits.update(round(im["mjd"], 5) for im in imgs)
    P = []
    for ms in group_passes(sorted(hits)):
        mid = float(np.median(ms))
        e, e0, e1 = nearest(mid), nearest(ms[0]), nearest(ms[-1])
        drift = np.hypot((e1["ra"] - e0["ra"]) * np.cos(np.radians(e["dec"])), e1["dec"] - e0["dec"])
        P.append({"mjd0": ms[0], "mjd1": ms[-1], "n_images": len(ms), "mid": mid, "ra": e["ra"], "dec": e["dec"],
                  "V": e["V"], "r_au": e["r_au"], "delta_au": e["delta_au"], "drift_deg": round(float(drift), 3)})
    return P


def main():
    res = {}
    for name, cmd in TARGETS.items():
        P = coverage(cmd)
        res[name] = {"passes": P}
        print(name, [(round(p["mjd0"]), round(p["mjd1"]), p["n_images"], round(p["ra"], 2), round(p["dec"], 2), p["V"],
                      round(p["r_au"], 2), p["drift_deg"]) for p in P], flush=True)
    write_json(OUTPUTS / "dwarf_coverage.json", res)


if __name__ == "__main__":
    main()
