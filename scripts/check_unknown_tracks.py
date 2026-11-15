"""Re-check the strongest unidentified fast tracks against JPL sb_ident directly at each track's own epoch and
position (box 0.15 deg, V <= 24, asteroids and comets), and report the nearest known body and its offset.

    python scripts/check_unknown_tracks.py          (any working directory)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, OUTPUTS, read_json  # noqa: E402

MIN_DET = 10            # tracks with at least this many detections
BOX_DEG, VMAX = 0.15, 24.0


def unidentified_tracks():
    rows = []
    for fn in sorted((OUTPUTS / "survey").glob("*/field.json")) + sorted(FIELDS.glob("*/field.json")):
        d = read_json(fn)
        ex = d["exposures"]
        cands = {c["id"]: c for c in d["candidates"]}
        for t in d["tracks"]:
            if t.get("kind") == "distant" or t.get("known") or len(t["members"]) < MIN_DET:
                continue
            mem = [cands[m] for m in t["members"]]
            mjd = np.array([ex[c["i"]]["mjd"] for c in mem])
            k = int(np.argsort(mjd)[len(mjd) // 2])
            rows.append((fn.parent.name, t["id"], len(mem), t["mean_p"], mem, mjd, k))
    return rows


def main():
    from sxlib import archive
    rows = unidentified_tracks()
    print(f"{len(rows)} unidentified tracks with >= {MIN_DET} detections")
    for fid, tid, n, p, mem, mjd, k in rows:
        c = mem[k]
        t0 = mjd[k]
        kb = archive.known_small_bodies(c["ra"], c["dec"], t0, BOX_DEG, VMAX, ("a", "c"))
        best = None
        if kb:
            ra = np.array([b["ra"] for b in kb]); dec = np.array([b["dec"] for b in kb])
            sep = np.hypot((ra - c["ra"]) * np.cos(np.radians(c["dec"])), dec - c["dec"]) * 3600
            j = int(np.argmin(sep))
            best = (sep[j], kb[j]["name"], kb[j]["V"])
        span_h = (mjd.max() - mjd.min()) * 24
        near = ('%.1f" %s V=%s' % best) if best else "none"
        print(f"{fid} track {tid}: {n} det, p={p}, span {span_h:.1f} h, at RA {c['ra']:.4f} Dec {c['dec']:.4f} "
              f"MJD {t0:.4f}; {len(kb)} known in box; nearest: {near}")


if __name__ == "__main__":
    main()
