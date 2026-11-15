"""Security headers and the CSP (web/server.py), and the lab stacks served without on-the-fly gzip."""
import base64
import hashlib
import os
import re
import time
from pathlib import Path

import pytest

from asgi_client import get
from web import server

ROOT = Path(__file__).resolve().parent.parent


def _hash(body):
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"


def _fresh_csp():
    server._csp.update(checked=0.0, key=None, value=None)


@pytest.fixture
def tmp_dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text(
        "<!doctype html><html><head><title>X</title>\n"
        '<meta property="og:title" content="X" />\n<meta property="og:image" content="/media/og.jpg" />\n'
        "<script>window.a=1</script>\n<script type=\"module\" src=\"/assets/i.js\"></script>\n</head><body></body></html>", encoding="utf-8")
    monkeypatch.setattr(server, "DIST", d)
    _fresh_csp()
    yield d
    _fresh_csp()


@pytest.mark.parametrize("path", ["/", "/api/health", "/api/field/nope"])
def test_security_headers(path):
    r = get(server.app, path)
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    for feat in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feat}=()" in h["permissions-policy"]
    csp = h["content-security-policy"]
    for d in ("default-src 'self'", "frame-ancestors *", "object-src 'none'", "base-uri 'self'", "'wasm-unsafe-eval'",
              "worker-src 'self' blob:", "https://cdn.jsdelivr.net", "https://irsa.ipac.caltech.edu"):
        assert d in csp
    assert "x-frame-options" not in h            # embedding the player is a feature


def test_csp_hashes_real_index():
    """Every inline <script> of the built index.html is allowed by hash, and nothing else is inline-allowed."""
    idx = server.DIST / "index.html"
    if not idx.exists():
        pytest.skip("no built frontend")
    _fresh_csp()
    csp = get(server.app, "/").headers["content-security-policy"]
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src
    for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", idx.read_text(encoding="utf-8"), re.S):
        if "src=" not in attrs:
            assert _hash(body) in script_src


def test_csp_hash_follows_index_changes(tmp_dist):
    csp = server.csp_value()
    assert _hash("window.a=1") in csp
    assert csp.count("'sha256-") == 1                # the module script with src= is not hashed
    p = tmp_dist / "index.html"
    p.write_text(p.read_text(encoding="utf-8").replace("window.a=1", "window.a=2"))
    os.utime(p, (time.time() + 5, time.time() + 5))
    server._csp["checked"] = 0.0                     # skip the 2 s re-check interval
    csp = server.csp_value()
    assert _hash("window.a=2") in csp and _hash("window.a=1") not in csp


def test_stack_bins_are_not_gzipped():
    files = sorted((ROOT / "web" / "data").glob("fields/*/pass/stacks*.bin"))
    if not files:
        pytest.skip("no field data")
    for f in files[:3]:
        rel = f.relative_to(ROOT / "web" / "data").as_posix()
        r = get(server.app, f"/data/{rel}", {"accept-encoding": "gzip"})
        assert r.status_code == 200
        assert "content-encoding" not in r.headers
        assert int(r.headers["content-length"]) == f.stat().st_size == len(r.content)
    js = sorted((ROOT / "web" / "data").glob("fields/*/overlays.json"))
    if js and js[0].stat().st_size > 2048:          # other files are still compressed
        rel = js[0].relative_to(ROOT / "web" / "data").as_posix()
        assert get(server.app, f"/data/{rel}", {"accept-encoding": "gzip"}).headers.get("content-encoding") == "gzip"


def test_stack_groups_match_stacks_bin():
    """pass/stacks_g{k}.bin hold exactly group k of stacks.bin (scripts/split_stacks.py, sxlib/products.py)."""
    from sxlib.products import read_stacks
    import numpy as np
    sbs = sorted((ROOT / "web" / "data").rglob("pass/stacks.bin"))
    if not sbs:
        pytest.skip("no field data")
    for sb in sbs:
        st = read_stacks(sb)
        P, B, n0, n1 = st.shape
        for k in range(B):
            g = np.fromfile(sb.parent / f"stacks_g{k}.bin", np.float16)
            assert g.size == P * n0 * n1
            assert g.tobytes() == np.ascontiguousarray(st[:, k]).tobytes()


def test_write_stack_groups(tmp_path):
    import numpy as np
    from sxlib.products import write_stack_groups
    a = (np.arange(2 * 7 * 3 * 3).reshape(2, 7, 3, 3) / 7).astype(np.float16)
    a[0, 2, 1, 1] = np.nan
    write_stack_groups(a, tmp_path)
    for k in range(7):
        g = np.fromfile(tmp_path / f"stacks_g{k}.bin", np.float16).reshape(2, 3, 3)
        assert g.tobytes() == a[:, k].tobytes()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("path,query,before,after", [
    ("/assets/index-abc.js", "", None, "public, max-age=31536000, immutable"),
    ("/assets/index-abc.js", "", "no-store", "public, max-age=31536000, immutable"),     # always overridden
    ("/sw.js", "", "public, max-age=99", "no-cache"),
    ("/", "", None, "no-cache"),
    ("/data/fields/x/field.json", "", None, "no-cache"),                                  # JSON before the data rules
    ("/api/field/x", "", "public, max-age=60", "public, max-age=60"),                     # an endpoint's own choice stays
    ("/data/quick/k1/sci/0001.webp", "", None, "public, max-age=31536000, immutable"),
    ("/data/quick/k1/stack/p0_d0.webp", "n=4", None, "public, max-age=31536000, immutable"),
    ("/data/quick/k1/stack/p0_d0.webp", "", None, "no-cache"),
    ("/data/fields/x/sci/0001.webp", "", None, "public, max-age=86400"),
    ("/media/og.jpg", "", None, "public, max-age=3600"),
    ("/api/health", "", None, "no-store"),
    ("/favicon.ico", "", None, None),
])
def test_cache_control_rules(path, query, before, after):
    from starlette.datastructures import MutableHeaders
    msg = {"type": "http.response.start", "status": 200, "headers": []}
    h = MutableHeaders(scope=msg)
    if before:
        h["Cache-Control"] = before
    server._cache_control(h, path, bool(query))
    assert h.get("cache-control") == after


def test_cache_headers_on_real_responses():
    assert get(server.app, "/api/health").headers["cache-control"] == "no-store"
    assert get(server.app, "/api/field/nope").headers["cache-control"] == "no-store"
    files = sorted((ROOT / "web" / "data").glob("fields/*/sci/0000.webp"))
    if files:
        rel = files[0].relative_to(ROOT / "web" / "data").as_posix()
        assert get(server.app, f"/data/{rel}").headers["cache-control"] == "public, max-age=86400"


def test_rate_ok_sliding_window():
    from web.common import rate_ok
    store = {}
    assert [rate_ok(store, "a", 2, 60, now=t) for t in (0, 1, 2)] == [True, True, False]
    assert rate_ok(store, "b", 2, 60, now=2)                  # per key
    assert rate_ok(store, "a", 2, 60, now=60.5)               # the first call has left the window
    assert store["a"] == [1, 60.5]
