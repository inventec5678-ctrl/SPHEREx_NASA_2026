"""Bright known-asteroid benchmark fields (evaluation only, no injections).

For dates inside each SPHEREx survey pass, look at the ecliptic at +-90 deg from the Sun
(where SPHEREx points), find asteroids with 13 <= V <= 17 (JPL sb_ident), and build a
0.5 deg field centred on each one, using only that week's exposures.
Writes data/ds/kb_*.npz with the same format as make_dataset.py.

  python scripts/known_benchmark.py [--out data/ds] [--per-point 2] [--procs 4]
"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write_json  # noqa: E402
from make_dataset import process_field  # noqa: E402

DATES = ["2025-05-20", "2025-06-10", "2025-11-20", "2025-12-15", "2026-05-20", "2026-06-10"]
SIDES = (90, -90)                  # ecliptic longitude from the Sun (deg)
SEARCH_RADIUS = 2.0                # deg
V_MIN, V_MAX = 13.0, 17.0
FIELD_SIZE = 0.5
QUERY_THREADS = 4


def candidates(date, side):
    import astropy.units as u
    from astropy.coordinates import GeocentricTrueEcliptic, SkyCoord, get_sun
    from astropy.time import Time
    from sxlib import archive
    t = Time(date)
    frame = GeocentricTrueEcliptic(equinox=t)
    lsun = get_sun(t).transform_to(frame).lon.deg
    c = SkyCoord((lsun + side) % 360 * u.deg, 0 * u.deg, frame=frame).icrs
    kb = archive.known_small_bodies(c.ra.deg, c.dec.deg, t.mjd, SEARCH_RADIUS, vmag_lim=V_MAX, kinds=("a",))
    return date, side, [b for b in kb if V_MIN <= b["V"] <= V_MAX]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ds")
    ap.add_argument("--per-point", type=int, default=2)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    pts = [(d, s) for d in DATES for s in SIDES]
    with ThreadPoolExecutor(QUERY_THREADS) as ex:
        found = list(ex.map(lambda p: candidates(*p), pts))
    fields = []
    for date, side, kb in found:
        kb.sort(key=lambda b: b["V"])
        for b in kb[: a.per_point]:
            fields.append({"name": f"kb_{date}_{'E' if side > 0 else 'W'}_{b['name'].split()[0]}",
                           "ra": round(b["ra"], 4), "dec": round(b["dec"], 4), "target": b["name"], "V": b["V"],
                           "mjd": float(b["mjd"])})   # all passes are used: references need other epochs
        print(date, side, len(kb), "bright asteroids;", [f"{b['name']} V={b['V']}" for b in kb[:3]], flush=True)
    write_json(Path(a.out) / "kb_fields.json", fields)
    with ProcessPoolExecutor(a.procs) as ex:
        futs = [ex.submit(process_field, fd, a.out, FIELD_SIZE, 0, 0, 0) for fd in fields]
        for f in futs:
            try:
                print("RESULT", *f.result(), flush=True)
            except Exception as e:  # noqa: BLE001
                print("FAILED", e, flush=True)


if __name__ == "__main__":
    main()
