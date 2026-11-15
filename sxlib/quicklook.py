"""Quick look: play any patch of sky within a minute, no AI and no catalogues.

Cutouts are requested in an order that covers every survey pass and every detector early (round robin over
(pass, detector) groups), aligned onto the field grid as they arrive and written straight to WebP frames (with a
contamination-flag overlay and the share of each SPHEREx flag), so the web player can start while the rest
download. When every cutout is in, a second phase adds per-pixel wavelength-matched difference frames (the same
differencing as the full pipeline) and per-pass, per-detector stacks; a third searches for moving stars; a fourth
writes the field lab's products (sxlib/products.py: pass x detector stacks, the flux/variance/flag/wavelength cube
for spectra and light curves on the fly, per-pass flag maps, Gaia/CatWISE overlays) and runs the variable search,
so the same lab tools work on any position. Output: <out>/preview.json, sci/NNNN.webp, diff/NNNN.webp,
flag/NNNN.webp, stack/p{k}_d{d}.webp, and field.json, cube/, pass/, overlays.json, pm_candidates.json,
var_candidates.json.

Frame files are numbered in arrival order; preview.json lists them with their time, detector and wavelength,
and the player sorts by time.
"""
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from astropy.time import Time
from PIL import Image

from . import archive
from . import products as _products
from .products import flag_code, save_flag_webp
from .stack import Field

PASS_GAP_D = 40.0          # survey passes are ~6 months apart; a gap longer than this starts a new pass
QUICK_VERSION = 2          # 2: flag frames and the field lab's products; the server re-runs older finished looks
REF_KW = {"lam_tol": 0.03, "eps": 0.1}      # the full pipeline's differencing (sxlib.analyze.REF_KW)
CUTOUT_MARGIN = 1.5        # cutout side / field side (the detector frame is rotated)
STACK_EVERY = 30           # pass stacks are rewritten every this many arrivals
PROVISIONAL_AT = (0.3, 0.65)   # provisional differences at these shares of the download ...
PROVISIONAL_MAX_N = 200        # ... for fields up to this many pixels across ...
PROVISIONAL_MIN_EXP = 60       # ... with at least this many exposures
KEEP_CACHE_FREE_B = 3e9        # cutouts are kept for a later full analysis only with this much free disk


def passes_of(mjd):
    """Survey pass number (0, 1, ...) of each time: a gap longer than PASS_GAP_D days starts a new pass."""
    return _products.passes_of(np.asarray(mjd, float), PASS_GAP_D)


def _diff8(snr):
    """Difference S/N as an 8-bit frame: 128 + 16 S/N."""
    return np.clip(128 + 16 * np.nan_to_num(snr, nan=0.0), 0, 255).astype(np.uint8)


def interleave(metas):
    """Round robin over (pass, detector) groups so the first frames already span the whole time range."""
    p = passes_of([m["mjd"] for m in metas])
    groups = {}
    for m, k in zip(metas, p):
        groups.setdefault((k, m["detector"]), []).append(m)
    for g in groups.values():                 # within a group start in the middle, then spread outwards
        g.sort(key=lambda m: m["mjd"])
        mid = len(g) // 2
        g[:] = [g[i] for i in sorted(range(len(g)), key=lambda i: (abs(i - mid), i))]
    out, keys = [], sorted(groups)
    while any(groups[k] for k in keys):
        for k in keys:
            if groups[k]:
                out.append(groups[k].pop(0))
    return out


def _write_json_atomic(path, obj):
    tmp = path.with_name("." + path.name)
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def _webp(arr, path):
    tmp = path.with_name("." + path.name)
    Image.fromarray(arr[::-1]).save(tmp, format="WEBP", lossless=True, quality=100, method=4)
    os.replace(tmp, path)


