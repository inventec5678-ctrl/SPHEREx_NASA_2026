"""Shared helpers for the command-line scripts in scripts/ (paths, JSON I/O, field lists, TLS switch, tools).

Every script starts with

    import sys; from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import ROOT, ...  # noqa: E402

which works whether the script is run as ``python scripts/x.py``, ``python -m scripts.x``, imported as
``scripts.x`` (web/worker.py, sxlib/products.py) or loaded by a test with importlib. Importing this module also puts
the project root and scripts/ on sys.path, so ``import sxlib`` and sibling imports (``from train_cnn import TEST``)
work in all of those cases, on Linux and on Windows.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# project directories (all relative to the repository root, never to the working directory)
WEB = ROOT / "web"
DATA = WEB / "data"                       # web/data: analysed fields, quick looks, validation products
FIELDS = DATA / "fields"
QUICK = DATA / "quick"
VALIDATION = DATA / "validation"
APP = WEB / "app"
PUBLIC = APP / "public"
MEDIA = PUBLIC / "media"
OUTPUTS = ROOT / "outputs"
MODELS = ROOT / "models"
CACHE = ROOT / "cache"
PAPER_EVIDENCE = ROOT / "paper_evidence"
PAPER_AAS = ROOT / "paper_aas"
PAPER_TEX = ROOT / "paper_tex"

# SX_INSECURE=1 turns off TLS certificate checks (machines behind an intercepting proxy); same switch as sxlib.
VERIFY = os.environ.get("SX_INSECURE") != "1"


def insecure() -> bool:
    """True when SX_INSECURE=1 (read at call time, for scripts that let the caller set it late)."""
    return os.environ.get("SX_INSECURE") == "1"


# ---------------------------------------------------------------------------------------------------------- JSON I/O
def read_json(path: str | os.PathLike, default: Any = None) -> Any:
    """Parse a UTF-8 JSON file; ``default`` when it does not exist (other errors propagate)."""
    p = Path(path)
    if default is not None and not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def dumps(obj: Any, indent: int | None = 1, compact: bool = False, **kw) -> str:
    """json.dumps with the project's two styles: indent=1 (readable) or compact=True (no whitespace, for the web)."""
    if compact:
        return json.dumps(obj, separators=(",", ":"), **kw)
    return json.dumps(obj, indent=indent, **kw)


def write_json(path: str | os.PathLike, obj: Any, indent: int | None = 1, compact: bool = False,
               atomic: bool = False, **kw) -> Path:
    """Write ``obj`` as UTF-8 JSON, creating parent directories. ``atomic`` writes a sibling temp file and renames
    it over the target (os.replace is atomic on POSIX and Windows), so a reader never sees half a file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(obj, indent=indent, compact=compact, **kw)
    if atomic:
        tmp = p.with_name(p.name + ".tmp")
        _write(tmp, text)
        os.replace(tmp, p)
    else:
        _write(p, text)
    return p


def _write(p: Path, text: str) -> None:
    """UTF-8 with LF line endings on every OS, so outputs (and their hashes) match between Linux and Windows."""
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_text(path: str | os.PathLike) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | os.PathLike, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _write(p, text)
    return p


# ------------------------------------------------------------------------------------------------------ field lists
def field_ids(ids: Iterable[str] | None = None, marker: str = "field.json", base: Path = FIELDS,
              skip_dotted: bool = False) -> list[str]:
    """The ids given on the command line, else every directory under ``base`` holding ``marker`` (a path relative
    to the field directory, e.g. "cube/img.npy"), sorted. ``skip_dotted`` leaves out rebuilds in progress
    ("<id>.new") and kept old copies ("<id>.old")."""
    ids = list(ids or [])
    if ids:
        return ids
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir()
                  if (d / marker).exists() and not (skip_dotted and "." in d.name))


# ------------------------------------------------------------------------------------------------- external tools
def which(name: str, *fallbacks: str | os.PathLike) -> str | None:
    """Path of an executable on PATH (``.exe`` is found on Windows), else the first existing fallback."""
    hit = shutil.which(name)
    if hit:
        return hit
    for f in fallbacks:
        if f and Path(f).exists():
            return str(f)
    return None


def tectonic() -> str:
    """The tectonic TeX engine: PATH first, then the usual conda locations (Linux and Windows)."""
    home = Path.home()
    return which("tectonic", home / "miniconda3/bin/tectonic", home / "miniconda3/Library/bin/tectonic.exe",
                 home / "anaconda3/Library/bin/tectonic.exe") or "tectonic"


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    """subprocess.run with check=True and no shell (portable); the program is resolved on PATH first so a Windows
    ``.exe``/``.cmd`` is found."""
    cmd = [str(c) for c in cmd]
    exe = shutil.which(cmd[0])
    if exe:
        cmd[0] = exe
    kw.setdefault("check", True)
    return subprocess.run(cmd, **kw)


def rel(p: str | os.PathLike) -> str:
    """A path relative to the project root with forward slashes (stable in JSON across operating systems)."""
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()
