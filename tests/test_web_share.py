"""Share-link previews: the server rewrites index.html's title and preview tags for /?ra=&dec=, /?target=, /?q=,
and /api/og.jpg makes the preview picture."""
import html
import io
import re

import pytest

from asgi_client import get
from web import server

PROXY = {"x-forwarded-proto": "https", "host": "sky.example.org"}


def _meta(doc, key):
    for tag in re.findall(r"<meta\b[^>]*>", doc):
        a = dict((k, v[1:-1]) for k, v in re.findall(r"""([\w:-]+)\s*=\s*("[^"]*"|'[^']*')""", tag))
        if key in (a.get("name"), a.get("property")):
            return html.unescape(a["content"])
    return None


def _title(doc):
    return html.unescape(re.search(r"<title>(.*?)</title>", doc, re.S).group(1))


@pytest.fixture(autouse=True)
def _need_dist():
    if not (server.DIST / "index.html").exists():
        pytest.skip("no built frontend")


@pytest.fixture
def og_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OG_DIR", tmp_path / "og")
    return tmp_path / "og"


def test_plain_home_gets_absolute_og_image():
    r = get(server.app, "/", PROXY)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    doc = r.text
    assert _meta(doc, "og:image").startswith("https://sky.example.org/")
    assert _meta(doc, "twitter:image") == _meta(doc, "og:image")
    assert _meta(doc, "og:url") == "https://sky.example.org/"
    assert '<div id="root">' in doc                        # still the app


def test_position_link():
    doc = get(server.app, "/?ra=133.79&dec=-7.25", PROXY).text
    assert _title(doc) == "RA 133.79°, Dec −7.25° · SPHEREx Sky Change"
    assert _meta(doc, "og:title") == _title(doc) == _meta(doc, "twitter:title")
    img = _meta(doc, "og:image")
    assert img.startswith("https://sky.example.org/")
    assert _meta(doc, "og:url") == "https://sky.example.org/?ra=133.79&dec=-7.25"
    assert "133.79" in _meta(doc, "description") and _meta(doc, "og:description") == _meta(doc, "description")
    if (server.FIELDS / "wise0855" / "field.json").exists():
        assert img == "https://sky.example.org/api/og.jpg?ra=133.7900&dec=-7.2500"


def test_host_header_fallback_and_bad_host():
    doc = get(server.app, "/?ra=10&dec=20", {"host": "localhost:8791"}).text
    assert _meta(doc, "og:image").startswith("http://localhost:8791/")
    doc = get(server.app, "/", {"host": 'evil"><script>x'}).text
    assert "evil" not in doc                                # an unusable Host is replaced, never echoed
    assert re.match(r"https?://[\w.:-]+/", _meta(doc, "og:image"))


def test_target_link_uses_name():
    if not (server.FIELDS / "barnard" / "field.json").exists():
        pytest.skip("no barnard field")
    for q in ("/?target=barnard", "/?target=Barnard%27s%20Star", "/?q=barnard"):
        doc = get(server.app, q, PROXY).text
        assert _title(doc) == "Barnard's Star · SPHEREx Sky Change"
        assert _meta(doc, "og:image") == "https://sky.example.org/api/og.jpg?id=barnard"
        assert "Barnard&#x27;s Star" in doc                 # escaped inside attributes


def test_inserted_text_is_escaped():
    evil = '<script>alert(1)</script>"\'&'
    from urllib.parse import quote
    doc = get(server.app, "/?target=" + quote(evil), PROXY).text
    head = doc.split("</head>")[0]
    assert "<script>alert(1)" not in head
    assert _title(doc).startswith(evil)
    assert _meta(doc, "og:title").startswith(evil)
    assert _meta(doc, "og:url").startswith("https://sky.example.org/?target=")


def test_missing_tags_are_inserted(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text('<html><head>\n<meta charset="utf-8" />\n<title>T</title>\n'
                                  '<meta content="/media/og.jpg" property="og:image">\n</head><body></body></html>', encoding="utf-8")
    monkeypatch.setattr(server, "DIST", d)
    doc = get(server.app, "/?ra=1&dec=2", PROXY).text
    for k in ("description", "og:title", "og:description", "og:image", "og:url", "twitter:card", "twitter:title",
              "twitter:description", "twitter:image"):
        assert _meta(doc, k), k
    assert doc.count('property="og:image"') == 1
    assert _meta(doc, "og:image") == "https://sky.example.org/media/og.jpg"     # nothing covers RA 1, Dec 2


def test_og_jpg(og_dir):
    from PIL import Image
    if not (server.FIELDS / "barnard" / "field.json").exists():
        pytest.skip("no barnard field")
    r = get(server.app, "/api/og.jpg?id=barnard")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "max-age=604800" in r.headers["cache-control"]
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    assert len(list(og_dir.glob("*.jpg"))) == 1
    get(server.app, "/api/og.jpg?id=barnard")
    assert len(list(og_dir.glob("*.jpg"))) == 1                               # cached on disk
    b = server._summary(server.FIELDS / "barnard")
    r = get(server.app, f"/api/og.jpg?ra={b['ra']:.4f}&dec={b['dec']:.4f}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_og_jpg_fallback(og_dir):
    for q in ("ra=10&dec=20", "id=nope", "ra=abc&dec=1", "id=../../etc"):
        r = get(server.app, "/api/og.jpg?" + q)
        assert r.status_code == 302 and r.headers["location"] == "/media/og.jpg", q
    assert not og_dir.exists() or not list(og_dir.glob("*.jpg"))


def test_og_cache_size_cap(og_dir, monkeypatch):
    og_dir.mkdir(parents=True)
    for k in range(5):
        (og_dir / f"old{k}.jpg").write_bytes(b"x" * 1000)
    monkeypatch.setattr(server, "OG_MAX_BYTES", 2500)
    server._og_prune()
    assert sum(p.stat().st_size for p in og_dir.glob("*.jpg")) <= 2000