def _fill_bad(img, bad):
    """Hot and flagged pixels shown as the local median (display only; the data keep their flags)."""
    from scipy.ndimage import median_filter
    fix = bad & np.isfinite(img)
    if not fix.any():
        return img
    out = img.copy()
    out[fix] = median_filter(np.where(bad, np.nan_to_num(np.nanmedian(img)), np.nan_to_num(img)), 5)[fix]
    return out


def _stretch(img, noise):
    s = np.arcsinh(np.nan_to_num(img) / (3 * noise)) / np.arcsinh(300)
    return np.clip(s * 255, 0, 255).astype(np.uint8)


def _movers(f, acc, log, ov=None):
    from .pmsearch import search_all
    from .products import overlays
    P = 1 + max(k[0] for k in acc)
    n = f.shape[0]
    st = np.full((P, 7, n, n), np.nan, np.float32)
    mjd = []
    for p in range(P):
        num, den, mj = np.zeros((n, n)), np.zeros((n, n)), []
        for d in range(1, 7):
            if (p, d) in acc:
                sm, cnt, _, m = acc[(p, d)]
                with np.errstate(all="ignore"):
                    st[p, d] = np.where(cnt >= 2, sm / np.maximum(cnt, 1), np.nan)
                num += sm
                den += cnt
                mj += m
        with np.errstate(all="ignore"):
            st[p, 0] = np.where(den >= 2, num / np.maximum(den, 1), np.nan)
        mjd.append(float(np.median(mj)) if mj else np.nan)
    ok = [p for p in range(P) if np.isfinite(mjd[p])]
    if len(ok) < 2:
        return {"candidates": [], "stats": {"reason": "one_pass"}}
    if ov is None:
        ov = overlays(f, log=lambda m: None)
    times = {b: [[float(m) for d in range(1, 7) if (b == 0 or d == b) and (p, d) in acc for m in acc[(p, d)][3]] for p in ok]
             for b in range(7)}
    res = search_all(st[ok], [mjd[p] for p in ok], ov, cdelt=list(map(float, f.wcs.wcs.cdelt)), ra=f.ra, dec=f.dec,
                     pass_times=times, log=log)
    for c in res["candidates"]:
        r_, d_ = f.pix_to_world(c["x"], c["y"])
        c["ra"], c["dec"] = round(float(r_), 6), round(float(d_), 6)
        for t in c["track"]:
            t["mjd"] = round(mjd[ok[t["k"]]], 3)
            t["k"] = ok[t["k"]]
    res["pass_mjd"] = [round(mjd[p], 3) for p in ok]
    return res


