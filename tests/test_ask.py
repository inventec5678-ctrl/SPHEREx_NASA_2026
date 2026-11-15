"""POST /api/ask and GET /api/ask/health: the stub stream, site facts, validation, limits, retrieval over a tiny index.
No network and no embedding model: retrieval is monkeypatched (or given a fake encoder)."""
import json

import numpy as np
import pytest

from asgi_client import get, post_json, request
from web import api_ask as A
from web import server

_real_retrieve = A.retrieve          # captured at import, before the autouse fixture replaces it

CHUNK = {"id": "p1#0", "paper_id": "p1", "title": "SPHEREx: An All-Sky Spectral Survey", "authors": "Doré et al.",
         "year": 2014, "arxiv": "1412.4872", "url": "https://arxiv.org/abs/1412.4872",
         "text": "SPHEREx will perform an all-sky near-infrared spectral survey " * 20}


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    monkeypatch.setattr(A, "LLM_URL", "stub")
    monkeypatch.setattr(A, "STUB_DELAY_S", 0)
    monkeypatch.setattr(A, "retrieve", lambda q, k=A.TOP_K: [])
    A._ip_min.clear()
    A._ip_day.clear()
    A._inflight["n"] = 0
    yield
    A._ip_min.clear()
    A._ip_day.clear()
    A._inflight["n"] = 0


def _events(r):
    assert r.status_code == 200, r.text
    out = []
    for block in r.text.split("\n\n"):
        if block.strip():
            assert block.startswith("data: ")
            out.append(json.loads(block[6:]))
    return out


def _answer(evs):
    return "".join(e["text"] for e in evs if e["type"] == "token")


def test_stub_stream_order_and_headers(monkeypatch):
    real = A.stub_answer
    monkeypatch.setattr(A, "stub_answer", lambda req, s: real(req, s) + " ..." * 400)   # past the gzip minimum size
    r = post_json(server.app, "/api/ask", {"question": "What is SPHEREx?", "lang": "en"}, headers={"accept-encoding": "gzip"})
    evs = _events(r)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-accel-buffering"] == "no"
    assert "content-encoding" not in r.headers                      # not gzip-buffered
    assert evs[0] == {"type": "sources", "items": []}
    assert evs[-1] == {"type": "done", "grounded": False, "model": "stub"}
    tokens = [e for e in evs[1:-1]]
    assert len(tokens) > 3 and all(e["type"] == "token" for e in tokens)
    assert "no source" in _answer(evs)
    assert A._inflight["n"] == 0                                    # the slot was given back


def test_stub_mentions_context_and_sources(monkeypatch):
    seen = []
    monkeypatch.setattr(A, "retrieve", lambda q, k=A.TOP_K: seen.append(q) or [CHUNK | {"score": 0.8}])
    evs = _events(post_json(server.app, "/api/ask", {"question": "How fast does it move?", "lang": "zh-Hant",
                                                     "context": {"kind": "target", "id": "barnard", "name": "Barnard's Star"}}))
    (src,) = evs[0]["items"]
    assert set(src) == {"id", "title", "authors", "year", "arxiv", "url", "snippet"}
    assert src["year"] == 2014 and src["arxiv"] == "1412.4872" and len(src["snippet"]) <= A.SNIPPET_CHARS + 3
    text = _answer(evs)
    assert "Barnard's Star" in text and CHUNK["title"] in text and "示範" in text
    assert evs[-1]["grounded"] is True
    assert seen == ["target Barnard's Star: How fast does it move?"]       # context goes into the retrieval query


def test_site_facts_in_prompt(monkeypatch):
    captured = {}

    async def fake_llm(messages):
        captured["messages"] = messages
        for t in ("Barnard's ", "Star moves ", "10.4\"/yr."):
            yield t
    monkeypatch.setattr(A, "llm_tokens", fake_llm)
    evs = _events(post_json(server.app, "/api/ask", {
        "question": "How many exposures?", "lang": "en",
        "history": [{"role": "user", "content": f"q{k}"} if k % 2 == 0 else {"role": "assistant", "content": f"a{k}"}
                    for k in range(12)],
        "context": {"kind": "field", "id": "barnard", "name": "Barnard's Star", "ra": 269.45, "dec": 4.74,
                    "facts": {"tab": "lab", "frame": 3}}}))
    assert _answer(evs) == "Barnard's Star moves 10.4\"/yr." and evs[-1]["model"] == A.LLM_MODEL
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system" and "English" in msgs[0]["content"] and "[1]" in msgs[0]["content"]
    assert [m["content"] for m in msgs[1:-1]] == [f"q{k}" if k % 2 == 0 else f"a{k}" for k in range(4, 12)]   # last 8 turns
    user = msgs[-1]["content"]
    n_exp = len(json.loads((A.FIELDS / "barnard" / "field.json").read_text(encoding="utf-8"))["exposures"])
    assert f"SPHEREx exposures analysed: {n_exp}" in user and "Target measurement:" in user and "pm_total=" in user
    assert "frame=3" in user and user.endswith("Question: How many exposures?")
    facts = A.site_facts(A.Context(kind="field", id="barnard"))
    assert facts in user and 0 < len(facts) <= A.FACTS_MAX_CHARS


def test_no_facts_for_other_kinds_or_unknown_ids():
    assert A.site_facts(A.Context(kind="star", id="barnard")) == ""
    assert A.site_facts(A.Context(kind="field", id="no_such_field")) == ""
    assert A.site_facts(A.Context(kind="field", id="../barnard")) == ""
    assert A.site_facts(None) == ""


