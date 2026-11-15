"""SPHEREx Sky Change Explorer - web backend.

  uvicorn web.server:app --host 127.0.0.1 --port 8791

Precomputed fields live in web/data/fields/<id>/ (field.json + frames); finished quick looks in web/data/quick/<id>/.
New full analyses are queued here and run by web/worker.py (a separate service, one job at a time); quick looks run as
detached processes (web/quick.py). Feature endpoints live in web/api_*.py and are included through their `router`.

Sections: middleware (cache + security headers, gzip) - fields - jobs - citizen reports - measurement pool -
fresh/refresh - quick looks - name resolver - movers and validation - client errors - share pages and preview images.
"""
import asyncio
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from web.common import client_ip, ip_key, rate_ok, spawn_detached, visitor  # noqa: E402

DATA = ROOT / "web" / "data"
FIELDS = DATA / "fields"
QUICK = DATA / "quick"
MODELS = ROOT / "models"
DIST = ROOT / "web" / "app" / "dist"
PUBLIC = ROOT / "web" / "app" / "public"
VAR = ROOT / "var"
QUEUE, JOBS = VAR / "queue", VAR / "jobs"
for _d in (FIELDS, QUICK, QUEUE, JOBS):
    _d.mkdir(parents=True, exist_ok=True)

ID_RE = re.compile(r"[\w.+-]+")                          # field / job ids as they appear in URLs
QUICK_ID = re.compile(r"k\d{3}p\d{3}[+-]\d{2}p\d{3}s\d{2}")
DAY_S, HOUR_S = 86400, 3600
FRESH_TTL_S = 6 * HOUR_S                                 # how long an IRSA "newer images?" answer is reused
NEWER_MJD = 0.01                                         # an exposure this much later than the last one used is new
HEARTBEAT_S = 180                                        # a quick look without a heartbeat for this long has stalled
NO_VOTES = {"real": 0, "artifact": 0, "unsure": 0}


@asynccontextmanager
async def _lifespan(app):
    yield
    _stop_measure_pool()          # the measurement worker processes go down with the server


app = FastAPI(title="SPHEREx Sky Change Explorer", lifespan=_lifespan)


# ======================================== middleware ========================================
class _GZip(GZipMiddleware):
    """Compress as usual, except the lab's float16 stacks (/data/**/*.bin): they barely compress (3.6 -> 3.2 MB)
    and the page shows their download progress, which needs the file's Content-Length."""
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/data/") and scope["path"].endswith(".bin"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


CACHE_YEAR = "public, max-age=31536000, immutable"
CACHE_HOUR = "public, max-age=3600"
CACHE_DAY = "public, max-age=86400"


def _cache_control(h: MutableHeaders, path: str, has_query: bool):
    """Hashed Vite bundles and finished frames never change: cache for a year. HTML and JSON: always revalidate
    (StaticFiles answers 304 from the ETag). Other static media: an hour. APIs: not stored unless they say so."""
    if path.startswith("/assets/"):
        h["Cache-Control"] = CACHE_YEAR
    elif path == "/sw.js":
        h["Cache-Control"] = "no-cache"                  # the service worker must update with the site
    elif path.endswith(".html") or path == "/" or path.endswith(".json"):
        h.setdefault("Cache-Control", "no-cache")
    elif path.startswith("/data/quick/"):
        # a frame is written once; a pass stack is rewritten as frames arrive, so its URL carries ?n=<frames>
        frame = "/sci/" in path or "/diff/" in path or "/flag/" in path
        h["Cache-Control"] = CACHE_YEAR if frame or ("/stack/" in path and has_query) else "no-cache"
    elif path.startswith("/data/fields/"):
        h["Cache-Control"] = CACHE_DAY
    elif path.startswith(("/media/", "/paper/", "/discovery/", "/models/")):
        h.setdefault("Cache-Control", CACHE_HOUR)
    elif path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")


# External hosts the pages use: Aladin Lite v3 (an ES module from jsDelivr; WebAssembly, web workers) shows HiPS tiles
# from IRSA and may ask CDS (Strasbourg) for survey lists and names; the fonts come from Google Fonts.
CSP_CONNECT = ("https://cdn.jsdelivr.net", "https://irsa.ipac.caltech.edu", "https://*.ipac.caltech.edu",
               "https://*.unistra.fr", "https://*.u-strasbg.fr", "https://simbad.cfa.harvard.edu")
CSP_RECHECK_S = 2
_INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_SRC_ATTR = re.compile(r"\bsrc\s*=", re.I)
_csp = {"checked": 0.0, "key": None, "value": None}
_csp_lock = threading.Lock()


def _inline_script_hashes(pages):
    """'sha256-...' of every inline <script> in the built pages (index.html and the paper's redirect pages)."""
    out = []
    for p in pages:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for attrs, body in _INLINE_SCRIPT.findall(text):
            if _SRC_ATTR.search(attrs):
                continue
            h = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"
            if h not in out:
                out.append(h)
    return out


def csp_value():
    """The Content-Security-Policy; the inline-script hashes are recomputed when a built page changes (checked at
    most every CSP_RECHECK_S seconds)."""
    now = time.time()
    if _csp["value"] is not None and now - _csp["checked"] < CSP_RECHECK_S:
        return _csp["value"]
    with _csp_lock:
        pages = sorted(DIST.rglob("*.html"))
        try:
            key = tuple((str(p), p.stat().st_mtime_ns) for p in pages)
        except OSError:
            key = None
        if _csp["value"] is None or key != _csp["key"]:
            hashes = " ".join(_inline_script_hashes(pages))
            _csp["value"] = "; ".join((
                "default-src 'self'",
                f"script-src 'self' https://cdn.jsdelivr.net 'wasm-unsafe-eval'{' ' + hashes if hashes else ''}",
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
                "img-src 'self' data: blob: https:",
                "media-src 'self' blob:",
                "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
                "connect-src 'self' data: " + " ".join(CSP_CONNECT),       # Aladin fetches its WebAssembly from a data: URL
                "worker-src 'self' blob:",
                "frame-ancestors *",          # the embeddable player is a feature: no X-Frame-Options either
                "base-uri 'self'",
                "object-src 'none'",
            ))
            _csp["key"] = key
        _csp["checked"] = now
        return _csp["value"]


