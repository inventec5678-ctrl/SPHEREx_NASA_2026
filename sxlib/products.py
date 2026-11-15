"""Per-field products for the field lab (everything the challenge's "potential considerations" ask for).

  pass/stacks.bin   float16 [pass][band][n][n]: median stack of each survey pass, all bands (0) and each of the
                    six detector arrays (1-6), so the page can add, subtract or blink passes and bands itself
  pass/stacks_g{k}.bin  the same, one file per band group k (float16 [pass][n][n], no header): the lab downloads
                    only the group it shows
  pass/p{k}_d{d}.webp  the same stacks as 8-bit previews (one shared stretch per band)
  cube/*.npy        every exposure on the field grid (float16 flux and variance, uint8 flags, coarse wavelength map)
                    for on-the-fly light curves and spectra at any pixel (/api/field/<id>/point)
  flag/NNNN.webp    per-exposure contamination overlay (unusable / saturated / persistence / ghost / outlier)
  pass/flags.bin    uint8 [pass][n][n]: which contamination flags cover each pixel in a pass (see pass_flags)
  overlays.json     Gaia DR3 and CatWISE2020 sources in the field with their proper motions, in field pixels
  doc["products"]   an index of all of the above; doc["target"] for a named target (see scripts/build_targets.py)
"""
import json
import os
import struct
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

from .stack import FEAT_GHOST, FEAT_OUTLIER, FEAT_OVERFLOW, FEAT_PERSIST, FEAT_SOURCE, PIX_ARCSEC

PIX_SR = (PIX_ARCSEC / 206264.806) ** 2
LAM_DS = 5                     # wavelength map is smooth: keep every 5th pixel
R_AP, R_IN, R_OUT = 2.0, 5.0, 9.0
MJD_GAIA, MJD_CATWISE = 57388.0, 57170.0      # J2016.0 and the CatWISE2020 reference epoch (2015.4)
PASS_GAP_D = 40.0              # a gap longer than this (days) starts a new survey pass
F16_MAX = 6e4                  # float16 limit used for the cube (only saturated cores and artefacts exceed it)
N_BANDS = 7                    # stack bands: 0 all detectors, 1-6 one detector each
IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
OVERLAY_TOP, GAIA_G_MAX, CATWISE_W2_MAX = 4000, 19, 17
MAS_PER_DEG = 3.6e6


# cube flag bits: 1 unusable (SPHEREx hard-bad bits or off the detector), 2 catalogued source, 4 ghost, 8 outlier,
# 16 saturated (OVERFLOW), 32 persistence. 16 and 32 always come with 1; they say why.
FL_BAD, FL_SOURCE, FL_GHOST, FL_OUTLIER, FL_SAT, FL_PERSIST = 1, 2, 4, 8, 16, 32


def flag_code(bad, feat):
    feat = np.asarray(feat)
    return (np.asarray(bad).astype(np.uint8) | ((feat & FEAT_SOURCE) > 0) * FL_SOURCE | ((feat & FEAT_GHOST) > 0) * FL_GHOST
            | ((feat & FEAT_OUTLIER) > 0) * FL_OUTLIER | ((feat & FEAT_OVERFLOW) > 0) * FL_SAT
            | ((feat & FEAT_PERSIST) > 0) * FL_PERSIST).astype(np.uint8)


def _flag_palette():
    """RGBA per flag code: saturated red, persistence violet, ghost magenta, outlier orange, other unusable grey.
    Catalogued-source pixels are too common to paint."""
    pal = np.zeros((64, 4), np.uint8)
    for v in range(64):
        if v & FL_SAT: pal[v] = (255, 70, 70, 175)
        elif v & FL_PERSIST: pal[v] = (170, 120, 255, 170)
        elif v & FL_GHOST: pal[v] = (255, 79, 216, 170)
        elif v & FL_OUTLIER: pal[v] = (255, 160, 60, 170)
        elif v & FL_BAD: pal[v] = (150, 150, 150, 140)
    return pal