def test_llm_failure_mid_stream_sends_error(monkeypatch):
    async def broken(messages):
        yield "partial "
        raise A.LLMFailed("llm_failed")
    monkeypatch.setattr(A, "llm_tokens", broken)
    evs = _events(post_json(server.app, "/api/ask", {"question": "hi", "lang": "en"}))
    assert [e["type"] for e in evs] == ["sources", "token", "error"] and evs[-1]["message"] == "llm_failed"


def test_unreachable_server_falls_back_to_stub(monkeypatch):
    monkeypatch.setattr(A, "LLM_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(A, "LLM_CONNECT_S", 1.0)
    evs = _events(post_json(server.app, "/api/ask", {"question": "hi", "lang": "en"}))
    assert evs[-1] == {"type": "done", "grounded": False, "model": "stub"}


@pytest.mark.parametrize("body", [
    {},
    {"question": ""},
    {"question": "   "},
    {"question": "x" * 1001},
    {"question": "hi", "lang": "fr"},
    {"question": "hi", "history": [{"role": "system", "content": "x"}]},
    {"question": "hi", "context": {"kind": "galaxy"}},
    {"question": "hi", "context": {"kind": "field", "facts": {f"k{i}": i for i in range(21)}}},
    {"question": "hi", "context": {"kind": "field", "dec": 91}},
])
def test_validation_errors(body):
    r = post_json(server.app, "/api/ask", body)
    assert r.status_code == 422
    assert "x" * 50 not in r.text                                    # what was typed is not echoed back


def test_bad_json_and_oversized_body():
    assert request(server.app, "POST", "/api/ask", {"content-type": "application/json"}, b"not json").status_code == 422
    big = {"question": "hi", "history": [{"role": "user", "content": "y" * 3999}] * 20}
    r = post_json(server.app, "/api/ask", big)
    assert r.status_code == 422 and r.json()["detail"] == "too_large"
    assert not A._ip_min                                             # rejected requests do not count


def test_rate_limit_per_visitor(monkeypatch):
    monkeypatch.setattr(A, "PER_MIN", 3)
    for _ in range(3):
        assert post_json(server.app, "/api/ask", {"question": "hi"}, client_ip="198.51.100.9").status_code == 200
    r = post_json(server.app, "/api/ask", {"question": "hi"}, client_ip="198.51.100.9")
    assert r.status_code == 429 and r.json() == {"detail": "slow_down"} and "retry-after" in r.headers
    assert post_json(server.app, "/api/ask", {"question": "hi"}, client_ip="198.51.100.10").status_code == 200


def test_daily_limit(monkeypatch):
    monkeypatch.setattr(A, "PER_DAY", 2)
    for _ in range(2):
        assert post_json(server.app, "/api/ask", {"question": "hi"}).status_code == 200
    r = post_json(server.app, "/api/ask", {"question": "hi"})
    assert r.status_code == 429 and r.json()["detail"] == "daily_limit"


def test_concurrency_cap(monkeypatch):
    A._inflight["n"] = A.MAX_INFLIGHT
    r = post_json(server.app, "/api/ask", {"question": "hi"})
    assert r.status_code == 429 and r.json()["detail"] == "busy"
    A._inflight["n"] = 0
    assert post_json(server.app, "/api/ask", {"question": "hi"}).status_code == 200 and A._inflight["n"] == 0


def test_health(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "INDEX_DIR", tmp_path)                  # no index there
    monkeypatch.setattr(A, "_index", {"loaded": False, "chunks": [], "emb": None, "papers": 0})
    r = get(server.app, "/api/ask/health")
    assert r.status_code == 200 and r.json() == {"llm": "stub", "index": {"chunks": 0, "papers": 0}}
    assert r.headers["cache-control"] == "no-store"


class _FakeEncoder:
    def __init__(self, vec):
        self.vec, self.seen = vec, []

    def encode(self, texts, normalize_embeddings=False):
        self.seen += texts
        return np.array([self.vec], dtype="float32")


def test_retrieve_over_tiny_index(monkeypatch, tmp_path):
    chunks = [CHUNK | {"id": f"p{i}#0", "paper_id": f"p{i // 2}", "title": f"Paper {i}"} for i in range(4)]
    (tmp_path / "chunks.jsonl").write_text("\n".join(json.dumps(c) for c in chunks), encoding="utf-8")
    np.save(tmp_path / "embeddings.npy", np.eye(4, dtype="float32"))
    monkeypatch.setattr(A, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(A, "_index", {"loaded": False, "chunks": [], "emb": None, "papers": 0})
    v = np.array([0.05, 0.8, 0.0, 0.75], dtype="float32")             # scores 0.05, 0.73, 0, 0.68 after normalising
    enc = _FakeEncoder(v / np.linalg.norm(v))
    monkeypatch.setattr(A, "_embed", {"model": enc, "failed_at": None})
    monkeypatch.setattr(A, "retrieve", _real_retrieve)
    hits = A.retrieve("why", k=5)
    assert [h["title"] for h in hits] == ["Paper 1", "Paper 3"]       # 0.73 and 0.68 pass MIN_SCORE, 0.05 and 0 do not
    assert hits[0]["score"] > hits[1]["score"] >= A.MIN_SCORE
    assert enc.seen == [A.QUERY_PREFIX + "why"]
    r = get(server.app, "/api/ask/health")
    assert r.json()["index"] == {"chunks": 4, "papers": 2}


def test_retrieve_without_model_is_empty(monkeypatch, tmp_path):
    (tmp_path / "chunks.jsonl").write_text(json.dumps(CHUNK), encoding="utf-8")
    np.save(tmp_path / "embeddings.npy", np.ones((1, 4), dtype="float32") / 2)
    monkeypatch.setattr(A, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(A, "_index", {"loaded": False, "chunks": [], "emb": None, "papers": 0})
    monkeypatch.setattr(A, "_embed", {"model": None, "failed_at": 1e18})     # a load failed just now: not retried
    assert _real_retrieve("anything") == []
