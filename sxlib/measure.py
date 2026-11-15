"""Measurements at one field pixel for the web server (/api/field/<id>/point and /api/probe), run in a pool of worker
processes so that numpy work on the data cubes never holds up the web process (see web/server.py, _measure).

Only the standard library is imported at module level: a freshly spawned worker runs init_worker() first, which pins
the numerical libraries to one thread each before numpy is loaded (8 workers x 64 BLAS threads would fight for the
cores). Each worker keeps its own small caches, keyed by (path, mtime), so a field that is re-analysed is re-read.

Every function returns (status, payload): 200 and the JSON body as bytes, rendered exactly as FastAPI's JSONResponse
renders a returned dict, or an HTTP error status and its detail string.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")


def init_worker():
    for k in THREAD_VARS:
        os.environ[k] = "1"


def warm():
    """Load what every point measurement needs, so the first real request in this worker is fast."""
    import numpy  # noqa: F401
    from . import products, specclass  # noqa: F401
    try:
        specclass._weights()
    except Exception:  # noqa: BLE001 - the classifier is optional
        pass
    return os.getpid()


def _render(content):
    """The bytes FastAPI sends for a returned dict (jsonable_encoder, then JSONResponse.render)."""
    from fastapi.encoders import jsonable_encoder
    return json.dumps(jsonable_encoder(content), ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=16)
def _doc(path, mtime):
    return json.loads(Path(path).read_text())


@lru_cache(maxsize=4)
def _cube(d, mtime):
    import numpy as np
    d = Path(d)
    return {k: np.load(d / f"{k}.npy", mmap_mode="r") for k in ("img", "var", "flag", "lam")}


def _mtime(p):
    return Path(p).stat().st_mtime


def point(fdir, x, y):
    """Forced aperture photometry at field pixel (x, y) in every exposure: a light curve and an on-the-fly spectrum.
    fdir is the field's (or finished quick look's) directory; the caller has checked that field.json and the cube exist."""
    import numpy as np
    from .products import R_OUT, phot
    fdir = Path(fdir)
    doc = _doc(str(fdir / "field.json"), _mtime(fdir / "field.json"))
    c = _cube(str(fdir / "cube"), _mtime(fdir / "cube" / "img.npy"))
    n = c["img"].shape[1]
    if not (0 <= x < n and 0 <= y < n):
        return 422, "outside"
    ds = doc.get("products", {}).get("lam_ds", 5)
    xi, yi = min(int(round(x)), n - 1), min(int(round(y)), n - 1)      # x = n - 0.4 rounds to n (was an IndexError)
    # Read only the photometry window of every exposure from the memory-mapped cube (one slice per array, not a
    # whole frame per exposure). The window is exactly the box phot() cuts, so its results are unchanged.
    x0, x1 = max(0, int(x - R_OUT - 1)), min(n, int(x + R_OUT + 2))
    y0, y1 = max(0, int(y - R_OUT - 1)), min(n, int(y + R_OUT + 2))
    img_w = np.asarray(c["img"][:, y0:y1, x0:x1])
    var_w = np.asarray(c["var"][:, y0:y1, x0:x1])
    bad_w = (np.asarray(c["flag"][:, y0:y1, x0:x1]) & 1).astype(bool)
    flag_px = np.asarray(c["flag"][:, yi, xi])
    lam_px = np.asarray(c["lam"][:, min(yi // ds, c["lam"].shape[1] - 1), min(xi // ds, c["lam"].shape[2] - 1)], float)
    out = []
    for i in range(c["img"].shape[0]):
        p = phot(img_w[i], var_w[i], bad_w[i], x - x0, y - y0)
        e = doc["exposures"][i]
        lam = float(lam_px[i])
        out.append({"i": i, "mjd": e["mjd"], "det": e["detector"], "lam": round(lam if np.isfinite(lam) else e["lam_um"], 4),
                    "f": None if p is None else round(p[0], 2), "e": None if p is None else round(p[1], 2),
                    "flag": int(flag_px[i])})
    bd = None
    try:
        from .specclass import score_points
        good = [q for q in out if q["f"] is not None and not (q["flag"] & 5)]
        bd = score_points([q["lam"] for q in good], [q["f"] for q in good], [q["e"] for q in good])
    except Exception:  # noqa: BLE001 - the classifier is optional
        pass
    return 200, _render({"x": x, "y": y, "points": out, "bd_score": None if bd is None else round(bd, 3)})


# ---- "is this point a planet?" ----
@lru_cache(maxsize=16)
def _probe_data(fdir, mtime):
    fdir = Path(fdir)
    doc = json.loads((fdir / "field.json").read_text())
    uni = fdir / "universe.json"
    src = json.loads(uni.read_text())["sources"] if uni.exists() else []
    return doc, src


CACHE = Path(os.environ.get("SX_MEASURE_CACHE", Path(__file__).resolve().parent.parent / "var" / "measure"))


@lru_cache(maxsize=8)
def _blind_distant(fdir, mtime):
    """The field's blind distant-body search (AI score only, no catalogue), computed once per field version.
    It takes seconds, so the result is also kept on disk (var/measure/) for the other workers and the next start."""
    import hashlib
    import pickle
    from . import link
    from .analyze import P_LINK
    doc, _ = _probe_data(fdir, mtime)
    ex = doc["exposures"]
    pool = [dict(c, mjd=ex[c["i"]]["mjd"]) for c in doc["candidates"] if c["p"] >= P_LINK and not c.get("known")]
    name = Path(fdir).name
    p = CACHE / f"blind_{name}_{hashlib.sha1(f'{fdir}|{mtime!r}'.encode()).hexdigest()[:16]}.pkl"
    try:
        return pool, pickle.loads(p.read_bytes())
    except (OSError, EOFError, pickle.UnpicklingError):
        pass
    tracks = link.search_distant(pool)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        for old in CACHE.glob(f"blind_{name}_*.pkl"):          # an earlier version of this field
            if old != p:
                old.unlink(missing_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_bytes(pickle.dumps(tracks))
        os.replace(tmp, p)
    except OSError:
        pass
    return pool, tracks


def probe(fdir, field, x, y, i):
    """Everything we can say about the sky at pixel (x, y) [field pixels, y up] around exposure i: the detection
    there, whether it belongs to a track, whether the same spot lights up in other survey passes (a fixed source),
    the spectral fit of a catalogued source there, and a seeded parallax + orbital-motion search asking whether it
    could be a distant planet. The caller has checked that the field exists."""
    from . import link
    mt = _mtime(Path(fdir) / "field.json")
    doc, src = _probe_data(str(fdir), mt)
    ex = doc["exposures"]
    if not 0 <= i < len(ex):
        return 422, "bad exposure"
    from .analyze import P_LINK
    cands = doc["candidates"]
    near = lambda c, r: (c["x"] - x) ** 2 + (c["y"] - y) ** 2 <= r * r  # noqa: E731
    here = min((c for c in cands if c["i"] == i and near(c, 3)), key=lambda c: (c["x"] - x) ** 2 + (c["y"] - y) ** 2, default=None)
    passes = lambda m: int(round((m - ex[0]["mjd"]) / 90))  # noqa: E731
    spot = [c for c in cands if near(c, 1.5) and c["p"] >= P_LINK]
    spot_passes = sorted({passes(ex[c["i"]]["mjd"]) for c in spot})
    out = {"field": field, "x": x, "y": y, "i": i, "here": here, "same_spot": {"n": len(spot), "passes": len(spot_passes)},
           "n_passes_field": len({passes(e["mjd"]) for e in ex})}
    if here and here.get("track") is not None:
        t = doc["tracks"][here["track"]]
        out["track"] = {k: t.get(k) for k in ("id", "kind", "known", "d_au", "rate_arcsec_h", "span_h", "mean_p")}
    s = min((s for s in src if (s["x"] - x) ** 2 + (s["y"] - y) ** 2 <= 9), key=lambda s: (s["x"] - x) ** 2 + (s["y"] - y) ** 2, default=None)
    if s:
        out["source"] = {"id": s["id"], "kind": s["kind"], "T": round(s["fit"]["T"]) if s.get("fit") else None,
                         "distance_pc": s.get("distance_pc"), "snr": s.get("snr")}
    # the parallax test needs a confident detection to start from: first look it up in the field's blind
    # distant search (cached), then fall back to a search seeded at this detection
    if here and here["p"] >= P_LINK and not here.get("known"):
        pool, tracks = _blind_distant(str(fdir), mt)
        seed = next((k for k, c in enumerate(pool) if c["id"] == here["id"]), None)
        hit = next((t for t in tracks if seed in t["members"]), None) if seed is not None else None
        if hit:
            r = {"ok": True, "d_au": round(hit["d_au"], 1), "pm_arcsec_yr": hit.get("pm_arcsec_yr"), "rms_arcsec": round(hit["rms_arcsec"], 2),
                 "n_passes": hit["n_passes"], "members": hit["members"], "via": "blind"}
        elif seed is not None:
            r = link.probe_distant(pool, seed) | {"via": "seeded"}
        else:
            r = {"ok": False, "reason": "no_parallax_partner"}
        if r.get("members"):
            r["members"] = [pool[k]["id"] for k in r["members"]]
        out["distant"] = r
    return 200, _render(out)

