"""The in-site assistant: a question about the page being viewed, answered from the indexed papers and the site's own
numbers, streamed back as server-sent events.

  POST /api/ask         {question, lang, history?, context?}  ->  text/event-stream
  GET  /api/ask/health  {"llm": "up"|"down"|"stub", "index": {"chunks", "papers"}}

Events (one JSON `data:` line each): {"type":"sources","items":[...]} first (may be empty), then many
{"type":"token","text":...}, then {"type":"done","grounded":bool,"model":str}; {"type":"error","message":...} on failure.

Retrieval: llm/index/chunks.jsonl + embeddings.npy (L2-normalised, same order), queried with a sentence-transformers
model (SX_EMBED_MODEL); both are loaded on the first question and kept in memory. Without them retrieval is empty and
the assistant still answers (ungrounded). The language model is any OpenAI-compatible chat-completions server
(SX_LLM_URL, SX_LLM_MODEL); with SX_LLM_URL=stub, or when that server cannot be reached, a canned answer is streamed so
the page still works. See llm/README.md. Question text is never logged or stored.
"""
import asyncio
import json
import os
import re
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from web.common import rate_ok, visitor  # noqa: E402

router = APIRouter()

INDEX_DIR = ROOT / "llm" / "index"
FIELDS = ROOT / "web" / "data" / "fields"
EMBED_MODEL = os.environ.get("SX_EMBED_MODEL", "BAAI/bge-m3")   # multilingual: Chinese questions find English papers
QUERY_PREFIX, PASSAGE_PREFIX = "", ""     # bge-m3 needs none; llm/build_index.py embeds passages with PASSAGE_PREFIX
LLM_URL = os.environ.get("SX_LLM_URL", "http://127.0.0.1:8800/v1")
LLM_MODEL = os.environ.get("SX_LLM_MODEL", "spherex-assistant")
LLM_TIMEOUT_S = float(os.environ.get("SX_LLM_TIMEOUT", "60"))   # between streamed chunks
LLM_CONNECT_S = 3.0
MAX_TOKENS, TEMPERATURE = 512, 0.3
TOP_K = 5
MIN_SCORE = 0.53                 # cosine, bge-m3 on this index: 16 off-topic en/zh questions top out at 0.39-0.53,
                                 # 22 on-topic ones score 0.51-0.74 (multilingual-e5-small overlapped: 0.77-0.85 vs 0.81-0.91)
SNIPPET_CHARS, PASSAGE_CHARS = 300, 1200
FACTS_MAX_CHARS = 1500
HISTORY_TURNS, HISTORY_CHARS = 8, 2000
MAX_BODY = 64 * 1024
PER_MIN, PER_DAY = int(os.environ.get("SX_ASK_PER_MIN", "10")), int(os.environ.get("SX_ASK_PER_DAY", "200"))
MAX_INFLIGHT = int(os.environ.get("SX_ASK_INFLIGHT", "4"))
RATE_KEYS_MAX = 5000
EMBED_RETRY_S = 300              # a failed model load is tried again after this long
HEALTH_TTL_S = 15
STUB_MODEL, STUB_DELAY_S, STUB_CHUNK = "stub", 0.015, 6
ID_RE = re.compile(r"[\w.+-]{1,64}")

_ip_min: dict = {}
_ip_day: dict = {}
_inflight = {"n": 0}
_load_lock = threading.Lock()
_index: dict = {"loaded": False, "chunks": [], "emb": None, "papers": 0}
_embed: dict = {"model": None, "failed_at": None}
_health_cache: dict = {"t": 0.0, "llm": None}


# ======================================== request ========================================
Kind = Literal["field", "target", "object", "star", "body", "page", "room"]


class Turn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class Context(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Kind
    id: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)
    ra: float | None = Field(default=None, ge=-360, le=360, allow_inf_nan=False)
    dec: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    facts: dict[str, str | int | float] | None = None

    @field_validator("facts")
    @classmethod
    def _small_facts(cls, v):
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("at most 20 facts")
        for k, x in v.items():
            if len(k) > 60 or (isinstance(x, str) and len(x) > 300):
                raise ValueError("fact too long")
            if isinstance(x, float) and x != x:
                raise ValueError("fact is NaN")
        return v


class AskReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field(min_length=1, max_length=1000)
    lang: Literal["en", "zh-Hant"] = "en"
    history: list[Turn] = Field(default_factory=list, max_length=40)
    context: Context | None = None

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip():
            raise ValueError("blank question")
        return v.strip()