def _lab(qid, f, arrival, out, ov, movers, log):
    """The field lab's products for a quick look: the same files an analysed field has, so the same page works."""
    import sys
    from .products import build
    w = f.wcs.wcs
    doc = {"id": qid, "name": f"RA {f.ra:.4f} Dec {f.dec:+.4f}", "quick": True, "ra": f.ra, "dec": f.dec, "size_deg": f.size,
           "shape": list(f.shape), "wcs": {"crval": list(map(float, w.crval)), "crpix": list(map(float, w.crpix)), "cdelt": list(map(float, w.cdelt))},
           "exposures": [{"i": j, "f": int(arrival[j]), "obs_id": e["obs_id"], "mjd": round(e["mjd"], 5),
                          "iso": Time(e["mjd"], format="mjd").iso[:16], "detector": int(e["detector"]), "lam_um": round(e["lam_um"], 4),
                          "release": e.get("release", "")}
                         for j, e in enumerate(f.exps)],
           "candidates": [], "tracks": [], "known_bodies": [], "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    build(f, doc, out, log=log, ov=ov, flag_frames=False, pm=False)
    if movers is not None:
        res = json.loads(json.dumps(movers))
        try:                                   # brown-dwarf spectral score along each track, as an analysed field has
            root = str(Path(__file__).resolve().parent.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            from scripts.pm_search import score_candidates
            for c in res.get("candidates", []):
                tr = [dict(t, k=j) for j, t in enumerate(c["track"])]
                one = dict(c, track=tr)
                score_candidates(out, doc, [one], [t["mjd"] for t in c["track"]])
                c["bd_score"], c["bd_points"] = one.get("bd_score"), one.get("bd_points")
        except Exception as e:  # noqa: BLE001
            log(f"{qid}: spectral scores skipped: {e}")
        res.update(field=qid, created=doc["created"])
        (out / "pm_candidates.json").write_text(json.dumps(res))
        doc["products"]["pm"] = {"n_candidates": len(res.get("candidates", [])),
                                 "n_new": sum(1 for c in res.get("candidates", []) if c.get("status") == "new")}
        movers = res
    _write_json_atomic(out / "field.json", doc)
    try:                                       # automatic variable search on the cube (needs field.json on disk)
        from .varsearch import search as var_search
        vr = var_search(out, log=lambda m: None)
        (out / "var_candidates.json").write_text(json.dumps({"candidates": vr["candidates"], "stats": vr["stats"]}))
        doc["products"]["var"] = {"n_candidates": len(vr["candidates"])}
        _write_json_atomic(out / "field.json", doc)
    except Exception as e:  # noqa: BLE001 - the lab works without it
        log(f"{qid}: variable search skipped: {e}")
    return doc, movers


class Doc:
    """preview.json, rewritten atomically at most every `every` seconds (and on demand)."""

    def __init__(self, out, doc, every=2.0):
        self.out, self.doc, self.every, self.t = out, doc, every, 0.0
        self.lock = threading.Lock()

    def save(self, force=False):
        with self.lock:
            now = time.time()
            if not force and now - self.t < self.every:
                return
            self.t = now
            self.doc["heartbeat"] = now
            _write_json_atomic(self.out / "preview.json", self.doc)


def run(qid, ra, dec, size, out, tmp_cache, workers=20, keep_cache=None, log=print):
    # 20 parallel cutouts: 12 -> 24 measured 0.83 -> 1.13 cutouts/s from IRSA (2026-11-12), with no extra failures to speak of
    out = Path(out)
    for sub in ("sci", "diff", "stack", "flag"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    f = Field(ra, dec, size)
    w = f.wcs.wcs
    D = Doc(out, {"id": qid, "v": QUICK_VERSION, "ra": ra, "dec": dec, "size_deg": size, "shape": list(f.shape),
                  "wcs": {"crval": list(map(float, w.crval)), "crpix": list(map(float, w.crpix)), "cdelt": list(map(float, w.cdelt))},
                  "status": "searching", "phase": "search", "n_total": 0, "n_done": 0, "n_failed": 0, "frames": [],
                  "started": time.time(), "pid": os.getpid()})
    D.save(True)
    try:
        metas = archive.search_images(ra, dec)
        if not metas:
            raise RuntimeError("no_data")
        metas = interleave(metas)
        pass_of = dict(zip((m["url"] for m in metas), passes_of([m["mjd"] for m in metas])))
        acc = {}                                           # (pass, det) -> [sum, count, noises, mjds]

        def write_stacks(final=False):
            out_st = []
            for (pk, det), (sm, cnt, noises, mj) in sorted(acc.items()):
                n = int(max(1, len(noises)))
                with np.errstate(all="ignore"):
                    st = np.where(cnt > 0, sm / np.maximum(cnt, 1), np.nan)
                noise = float(np.median(noises)) / np.sqrt(n)
                _webp(_stretch(_fill_bad(st, cnt == 0), noise * 2), out / "stack" / f"p{pk}_d{det}.webp")
                md = float(np.median(mj))
                out_st.append({"pass": int(pk), "det": int(det), "n": n, "mjd": round(md, 3),
                               "iso": Time(md, format="mjd").iso[:10], "partial": not final})
            D.doc["stacks"] = out_st
        D.doc.update(status="running", phase="fetch", n_total=len(metas),
                     first=Time(min(m["mjd"] for m in metas), format="mjd").iso[:10],
                     last=Time(max(m["mjd"] for m in metas), format="mjd").iso[:10])
        D.save(True)
        cut = size * CUTOUT_MARGIN
        add_lock = threading.Lock()

        def one(m):
            return archive.fetch_cutout(m, ra, dec, cut, keep_psf=False, cache=tmp_cache)

        def provisional():
            """Differences from the frames that are in so far, so the Difference view opens minutes before the last
            cutout arrives. Each uses whatever same-wavelength frames exist; frames with too few references wait.
            The final pass recomputes every one (a new ?v= in the frame URL makes browsers fetch it again)."""
            n = len(f.exps)
            g = Field.__new__(Field)
            g.ra, g.dec, g.size, g.wcs, g.shape = f.ra, f.dec, f.size, f.wcs, f.shape
            order = np.argsort([e["mjd"] for e in f.exps[:n]])
            g.exps = [f.exps[i] for i in order]
            g.img, g.var, g.bad = np.stack(f._img[:n])[order], np.stack(f._var[:n])[order], np.stack(f._bad[:n])[order]
            g.feat, g.lam = np.stack(f._feat[:n])[order], np.stack(f._lam[:n])[order]
            g.mjd = np.array([e["mjd"] for e in g.exps]); g.det = np.array([e["detector"] for e in g.exps])
            by_f = {fr["f"]: fr for fr in D.doc["frames"]}
            ver = D.doc.get("diff_ver", 0) + 1
            for j, a in enumerate(order):
                fr = by_f.get(int(a))
                if fr is None:
                    continue
                d = g.difference(j, **REF_KW)
                ok = d["valid"]
                if not ok.any() or np.median(d["nref"][ok]) < 2:
                    continue
                _webp(_diff8(d["snr"]), out / "diff" / f"{int(a):04d}.webp")
                fr["diff"] = 1; fr["dv"] = ver
            D.doc.update(diff_ver=ver, diff_partial=True)
            D.save(True)

        # provisional differences at about a third and two thirds of the download (small fields only: the snapshot
        # copies every frame, which is too much memory for the 0.6 degree field)
        marks = sorted({int(len(metas) * q) for q in PROVISIONAL_AT}) \
            if f.shape[0] <= PROVISIONAL_MAX_N and len(metas) >= PROVISIONAL_MIN_EXP else []

        with ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(one, m) for m in metas]
            for fu in as_completed(futs):
                try:
                    e = fu.result()
                except Exception:  # noqa: BLE001 - a few failed cutouts are normal
                    e = None
                if e is None:
                    D.doc["n_failed"] += 1
                    D.save()
                    continue
                with add_lock:
                    k = len(f.exps)
                    if not f.add(e):
                        D.doc["n_failed"] += 1
                        D.save()
                        continue
                    img, var, bad, feat = f._img[-1], f._var[-1], f._bad[-1], f._feat[-1]
                    meta = f.exps[-1]
                good = ~bad & np.isfinite(img)
                noise = float(np.nanmedian(np.sqrt(var[good]))) if good.any() else 1.0
                _webp(_stretch(_fill_bad(img, bad), noise), out / "sci" / f"{k:04d}.webp")
                save_flag_webp(flag_code(bad, feat), out / "flag" / f"{k:04d}.webp")
                key = (int(pass_of.get(e.meta["url"], 0)), int(meta["detector"]))
                a = acc.setdefault(key, [np.zeros(f.shape, np.float64), np.zeros(f.shape, np.int32), [], []])
                a[0] += np.where(good, img, 0.0)
                a[1] += good
                a[2].append(noise)
                a[3].append(meta["mjd"])
                D.doc["frames"].append({"f": k, "mjd": round(meta["mjd"], 5), "iso": Time(meta["mjd"], format="mjd").iso[:16],
                                        "det": meta["detector"], "lam": round(meta["lam_um"], 3), "rel": meta.get("release", ""),
                                        "cov": round(float(good.mean()), 3), "noise": noise, "fl": meta.get("flag_frac", {})})
                D.doc["n_done"] = len(D.doc["frames"])
                if D.doc["n_done"] % STACK_EVERY == 0:              # pass stacks grow while the rest download
                    with add_lock:
                        write_stacks()
                    D.save(True)
                else:
                    D.save()
                if marks and D.doc["n_done"] >= marks[0]:
                    marks.pop(0)
                    try:
                        provisional()
                    except Exception as e:  # noqa: BLE001 - the final differences still come
                        log(f"{qid}: provisional differences skipped: {e}")
        if len(f.exps) < 3:
            raise RuntimeError("too_few")
        log(f"{qid}: {len(f.exps)} frames in {time.time() - D.doc['started']:.0f}s")

        # ---- phase 2: wavelength-matched differences and per-pass stacks -------------------------------------
        D.doc.update(phase="difference")
        D.save(True)
        order = np.argsort([e["mjd"] for e in f.exps])        # same order Field.freeze() uses
        f.freeze()
        arrival = {int(order[j]): j for j in range(len(order))}   # arrival number -> frozen index
        by_f = {fr["f"]: fr for fr in D.doc["frames"]}
        ver = D.doc.get("diff_ver", 0) + 1
        for a, j in sorted(arrival.items(), key=lambda t: t[1]):
            d = f.difference(j, **REF_KW)
            _webp(_diff8(d["snr"]), out / "diff" / f"{a:04d}.webp")
            by_f[a]["diff"] = 1; by_f[a]["dv"] = ver
            D.doc["n_diff"] = D.doc.get("n_diff", 0) + 1
            D.save()
        D.doc.update(diff_ver=ver, diff_partial=False)
        write_stacks(final=True)
        n_passes = len({st["pass"] for st in D.doc["stacks"]})
        # phase 3: automatic proper-motion search on the pass stacks, labelled with Gaia / CatWISE
        D.doc.update(phase="movers")
        D.save(True)
        from .products import overlays
        try:
            ov = overlays(f, log=lambda m: None)
        except Exception as e:  # noqa: BLE001
            ov = {"gaia": [], "catwise": [], "errors": {"all": str(e)[:200]}}
        try:
            D.doc["movers"] = _movers(f, acc, log, ov)
        except Exception as e:  # noqa: BLE001 - the preview is useful without it
            log(f"{qid}: mover search skipped: {e}")
        # phase 4: the field lab's products (add / subtract / false colour, spectra on the fly, overlays, flags)
        D.doc.update(phase="lab")
        D.save(True)
        try:
            lab, mv = _lab(qid, f, [int(order[j]) for j in range(len(order))], out, ov, D.doc.get("movers"), log)
            if mv is not None:
                D.doc["movers"] = mv
            D.doc["lab"] = {"passes": len(lab["products"]["passes"]), "gaia": len(ov["gaia"]), "catwise": len(ov["catwise"]),
                            "var": (lab["products"].get("var") or {}).get("n_candidates")}
        except Exception as e:  # noqa: BLE001 - the player is useful without it
            log(f"{qid}: lab products skipped: {e}")
        D.doc.update(status="done", phase="done", n_passes=n_passes, finished=time.time())
        D.save(True)
    except Exception as e:  # noqa: BLE001
        D.doc.update(status="error", error=str(e)[:200], finished=time.time())
        D.save(True)
        log(f"{qid}: error {e}")
    finally:
        # cutouts are kept for a later full analysis of the same patch only when the disk has room
        src = Path(tmp_cache)
        if keep_cache and src.exists() and shutil.disk_usage(keep_cache).free > KEEP_CACHE_FREE_B and D.doc.get("status") == "done":
            dst = Path(keep_cache) / "cutouts"
            dst.mkdir(parents=True, exist_ok=True)
            for p_ in (src / "cutouts").glob("*"):
                if not (dst / p_.name).exists():
                    shutil.move(str(p_), dst / p_.name)
        shutil.rmtree(src, ignore_errors=True)
    return D.doc