SECURITY_HEADERS = (("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "strict-origin-when-cross-origin"),
                    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"))


class _Headers:
    """Cache-Control by path, then the security headers, on every HTTP response. A plain ASGI middleware (no
    BaseHTTPMiddleware): it only edits the response-start message, so bodies stream through untouched."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, has_query = scope["path"], bool(scope.get("query_string"))      # read now: mounts rewrite the scope

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                _cache_control(h, path, has_query)
                for k, v in SECURITY_HEADERS + (("Content-Security-Policy", csp_value()),):
                    if k not in h:
                        h[k] = v
            await send(message)
        await self.app(scope, receive, send_with_headers)


app.add_middleware(_GZip, minimum_size=1024, compresslevel=6)
app.add_middleware(_Headers)          # added last: the outermost of our middleware
_lock = threading.Lock()


# ======================================== small helpers ========================================
def _check_id(fid, pattern=ID_RE, code=400, detail="bad id"):
    if not pattern.fullmatch(fid):
        raise HTTPException(code, detail)


_client_ip, _ip_key, _visitor, _rate_ok = client_ip, ip_key, visitor, rate_ok


def _json_or_none(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _live_dirs(pattern):
    """Files matching FIELDS/<pattern> in live field folders (not a refresh being built: <id>.new / <id>.old)."""
    return [p for p in sorted(FIELDS.glob(pattern)) if "." not in p.parent.name]


def _fdir(fid):
    """An analysed field's directory, or a finished quick look's (it has the same lab products)."""
    return (QUICK / fid) if QUICK_ID.fullmatch(fid) else (FIELDS / fid)


@lru_cache(maxsize=16)
def _doc(fid, mtime):
    return json.loads((_fdir(fid) / "field.json").read_text(encoding="utf-8"))


def _field_doc(fid):
    p = _fdir(fid) / "field.json"
    return _doc(fid, p.stat().st_mtime)


def _full_id(ra, dec, size):
    """Id of the full analysis of a position (POST /api/jobs)."""
    return f"q{ra:07.3f}{dec:+07.3f}".replace(".", "p") + ("" if size == 0.3 else f"s{int(size * 100):02d}")


def _qid(ra, dec, size):
    """Id of the quick look of a position (POST /api/quick)."""
    return f"k{ra:07.3f}{dec:+07.3f}s{int(round(size * 100)):02d}".replace(".", "p")


def _free_gb(path):
    return shutil.disk_usage(path).free / 1e9


# ======================================== fields ========================================
def _summary(field_dir: Path):
    s = field_dir / "summary.json"
    if s.exists() and s.stat().st_mtime >= (field_dir / "field.json").stat().st_mtime:
        return json.loads(s.read_text(encoding="utf-8"))
    from sxlib.analyze import summary_of
    return summary_of(json.loads((field_dir / "field.json").read_text(encoding="utf-8")))


FIELD_ORDER = {"cybele": 0, "planetx": 1, "barnard": 2, "epsindi": 3, "wise0855": 4, "rwaur": 5, "rdra": 6}


@app.get("/api/fields")
def list_fields():
    out = []
    for p in _live_dirs("*/field.json"):
        try:
            out.append(_summary(p.parent) | {"has_universe": (p.parent / "universe.json").exists()})
        except Exception:  # noqa: BLE001 - half-written field
            continue
    return sorted(out, key=lambda s: (FIELD_ORDER.get(s["id"], 9), s["name"]))


@app.get("/api/field/{fid}")
def get_field(fid: str):
    _check_id(fid)
    p = _fdir(fid) / "field.json"
    if not p.exists():
        raise HTTPException(404, "unknown field")
    return FileResponse(p, media_type="application/json", headers={"Cache-Control": "public, max-age=60"})


def _need_field(fid):
    """404 unless fid names an analysed field."""
    if not ID_RE.fullmatch(fid) or not (FIELDS / fid / "field.json").exists():
        raise HTTPException(404, "unknown field")


# ======================================== jobs ========================================
# The web process only validates and enqueues; web/worker.py (spherex-worker.service) runs them.
JOBS_ENABLED = os.environ.get("SX_JOBS_ENABLED", "1") == "1"
MAX_PENDING = int(os.environ.get("SX_MAX_PENDING", "3"))       # queued + running
PER_IP_DAY = int(os.environ.get("SX_JOBS_PER_IP", "2"))
MIN_FREE_GB = float(os.environ.get("SX_MIN_FREE_GB", "1.5"))   # one 0.3 deg field caches ~0.4 GB of cutouts
FAIL_COOLDOWN_S = 3600
SIZES = (0.15, 0.3, 0.6)                                        # field of view choices, degrees


def _job_state(fid):
    return _json_or_none(JOBS / f"{fid}.json")


def _all_jobs():
    return [j for j in (_job_state(p.stem) for p in JOBS.glob("*.json")) if j]


def _pending():
    return [j for j in _all_jobs() if j["status"] in ("queued", "running")]


def _public(j):
    pos = next((k + 1 for k, p in enumerate(sorted(QUEUE.glob("*.json"))) if p.stem.split("_", 1)[1] == j["id"]), 0)
    running = any(x["status"] == "running" for x in _pending())
    return {k: v for k, v in j.items() if k not in ("log", "ip")} | {"log": j.get("log", [])[-12:], "position": pos,
                                                                    "ahead_running": running}


def _can_enqueue(j, cooldown=False):
    """The checks shared by a new job and a refresh, in their order: disabled, (cooldown), disk, queue."""
    if not JOBS_ENABLED:
        raise HTTPException(503, "jobs_disabled")
    if cooldown and j and j["status"] == "error" and time.time() - j.get("finished", 0) < FAIL_COOLDOWN_S:
        raise HTTPException(429, "cooldown")
    if _free_gb(FIELDS) < MIN_FREE_GB:
        raise HTTPException(507, "disk_full")
    if len(_pending()) >= MAX_PENDING:
        raise HTTPException(429, "queue_full")


def _enqueue(job, item):
    (JOBS / f"{job['id']}.json").write_text(json.dumps(job), encoding="utf-8")
    (QUEUE / f"{time.time():.3f}_{job['id']}.json").write_text(json.dumps(item), encoding="utf-8")


class JobReq(BaseModel):
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    size: float = 0.3
    refresh: bool = False          # quick look: make it again with the newest data (only when IRSA has newer images)


@app.post("/api/jobs")
def submit(req: JobReq, request: Request):
    if req.size not in SIZES:
        raise HTTPException(422, "bad_size")
    fid = _full_id(req.ra, req.dec, req.size)
    if (FIELDS / fid / "field.json").exists():
        return {"id": fid, "status": "done"}
    with _lock:
        j = _job_state(fid)
        if j and j["status"] in ("queued", "running"):
            return _public(j)
        _can_enqueue(j, cooldown=True)
        ipk, day = _visitor(request), time.time() - DAY_S
        if sum(1 for x in _all_jobs() if x.get("ip") == ipk and x.get("queued", 0) > day) >= PER_IP_DAY:
            raise HTTPException(429, "per_ip_limit")
        item = {"id": fid, "ra": req.ra, "dec": req.dec, "size": req.size}
        j = item | {"status": "queued", "log": [], "queued": time.time(), "ip": ipk}
        _enqueue(j, item)
    return _public(j)


@app.get("/api/jobs/{fid}")
def job(fid: str):
    _check_id(fid)
    j = _job_state(fid)
    live = (FIELDS / fid / "field.json").exists()
    if live and (not j or j["status"] == "done" or (j["status"] == "error" and not j.get("refresh"))):
        return {"id": fid, "status": "done", "log": []}
    if not j:
        raise HTTPException(404, "unknown_job")
    return _public(j)


# ======================================== citizen reports ========================================
# Kept outside the static tree, validated, one vote per person per object.
REPORTS = VAR / "reports.jsonl"
SPOTS_PER_IP_DAY = 40
_votes: dict = {}          # field -> key -> {real, artifact, unsure}
_seen: set = set()         # (ip key, field, key) already voted
_spots: dict = {}          # (field, key) -> a position someone flagged in a lab: where, why, when
_spot_ip: dict = {}


def _key(rec):
    if rec.get("x") is not None:
        return f"s{int(round(rec['x']))}_{int(round(rec['y']))}"
    if rec.get("mover") is not None:
        return f"m{rec['mover']}"
    return f"c{rec['cand']}" if rec.get("cand") is not None else str(rec["track"])


def _count(rec):
    key, fid = _key(rec), rec["field"]
    _seen.add((rec.get("ip"), fid, key))
    c = _votes.setdefault(fid, {}).setdefault(key, dict(NO_VOTES))
    c[rec["verdict"]] += 1
    if rec.get("x") is not None:
        sp = _spots.setdefault((fid, key), {"field": fid, "x": int(round(rec["x"])), "y": int(round(rec["y"])),
                                            "kinds": {}, "t": rec.get("t", 0)})
        if rec.get("kind"):
            sp["kinds"][rec["kind"]] = sp["kinds"].get(rec["kind"], 0) + 1


def _load_reports():
    if not REPORTS.exists():
        return
    for line in REPORTS.read_text(encoding="utf-8").splitlines():
        try:
            _count(json.loads(line))
        except json.JSONDecodeError:
            continue


_load_reports()


@lru_cache(maxsize=64)
def _ids(fid, mtime):
    doc = json.loads((FIELDS / fid / "field.json").read_text(encoding="utf-8"))
    return {t["id"] for t in doc["tracks"]}, {c["id"] for c in doc["candidates"]}


@lru_cache(maxsize=4)
def _n_discovery_at(path, mtime_ns):
    return len(json.loads(Path(path).read_text(encoding="utf-8")).get("candidates", []))


def _n_discovery():
    for p in (DIST / "discovery" / "discovery.json", PUBLIC / "discovery" / "discovery.json"):
        if p.exists():
            return _n_discovery_at(str(p), p.stat().st_mtime_ns)
    return 0


class Report(BaseModel):
    field: str = Field(pattern=r"^[\w.+-]{1,64}$")
    track: int | None = None
    cand: int | None = None
    mover: int | None = None
    x: float | None = None          # a position flagged in a lab (field pixels), instead of a track / candidate / mover
    y: float | None = None
    kind: str | None = Field(default=None, pattern="^(moving|variable|spectrum|other)$")
    verdict: str = Field(pattern="^(real|artifact|unsure)$")
    note: str | None = Field(default=None, max_length=500)


def _check_report_target(r: Report, ipk):
    if r.x is not None or r.y is not None:
        # anyone can flag a position in a field lab or a finished quick look; others then vote on it
        if r.x is None or r.y is None or r.track is not None or r.cand is not None or r.mover is not None:
            raise HTTPException(422, "bad_target")
        p = _fdir(r.field) / "field.json"
        if not p.exists():
            raise HTTPException(422, "bad_target")
        n0, n1 = _doc(r.field, p.stat().st_mtime)["shape"]
        if not (0 <= r.x < n1 and 0 <= r.y < n0):
            raise HTTPException(422, "outside")
        if not _rate_ok(_spot_ip, ipk, SPOTS_PER_IP_DAY, DAY_S):
            raise HTTPException(429, "per_ip_limit")
    elif r.mover is not None:
        # votes on automatic proper-motion candidates (index into the field's or quick look's mover list)
        if r.track is not None or r.cand is not None or not 0 <= r.mover < len(_mover_list(r.field)):
            raise HTTPException(422, "bad_target")
    elif r.field == "discovery":
        # votes on the survey's distant-body candidates (index into discovery.json)
        if r.cand is None or r.track is not None or not 0 <= r.cand < _n_discovery():
            raise HTTPException(422, "bad_target")
    else:
        p = FIELDS / r.field / "field.json"
        if not p.exists() or (r.track is None) == (r.cand is None):
            raise HTTPException(422, "bad_target")
        tracks, cands = _ids(r.field, p.stat().st_mtime)
        if (r.track is not None and r.track not in tracks) or (r.cand is not None and r.cand not in cands):
            raise HTTPException(422, "bad_target")


@app.post("/api/report")
def report(r: Report, request: Request):
    ipk = _visitor(request)
    _check_report_target(r, ipk)
    rec = r.model_dump() | {"t": time.time(), "ip": ipk}
    with _lock:
        if (ipk, r.field, _key(rec)) in _seen:
            return reports(r.field) | {"_duplicate": True}
        with open(REPORTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        _count(rec)
    return reports(r.field)


@app.get("/api/reports/{fid}")
def reports(fid: str):
    return _votes.get(fid, {})


def _pix2world(w, x, y):
    """Field pixel (0-based) -> (ra, dec) for the TAN grid of a field document (as lib.js pix2world)."""
    d2r = math.pi / 180
    xi, eta = (x + 1 - w["crpix"][0]) * w["cdelt"][0] * d2r, (y + 1 - w["crpix"][1]) * w["cdelt"][1] * d2r
    a0, d0 = w["crval"][0] * d2r, w["crval"][1] * d2r
    den = math.cos(d0) - eta * math.sin(d0)
    ra = a0 + math.atan2(xi, den)
    return (ra / d2r) % 360, math.atan2(math.sin(d0) + eta * math.cos(d0), math.hypot(xi, den)) / d2r


@app.get("/api/spots")
def spots():
    """Positions people flagged in a field lab or a quick look, with their votes: the second half of the review queue."""
    out = []
    for (fid, key), sp in list(_spots.items()):
        p = _fdir(fid) / "field.json"
        if not p.exists():                 # a quick look that has been pruned
            continue
        doc = _doc(fid, p.stat().st_mtime)
        ra, dec = _pix2world(doc["wcs"], sp["x"], sp["y"])
        n_pass = len((doc.get("products") or {}).get("passes") or [None])
        out.append({**sp, "key": key, "track": [{"k": 0, "x": sp["x"], "y": sp["y"]}, {"k": n_pass - 1, "x": sp["x"], "y": sp["y"]}],
                    "ra": round(ra, 5), "dec": round(dec, 5), "source": "quick" if doc.get("quick") else "field",
                    "centre": {"ra": doc["ra"], "dec": doc["dec"], "size": doc["size_deg"]}, "name": doc.get("name"),
                    "votes": _votes.get(fid, {}).get(key, dict(NO_VOTES))})
    out.sort(key=lambda c: (-(c["votes"]["real"] - c["votes"]["artifact"]), -c["t"]))
    return out


@app.get("/api/metrics")
def metrics():
    """The headline numbers, from the same evidence file the paper is built from."""
    p = DIST / "paper" / "research" / "evidence.json"
    if not p.exists():
        p = PUBLIC / "paper" / "research" / "evidence.json"
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})


# ======================================== measurement pool ========================================
# The numpy work for /point, /probe and /starcheck runs in a pool of spawned worker processes (sxlib/measure.py);
# the web process only checks the request, caps how many measurements one visitor has in flight, and passes the
# worker's JSON bytes on. (In-process, 16 requests at once took 4.3 s each and /api/health slowed from 14 to 300 ms.)
MEASURE_WORKERS = int(os.environ.get("SX_MEASURE_WORKERS", "8"))
MEASURE_PER_IP = int(os.environ.get("SX_MEASURE_PER_IP", "4"))      # in flight at once, per visitor
MEASURE_MAX = int(os.environ.get("SX_MEASURE_MAX", "64"))           # queued + running, all visitors together
_mpool = None
_mpool_lock = threading.Lock()
_inflight: dict = {}          # ip key -> measurements in flight (memory only)


def _measure_pool():
    """The worker pool, started on first use with every worker at once (spawned, not forked: the web process has
    threads)."""
    global _mpool
    with _mpool_lock:
        if _mpool is None:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor
            from sxlib import measure
            _mpool = ProcessPoolExecutor(MEASURE_WORKERS, mp_context=mp.get_context("spawn"), initializer=measure.init_worker)
            for _ in range(MEASURE_WORKERS):
                _mpool.submit(measure.warm)
        return _mpool


def _stop_measure_pool():
    global _mpool
    with _mpool_lock:
        pool, _mpool = _mpool, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)


async def _measure(request: Request, fn, *args):
    from concurrent.futures.process import BrokenProcessPool
    global _mpool
    ipk = _visitor(request)
    if _inflight.get(ipk, 0) >= MEASURE_PER_IP:
        return JSONResponse({"detail": "too_many_measurements"}, status_code=429, headers={"Retry-After": "1"})
    if sum(_inflight.values()) >= MEASURE_MAX:
        return JSONResponse({"detail": "busy"}, status_code=429, headers={"Retry-After": "2"})
    _inflight[ipk] = _inflight.get(ipk, 0) + 1
    try:
        for attempt in range(2):
            pool = _measure_pool()
            try:
                status, body = await asyncio.wrap_future(pool.submit(fn, *args))
                break
            except BrokenProcessPool:                 # a worker died (out of memory, killed): one fresh pool, one retry
                with _mpool_lock:
                    if _mpool is pool:
                        _mpool = None
                if attempt:
                    raise
    finally:
        _inflight[ipk] -= 1
        if not _inflight[ipk]:
            del _inflight[ipk]
    if status != 200:
        raise HTTPException(status, body)
    return Response(body, media_type="application/json")


def _need_cube(fid):
    """The lab directory of a field or quick look that has its data cube, else 404 no_cube."""
    d = _fdir(fid) if ID_RE.fullmatch(fid) else None
    if d is None or not (d / "cube" / "img.npy").exists() or not (d / "field.json").exists():
        raise HTTPException(404, "no_cube")
    return d


@app.get("/api/probe")
async def probe(field: str, x: float, y: float, i: int, request: Request):
    """Everything we can say about the sky at pixel (x, y) [field pixels, y up] around exposure i:
    the detection there, whether it belongs to a track, whether the same spot lights up in other survey
    passes (a fixed source), the spectral fit of a catalogued source there, and a seeded parallax +
    orbital-motion search asking whether it could be a distant planet (sxlib/measure.py)."""
    from sxlib import measure
    _need_field(field)
    return await _measure(request, measure.probe, str(FIELDS / field), field, x, y, i)


@app.get("/api/field/{fid}/point")
async def point(fid: str, x: float, y: float, request: Request):
    """Forced aperture photometry at field pixel (x, y) in every exposure: a light curve and an on-the-fly spectrum
    (sxlib/measure.py, in a worker process)."""
    from sxlib import measure
    d = _need_cube(fid)
    return await _measure(request, measure.point, str(d), x, y)


@app.get("/api/field/{fid}/starcheck")
async def starcheck(fid: str, x: float, y: float, request: Request):
    """Is the bright spot at field pixel (x, y) a star? A point-source (PSF) model fit on the median of all exposures,
    its presence in each exposure, the pixel flags and the Gaia / CatWISE catalogues (sxlib/starcheck.py)."""
    from sxlib import starcheck as sc
    d = _need_cube(fid)
    return await _measure(request, sc.check, str(d), x, y)


# ======================================== new data at IRSA ========================================
_fresh: dict = {}
_quick_fresh: dict = {}


def _irsa_newer(ra, dec, last):
    """(newest exposure IRSA has, how many are newer than `last`, how many in all) for a position."""
    from sxlib import archive
    try:
        metas = archive.search_images(ra, dec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"irsa: {e}") from e
    return (max((m["mjd"] for m in metas), default=last), sum(1 for m in metas if m["mjd"] > last + NEWER_MJD), len(metas))


@app.get("/api/field/{fid}/fresh")
def fresh(fid: str):
    """How many SPHEREx exposures of this field IRSA has that are newer than the ones analysed (cached 6 h)."""
    _need_field(fid)
    hit = _fresh.get(fid)
    if hit and time.time() - hit["t"] < FRESH_TTL_S:
        return hit["r"]
    doc = _field_doc(fid)
    last = max(e["mjd"] for e in doc["exposures"])
    avail, n_new, n_total = _irsa_newer(doc["ra"], doc["dec"], last)
    r = {"id": fid, "analysed_to": last, "available_to": avail, "n_new": n_new, "n_total": n_total}
    _fresh[fid] = {"t": time.time(), "r": r}
    return r


@app.post("/api/field/{fid}/refresh")
def refresh(fid: str, request: Request):
    """Re-run the whole analysis with the newest data; the current version stays online until the new one is ready."""
    _need_field(fid)
    if fresh(fid)["n_new"] == 0:
        return {"id": fid, "status": "up_to_date"}
    doc = _field_doc(fid)
    with _lock:
        j = _job_state(fid)
        if j and j["status"] in ("queued", "running"):
            return _public(j)
        _can_enqueue(j)
        item = {"id": fid, "ra": doc["ra"], "dec": doc["dec"], "size": doc["size_deg"], "refresh": True,
                "name": doc["name"], "description": doc.get("description", ""), "simulate": bool(doc.get("simulated"))}
        j = {"id": fid, "ra": doc["ra"], "dec": doc["dec"], "size": doc["size_deg"], "status": "queued", "log": [],
             "queued": time.time(), "ip": _visitor(request), "refresh": True, "item": item}
        _enqueue(j, item)
    return _public(j)


# ======================================== quick looks ========================================
# Any position plays within about a minute (frames stream in while the rest download).
QUICK_MAX_RUNNING = int(os.environ.get("SX_QUICK_RUNNING", "2"))
QUICK_PER_IP = int(os.environ.get("SX_QUICK_PER_IP", "12"))
QUICK_KEEP = int(os.environ.get("SX_QUICK_KEEP", "30"))           # previews kept on disk (oldest removed first)
QUICK_BUDGET_GB = float(os.environ.get("SX_QUICK_GB", "3.0"))     # a finished look keeps its lab cube (15-250 MB)
_quick_ip: dict = {}


@lru_cache(maxsize=64)
def _preview_at(qid, mtime_ns, size):
    return _json_or_none(QUICK / qid / "preview.json")


def _preview(qid):
    """A quick look's preview.json (parsed once per version of the file; callers must not modify it)."""
    try:
        st = (QUICK / qid / "preview.json").stat()
    except OSError:
        return None
    return _preview_at(qid, st.st_mtime_ns, st.st_size)


def _alive(p):
    return bool(p) and p.get("status") in ("searching", "running") and time.time() - p.get("heartbeat", 0) < HEARTBEAT_S


def _quick_alive(qid):
    return _alive(_preview(qid))


def _quick_dirs():
    return [d for d in QUICK.iterdir() if d.is_dir()]


def _prune_quick():
    total = 0.0
    for k, d in enumerate(sorted(_quick_dirs(), key=lambda d: d.stat().st_mtime, reverse=True)):
        # "keep": an example linked from the home page; a look someone reported on or voted in stays for the others
        if _quick_alive(d.name) or (d / "keep").exists() or d.name in _votes:
            continue
        total += sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e9
        if k >= QUICK_KEEP or total > QUICK_BUDGET_GB:
            shutil.rmtree(d, ignore_errors=True)


def _spawn_quick(qid, ra, dec, size):
    args = [sys.executable, "-m", "web.quick", qid, repr(ra), repr(dec), repr(size)]
    spawn_detached(args, "sxquick-" + hashlib.sha1(qid.encode()).hexdigest()[:12], "6G", "quick.log")


@app.get("/api/health")
def health():
    """Disk and queue state, for monitoring (no personal data)."""
    free = _free_gb(FIELDS)
    dirs = _quick_dirs()
    return {"ok": free >= MIN_FREE_GB, "disk_free_gb": round(free, 2), "min_free_gb": MIN_FREE_GB,
            "jobs_pending": len(_pending()), "quick_running": sum(1 for d in dirs if _quick_alive(d.name)),
            "quick_kept": len(dirs)}


@app.post("/api/quick")
def quick(req: JobReq, request: Request):
    from sxlib.quicklook import QUICK_VERSION          # imported on use: keeps astropy out of server start-up
    if req.size not in SIZES:
        raise HTTPException(422, "bad_size")
    qid = _qid(req.ra, req.dec, req.size)
    p = _preview(qid)
    # a finished look is reused, unless it was made before the lab existed (then it is made again, once), or the
    # visitor asked for the newest data and IRSA really has newer images
    stale = bool(req.refresh and p and p["status"] == "done" and quick_fresh(qid).get("n_new"))
    if p and ((p["status"] == "done" and p.get("v", 1) >= QUICK_VERSION and not stale) or _alive(p)):
        os.utime(QUICK / qid)
        return {"id": qid, "status": p["status"]}
    with _lock:
        if sum(1 for d in _quick_dirs() if _quick_alive(d.name)) >= QUICK_MAX_RUNNING:
            raise HTTPException(429, "quick_busy")
        need = 0.6 + 0.5 * (req.size / 0.3) ** 2
        if _free_gb(QUICK) < need:
            raise HTTPException(507, "disk_full")
        if not _rate_ok(_quick_ip, _visitor(request), QUICK_PER_IP, DAY_S):
            raise HTTPException(429, "per_ip_limit")
        _prune_quick()
        d = QUICK / qid
        keep = (d / "keep").exists()                    # an example linked from the home page stays one
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        if keep:
            (d / "keep").touch()
        (d / "preview.json").write_text(json.dumps({"id": qid, "ra": req.ra, "dec": req.dec, "size_deg": req.size,
                                                    "status": "searching", "frames": [], "n_total": 0, "n_done": 0,
                                                    "heartbeat": time.time()}), encoding="utf-8")
        _spawn_quick(qid, req.ra, req.dec, req.size)
    return {"id": qid, "status": "searching"}


@app.get("/api/quick/{qid}/fresh")
def quick_fresh(qid: str):
    """How many SPHEREx exposures of a finished quick look IRSA has now that are newer than the ones it used (6 h cache)."""
    _check_id(qid, QUICK_ID)
    p = _preview(qid)
    if not p or p.get("status") != "done" or not p.get("frames"):
        raise HTTPException(404, "unknown")
    hit = _quick_fresh.get(qid)
    if hit and time.time() - hit["t"] < FRESH_TTL_S and hit["finished"] == p.get("finished"):
        return hit["r"]
    last = max(f["mjd"] for f in p["frames"])
    avail, n_new, n_total = _irsa_newer(p["ra"], p["dec"], last)
    r = {"id": qid, "made": p.get("finished"), "used_to": last, "available_to": avail, "n_new": n_new, "n_total": n_total}
    _quick_fresh[qid] = {"t": time.time(), "r": r, "finished": p.get("finished")}
    return r


_QUICK_STATE_ID = re.compile(r"k[\w+-]+")


@app.get("/api/quick/{qid}")
def quick_state(qid: str):
    _check_id(qid, _QUICK_STATE_ID)
    p = _preview(qid)
    if not p:
        raise HTTPException(404, "unknown")
    p = dict(p)                                         # the parsed file is shared: answer with a copy
    if p["status"] in ("searching", "running") and not _alive(p):
        p["status"], p["error"] = "error", "stalled"
    p["full_id"] = _full_id(p["ra"], p["dec"], p["size_deg"])
    p["full_done"] = (FIELDS / p["full_id"] / "field.json").exists()
    p.pop("pid", None)
    return p


# ======================================== name resolver ========================================
_resolve_cache: dict = {}
_resolve_ip: dict = {}           # ip key -> times of recent uncached look-ups (this endpoint calls SIMBAD on the visitor's behalf)
RESOLVE_PER_MIN = 20
RESOLVE_CACHE_MAX, RESOLVE_IP_MAX = 2000, 5000
SIMBAD_TAP = "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync"
_NAME_RE = re.compile(r"[\w .+\-'*()\[\]/]+")
MJD_UNIX0, MJD_J2000 = 40587, 51544.5


@app.get("/api/resolve")
def resolve(q: str, request: Request):
    """Object name -> position now. SIMBAD (Harvard mirror) gives the J2000 position and the proper motion; the
    position is moved to today, because a nearby star has left its J2000 place (Barnard's Star by 4.5')."""
    import requests
    q = " ".join(q.split())
    if not (1 < len(q) <= 60) or not _NAME_RE.fullmatch(q):
        raise HTTPException(422, "bad_name")
    key = q.lower()
    if key in _resolve_cache:
        hit = _resolve_cache[key]
        if hit is None:
            raise HTTPException(404, "not_found")
        return hit
    ipk = _visitor(request)
    if not _rate_ok(_resolve_ip, ipk, RESOLVE_PER_MIN, 60):
        raise HTTPException(429, "slow_down")
    if len(_resolve_ip) > RESOLVE_IP_MAX:              # forget everyone else rather than grow without bound
        mine = _resolve_ip[ipk]
        _resolve_ip.clear()
        _resolve_ip[ipk] = mine
    adql = ("SELECT TOP 1 main_id, ra, dec, pmra, pmdec, plx_value, otype FROM basic JOIN ident ON oidref = oid "
            f"WHERE id = '{q.replace(chr(39), chr(39) * 2)}'")
    try:
        r = requests.get(SIMBAD_TAP, timeout=12, verify=False,
                         params={"request": "doQuery", "lang": "adql", "format": "json", "query": adql})
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception:  # noqa: BLE001 - network or SIMBAD down
        raise HTTPException(502, "resolver_down")
    if not rows or rows[0][1] is None:
        _resolve_cache[key] = None
        raise HTTPException(404, "not_found")
    name, ra, dec, pmra, pmdec, plx, otype = rows[0]
    has_pm = pmra is not None and pmdec is not None
    if has_pm:
        yr = (time.time() / DAY_S + MJD_UNIX0 - MJD_J2000) / 365.25          # years since J2000
        dec2 = dec + pmdec * yr / 3.6e6
        ra2 = (ra + pmra * yr / 3.6e6 / max(0.05, math.cos(math.radians(dec)))) % 360
    else:
        ra2, dec2 = ra, dec
    out = {"name": " ".join(str(name).replace("NAME ", "").split()), "ra": round(ra2, 5), "dec": round(dec2, 5),
           "ra_j2000": ra, "dec_j2000": dec, "pm_arcsec_yr": round((pmra ** 2 + pmdec ** 2) ** 0.5 / 1000, 3) if has_pm else None,
           "plx_mas": plx, "otype": otype, "source": "SIMBAD"}
    if len(_resolve_cache) > RESOLVE_CACHE_MAX:
        _resolve_cache.clear()
    _resolve_cache[key] = out
    return out


# ======================================== movers and validation ========================================
def _mover_list(fid):
    """Automatic proper-motion candidates of an analysed field (pm_candidates.json) or a quick look (preview.json)."""
    if not re.fullmatch(r"[\w.+-]{1,64}", fid):
        return []
    try:
        if fid.startswith("k"):
            return (_preview(fid) or {}).get("movers", {}).get("candidates", [])
        return json.loads((FIELDS / fid / "pm_candidates.json").read_text(encoding="utf-8"))["candidates"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []


MOVER_RANK = {"new": 0, "mismatch": 1, "known": 2, "static": 3}
MOVER_KEYS = ("id", "x", "y", "ra", "dec", "pm_arcsec_yr", "pmra", "pmdec", "sig", "snr", "status", "match", "n_bands_agree",
              "n_bands_fit", "det_band", "track", "shift_px", "bd_score", "bd_points", "method", "baseline_yr",
              "pm_err_arcsec_yr", "plx_mas", "plx_err_mas", "dist_pc", "bands", "dx", "dy")


@app.get("/api/movers")
def movers():
    """Every automatic proper-motion candidate, newest-looking first, with its votes: the public review queue."""
    srcs = [(p.parent.name, "field", None) for p in FIELDS.glob("*/pm_candidates.json") if "." not in p.parent.name]
    for d in _quick_dirs():
        pv = _preview(d.name)
        if pv and pv.get("movers"):
            srcs.append((d.name, "quick", {"ra": pv["ra"], "dec": pv["dec"], "size": pv["size_deg"]}))
    out = []
    for fid, kind, centre in srcs:
        votes = _votes.get(fid, {})
        for c in _mover_list(fid):
            out.append({"field": fid, "source": kind, "centre": centre, **{k: c.get(k) for k in MOVER_KEYS},
                        "votes": votes.get(f"m{c['id']}", dict(NO_VOTES))})
    out.sort(key=lambda c: (MOVER_RANK.get(c["status"], 9), -c["sig"]))
    return out


PIX_ARCSEC = 6.15                # the field grid's pixel
_MIN_SHIFT_ARCSEC = 0.738        # sxlib.pmsearch: MIN_SHIFT_PX (0.12) x PIX (6.15); tests/test_web_validation.py keeps them equal
PM_STRATA = ((0.5, 1.0), (1.0, 2.0), (2.0, 99))
PM_TARGETS = ("barnard", "epsindi", "wise0855")
TARGET_MATCH_PX = 2.5


def _known_star_row(s):
    """One star of the known-star test (outputs/pm_validation.json), compact, for the guide's scatter plot.
    pred / meas: the shift between the first and last pass in arcsec, as Gaia predicts it and as measured directly at
    the star's position (None when that fit failed); resid: their vector difference; meas_pm, sig: what the blind
    search reported if it found the star."""
    st, r = s["star"], s["result"]
    di = r.get("direct") or {}
    mp = di.get("meas_px")
    return {"id": str(st["id"]), "ra": round(st["ra"], 5), "dec": round(st["dec"], 5), "g": round(st["g"], 2), "pm": round(st["pm"], 3),
            "dt_yr": r.get("dt_yr"), "pred": r.get("pred_arcsec"), "meas": round(math.hypot(*mp) * PIX_ARCSEC, 3) if mp else None,
            "resid": di.get("resid_arcsec"), "found": bool(r.get("found")), "meas_pm": r.get("meas_pm"), "sig": r.get("sig")}


def _known_stars(d):
    import numpy as np
    rows = [s for s in d["stars"] if "result" in s and not s["result"].get("skip")]
    strata = []
    for lo, hi in PM_STRATA:
        g = [s for s in rows if lo <= s["star"]["pm"] < hi]
        strata.append({"pm_lo": lo, "pm_hi": hi, "n": len(g), "found": sum(s["result"]["found"] for s in g),
                       "known_label": sum(1 for s in g if s["result"]["found"] and s["result"]["status"] == "known")})
    res = [s["result"]["direct"]["resid_arcsec"] for s in rows if s["result"].get("direct")]
    meas = [(s["result"]["meas_pm"], s["star"]["pm"]) for s in rows if s["result"]["found"]]
    return {"n_total": len(d["stars"]), "n_done": sum("result" in s for s in d["stars"]), "n_usable": len(rows),
            "strata": strata, "astrometry_resid_arcsec": {"median": round(float(np.median(res)), 3) if res else None,
                                                          "p90": round(float(np.percentile(res, 90)), 3) if res else None, "n": len(res)},
            "pm_ratio_median": round(float(np.median([m / t for m, t in meas])), 3) if meas else None,
            "false_new_candidates": sum(s["result"].get("n_new_other", 0) for s in rows), "updated": d.get("updated"),
            "per_pass_exposures": 45, "field_deg": 0.15,
            "min_shift_arcsec": _MIN_SHIFT_ARCSEC, "stars": [_known_star_row(s) for s in rows]}


def _pm_targets(pm):
    tg = []
    for tid in PM_TARGETS:
        try:
            cs = pm[tid]["candidates"]
            t = _field_doc(tid)["target"]
            p0 = t["passes"][0]
            hit = next((c for c in cs if abs(c["x"] - p0["x"]) < TARGET_MATCH_PX and abs(c["y"] - p0["y"]) < TARGET_MATCH_PX), None)
            tg.append({"id": tid, "found": bool(hit), "pm": hit and hit["pm_arcsec_yr"], "pm_cat": round(t["pm_total"], 2),
                       "bd_score": hit and hit.get("bd_score")})
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    return tg


def _variables(v):
    fl = v.get("fields", {})
    cat = [f.get("catalogued_variables") or {} for f in fl.values()]
    out = {
        "fields": len(fl), "n_searched": sum(f.get("n_searched", 0) for f in fl.values()),
        "n_candidates": sum(f.get("n_candidates", 0) for f in fl.values()),
        "by_status": {k: sum((f.get("by_status") or {}).get(k, 0) for f in fl.values())
                      for k in ("known_variable", "new", "catalogued_constant")},
        "targets": {k: {a: (fl[k].get("target_check") or {}).get(a) for a in ("flagged", "amp", "sig")}
                    for k in ("rdra", "rwaur", "barnard") if k in fl},
        "catalogued": {"in_fields": sum(c.get("n_in_field", 0) for c in cat), "searched": sum(c.get("n_searched", 0) for c in cat),
                       "flagged": sum(c.get("n_flagged", 0) for c in cat)},
        "by_field": {k: {"n_searched": f.get("n_searched", 0), "n_candidates": f.get("n_candidates", 0),
                         "catalogued_constant": (f.get("by_status") or {}).get("catalogued_constant", 0)} for k, f in fl.items()},
        "updated": v.get("updated")}
    vt = (_json_or_none(ROOT / "outputs" / "var_targets.json") or {}).get("targets") or {}
    for k, t in out["targets"].items():          # brightness in each survey pass, relative to the star's mean
        if vt.get(k, {}).get("passes"):
            t["passes"] = vt[k]["passes"]
    return out


@app.get("/api/validation")
def validation():
    """Every honest number behind the automatic search and the spectral classifier, in one place."""
    out = {}
    pv = ROOT / "outputs" / "pm_validation.json"
    if pv.exists():
        out["known_stars"] = _known_stars(json.loads(pv.read_text(encoding="utf-8")))
    # every live field's proper-motion search, read once (a corrupt file fails the request, as it always has)
    pm = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in _live_dirs("*/pm_candidates.json")}
    out["targets"] = _pm_targets(pm)
    false_by_field = {fid: sum(1 for c in d["candidates"] if c["status"] in ("static",)) for fid, d in pm.items()}
    out["false_movers_in_fields"] = sum(false_by_field.values())
    out["fields_searched"] = len(pm)
    out["false_movers_by_field"] = false_by_field
    m = MODELS / "bd_spec_metrics.json"
    if m.exists():
        out["spectral"] = json.loads(m.read_text(encoding="utf-8"))
        sc = _json_or_none(MODELS / "bd_spec_scores.json")          # one row per star (scripts/export_validation_detail.py)
        if sc:
            out["spectral"]["scores"] = {k: sc.get(k) for k in ("created", "source", "matches_metrics", "positives", "negatives")}
    try:
        out["mira"] = _field_doc("rdra")["target"].get("external_check")
        out["ring_control"] = _field_doc("barnard")["target"].get("pass_ratio")
    except OSError:
        pass
    xe = ROOT / "outputs" / "xepoch_validation.json"
    if xe.exists():                                   # cross-epoch proper motions, SPHEREx vs CatWISE (scripts/pm_search.py --validate)
        x = json.loads(xe.read_text(encoding="utf-8"))
        out["xepoch"] = {k: x.get(k) for k in ("n_measured", "scatter_per_axis_mas_yr", "recall", "static", "no_gaia",
                                               "injected_isolated", "isolated_fraction", "created")}
    vs = ROOT / "outputs" / "var_search.json"
    if vs.exists():                                   # automatic variable-star search (scripts/var_search.py)
        out["variables"] = _variables(json.loads(vs.read_text(encoding="utf-8")))
    # bright-star control: unidentified fast tracks per field (far from the ecliptic they can only be false)
    try:
        out["static_veto"] = {p.parent.name: json.loads(p.read_text(encoding="utf-8")).get("n_unknown")
                              for p in FIELDS.glob("*/summary.json") if "." not in p.parent.name}
    except (OSError, json.JSONDecodeError):
        pass
    return out


# only the released model and its metrics are public, not training checkpoints or raw score dumps
PUBLIC_MODELS = {"rb_cnn.pt", "metrics.json", "recovery.json", "dataset.json", "bd_spec.npz", "bd_spec_metrics.json"}


@app.get("/models/{name}")
def model_file(name: str):
    if name not in PUBLIC_MODELS or not (MODELS / name).exists():
        raise HTTPException(404, "not found")
    return FileResponse(MODELS / name)


# ======================================== front-end error reports ========================================
# No IPs stored (they only feed the in-memory rate limit).
CLIENTERR = ROOT / "outputs" / "clienterr.jsonl"
CLIENTERR_MAX_BYTES = 5 * 1024 * 1024          # then the file is rotated to clienterr.jsonl.1
CLIENTERR_MAX_BODY = 32768
CLIENTERR_PER_IP_HOUR, CLIENTERR_PER_DAY = 20, 1000
CLIENTERR_LIMITS = {"msg": 300, "stack": 2000, "route": 200, "ua": 200}
_cerr_ip: dict = {}           # ip key -> times of recent reports
_cerr_all: list = []          # times of all reports in the last day
_cerr_lock = threading.Lock()


@app.post("/api/clienterr", status_code=204)
async def clienterr(request: Request):
    """One JavaScript error from a visitor's browser: {msg, stack, route, ua}, truncated, one JSON line per report."""
    if int(request.headers.get("content-length") or 0) > CLIENTERR_MAX_BODY:
        raise HTTPException(413, "too_large")
    body = await request.body()
    if len(body) > CLIENTERR_MAX_BODY:
        raise HTTPException(413, "too_large")
    try:
        d = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "bad_json")
    if not isinstance(d, dict):
        raise HTTPException(400, "bad_json")
    now = time.time()
    ipk = _visitor(request)
    with _cerr_lock:
        mine = [t for t in _cerr_ip.get(ipk, []) if now - t < HOUR_S]
        _cerr_all[:] = [t for t in _cerr_all if now - t < DAY_S]
        if len(mine) >= CLIENTERR_PER_IP_HOUR or len(_cerr_all) >= CLIENTERR_PER_DAY:
            raise HTTPException(429, "slow_down")
        if len(_cerr_ip) > 5000:
            for k in [k for k, ts in _cerr_ip.items() if not ts or now - ts[-1] >= HOUR_S]:
                del _cerr_ip[k]
        _cerr_ip[ipk] = mine + [now]
        _cerr_all.append(now)
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
        for k, n in CLIENTERR_LIMITS.items():
            v = d.get(k)
            v = v if isinstance(v, str) else ("" if v is None else str(v))
            if k == "route":
                v = v.split("?", 1)[0]             # a hash route's query can carry what someone typed
            rec[k] = v[:n]
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        CLIENTERR.parent.mkdir(parents=True, exist_ok=True)
        try:
            if CLIENTERR.stat().st_size + len(line.encode()) > CLIENTERR_MAX_BYTES:
                os.replace(CLIENTERR, CLIENTERR.with_name(CLIENTERR.name + ".1"))
        except FileNotFoundError:
            pass
        with open(CLIENTERR, "a", encoding="utf-8") as fh:
            fh.write(line)
    return Response(status_code=204)


# ======================================== share pages and preview images ========================================
# The server rewrites the page's title and preview tags for /?ra=&dec= , /?target= and /?q= (the app itself turns
# those queries into hash routes when it loads).
SITE = "SPHEREx Sky Change"
TARGET_ALIASES = ((r"barnard", "barnard"), (r"eps(ilon)?\s*ind", "epsindi"), (r"wise\s*(j?0855|085510)", "wise0855"),
                  (r"^0855$", "wise0855"), (r"^rw\s*aur", "rwaur"), (r"^r\s*dra", "rdra"))     # as web/app/src/sky.js
DEFAULT_OG = "/media/og.jpg"
OG_DIR = DATA / "og"
OG_MAX_BYTES = int(float(os.environ.get("SX_OG_MB", "64")) * 1e6)
OG_PER_MIN = 60               # new preview images rendered per minute (all visitors); beyond that the default one
OG_VERSION = 1
PLACES_TTL_S = 5
COVER_FRACTION = 0.45         # a position is "inside" a place within this fraction of its size from the centre
_og_made: list = []
_og_lock = threading.Lock()
_page = {"key": None, "html": ""}
_places_cache = {"t": 0.0, "v": []}
_HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,253}(:\d{1,5})?|\[[0-9A-Fa-f:.]{2,45}\](:\d{1,5})?")
_NUM_RE = re.compile(r"[+-]?\d{1,3}(\.\d{0,12})?")
_POS_TEXT = re.compile(r"\s*([+-]?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*([+\-−]?\d{1,2}(?:\.\d+)?)\s*")
_TITLE_RE = re.compile(r"<title>.*?</title>", re.S | re.I)
_HEAD_END = re.compile(r"</head>", re.I)
_META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
_TAG_ATTR = re.compile(r"""([\w:-]+)\s*=\s*("[^"]*"|'[^']*')""")


