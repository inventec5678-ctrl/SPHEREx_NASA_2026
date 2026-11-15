"""Gaia DR3 for the field lab's star card and the colour-magnitude diagram (sxlib/gaia.py: ESA first, MAST fallback).

  GET /api/gaia/star?ra=&dec=[&mjd=]   the Gaia DR3 source a click means (brightest within 1.5 SPHEREx pixels, Gaia
                                       positions moved to the image's epoch), its variability class, and neighbours
                                       within 30". Disk-cached under cache/gaia/star/.
  GET /api/gaia/marks                  points for the colour-magnitude diagram: the challenge's targets
                                       (web/data/gaia/targets.json, scripts/gaia_build.py) and every moving star the
                                       automatic search found (/api/movers), each matched to Gaia DR3.
The background of the diagram is static: web/data/gaia/cmd.json.
"""
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sxlib import gaia  # noqa: E402
from web.common import rate_ok, visitor  # noqa: E402

router = APIRouter()
CACHE = ROOT / "cache" / "gaia" / "star"
DATA = ROOT / "web" / "data"
PER_IP = 90                    # uncached look-ups per visitor per 10 minutes
PER_IP_WINDOW_S = 600
MARKS_TTL_S = 600
DEFAULT_EPOCH = 2025.8         # image epoch when the request gives no usable MJD
MOVER_EPOCH = 2025.6           # first-pass epoch of a mover whose field has no pass times
PM_AGREE = 2.5                 # Gaia and SPHEREx proper motions agree within this factor
SAME_POS_DEG = 3e-3            # movers without Gaia closer than this are one star seen twice
_lock = threading.Lock()
_sem = threading.BoundedSemaphore(4)
_ip: dict = {}
_marks = {"t": 0.0, "doc": None}
_epochs: dict = {}
_pool = ThreadPoolExecutor(4)


def _key(ra, dec, epoch):
    return f"{ra:.5f}_{dec:+.5f}_{epoch:.1f}"


def _path(ra, dec, epoch):
    return CACHE / f"{_key(ra, dec, epoch)}.json"


def lookup(ra, dec, epoch):
    """gaia.star with a disk cache (a Gaia DR3 answer does not change)."""
    p = _path(ra, dec, epoch)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    with _sem:
        doc = gaia.star(round(ra, 5), round(dec, 5), epoch=round(epoch, 1))
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")      # parallel look-ups never share one
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, p)
    return doc


def cached(ra, dec, epoch):
    return _path(ra, dec, epoch).exists()


@router.get("/api/gaia/star")
def star(ra: float, dec: float, request: Request, mjd: float | None = None):
    if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
        raise HTTPException(400, "ra must be in [0, 360) and dec in [-90, 90] degrees")
    epoch = gaia.epoch_of_mjd(mjd) if mjd is not None and math.isfinite(mjd) and 50000 < mjd < 80000 else DEFAULT_EPOCH
    if not cached(ra, dec, epoch):
        with _lock:
            if not rate_ok(_ip, visitor(request), PER_IP, PER_IP_WINDOW_S):
                raise HTTPException(429, "too many Gaia look-ups; try again in a few minutes")
    try:
        return lookup(ra, dec, epoch)
    except gaia.GaiaError as e:
        return JSONResponse({"error": "Gaia DR3 could not be reached (ESA and MAST)", "detail": str(e)[:300]}, status_code=503)


def _field_epoch(fid):
    """Mid-time of a field's first survey pass, the epoch of its movers' first-pass positions."""
    p = DATA / "fields" / fid / "field.json"
    try:
        m = p.stat().st_mtime_ns
    except OSError:
        return None
    if _epochs.get(fid, (None,))[0] != m:
        try:
            ps = json.loads(p.read_text(encoding="utf-8"))["products"]["passes"]
            _epochs[fid] = (m, gaia.epoch_of_mjd((ps[0]["mjd0"] + ps[0]["mjd1"]) / 2))
        except (OSError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            _epochs[fid] = (m, None)
    return _epochs[fid][1]


def _mover_points(budget_s=20.0):
    from web import server                           # imported here: server.py includes this module at its end
    movers = [c for c in server.movers() if c.get("status") != "static" and c.get("ra") is not None]
    futs = {}
    for c in movers:
        mj = (c.get("track") or [{}])[0].get("mjd")
        ep = gaia.epoch_of_mjd(mj) if mj else (_field_epoch(c["field"]) or MOVER_EPOCH)
        futs[_pool.submit(lookup, c["ra"], c["dec"], ep)] = c
    done, _ = wait(futs, timeout=budget_s)
    out, seen = [], set()
    for f, c in futs.items():
        base = {"field": c["field"], "pm_arcsec_yr": c.get("pm_arcsec_yr"), "status": c.get("status"),
                "match_cat": (c.get("match") or {}).get("cat"), "ra": c["ra"], "dec": c["dec"]}
        if f not in done or f.exception() is not None:
            out.append({**base, "pending": True})
            continue
        s = f.result().get("star")
        # the brightest Gaia star at the spot is this mover only if the pipeline matched it to Gaia, or if Gaia's
        # proper motion agrees with SPHEREx's within x2.5 (a mover matched to CatWISE can sit next to a Gaia star)
        pm = c.get("pm_arcsec_yr") or 0
        if s is not None and base["match_cat"] != "Gaia DR3" and not (s["pm"] and pm / PM_AGREE <= s["pm"] / 1000 <= pm * PM_AGREE):
            s = None
        if s is None:
            out.append({**base, "in_gaia": False})
            continue
        if s["source_id"] in seen:
            continue
        seen.add(s["source_id"])
        out.append({**base, "in_gaia": True, "source_id": s["source_id"], "g": s["g"], "bp_rp": s["bp_rp"],
                    "abs_g": s["abs_g"], "dist_pc": s["dist_pc"], "pm_gaia": s["pm"], "sep": s["sep"]})
    # one entry per Gaia star; stars without a Gaia counterpart once per position (quick looks repeat fields)
    uniq, pos = [], []
    for m in out:
        if m.get("in_gaia"):
            uniq.append(m)
        elif not any(abs(m["ra"] - a) < SAME_POS_DEG and abs(m["dec"] - b) < SAME_POS_DEG for a, b in pos):
            pos.append((m["ra"], m["dec"])); uniq.append(m)
    return uniq


@router.get("/api/gaia/marks")
def marks():
    now = time.time()
    if _marks["doc"] is not None and now - _marks["t"] < MARKS_TTL_S and not any(m.get("pending") for m in _marks["doc"]["movers"]):
        return _marks["doc"]
    try:
        targets = json.loads((DATA / "gaia" / "targets.json").read_text(encoding="utf-8"))["targets"]
    except (OSError, KeyError, json.JSONDecodeError):
        targets = []
    doc = {"targets": targets, "movers": _mover_points()}
    _marks.update(t=now, doc=doc)
    return doc