FLAG_PAL = _flag_palette()


def flag_rgba(code):
    return FLAG_PAL[np.asarray(code) & 63]


def save_flag_webp(code, path):
    Image.fromarray(flag_rgba(code)[::-1]).save(path, format="WEBP", lossless=True, quality=100, method=2)


def pass_flags(code, lab, P, share=0.2):
    """uint8 [P][n][n]: per pass, the flags carried by at least `share` of its exposures at each pixel.
    Bits: 1 unusable (other reasons; mostly the detector edge), 2 saturated, 4 ghost, 8 outlier, 16 persistence."""
    n0, n1 = code.shape[1:]
    out = np.zeros((P, n0, n1), np.uint8)
    for p in range(P):
        c = code[lab == p]
        if not len(c):
            continue
        sat, per = (c & FL_SAT) > 0, (c & FL_PERSIST) > 0
        other = ((c & FL_BAD) > 0) & ~sat & ~per
        for bit, m, s in ((1, other, 0.5), (2, sat, share), (4, (c & FL_GHOST) > 0, share), (8, (c & FL_OUTLIER) > 0, share), (16, per, share)):
            out[p] |= (m.mean(0) >= s).astype(np.uint8) * bit
    return out


def passes_of(mjd, gap=PASS_GAP_D):
    """Pass label (0, 1, ...) of each time, in time order; a gap longer than `gap` days starts a new pass."""
    mjd = np.asarray(mjd)
    order = np.argsort(mjd)
    lab = np.zeros(len(mjd), int)
    if len(mjd) > 1:
        lab[order[1:]] = np.cumsum(np.diff(mjd[order]) > gap)
    return lab


def write_stack_groups(stacks16, pass_dir):
    """pass/stacks_g{k}.bin (k = 0 all detectors, 1-6 one detector): float16, C order, shape (P, n, n), no header,
    one per band group of stacks.bin, so the lab can draw the group it shows without downloading all seven.
    Each file is written to a temporary name and renamed, so a reader never sees half of one."""
    pass_dir = Path(pass_dir)
    for k in range(stacks16.shape[1]):
        p = pass_dir / f"stacks_g{k}.bin"
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_bytes(np.ascontiguousarray(stacks16[:, k], dtype=np.float16).tobytes())
        os.replace(tmp, p)


def read_stacks(path):
    """pass/stacks.bin -> float16 array (P, 7, n, n)."""
    raw = Path(path).read_bytes()
    P, B, n0, n1 = struct.unpack("<4i", raw[:16])
    return np.frombuffer(raw, np.float16, offset=16).reshape(P, B, n0, n1)


def _stretch(stacks):
    v = np.concatenate([s[np.isfinite(s)].ravel() for s in stacks if np.isfinite(s).any()] or [np.zeros(1)])
    lo, hi = np.percentile(v, 25), np.percentile(v, 99.85)
    sig = max(1e-6, float(np.percentile(np.abs(v - np.median(v)), 50)) * 1.48)
    den = np.arcsinh(max(hi - lo, 1e-6) / (3 * sig))

    def f(a):
        z = np.arcsinh(np.clip(a - lo, 0, None) / (3 * sig)) / den
        return np.nan_to_num(np.clip(z * 255, 0, 255)).astype(np.uint8)
    return f


def _save(arr8, path):
    Image.fromarray(arr8[::-1]).save(path, lossless=True, quality=100, method=4)