def _desc_of(what):
    return (f"NASA SPHEREx infrared images of {what}: every exposure played in order, "
            "with difference images that show what moved, brightened or faded.")


def _index_html():
    p = DIST / "index.html"
    st = p.stat()
    if _page["key"] != (str(p), st.st_mtime_ns, st.st_size):
        _page["html"], _page["key"] = p.read_text(encoding="utf-8"), (str(p), st.st_mtime_ns, st.st_size)
    return _page["html"]


def _base_url(request: Request):
    """scheme://host as the visitor sees it (the site runs behind a Cloudflare tunnel, which sets X-Forwarded-*)."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip().lower()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if proto not in ("http", "https"):
        proto = "http"
    if not _HOST_RE.fullmatch(host):
        srv = request.scope.get("server") or ("localhost", None)
        host = f"{srv[0]}:{srv[1]}" if srv[1] else str(srv[0])
    return f"{proto}://{host}"


def _num(v):
    v = (v or "").strip().replace("−", "-")
    return float(v) if _NUM_RE.fullmatch(v) else None


def _pos_label(ra, dec, nd=2):
    return f"RA {ra:.{nd}f}°, Dec {dec:.{nd}f}°".replace("-", "−")


def _sep(a, b, c, d):
    r = math.pi / 180
    return math.degrees(math.acos(min(1.0, math.sin(b * r) * math.sin(d * r) + math.cos(b * r) * math.cos(d * r) * math.cos((a - c) * r))))


@lru_cache(maxsize=256)
def _quick_place(qid, mtime):
    p = _preview(qid)
    if not p or p.get("status") != "done":
        return None
    return {"kind": "quick", "id": qid, "name": _pos_label(p["ra"], p["dec"]), "ra": p["ra"], "dec": p["dec"],
            "size": p["size_deg"], "about": "", "dir": QUICK / qid}


def _places():
    """Analysed fields and finished quick looks: where they are, what they are called, where their images are
    (re-read at most every PLACES_TTL_S seconds)."""
    if time.time() - _places_cache["t"] < PLACES_TTL_S:
        return _places_cache["v"]
    out = []
    for p in _live_dirs("*/field.json"):
        try:
            s = _summary(p.parent)
        except Exception:  # noqa: BLE001 - half-written field
            continue
        tg = s.get("target") or {}
        out.append({"kind": "field", "id": s["id"], "name": tg.get("name") or s["name"], "ra": s["ra"], "dec": s["dec"],
                    "size": s["size_deg"], "about": s.get("description") or "", "dir": p.parent, "thumb": s.get("thumb", 0)})
    for d in QUICK.iterdir():
        try:
            q = _quick_place(d.name, (d / "preview.json").stat().st_mtime) if QUICK_ID.fullmatch(d.name) else None
        except OSError:
            q = None
        if q:
            out.append(q)
    _places_cache.update(t=time.time(), v=out)
    return out


def _covering(ra, dec):
    """The field (else the finished quick look) whose centre is nearest a position inside it, as the app picks one."""
    best = None
    for pl in _places():
        d = _sep(ra, dec, pl["ra"], pl["dec"])
        if d < pl["size"] * COVER_FRACTION:
            k = (pl["kind"] != "field", d)
            if best is None or k < best[0]:
                best = (k, pl)
    return best and best[1]


def _target(text):
    """A challenge target name, a field or quick-look id, or a field's name -> that place; else None."""
    t = " ".join(str(text).split())
    if not t:
        return None
    places = _places()
    by_id = {pl["id"].lower(): pl for pl in places}
    if t.lower() in by_id:
        return by_id[t.lower()]
    for rx, fid in TARGET_ALIASES:
        if re.search(rx, t, re.I) and fid in by_id:
            return by_id[fid]
    return next((pl for pl in places if pl["name"].lower() == t.lower()), None)


