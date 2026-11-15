"""POST /api/clienterr: truncation, no IPs stored, rate limits, file rotation."""
import json

import pytest

from asgi_client import post_json, request
from web import server


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    p = tmp_path / "out" / "clienterr.jsonl"
    monkeypatch.setattr(server, "CLIENTERR", p)
    server._cerr_ip.clear()
    server._cerr_all.clear()
    yield p
    server._cerr_ip.clear()
    server._cerr_all.clear()


def _lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


def test_truncation_and_no_ip(log):
    r = post_json(server.app, "/api/clienterr", {"msg": "m" * 1000, "stack": "s" * 5000, "route": "#/sky/" + "r" * 300 + "?q=secret",
                                                 "ua": "u" * 500, "extra": "dropped"}, client_ip="203.0.113.7")
    assert r.status_code == 204 and r.content == b""
    (rec,) = _lines(log)
    assert set(rec) == {"t", "msg", "stack", "route", "ua"}
    assert len(rec["msg"]) == 300 and len(rec["stack"]) == 2000 and len(rec["ua"]) == 200 and len(rec["route"]) == 200
    assert rec["t"].endswith("Z")
    assert "203.0.113.7" not in log.read_text(encoding="utf-8") and server._ip_key("203.0.113.7") not in log.read_text(encoding="utf-8")


def test_query_dropped_from_route(log):
    post_json(server.app, "/api/clienterr", {"msg": "x", "stack": "", "route": "#/sky/Barnard?fov=0.15&k=3", "ua": "UA"})
    post_json(server.app, "/api/clienterr", {"msg": 5, "route": None})
    a, b = _lines(log)
    assert a["route"] == "#/sky/Barnard"
    assert b["msg"] == "5" and b["route"] == "" and b["stack"] == ""


def test_bad_bodies(log):
    assert request(server.app, "POST", "/api/clienterr", {"content-type": "application/json"}, b"not json").status_code == 400
    assert request(server.app, "POST", "/api/clienterr", {"content-type": "application/json"}, b"[1,2]").status_code == 400
    assert request(server.app, "POST", "/api/clienterr", {"content-type": "application/json"}, b"x" * 40000).status_code == 413
    assert not log.exists()


def test_rate_limit_per_ip_and_per_day(log, monkeypatch):
    for k in range(20):
        assert post_json(server.app, "/api/clienterr", {"msg": str(k)}, client_ip="198.51.100.1").status_code == 204
    r = post_json(server.app, "/api/clienterr", {"msg": "21"}, client_ip="198.51.100.1")
    assert r.status_code == 429
    assert post_json(server.app, "/api/clienterr", {"msg": "other"}, client_ip="198.51.100.2").status_code == 204
    assert len(_lines(log)) == 21
    monkeypatch.setattr(server, "CLIENTERR_PER_DAY", 22)
    assert post_json(server.app, "/api/clienterr", {"msg": "a"}, client_ip="198.51.100.3").status_code == 204
    assert post_json(server.app, "/api/clienterr", {"msg": "b"}, client_ip="198.51.100.4").status_code == 429


def test_rotation(log, monkeypatch):
    monkeypatch.setattr(server, "CLIENTERR_MAX_BYTES", 400)
    for k in range(6):
        assert post_json(server.app, "/api/clienterr", {"msg": "x" * 100}, client_ip=f"192.0.2.{k}").status_code == 204
    old = log.with_name("clienterr.jsonl.1")
    assert old.exists() and log.stat().st_size <= 400 and old.stat().st_size <= 400