async def _read_body(request: Request):
    """The raw body, refused with 422 past MAX_BODY bytes (read in pieces, so a huge body is not held in memory)."""
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(422, "too_large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise HTTPException(422, "too_large")
    return bytes(body)


# ======================================== retrieval ========================================
def _load_index():
    """chunks.jsonl + embeddings.npy, once. A missing or inconsistent index leaves an empty one."""
    if _index["loaded"]:
        return _index
    with _load_lock:
        if _index["loaded"]:
            return _index
        chunks, emb = [], None
        try:
            import numpy as np
            with open(INDEX_DIR / "chunks.jsonl", encoding="utf-8") as fh:
                chunks = [json.loads(line) for line in fh if line.strip()]
            emb = np.load(INDEX_DIR / "embeddings.npy").astype("float32", copy=False)
            if emb.ndim != 2 or emb.shape[0] != len(chunks):
                chunks, emb = [], None
        except (OSError, ValueError, ImportError):
            chunks, emb = [], None
        _index.update(loaded=True, chunks=chunks, emb=emb, papers=len({c.get("paper_id") for c in chunks}))
        return _index


def _embedder():
    """The sentence-transformers query model, or None when it (or the package) is not available."""
    if _embed["model"] is not None:
        return _embed["model"]
    if _embed["failed_at"] and time.time() - _embed["failed_at"] < EMBED_RETRY_S:
        return None
    with _load_lock:
        if _embed["model"] is None:
            try:
                from sentence_transformers import SentenceTransformer
                _embed["model"] = SentenceTransformer(EMBED_MODEL, device="cpu")
                _embed["failed_at"] = None
            except Exception:  # noqa: BLE001 - package missing, model not downloaded, bad path
                _embed["failed_at"] = time.time()
        return _embed["model"]


def retrieve(query: str, k: int = TOP_K):
    """Up to k index chunks with cosine >= MIN_SCORE, best first, each with its "score"; [] without an index/model."""
    idx = _load_index()
    if idx["emb"] is None or not idx["chunks"]:
        return []
    model = _embedder()
    if model is None:
        return []
    import numpy as np
    q = np.asarray(model.encode([QUERY_PREFIX + query], normalize_embeddings=True), dtype="float32").reshape(-1)
    if q.shape[0] != idx["emb"].shape[1]:
        return []
    scores = idx["emb"] @ q
    k = min(k, len(scores))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [idx["chunks"][i] | {"score": float(scores[i])} for i in top if scores[i] >= MIN_SCORE]


def _query_text(req: AskReq):
    c = req.context
    if c and (c.name or c.id):
        return f"{c.kind} {c.name or c.id}: {req.question}"
    return req.question


def _source_item(c):
    year = c.get("year")
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = 0
    text = " ".join(str(c.get("text", "")).split())
    return {"id": str(c.get("id", "")), "title": str(c.get("title", "")), "authors": str(c.get("authors", "")),
            "year": year, "arxiv": str(c.get("arxiv", "") or ""), "url": str(c.get("url", "") or ""),
            "snippet": text[:SNIPPET_CHARS] + ("..." if len(text) > SNIPPET_CHARS else "")}


# ======================================== site facts ========================================
def _num(x, nd=7):
    if isinstance(x, float):
        return f"{round(x, 4):.{nd}g}" if abs(x) >= 1e-3 or x == 0 else f"{x:.3e}"
    return str(x)


def _mjd_date(mjd):
    return time.strftime("%Y-%m-%d", time.gmtime((mjd - 40587) * 86400))


@lru_cache(maxsize=32)
def _facts_at(fid, mtime_ns):
    d = json.loads((FIELDS / fid / "field.json").read_text(encoding="utf-8"))
    lines = [f"Field \"{d.get('name', fid)}\" (id {fid}): centre RA {_num(float(d['ra']), 7)} deg, "
             f"Dec {_num(float(d['dec']), 6)} deg, {d.get('size_deg', '?')} deg wide."]
    if d.get("description"):
        lines.append("About: " + str(d["description"])[:300])
    ex = d.get("exposures") or []
    mjds = [e["mjd"] for e in ex if isinstance(e.get("mjd"), (int, float))]
    lines.append(f"SPHEREx exposures analysed: {len(ex)}"
                 + (f", {_mjd_date(min(mjds))} to {_mjd_date(max(mjds))}." if mjds else "."))
    tracks = d.get("tracks") or []
    lines.append(f"Moving-object tracks found: {len(tracks)} ({sum(1 for t in tracks if t.get('known'))} matched to known "
                 f"bodies); known bodies predicted in the field: {len(d.get('known_bodies') or [])}.")
    t = d.get("target")
    if isinstance(t, dict) and t:
        parts = [f"{k}={_num(v)}" for k, v in t.items()
                 if k not in ("id", "about", "points") and isinstance(v, (str, int, float)) and not isinstance(v, bool)]
        for sub in ("motion", "vsx"):
            if isinstance(t.get(sub), dict):
                parts += [f"{sub}.{k}={_num(v)}" for k, v in t[sub].items()
                          if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
        units = "pmra/pmdec in mas/yr, pm_total in arcsec/yr, plx in mas, ra/dec in deg"
        if isinstance(t.get("motion"), dict):
            units += "; motion.*_arcsec = shift over motion.days days"
        lines.append(f"Target measurement: {', '.join(parts)}. ({units})")
        if t.get("about") and t["about"] != d.get("description"):
            lines.append("Target: " + str(t["about"])[:300])
    out = "\n".join(lines)
    return out if len(out) <= FACTS_MAX_CHARS else out[:FACTS_MAX_CHARS - 3] + "..."


def site_facts(ctx: "Context | None"):
    """A short facts block for a field or target page, from web/data/fields/<id>/field.json; "" otherwise."""
    if not ctx or ctx.kind not in ("field", "target") or not ctx.id or not ID_RE.fullmatch(ctx.id):
        return ""
    p = FIELDS / ctx.id / "field.json"
    try:
        return _facts_at(ctx.id, p.stat().st_mtime_ns)
    except (OSError, ValueError, KeyError, TypeError):
        return ""


# ======================================== prompt ========================================
SYSTEM_PROMPT = """You are the SPHEREx Sky Change assistant, built into a website that shows how the infrared sky \
changes in NASA SPHEREx survey images: moving asteroids and comets, high proper-motion stars, variable stars and the \
site's own measurements of them.

Rules:
- Answer in {language}, whatever language the passages are in.
- The user message may contain numbered source passages from scientific papers. When you use a passage, cite it \
inline as [1], [2], ... using its number. Never cite a number that is not listed, and never invent papers.
- The user message may contain site facts measured by this website. Use them for any number about the field or \
object being viewed, and say they are this site's measurements.
- If no passage covers the question, you may answer from general knowledge, but say clearly that this part of the \
answer has no source.
- Be concise (a short paragraph or a few bullet points), accurate and friendly to non-specialists. If you do not \
know, say so."""

LANG_NAME = {"en": "English", "zh-Hant": "Traditional Chinese (繁體中文, as used in Taiwan)"}


def build_messages(req: AskReq, sources, facts):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(language=LANG_NAME[req.lang])}]
    for t in req.history[-HISTORY_TURNS:]:
        msgs.append({"role": t.role, "content": t.content[:HISTORY_CHARS]})
    parts = []
    if sources:
        parts.append("Source passages:\n" + "\n\n".join(
            f"[{n}] {c.get('title', '')} ({c.get('authors', '')}, {c.get('year', '')})\n"
            + " ".join(str(c.get("text", "")).split())[:PASSAGE_CHARS] for n, c in enumerate(sources, 1)))
    else:
        parts.append("Source passages: none found for this question.")
    c = req.context
    if c:
        page = [f"kind={c.kind}"] + [f"{k}={v}" for k, v in (("id", c.id), ("name", c.name), ("ra", c.ra), ("dec", c.dec))
                                     if v is not None]
        page += [f"{k}={v}" for k, v in (c.facts or {}).items()]
        parts.append("The user is viewing: " + ", ".join(page))
    if facts:
        parts.append("Site facts (measured by this website):\n" + facts)
    parts.append("Question: " + req.question)
    msgs.append({"role": "user", "content": "\n\n".join(parts)})
    return msgs


