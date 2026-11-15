"""/api/field/<id>/point and /api/probe run in a process pool (sxlib/measure.py): same bytes as the old in-process
code, the per-visitor cap on measurements in flight, and the pool shut down afterwards."""
import json

import numpy as np
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from asgi_client import gather, get
from web import server


@pytest.fixture(scope="module", autouse=True)
def pool():
    if not (server.FIELDS / "cybele" / "cube" / "img.npy").exists():
        pytest.skip("no cybele cube")
    server.MEASURE_WORKERS = 2
    yield
    server._stop_measure_pool()
    assert server._mpool is None


def old_point(fid, x, y):
    """The endpoint as it was before the pool (web/server.py, in-process), rendered as FastAPI rendered it."""
    from sxlib.products import phot
    d = server._fdir(fid)
    doc = json.loads((d / "field.json").read_text(encoding="utf-8"))
    c = {k: np.load(d / "cube" / f"{k}.npy", mmap_mode="r") for k in ("img", "var", "flag", "lam")}
    ds = doc.get("products", {}).get("lam_ds", 5)
    xi, yi = int(round(x)), int(round(y))
    out = []
    for i in range(c["img"].shape[0]):
        bad = (c["flag"][i] & 1).astype(bool)
        p = phot(c["img"][i], c["var"][i], bad, x, y)
        e = doc["exposures"][i]
        lam = float(c["lam"][i, min(yi // ds, c["lam"].shape[1] - 1), min(xi // ds, c["lam"].shape[2] - 1)])
        fl = int(c["flag"][i, yi, xi])
        out.append({"i": i, "mjd": e["mjd"], "det": e["detector"], "lam": round(lam if np.isfinite(lam) else e["lam_um"], 4),
                    "f": None if p is None else round(p[0], 2), "e": None if p is None else round(p[1], 2), "flag": fl})
    bd = None
    try:
        from sxlib.specclass import score_points
        good = [q for q in out if q["f"] is not None and not (q["flag"] & 5)]
        bd = score_points([q["lam"] for q in good], [q["f"] for q in good], [q["e"] for q in good])
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(jsonable_encoder({"x": x, "y": y, "points": out, "bd_score": None if bd is None else round(bd, 3)})).body


@pytest.mark.parametrize("fid,x,y", [("cybele", 100, 100), ("cybele", 10.4, 280.7), ("cybele", 0, 0), ("cybele", 146.0, 146.0),
                                     ("barnard", 88.5, 88.5)])
def test_point_unchanged(fid, x, y):
    if not (server._fdir(fid) / "cube" / "img.npy").exists():
        pytest.skip(f"no {fid} cube")
    r = get(server.app, f"/api/field/{fid}/point?x={x}&y={y}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.content == old_point(fid, float(x), float(y))


def test_point_errors_unchanged():
    n = json.loads((server.FIELDS / "cybele" / "field.json").read_text(encoding="utf-8"))["shape"][1]
    r = get(server.app, f"/api/field/cybele/point?x={n + 5}&y=3")
    assert (r.status_code, r.content) == (422, b'{"detail":"outside"}')
    r = get(server.app, "/api/field/nope/point?x=1&y=1")
    assert (r.status_code, r.content) == (404, b'{"detail":"no_cube"}')
    r = get(server.app, f"/api/field/cybele/point?x={n - 0.4}&y=3")    # rounded to the edge: used to be a 500
    assert r.status_code == 200


def test_probe_errors_and_cheap_case():
    assert get(server.app, "/api/probe?field=nope&x=1&y=1&i=0").content == b'{"detail":"unknown field"}'
    r = get(server.app, "/api/probe?field=cybele&x=1&y=1&i=999999")
    assert (r.status_code, r.content) == (422, b'{"detail":"bad exposure"}')
    r = get(server.app, "/api/probe?field=cybele&x=100&y=100&i=5")
    assert r.status_code == 200
    d = r.json()
    assert d["field"] == "cybele" and d["i"] == 5 and "same_spot" in d and "n_passes_field" in d


def test_per_ip_cap(monkeypatch):
    monkeypatch.setattr(server, "MEASURE_PER_IP", 2)
    get(server.app, "/api/field/cybele/point?x=50&y=50")                     # pool up and warm
    calls = [("GET", f"/api/field/cybele/point?x={40 + k}&y=60", {"cf-connecting-ip": "203.0.113.9"}) for k in range(6)]
    rs = gather(server.app, calls)
    codes = sorted(r.status_code for r in rs)
    assert codes == [200, 200, 429, 429, 429, 429]
    busy = next(r for r in rs if r.status_code == 429)
    assert busy.json() == {"detail": "too_many_measurements"} and busy.headers.get("retry-after")
    # the cap is per visitor: six visitors get six answers
    calls = [("GET", f"/api/field/cybele/point?x={40 + k}&y=60", {"cf-connecting-ip": f"203.0.113.{20 + k}"}) for k in range(6)]
    assert all(r.status_code == 200 for r in gather(server.app, calls))
    assert server._inflight == {}                                            # every slot released
