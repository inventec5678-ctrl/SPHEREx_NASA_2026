"""NEOSSat (Canadian Space Agency) coverage of any sky position, from the CADC archive (UPGRADE_PLAN.md §10, R11).

  GET /api/neossat/coverage?ra=&dec=
      {"status": "ok", "n": exposures, "dates": [{date, n, targets, exp_s, calibrated, thumb, obs_id}], "years": {...},
       "first", "last", "thumb", ...}                    when the position has been asked before (disk cache)
      {"status": "pending"}                              while a background thread asks CADC (seconds to ~2 min);
                                                          the page polls again
      {"status": "error"} / {"status": "busy"}

A position is rounded to 0.02 deg (72"; NEOSSat's field is ~50' across, its raw sub-frames 13'), and CADC is asked
for every NEOSSat frame whose footprint contains it. Results are kept 30 days in cache/neossat/coverage/ (not served);
scripts/neossat_build.py coverage fills it for every analysed field and quick look.
"""
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from sxlib import neossat as N

router = APIRouter()
COV = N.CACHE / "coverage"
STEP = 0.02                      # position rounding, degrees (72")
TTL_OK = 30 * 86400              # a coverage answer is kept 30 days
TTL_ERR = 600                    # an error is retried after 10 minutes
MAX_INFLIGHT = 12                # positions being asked at CADC at once
MAX_DATES = 120                  # newest observing dates listed in a document
CADC_TIMEOUT_S = 300
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="neossat")
_lock = threading.Lock()
_inflight = {}


def key_of(ra, dec):
    """Rounded position and its cache key, e.g. (269.44, 4.74, '269.44_+4.74')."""
    rr = round((ra % 360) / STEP) * STEP % 360
    dd = max(-90.0, min(90.0, round(dec / STEP) * STEP))
    return rr, dd, f"{rr:.2f}_{dd:+.2f}"


def _path(key):
    return COV / f"{key}.json"


def _read(key):
    p = _path(key)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ttl = TTL_OK if doc.get("status") == "ok" else TTL_ERR
    return doc if time.time() - doc.get("checked", 0) < ttl else None


def _write(key, doc):
    COV.mkdir(parents=True, exist_ok=True)
    p = _path(key)
    tmp = p.with_name(p.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def summarise(rows, ra, dec):
    """Coverage document from CADC ObsCore rows (pure; unit-tested)."""
    dates = N.coverage_summary(rows)
    years = {}
    for d in dates:
        y = d["date"][:4]
        years[y] = years.get(y, 0) + d["n"]
    n = sum(d["n"] for d in dates)
    cal = [d for d in dates if d["calibrated"]]
    pick = (cal or dates)[-1] if dates else None
    return {"status": "ok", "ra": ra, "dec": dec, "n": n, "n_dates": len(dates),
            "first": dates[0]["date"] if dates else None, "last": dates[-1]["date"] if dates else None,
            "years": years, "dates": dates[-MAX_DATES:], "truncated": max(0, len(dates) - MAX_DATES),
            "thumb": pick and {"url": pick["thumb"], "date": pick["date"], "obs_id": pick["obs_id"],
                               "full": N.thumb_url(pick["obs_id"], pick["product"], size=None)},
            "credit_en": N.CREDIT_EN, "credit_zh": N.CREDIT_ZH, "checked": time.time()}


def coverage_now(ra, dec):
    """Ask CADC now (blocking) and cache the answer; used by the background thread and the build script."""
    rr, dd, key = key_of(ra, dec)
    doc = _read(key)
    if doc:
        return doc
    try:
        rows = N.search(rr, dd, timeout=CADC_TIMEOUT_S, max_age_s=TTL_OK)
        doc = summarise(rows, rr, dd)
    except Exception as e:  # noqa: BLE001
        doc = {"status": "error", "ra": rr, "dec": dd, "error": type(e).__name__, "checked": time.time()}
    _write(key, doc)
    return doc


def _run(ra, dec, key):
    try:
        coverage_now(ra, dec)
    finally:
        with _lock:
            _inflight.pop(key, None)


@router.get("/api/neossat/coverage")
def coverage(ra: float = Query(..., ge=-360, le=720), dec: float = Query(..., ge=-90, le=90)):
    if not (math.isfinite(ra) and math.isfinite(dec)):
        raise HTTPException(400, "bad position")
    rr, dd, key = key_of(ra, dec)
    doc = _read(key)
    if doc:
        out = {k: v for k, v in doc.items() if k != "checked"}
        return JSONResponse(out, headers={"Cache-Control": "public, max-age=3600" if doc["status"] == "ok" else "no-store"})
    with _lock:
        if key not in _inflight:
            if len(_inflight) >= MAX_INFLIGHT:
                return JSONResponse({"status": "busy", "ra": rr, "dec": dd}, headers={"Cache-Control": "no-store"})
            _inflight[key] = time.time()
            _pool.submit(_run, rr, dd, key)
    return JSONResponse({"status": "pending", "ra": rr, "dec": dd}, headers={"Cache-Control": "no-store"})