def _og_source(pl):
    """The picture of a place: the deep colour image, else the last survey pass stacked over all detectors, else
    any stack, else one exposure. Candidates are tried in that order and globbed only when needed."""
    d = pl["dir"]
    tries = (lambda: [d / "deep_rgb.webp"],
             lambda: sorted(d.glob("pass/p*_d0.webp"), reverse=True),
             lambda: sorted(d.glob("stack/p*_d0.webp"), reverse=True),
             lambda: sorted(d.glob("stack/p*_d*.webp"))[:1],
             lambda: [d / "sci" / f"{pl.get('thumb', 0):04d}.webp"],
             lambda: sorted(d.glob("sci/*.webp"))[:1])
    for t in tries:
        p = next((p for p in t() if p.is_file()), None)
        if p:
            return p
    return None


def _share(request: Request):
    """Title, description and preview image (a site path) for this page's query, or None for the plain home page."""
    q = request.query_params
    ra, dec = _num(q.get("ra")), _num(q.get("dec"))
    text = (q.get("target") or q.get("q") or "").strip()
    if (ra is None or dec is None) and text:
        m = _POS_TEXT.fullmatch(text)
        if m:
            ra, dec = _num(m.group(1)), _num(m.group(2))
    if ra is not None and dec is not None and 0 <= ra < 360 and -90 <= dec <= 90:
        pl = _covering(ra, dec)
        desc = (f"NASA SPHEREx infrared images of {_pos_label(ra, dec, 4)}: every exposure since 2025 played in order, "
                "with difference images that show what moved, brightened or faded.")
        if pl and pl["kind"] == "field":
            desc += f" Inside the analysed field “{pl['name']}”."
        img = f"/api/og.jpg?ra={ra:.4f}&dec={dec:.4f}" if pl and _og_source(pl) else DEFAULT_OG
        return {"title": f"{_pos_label(ra, dec)} · {SITE}", "desc": desc, "image": img}
    if text:
        pl = _target(text)
        if pl:
            img = f"/api/og.jpg?id={pl['id']}" if _og_source(pl) else DEFAULT_OG
            return {"title": f"{pl['name']} · {SITE}", "desc": pl["about"] or _desc_of(pl["name"]), "image": img}
        name = text[:60]
        return {"title": f"{name} · {SITE}", "desc": _desc_of(name), "image": DEFAULT_OG}
    return None