# ======================================== generation ========================================
class LLMUnreachable(Exception):
    pass


class LLMFailed(Exception):
    pass


async def llm_tokens(messages):
    """Stream the answer's text pieces from the OpenAI-compatible server. LLMUnreachable before anything is sent when
    the server (or httpx) is not there; LLMFailed for any other failure."""
    if LLM_URL.strip().lower() == "stub":
        raise LLMUnreachable("stub")
    try:
        import httpx
    except ImportError as e:
        raise LLMUnreachable("httpx missing") from e
    payload = {"model": LLM_MODEL, "messages": messages, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE,
               "stream": True}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(LLM_TIMEOUT_S, connect=LLM_CONNECT_S)) as client:
            async with client.stream("POST", LLM_URL.rstrip("/") + "/chat/completions", json=payload) as r:
                if r.status_code != 200:
                    raise LLMFailed(f"llm_status_{r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        text = (json.loads(data)["choices"][0].get("delta") or {}).get("content")
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if text:
                        yield text
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise LLMUnreachable("unreachable") from e
    except httpx.HTTPError as e:
        raise LLMFailed("llm_failed") from e


def stub_answer(req: AskReq, sources):
    name = (req.context.name or req.context.id) if req.context else None
    titles = [str(s.get("title", "")) for s in sources]
    if req.lang == "zh-Hant":
        out = "（示範回答：語言模型尚未上線。）"
        out += f"你正在看「{name}」。" if name else ""
        out += f"你問的是：「{req.question[:80]}」。"
        out += ("相關文獻：" + "；".join(f"[{n}] {t}" for n, t in enumerate(titles, 1)) + "。") if titles else "沒有找到相關文獻，這個回答沒有來源。"
    else:
        out = "(Demo answer: the language model is not online yet.) "
        out += f"You are looking at {name}. " if name else ""
        out += f"You asked: \"{req.question[:80]}\". "
        out += ("Related papers: " + "; ".join(f"[{n}] {t}" for n, t in enumerate(titles, 1)) + ".") if titles else \
            "No source covers this question, so this answer has no source."
    return out


async def stub_tokens(text):
    for i in range(0, len(text), STUB_CHUNK):
        if STUB_DELAY_S:
            await asyncio.sleep(STUB_DELAY_S)
        yield text[i:i + STUB_CHUNK]


def _sse(ev):
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")


async def _events(req: AskReq):
    try:
        sources = await asyncio.to_thread(retrieve, _query_text(req))
    except Exception:  # noqa: BLE001 - a broken index must not break the assistant
        sources = []
    yield _sse({"type": "sources", "items": [_source_item(c) for c in sources]})
    model, started = LLM_MODEL, False
    try:
        try:
            async for text in llm_tokens(build_messages(req, sources, site_facts(req.context))):
                started = True
                yield _sse({"type": "token", "text": text})
        except LLMUnreachable:
            if started:
                raise LLMFailed("llm_failed")
            model = STUB_MODEL
            async for text in stub_tokens(stub_answer(req, sources)):
                yield _sse({"type": "token", "text": text})
    except LLMFailed as e:
        yield _sse({"type": "error", "message": str(e) or "llm_failed"})
        return
    except Exception:  # noqa: BLE001 - never leak internals into the page
        yield _sse({"type": "error", "message": "internal_error"})
        return
    yield _sse({"type": "done", "grounded": bool(sources), "model": model})


class _EventStream(StreamingResponse):
    """Frees the request's concurrency slot when the response ends, however it ends (finished, client gone, error),
    even if the body generator never started."""
    def __init__(self, content, release):
        super().__init__(content, media_type="text/event-stream",
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        self._release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


def _limited(detail, retry_after):
    return JSONResponse({"detail": detail}, status_code=429, headers={"Retry-After": str(retry_after)})


# ======================================== endpoints ========================================
@router.post("/api/ask")
async def ask(request: Request):
    body = await _read_body(request)
    try:
        req = AskReq.model_validate_json(body or b"{}")
    except ValidationError as e:          # the error list, without echoing what was typed
        return JSONResponse({"detail": e.errors(include_url=False, include_input=False, include_context=False)},
                            status_code=422)
    if _inflight["n"] >= MAX_INFLIGHT:
        return _limited("busy", 5)
    ipk = visitor(request)
    if not rate_ok(_ip_min, ipk, PER_MIN, 60):
        return _limited("slow_down", 30)
    if not rate_ok(_ip_day, ipk, PER_DAY, 86400):
        return _limited("daily_limit", 3600)
    for store in (_ip_min, _ip_day):                 # forget everyone else rather than grow without bound
        if len(store) > RATE_KEYS_MAX:
            mine = store[ipk]
            store.clear()
            store[ipk] = mine
    _inflight["n"] += 1
    done = []

    def release():
        if not done:
            done.append(1)
            _inflight["n"] -= 1
    return _EventStream(_events(req), release)


async def _llm_state():
    if LLM_URL.strip().lower() == "stub":
        return "stub"
    now = time.time()
    if _health_cache["llm"] and now - _health_cache["t"] < HEALTH_TTL_S:
        return _health_cache["llm"]
    state = "down"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.5)) as client:
            r = await client.get(LLM_URL.rstrip("/") + "/models")
            state = "up" if r.status_code < 500 else "down"
    except Exception:  # noqa: BLE001 - httpx missing or server unreachable
        state = "down"
    _health_cache.update(t=now, llm=state)
    return state


@router.get("/api/ask/health")
async def ask_health():
    idx = await asyncio.to_thread(_load_index)
    return {"llm": await _llm_state(), "index": {"chunks": len(idx["chunks"]), "papers": idx["papers"]}}
