"""Known asteroids/comets for every exposure of a Field (JPL sb_ident, parallel)."""
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import archive

HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
SPHEREX_HORIZONS = "-163182"      # JPL Horizons ID of the SPHEREx spacecraft (observer for predictions)
JPL_MATCH_ARCSEC = 5.0            # within ~1 pixel of the JPL position
JPL_CONSISTENT_FRAC = 0.75        # a quarter off-track = mixed-in detections
RETRY_PAUSE_S = 5.0               # pause before re-asking JPL about a visit whose first query failed
JPL_GAP_S = 1.0                   # pause between consecutive JPL queries


def time_clusters(mjd, span=0.5):
    """Indices grouped into visits: each cluster spans at most `span` days from its first (earliest) member."""
    order = np.argsort(mjd)
    clusters, cur = [], [order[0]]
    for i in order[1:]:
        if mjd[i] - mjd[cur[0]] > span:
            clusters.append(cur)
            cur = []
        cur.append(i)
    clusters.append(cur)
    return clusters


def known_for_field(field, half_width, kinds=("a",), vmag_lim=21.5, workers=1, log=print, with_status=False):
    """Returns ({exposure index: [(name, ra, dec), ...]}, {name: info}[, {ok, failed, visits}]).
    A failed JPL query leaves those visits without known objects, so callers should surface the status.
    JPL's SSD APIs answer HTTP 429 to parallel requests from one client, so visits are asked one at a time."""
    clusters = time_clusters(field.mjd)

    def query(cl):
        tmid = float(np.median(field.mjd[cl]))
        try:
            return cl, archive.known_small_bodies(field.ra, field.dec, tmid, half_width, vmag_lim, kinds)
        except Exception as e:  # noqa: BLE001
            log(f"  sb_ident failed: {e}")
            return cl, None
        finally:
            time.sleep(JPL_GAP_S)
    pos = {i: [] for i in range(len(field.exps))}
    bodies = {}
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(query, clusters))
    # JPL throttles bursts: give each failed visit one more, unhurried try before counting it as failed
    for j, (cl, kb) in enumerate(results):
        if kb is None:
            time.sleep(RETRY_PAUSE_S)
            results[j] = query(cl)
    failed = 0
    for k, (cl, kb) in enumerate(results):
        if kb is None:
            failed += 1
            kb = []
        mj = field.mjd[cl]
        for b in kb:
            bodies.setdefault(b["name"], {"name": b["name"], "V": b["V"], "kind": b["kind"]})
            ra, dec = archive.known_position(b, mj)          # every exposure of the visit at once
            for k_, i in enumerate(cl):
                pos[i].append((b["name"], ra[k_], dec[k_]))
    log(f"  known objects: {len(clusters)} visits checked, {failed} failed, {len(bodies)} bodies")
    if with_status:
        return pos, bodies, {"ok": failed == 0, "failed": failed, "visits": len(clusters)}
    return pos, bodies


def _horizons_command(name):
    """'65 Cybele (A861 EB)' -> '65;'   '(2010 JN40)' / '306113 (2010 JN40)' -> numbered or provisional."""
    m = re.match(r"^\s*(\d+)\b", name)
    if m:
        return f"'{m.group(1)};'"
    m = re.search(r"\(([^)]+)\)", name)
    return f"'DES={m.group(1) if m else name.strip()};'"


def jpl_residuals(doc, log=print):
    """For every track matched to a known object: JPL Horizons astrometric positions seen FROM SPHEREx at
    each detection time, and our measured offset from them (arcsec). Stored as track["jpl"]."""
    cand = {c["id"]: c for c in doc["candidates"]}
    ex = doc["exposures"]
    for tr in doc["tracks"]:
        if not tr.get("known"):
            continue
        mem = sorted((cand[m] for m in tr["members"]), key=lambda c: ex[c["i"]]["mjd"])
        q = {"format": "json", "COMMAND": _horizons_command(tr["known"]), "EPHEM_TYPE": "OBSERVER",
             "CENTER": f"'500@{SPHEREX_HORIZONS}'", "TLIST_TYPE": "JD", "QUANTITIES": "'1'", "ANG_FORMAT": "DEG",
             "EXTRA_PREC": "YES", "CSV_FORMAT": "YES", "OBJ_DATA": "NO",
             "TLIST": "'" + " ".join(f"{ex[c['i']]['mjd'] + 2400000.5:.6f}" for c in mem) + "'"}
        try:
            r = archive._get(HORIZONS_API + "?" + urllib.parse.urlencode(q), {}, timeout=120).json()["result"]
            rows = r[r.index("$$SOE") + 5:r.index("$$EOE")].strip().splitlines()
            res = []
            for c, row in zip(mem, rows):
                p = [x.strip() for x in row.split(",")]
                ra, dec = float(p[3]), float(p[4])
                res.append([c["id"], round((c["ra"] - ra) * np.cos(np.radians(dec)) * 3600, 2), round((c["dec"] - dec) * 3600, 2)])
            tot = np.hypot([x[1] for x in res], [x[2] for x in res])
            ok = tot <= JPL_MATCH_ARCSEC
            tr["jpl"] = {"observer": f"SPHEREx ({SPHEREX_HORIZONS})", "resid": res, "n_match": int(ok.sum()), "n": len(res),
                         "consistent": bool(ok.sum() >= JPL_CONSISTENT_FRAC * len(res)),
                         "median_arcsec": round(float(np.median(tot[ok])), 2) if ok.any() else None,
                         "median_all_arcsec": round(float(np.median(tot)), 2)}
            log(f"  JPL Horizons {tr['known']}: {tr['jpl']['n_match']}/{len(res)} within 5\", median {tr['jpl']['median_arcsec']}\"")
        except Exception as e:  # noqa: BLE001
            log(f"  JPL Horizons failed for {tr['known']}: {e}")
    return doc