def _meta_attrs(tag):
    return {k.lower(): v[1:-1] for k, v in _TAG_ATTR.findall(tag)}


def _meta_get(doc, key):
    for m in _META_TAG.finditer(doc):
        a = _meta_attrs(m.group(0))
        if key in (a.get("name"), a.get("property")):
            return html.unescape(a.get("content", ""))
    return None


def _meta_set(doc, attr, key, value):
    """Replace the <meta name|property=key> tag (inserted before </head> if missing) with one carrying value."""
    tag = f'<meta {attr}="{key}" content="{html.escape(value, quote=True)}" />'
    done = []

    def sub(m):
        a = _meta_attrs(m.group(0))
        if key not in (a.get("name"), a.get("property")):
            return m.group(0)
        out = "" if done else tag
        done.append(1)
        return out
    doc = _META_TAG.sub(sub, doc)
    if not done:
        doc = _HEAD_END.sub(lambda _: f"  {tag}\n</head>", doc, count=1)
    return doc


def share_page(request: Request):
    """index.html with this link's title, description and preview image; og:image is always an absolute URL."""
    doc = _index_html()
    base = _base_url(request)
    sh = _share(request)
    if sh:
        title, desc, image = sh["title"], sh["desc"], sh["image"]
        doc = _TITLE_RE.sub(lambda _: f"<title>{html.escape(title, quote=False)}</title>", doc, count=1)
        doc = _meta_set(doc, "name", "description", desc)
    else:
        title = _meta_get(doc, "og:title") or "SPHEREx Sky Change Explorer"
        desc = _meta_get(doc, "og:description") or _meta_get(doc, "description") or ""
        image = _meta_get(doc, "og:image") or DEFAULT_OG
    image = image if re.match(r"https?://", image) else base + "/" + image.lstrip("/")
    url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    for attr, key, value in (("property", "og:title", title), ("property", "og:description", desc), ("property", "og:image", image),
                             ("property", "og:url", url), ("name", "twitter:card", _meta_get(doc, "twitter:card") or "summary_large_image"),
                             ("name", "twitter:title", title), ("name", "twitter:description", desc), ("name", "twitter:image", image)):
        doc = _meta_set(doc, attr, key, value)
    return doc


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
def spa_index(request: Request):
    if not (DIST / "index.html").exists():
        raise HTTPException(404, "Not Found")
    return HTMLResponse(share_page(request), headers={"Cache-Control": "no-cache"})


