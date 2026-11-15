"""Follow an asteroid or comet through SPHEREx (#/follow/<name>): name lookup, background jobs, results.

  GET  /api/follow/resolve?q=Cybele   JPL Small-Body Database: is this a known asteroid or comet? (disk-cached)
  POST /api/follow  {q, t0?, t1?}     start (or reuse) a job; answers at once with its slug
  GET  /api/follow/job/<slug>         the job's progress and results (doc.json, written by sxlib/follow.py)
  GET  /api/follow/list               the showcase objects and the most recent finished results

A job runs as its own process (a transient systemd user unit when available, so restarting the web service does not
stop it): IRSA MOST lists the images, ~150 cutouts are downloaded (1-3 minutes) and measured, and frames appear in
web/data/follow/<slug>/ as they arrive. At most 2 jobs run at once; each visitor (by hashed IP) may start 6 a day;
at most ~25 results are kept (the showcases always stay).
"""
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sxlib import follow as F  # noqa: E402
from web.common import rate_ok, spawn_detached, visitor  # noqa: E402

router = APIRouter()
OUT = ROOT / "web" / "data" / "follow"
CACHE = ROOT / "cache" / "follow"
MAX_RUNNING = int(os.environ.get("SX_FOLLOW_RUNNING", "2"))
PER_IP_DAY = int(os.environ.get("SX_FOLLOW_PER_IP", "6"))
KEEP = int(os.environ.get("SX_FOLLOW_KEEP", "25"))
MIN_FREE_GB = float(os.environ.get("SX_MIN_FREE_GB", "1.5"))
RESOLVE_PER_MIN = 20
RESOLVE_IP_MAX, RESOLVED_MAX = 5000, 3000
HEARTBEAT_S = 180                 # a job without a heartbeat for this long has stalled
CUTOUT_KEEP_S, CUTOUT_KEEP_BYTES = 7 * 86400, 600e6
N_RECENT = 8
NAME_RE = re.compile(r"[\w .+\-'*()\[\]/]+")
DATE_RE = re.compile(r"20\d\d-[01]\d-[0-3]\d")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,90}")
_lock = threading.Lock()
_ip_jobs: dict = {}
_ip_resolve: dict = {}
_resolved: dict = {}


