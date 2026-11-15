"""A minimal in-process ASGI client for the web tests (FastAPI's TestClient needs httpx, which the venv does not have).
No lifespan events are sent; tests that start the measurement pool stop it themselves."""
import asyncio
import json
from urllib.parse import urlsplit


class Resp:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.raw_headers = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in headers]
        self.headers = dict(self.raw_headers)
        self.content = body

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


async def _call(app, method, url, headers=None, body=b"", client_ip="127.0.0.1"):
    parts = urlsplit(url)
    hdrs = [("host", "testserver")] + [(k.lower(), v) for k, v in (headers or {}).items() if k.lower() != "host"]
    if headers and any(k.lower() == "host" for k in headers):
        hdrs[0] = ("host", next(v for k, v in headers.items() if k.lower() == "host"))
    if body:
        hdrs.append(("content-length", str(len(body))))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(), "root_path": "",
             "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in hdrs],
             "client": (client_ip, 50000), "server": ("testserver", 80)}
    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if pending:
            return pending.pop(0)
        await asyncio.Event().wait()            # never disconnects; cancelled when the response is done
        return {"type": "http.disconnect"}

    out = {"status": None, "headers": [], "body": b""}

    async def send(m):
        if m["type"] == "http.response.start":
            out["status"], out["headers"] = m["status"], m.get("headers", [])
        elif m["type"] == "http.response.body":
            out["body"] += m.get("body", b"")
    await app(scope, receive, send)
    return Resp(out["status"], out["headers"], out["body"])


def request(app, method, url, headers=None, body=b"", client_ip="127.0.0.1"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    return asyncio.run(_call(app, method, url, headers, body, client_ip))


def get(app, url, headers=None, client_ip="127.0.0.1"):
    return request(app, "GET", url, headers, client_ip=client_ip)


def post_json(app, url, data, headers=None, client_ip="127.0.0.1"):
    return request(app, "POST", url, {"content-type": "application/json", **(headers or {})}, json.dumps(data).encode(), client_ip)


def gather(app, calls):
    """Several requests at once in one event loop: calls = [(method, url, headers), ...]."""
    async def run():
        return await asyncio.gather(*(_call(app, m, u, h) for m, u, h in calls))
    return asyncio.run(run())