def _og_render(src, title, sub):
    from web import og
    return og.render(src, title, sub)


def _og_prune():
    files = sorted(((p.stat().st_mtime, p.stat().st_size, p) for p in OG_DIR.glob("*.jpg")), key=lambda t: t[0])
    total = sum(s for _, s, _ in files)
    for _, s, p in files:
        if total <= OG_MAX_BYTES * 0.8:
            break
        p.unlink(missing_ok=True)
        total -= s


def _og_default(cache):
    return RedirectResponse(DEFAULT_OG, status_code=302, headers={"Cache-Control": cache})


@app.get("/api/og.jpg")
def og_image(ra: str | None = None, dec: str | None = None, id: str | None = None):
    """Link-preview picture (1200 x 630) for a position or a field / quick-look id, from that place's own images;
    the site's default picture when there is none. Rendered once and kept under web/data/og/."""
    pl, title, sub = None, "", ""
    if id and re.fullmatch(r"[\w.+-]{1,64}", id):
        pl = next((p for p in _places() if p["id"].lower() == id.lower()), None)
        if pl:
            title, sub = pl["name"], _pos_label(pl["ra"], pl["dec"]) + f" · {pl['size']:g}° field"
    else:
        a, b = _num(ra), _num(dec)
        if a is not None and b is not None and 0 <= a < 360 and -90 <= b <= 90:
            pl = _covering(a, b)
            if pl:
                title = _pos_label(a, b)
                sub = (pl["name"] + " · " if pl["kind"] == "field" else "") + f"{pl['size']:g}° field"
    src = _og_source(pl) if pl else None
    if not src:
        return _og_default(CACHE_HOUR)
    key = hashlib.sha256(f"{OG_VERSION}|{src}|{src.stat().st_mtime_ns}|{title}|{sub}".encode()).hexdigest()[:24]
    out = OG_DIR / f"{key}.jpg"
    if not out.exists():
        now = time.time()
        with _og_lock:
            _og_made[:] = [t for t in _og_made if now - t < 60]
            if len(_og_made) >= OG_PER_MIN:
                return _og_default("no-store")
            _og_made.append(now)
            OG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(_og_render(src, title, sub))
            os.replace(tmp, out)
            _og_prune()
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


# ======================================== feature modules and static files ========================================
# Every web/api_<name>.py that defines `router` (a FastAPI APIRouter) is served here, so a feature keeps its endpoints
# in its own file. Included before the static mounts, which would otherwise answer every path.
def _include_feature_routers():
    import importlib
    for f in sorted((ROOT / "web").glob("api_*.py")):
        mod = importlib.import_module(f"web.{f.stem}")
        if getattr(mod, "router", None) is not None:
            app.include_router(mod.router)


_include_feature_routers()
app.mount("/data", StaticFiles(directory=DATA), name="data")
app.mount("/legacy", StaticFiles(directory=ROOT / "web" / "legacy", html=True, check_dir=False), name="legacy")
app.mount("/", StaticFiles(directory=DIST, html=True, check_dir=False), name="app")