def _doc(slug):
    try:
        return json.loads((OUT / slug / "doc.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _alive(d):
    return bool(d) and d.get("status") in ("searching", "running") and time.time() - d.get("heartbeat", 0) < HEARTBEAT_S


def _clean_q(q):
    q = " ".join(str(q or "").split())
    if not (1 <= len(q) <= 60) or not NAME_RE.fullmatch(q):
        raise HTTPException(422, "bad_name")
    return q


def _resolve(q, request):
    key = q.lower()
    if key in _resolved:
        return _resolved[key]
    f = CACHE / "sbdb" / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
    if not f.exists():                                   # an uncached lookup asks JPL on the visitor's behalf
        ipk = visitor(request)
        if not rate_ok(_ip_resolve, ipk, RESOLVE_PER_MIN, 60):
            raise HTTPException(429, "slow_down")
        if len(_ip_resolve) > RESOLVE_IP_MAX:          # forget everyone else rather than grow without bound
            mine = _ip_resolve[ipk]
            _ip_resolve.clear()
            _ip_resolve[ipk] = mine
    try:
        r = F.sbdb_resolve(q, CACHE)
    except F.FollowError:
        raise HTTPException(502, "sbdb_down")
    if len(_resolved) > RESOLVED_MAX:
        _resolved.clear()
    _resolved[key] = r
    return r


@router.get("/api/follow/resolve")
def follow_resolve(q: str, request: Request):
    """Is this name a known asteroid or comet? {status: ok|ambiguous|unknown, name, short, kind, cls, choices}."""
    return _resolve(_clean_q(q), request)


class FollowReq(BaseModel):
    q: str
    t0: str | None = None
    t1: str | None = None


def _prune():
    """Keep the newest KEEP results; showcases (a 'keep' file) and running jobs always stay."""
    dirs = sorted((d for d in OUT.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    k = 0
    for d in dirs:
        if (d / "keep").exists() or _alive(_doc(d.name)):
            continue
        k += 1
        if k > KEEP:
            shutil.rmtree(d, ignore_errors=True)
    # downloaded cutouts of finished jobs: a week, at most ~600 MB (each file stat'ed once)
    cut = CACHE / "cutouts"
    if cut.exists():
        files = []
        for p in cut.glob("*"):
            try:
                files.append((p.stat(), p))
            except OSError:
                continue
        files.sort(key=lambda t: t[0].st_mtime, reverse=True)
        tot, now = 0, time.time()
        for st, p in files:
            tot += st.st_size
            if tot > CUTOUT_KEEP_BYTES or now - st.st_mtime > CUTOUT_KEEP_S:
                p.unlink(missing_ok=True)


def _spawn(slug, spkid, name, t0, t1, kind):
    """Start sxlib.follow for one object as a detached process (a systemd user unit when there is one)."""
    args = [sys.executable, "-m", "sxlib.follow", slug, spkid, name, t0 or "", t1 or "", kind or ""]
    spawn_detached(args, "sxfollow-" + hashlib.sha1(slug.encode()).hexdigest()[:12], "3G", "follow.log")


@router.post("/api/follow")
def follow_start(req: FollowReq, request: Request):
    q = _clean_q(req.q)
    t0, t1 = req.t0 or None, req.t1 or None
    for t in (t0, t1):
        if t is not None and not DATE_RE.fullmatch(t):
            raise HTTPException(422, "bad_date")
    if t0 and t1 and t1 < t0:
        raise HTTPException(422, "bad_date")
    r = _resolve(q, request)
    if r["status"] == "ambiguous":
        return {"status": "ambiguous", "choices": r["choices"]}
    if r["status"] != "ok":
        raise HTTPException(404, "unknown")
    slug = F.slugify(r["name"], t0, t1)
    d = _doc(slug)
    if d and ((d.get("status") == "done" and d.get("v", 0) >= F.FOLLOW_VERSION) or _alive(d)):
        os.utime(OUT / slug)
        return {"slug": slug, "status": d["status"], "name": r["name"]}
    with _lock:
        if sum(1 for x in OUT.iterdir() if x.is_dir() and _alive(_doc(x.name))) >= MAX_RUNNING:
            raise HTTPException(429, "busy")
        if shutil.disk_usage(OUT).free / 1e9 < MIN_FREE_GB:
            raise HTTPException(507, "disk_full")
        if not rate_ok(_ip_jobs, visitor(request), PER_IP_DAY, 86400):
            raise HTTPException(429, "per_ip_limit")
        _prune()
        keep = (OUT / slug / "keep").exists()
        shutil.rmtree(OUT / slug, ignore_errors=True)
        (OUT / slug / "f").mkdir(parents=True)
        if keep:
            (OUT / slug / "keep").touch()
        (OUT / slug / "doc.json").write_text(json.dumps({
            "slug": slug, "v": F.FOLLOW_VERSION, "name": r["name"], "short": r["short"], "kind": r["kind"], "t0": t0, "t1": t1,
            "status": "searching", "frames": [], "n_total": 0, "n_done": 0, "heartbeat": time.time(), "started": time.time()}), encoding="utf-8")
        _spawn(slug, r["spkid"], r["name"], t0, t1, r["kind"])
    return {"slug": slug, "status": "searching", "name": r["name"]}


@router.get("/api/follow/job/{slug}")
def follow_job(slug: str):
    if not SLUG_RE.fullmatch(slug):
        raise HTTPException(400, "bad_slug")
    d = _doc(slug)
    if not d:
        raise HTTPException(404, "unknown")
    if d.get("status") in ("searching", "running") and not _alive(d):
        d["status"], d["error"] = "error", "stalled"
    d.pop("pid", None)
    return d


def _card(slug, d):
    fr = d.get("frames") or []
    mid = fr[len(fr) // 2]["f"] if fr else None
    return {"slug": slug, "name": d.get("name"), "short": d.get("short"), "kind": d.get("kind"), "t0": d.get("t0"), "t1": d.get("t1"),
            "n": len(fr), "n_most": d.get("n_most"), "first": d.get("first"), "last": d.get("last"), "started": d.get("started"),
            "thumb": f"/data/follow/{slug}/f/{mid:04d}.webp?r={int(d.get('started') or 0)}" if mid is not None else None,
            "stack": f"/data/follow/{slug}/stack.webp?r={int(d.get('started') or 0)}" if d.get("stack") else None,
            "period_h": (d.get("lc") or {}).get("period_h"), "offset": (d.get("offset") or {}).get("median_arcsec")}


@router.get("/api/follow/list")
def follow_list():
    """Showcase objects (precomputed by scripts/follow_build.py, in its order) and the newest finished results."""
    show = []
    try:
        order = json.loads((OUT / "showcases.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        order = []
    for s in order:
        d = _doc(s.get("slug", ""))
        if d and d.get("status") == "done":
            show.append({**_card(s["slug"], d), "note": s.get("note")})
    taken = {c["slug"] for c in show}
    recent = []
    if OUT.exists():
        for x in sorted((x for x in OUT.iterdir() if x.is_dir() and x.name not in taken), key=lambda x: x.stat().st_mtime, reverse=True):
            d = _doc(x.name)
            if d and d.get("status") == "done":
                recent.append(_card(x.name, d))
            if len(recent) >= N_RECENT:
                break
    return {"showcase": show, "recent": recent}
