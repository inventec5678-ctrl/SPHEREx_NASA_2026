"""The interstellar comet page (#/comet): is the NEOSSat stack of 3I/ATLAS there yet?

The SPHEREx products are static files (web/data/comet/, scripts/comet_build.py). The NEOSSat stack is made separately
and may not exist yet; asking for web/data/comet/neossat.json directly would show a 404 in the browser console, so the
page asks here instead.

    GET /api/comet/neossat  ->  {"available": false}  or  {"available": true, ...neossat.json, "images": {...}}
"""
import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
DATA = Path(__file__).resolve().parent / "data" / "comet"
IMAGES = ("neossat.webp", "neossat_stars.webp")


def neossat_status(data=DATA):
    try:
        d = json.loads((data / "neossat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict):
        return {"available": False}
    return {**d, "available": True, "images": {k: (data / k).exists() for k in IMAGES}}


@router.get("/api/comet/neossat")
def neossat():
    return neossat_status()
