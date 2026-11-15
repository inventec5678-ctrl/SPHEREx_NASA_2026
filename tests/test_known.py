"""JPL known-object lookup: a failed query must be reported as failed, never as "no known bodies"."""
import numpy as np
import pytest
import requests

from sxlib import archive, known

ROW = ["65 Cybele (A861 EB)", "11:54:02.12", "+01 05'28.5\"", "0", "0", "0", "13.2", "23.98", "-8.477"]
FIELDS = ["Object name", "Astrometric RA (hh:mm:ss)", "Astrometric Dec (dd mm'ss\")", "Dist. from center RA (\")",
          "Dist. from center Dec (\")", "Dist. from center Norm (\")", "Visual magnitude (V)", "RA rate (\"/h)",
          "Dec rate (\"/h)"]


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


class _Field:
    ra, dec = 178.6, 1.1

    def __init__(self, mjds):
        self.mjd = np.asarray(mjds, float)
        self.exps = [{} for _ in mjds]


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(known, "RETRY_PAUSE_S", 0.0)
    monkeypatch.setattr(known, "JPL_GAP_S", 0.0)


def test_http_failure_raises(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("dropped")
    monkeypatch.setattr(archive, "_get", boom)
    with pytest.raises(requests.ConnectionError):
        archive.known_small_bodies(178.6, 1.1, 61027.0, 0.275, kinds=("a",))


def test_error_reply_raises(monkeypatch):
    monkeypatch.setattr(archive, "_get", lambda *a, **k: _Resp({"code": "503", "message": "busy"}))
    with pytest.raises(RuntimeError):
        archive.known_small_bodies(178.6, 1.1, 61027.0, 0.275, kinds=("a",))


def test_valid_empty_reply_is_zero_bodies(monkeypatch):
    monkeypatch.setattr(archive, "_get", lambda *a, **k: _Resp({"summary": {}, "n_second_pass": 0}))
    assert archive.known_small_bodies(178.6, 1.1, 61027.0, 0.275, kinds=("a",)) == []


def test_failed_visits_are_counted(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("dropped")
    monkeypatch.setattr(archive, "_get", boom)
    _, bodies, status = known.known_for_field(_Field([61027.0, 61027.1, 61030.0]), 0.275, log=lambda m: None,
                                              with_status=True)
    assert bodies == {}
    assert status == {"ok": False, "failed": 2, "visits": 2}


def test_retry_recovers_a_flaky_visit(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("dropped")
        return _Resp({"summary": {}, "fields_second": FIELDS, "data_second_pass": [ROW]})
    monkeypatch.setattr(archive, "_get", flaky)
    pos, bodies, status = known.known_for_field(_Field([61027.0]), 0.275, workers=1, log=lambda m: None,
                                                with_status=True)
    assert status["ok"] and status["failed"] == 0
    assert "65 Cybele (A861 EB)" in bodies
    assert pos[0][0][0] == "65 Cybele (A861 EB)"


def test_get_waits_as_long_as_a_429_asks(monkeypatch):
    class R:
        def __init__(self, code, headers=None):
            self.status_code, self.headers = code, headers or {}

        def raise_for_status(self):
            pass
    replies = iter([R(429, {"Retry-After": "7"}), R(200)])
    slept = []
    monkeypatch.setattr(archive._session, "get", lambda *a, **k: next(replies))
    monkeypatch.setattr(archive.time, "sleep", slept.append)
    assert archive._get("https://example.invalid").status_code == 200
    assert slept and slept[0] >= 7
