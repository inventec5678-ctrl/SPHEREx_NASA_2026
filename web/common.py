"""Helpers shared by web/server.py and the feature routers (web/api_*.py): visitor keys, in-memory rate limits and
detached background processes."""
import hashlib
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var"
SPAWN_ENV = ("SX_INSECURE", "SX_CACHE", "PYTHONUNBUFFERED")      # passed on to a systemd unit


def client_ip(request):
    """The visitor's address (Cloudflare's header first; the site runs behind a tunnel)."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


@lru_cache(maxsize=4096)
def ip_key(ip):
    """A short salted hash of an address: rate limits key on this, raw addresses are never stored."""
    return hashlib.sha256(f"sx:{ip}".encode()).hexdigest()[:16]


def visitor(request):
    return ip_key(client_ip(request))


def rate_ok(store: dict, key, limit, window_s, now=None):
    """Sliding-window limiter on an in-memory {key: [times]} store; records the call when it is allowed."""
    now = time.time() if now is None else now
    hist = [t for t in store.get(key, []) if now - t < window_s]
    if len(hist) >= limit:
        return False
    store[key] = hist + [now]
    return True


def spawn_detached(args, unit, memory_max, log_name):
    """Run `args` as its own transient systemd user unit, so restarting the web service does not kill it (a child
    process would share the web unit's cgroup and be stopped with it). Falls back to a plain detached process when
    there is no user systemd (a container, Windows)."""
    if shutil.which("systemd-run"):
        env = [f"--setenv={k}={os.environ[k]}" for k in SPAWN_ENV if k in os.environ]
        try:
            subprocess.run(["systemd-run", "--user", "--collect", "--quiet", f"--unit={unit}", f"--working-directory={ROOT}",
                            "--property=Nice=5", f"--property=MemoryMax={memory_max}", *env, *args], check=True, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return
        except Exception:  # noqa: BLE001 - no user session bus
            pass
    VAR.mkdir(parents=True, exist_ok=True)
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})
    with open(VAR / log_name, "a") as log:                 # the child keeps its own copy of the handle
        subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=log, **detach)