def phot(img, var, bad, x, y):
    """Forced aperture photometry (µJy) at field pixel (x, y), local sky from an annulus. None if unusable."""
    n0, n1 = img.shape
    x0, x1 = max(0, int(x - R_OUT - 1)), min(n1, int(x + R_OUT + 2))
    y0, y1 = max(0, int(y - R_OUT - 1)), min(n0, int(y + R_OUT + 2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    im, va, bd = img[y0:y1, x0:x1].astype(np.float32), var[y0:y1, x0:x1].astype(np.float32), bad[y0:y1, x0:x1]
    yy, xx = np.ogrid[y0:y1, x0:x1]
    r = np.hypot(xx - x, yy - y)
    ap, sky = r <= R_AP, (r >= R_IN) & (r <= R_OUT) & np.isfinite(im) & ~bd
    good = ap & np.isfinite(im) & np.isfinite(va) & ~bd
    if ap.sum() == 0 or good.sum() < 0.75 * ap.sum() or sky.sum() < 20:
        return None
    scale = ap.sum() / good.sum()
    s = float(np.median(im[sky]))
    return float(np.sum(im[good] - s) * scale * PIX_SR * 1e12), float(np.sqrt(np.sum(va[good])) * scale * PIX_SR * 1e12)


def _tap(url, q, timeout=200):
    import requests
    import urllib3
    urllib3.disable_warnings()
    r = requests.get(url, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}, verify=False, timeout=timeout)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if not lines or lines[0].startswith("<"):
        raise RuntimeError(r.text[:200])
    head = lines[0].split(",")
    return [dict(zip(head, ln.split(","))) for ln in lines[1:]]


def _fl(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except ValueError:
        return None


def overlays(f, log=print):
    """Gaia DR3 (G < 19) and CatWISE2020 sources, with positions at their catalogue epochs and motions in px/yr."""
    rad = f.size * 0.75
    out = {"gaia": [], "catwise": [], "errors": {}}

    def put(cat, recs, mjd0):
        """recs: [(ra, dec, pmra_mas, pmdec_mas, mag)]; positions and motions are projected in two WCS calls."""
        recs = [r for r in recs if r[0] is not None and r[1] is not None]
        if not recs:
            return
        ra = np.array([r[0] for r in recs])
        dec = np.array([r[1] for r in recs])
        x, y = (np.atleast_1d(v) for v in f.world_to_pix(ra, dec))
        inside = (-2 <= x) & (x <= f.shape[1] + 1) & (-2 <= y) & (y <= f.shape[0] + 1)
        has_pm = np.array([r[2] is not None and r[3] is not None for r in recs]) & inside
        x2, y2 = x.copy(), y.copy()
        if has_pm.any():
            k = np.flatnonzero(has_pm)
            c = np.maximum(np.cos(np.radians(dec[k])), 1e-6)
            pra = np.array([recs[j][2] for j in k], float)
            pde = np.array([recs[j][3] for j in k], float)
            x2[k], y2[k] = (np.atleast_1d(v) for v in f.world_to_pix(ra[k] + pra / MAS_PER_DEG / c, dec[k] + pde / MAS_PER_DEG))
        for j in np.flatnonzero(inside):
            xj, yj = float(x[j]), float(y[j])
            pmx, pmy = (float(x2[j]) - xj, float(y2[j]) - yj) if has_pm[j] else (0.0, 0.0)
            mag = recs[j][4]
            out[cat].append({"x": round(xj, 2), "y": round(yj, 2), "m": None if mag is None else round(mag, 2),
                             "pmx": round(pmx, 4), "pmy": round(pmy, 4), "mjd0": mjd0})
    try:
        from . import gaia                  # ESA's Gaia archive, MAST as the fallback
        rows = gaia.cone(f.ra, f.dec, rad, ["ra", "dec", "pmra", "pmdec", "phot_g_mean_mag"], max_g=GAIA_G_MAX,
                         top=OVERLAY_TOP, log=log)
        put("gaia", [(_fl(r["ra"]), _fl(r["dec"]), _fl(r["pmra"]), _fl(r["pmdec"]), _fl(r["phot_g_mean_mag"])) for r in rows],
            MJD_GAIA)
    except Exception as e:  # noqa: BLE001 - an overlay is optional
        out["errors"]["gaia"] = str(e)[:200]
        log(f"  Gaia overlay skipped: {e}")
    try:
        rows = _tap(IRSA_TAP,
                    f"SELECT TOP {OVERLAY_TOP} ra,dec,w1mpro,w2mpro,pmra,pmdec FROM catwise_2020 WHERE CONTAINS(POINT('ICRS',ra,dec),"
                    f"CIRCLE('ICRS',{f.ra},{f.dec},{rad}))=1 AND w2mpro<{CATWISE_W2_MAX} ORDER BY w2mpro")
        recs = []
        for r in rows:
            pa, pd = _fl(r["pmra"]), _fl(r["pmdec"])       # CatWISE motions are in arcsec/yr
            recs.append((_fl(r["ra"]), _fl(r["dec"]), None if pa is None else pa * 1000, None if pd is None else pd * 1000,
                         _fl(r["w2mpro"])))
        put("catwise", recs, MJD_CATWISE)
    except Exception as e:  # noqa: BLE001
        out["errors"]["catwise"] = str(e)[:200]
        log(f"  CatWISE overlay skipped: {e}")
    log(f"  overlays: {len(out['gaia'])} Gaia, {len(out['catwise'])} CatWISE sources")
    return out


class _Skip(Exception):
    pass


def build(f, doc, out, log=print, with_overlays=True, ov=None, flag_frames=True, pm=True):
    """Write every product for an analysed field. f is the frozen stack.Field, doc the field document.
    A quick look passes the overlays it already has (ov), writes its own flag frames and runs its own mover search."""
    out = Path(out)
    n = f.shape[0]
    idx = {(e["obs_id"], e["detector"]): e["i"] for e in doc["exposures"]}
    order = [idx.get((e["obs_id"], e["detector"])) for e in f.exps]
    keep = [k for k, i in enumerate(order) if i is not None]
    # cube in the document's exposure order
    perm = sorted(keep, key=lambda k: order[k])
    (out / "cube").mkdir(exist_ok=True)
    img16 = f.img[perm]
    hot = np.abs(np.nan_to_num(img16)) > F16_MAX          # beyond float16; only saturated cores and artefacts
    np.save(out / "cube" / "img.npy", np.clip(img16, -F16_MAX, F16_MAX).astype(np.float16))
    del img16
    np.save(out / "cube" / "var.npy", np.clip(f.var[perm], 0, F16_MAX).astype(np.float16))
    flag = flag_code(f.bad[perm] | hot, f.feat[perm])
    np.save(out / "cube" / "flag.npy", flag)
    np.save(out / "cube" / "lam.npy", f.lam[perm][:, ::LAM_DS, ::LAM_DS].astype(np.float16))
    log(f"  cube: {len(perm)} exposures")
    # contamination overlays (RGBA, see flag_rgba)
    if flag_frames:
        (out / "flag").mkdir(exist_ok=True)
        for j in range(len(perm)):
            save_flag_webp(flag[j], out / "flag" / f"{j:04d}.webp")
    shares = {nm: (((flag & bit) > 0).mean(axis=(1, 2)) if len(perm) else np.zeros(0))
              for nm, bit in (("ghost", FL_GHOST), ("outlier", FL_OUTLIER), ("sat", FL_SAT), ("persist", FL_PERSIST))}
    bad_share = (flag & FL_BAD).mean(axis=(1, 2)) if len(perm) else np.zeros(0)
    frac = [{"bad": round(float(bad_share[j]), 3), **{nm: round(float(v[j]), 4) for nm, v in shares.items()}}
            for j in range(len(perm))]
    for j, e in enumerate(doc["exposures"][:len(perm)]):
        e["flags"] = frac[j]
        if f.exps[perm[j]].get("flag_frac") is not None:
            e["flag_frac"] = f.exps[perm[j]]["flag_frac"]
    # pass x band stacks
    lab = passes_of(f.mjd)
    P = int(lab.max()) + 1
    stacks = np.full((P, N_BANDS, n, n), np.nan, np.float32)
    counts = np.zeros((P, N_BANDS), int)
    img = np.where(f.bad, np.nan, f.img)                   # masked once, not once per pass
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)    # all-NaN pixels (off the detector) stay NaN
        for p in range(P):
            sel = lab == p
            stacks[p, 0] = np.nanmedian(img[sel], axis=0)
            counts[p, 0] = int(sel.sum())
            for d in range(1, N_BANDS):
                s2 = sel & (f.det == d)
                if s2.sum() >= 2:
                    stacks[p, d] = np.nanmedian(img[s2], axis=0)
                    counts[p, d] = int(s2.sum())
    del img
    (out / "pass").mkdir(exist_ok=True)
    stacks16 = stacks.astype(np.float16)
    with open(out / "pass" / "stacks.bin", "wb") as fh:
        fh.write(struct.pack("<4i", P, N_BANDS, n, n))
        fh.write(stacks16.tobytes())
    write_stack_groups(stacks16, out / "pass")
    lab_perm = lab[perm]
    with open(out / "pass" / "flags.bin", "wb") as fh:
        fh.write(struct.pack("<4i", P, 1, n, n))
        fh.write(pass_flags(flag, lab_perm, P).tobytes())
    for d in range(N_BANDS):
        ok = [p for p in range(P) if counts[p, d]]
        if not ok:
            continue
        st = _stretch([stacks[p, d] for p in ok])
        for p in ok:
            _save(st(stacks[p, d]), out / "pass" / f"p{p}_d{d}.webp")
    passes = [{"k": p, "mjd0": round(float(f.mjd[lab == p].min()), 3), "mjd1": round(float(f.mjd[lab == p].max()), 3),
               "n": int(counts[p, 0]), "n_det": counts[p, 1:].tolist(), "dets": [d for d in range(7) if counts[p, d]]} for p in range(P)]
    log(f"  stacks: {P} passes x 7 bands")
    if ov is None:
        ov = overlays(f, log) if with_overlays else {"gaia": [], "catwise": [], "errors": {"all": "skipped"}}
    (out / "overlays.json").write_text(json.dumps(ov))
    # automatic proper-motion search on the pass stacks (sxlib/pmsearch.py)
    pm_stats = None
    try:
        if not pm:
            raise _Skip
        from .pmsearch import search_all
        import time as _t
        mid = [(q["mjd0"] + q["mjd1"]) / 2 for q in passes]
        # exposure times of each pass (all detectors, and each detector): the parallax factors of the joint fit
        times = {b: [[float(m) for m in f.mjd[(lab == p) & ((f.det == b) | (b == 0))]] for p in range(P)] for b in range(N_BANDS)}
        res = search_all(stacks, mid, ov, cdelt=list(map(float, f.wcs.wcs.cdelt)), ra=doc["ra"], dec=doc["dec"], pass_times=times, log=log)
        for c in res["candidates"]:
            r_, d_ = f.pix_to_world(c["x"], c["y"])
            c["ra"], c["dec"] = round(float(r_), 6), round(float(d_), 6)
        res.update(field=doc["id"], created=_t.strftime("%Y-%m-%dT%H:%M:%S"), pass_mjd=[round(m, 3) for m in mid])
        try:
            import sys as _s
            root = str(Path(__file__).resolve().parent.parent)
            if root not in _s.path:
                _s.path.insert(0, root)
            from scripts.pm_search import score_candidates
            score_candidates(out, doc, res["candidates"], mid)
        except Exception as e:  # noqa: BLE001
            log(f"  spectral scores skipped: {e}")
        (out / "pm_candidates.json").write_text(json.dumps(res))
        pm_stats = {k: res["stats"][k] for k in ("n_candidates", "n_new")}
    except _Skip:
        pass
    except Exception as e:  # noqa: BLE001 - the lab works without it
        log(f"  pm search skipped: {e}")
    doc["products"] = {"passes": passes, "stacks": "pass/stacks.bin", "pass_flags": "pass/flags.bin", "cube": True,
                       "flags": bool(flag_frames), "lam_ds": LAM_DS, "pm": pm_stats,
                       "overlays": {"gaia": len(ov["gaia"]), "catwise": len(ov["catwise"]), "errors": ov["errors"]},
                       "aperture_px": R_AP}
    return doc
