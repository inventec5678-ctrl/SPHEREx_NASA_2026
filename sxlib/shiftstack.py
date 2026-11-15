"""Shift-and-stack search for distant bodies too faint for single exposures.

Within one survey pass (a week or two) a body beyond ~50 au moves almost only by Earth's parallax, and that
motion is the same for the whole 0.5 deg field to within a fraction of a pixel. For each trial distance we
shift every difference S/N image of the pass back to the pass mid-time along the predicted parallax path and
add them: noise grows as sqrt(N), a body on the path as N, so S/N grows as sqrt(N) (~7x for 50 images).
Peaks found this way, one per pass, are then linked across passes with link.link_groups (parallax + bound
orbital drift), exactly like single-exposure detections.

Works from a field directory written by analyze.py (field.json + diff/<i>.webp, where 8-bit value = 128 + 16 S/N).
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import link

PIX = 6.15
LINK_TOL = 4.0     # stacked peaks are centroided to ~0.3 px; single detections use 8"
DIFF_ZERO, DIFF_GAIN = 128.0, 16.0     # diff/<i>.webp: 8-bit value = 128 + 16 S/N
PASS_GAP_D = 40.0
MIN_PASS_IMAGES = 8                    # passes with fewer images are not stacked
MERGE_PX = 2.5                         # stacked peaks closer than this are one peak
STATIC_DT_D = (100.0, 250.0)           # drop_static compares passes this far apart (days)


def _d_grid(d_grid):
    return d_grid if d_grid is not None else np.geomspace(40, 3000, 36)


def _star_mask_of(med):
    """Pixels within 2 px of a bright star core in a median sky image (8-bit display units)."""
    return ndimage.maximum_filter(med, size=5) > max(2 * np.percentile(med, 99), 120)


class FieldWCS:
    """The TAN grid of a field.json (same convention as the web app: x, y in pixels, y up, origin 0)."""
    def __init__(self, w):
        self.crval, self.crpix, self.cdelt = np.array(w["crval"]), np.array(w["crpix"]), np.array(w["cdelt"])

    def to_world(self, x, y):
        d2r = np.pi / 180
        xi = (np.asarray(x) + 1 - self.crpix[0]) * self.cdelt[0] * d2r
        eta = (np.asarray(y) + 1 - self.crpix[1]) * self.cdelt[1] * d2r
        a0, d0 = self.crval * d2r
        den = np.cos(d0) - eta * np.sin(d0)
        ra = a0 + np.arctan2(xi, den)
        dec = np.arctan2(np.sin(d0) + eta * np.cos(d0), np.hypot(xi, den))
        return (ra / d2r) % 360, dec / d2r

    def to_pix(self, ra, dec):
        d2r = np.pi / 180
        a, d = np.asarray(ra) * d2r, np.asarray(dec) * d2r
        a0, d0 = self.crval * d2r
        cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
        xi = np.cos(d) * np.sin(a - a0) / cosc
        eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
        return xi / d2r / self.cdelt[0] + self.crpix[0] - 1, eta / d2r / self.cdelt[1] + self.crpix[1] - 1


def load_field(fdir):
    """S/N maps (y up) and metadata of every exposure of a field written by analyze.py."""
    fdir = Path(fdir)
    doc = json.loads((fdir / "field.json").read_text())
    ext = doc.get("frame_ext", "png")
    maps = []
    for e in doc["exposures"]:
        with Image.open(fdir / "diff" / f"{e['i']:04d}.{ext}") as im:
            v = np.asarray(im.convert("L"), dtype=np.float32)[::-1]
        maps.append((v - DIFF_ZERO) / DIFF_GAIN)
    return doc, np.stack(maps)


def passes_of(mjd, gap=PASS_GAP_D):
    """Exposure indices of each survey pass (a gap longer than `gap` days starts a new one), each sorted."""
    order = np.argsort(mjd)
    out, cur = [], [order[0]]
    for i in order[1:]:
        if mjd[i] - mjd[cur[-1]] > gap:
            out.append(cur); cur = []
        cur.append(i)
    out.append(cur)
    return [np.array(sorted(p)) for p in out]


def stack_pass(doc, snr, idx, d_grid, thresh=6.0, min_cover=0.6, clip=3.0, at=None):
    """Stacked peaks of one pass: [{x, y, ra, dec, mjd, snr, d_au, n}] with positions at the pass mid-time.
    Each frame is clipped to +-clip sigma first: a body too faint for single exposures is ~1 sigma per frame,
    while asteroids, cosmic rays and subtraction residuals are single-frame outliers that would otherwise pile
    up into false stacked peaks. The stack is then scaled by its own robust noise (the difference images are
    not exactly unit-variance). at=(x, y, r): return only the highest stacked value within r px of (x, y)."""
    wcs = FieldWCS(doc["wcs"])
    ex = doc["exposures"]
    H, W = snr.shape[1:]
    mjd = np.array([ex[i]["mjd"] for i in idx])
    t0 = float(np.median(mjd))
    ra_c, dec_c = wcs.to_world((W - 1) / 2, (H - 1) / 2)
    x_c, y_c = (W - 1) / 2, (H - 1) / 2
    # a pixel equal to exactly 0 S/N in the 8-bit frame is mostly "no data"; count only pixels with a value
    valid = np.abs(snr[idx]) > 1e-6
    # the clipped frames and coverage maps do not depend on the trial distance: prepare them once per pass
    clipped = [np.where(valid[k], np.clip(snr[i], -clip, clip), 0) for k, i in enumerate(idx)]
    vmaps = valid.astype(np.float32)
    E = link._earth(mjd)
    E0 = link._earth(t0)[0]
    best = {}
    for dau in d_grid:
        pra, pdec = link.predict_distant(ra_c, dec_c, t0, dau, mjd, E, E0)
        px, py = wcs.to_pix(pra, pdec)
        acc = np.zeros((H, W), np.float32)
        cnt = np.zeros((H, W), np.float32)
        for k in range(len(idx)):
            dx, dy = px[k] - x_c, py[k] - y_c                     # where a body at the centre at t0 is at t_k
            acc += ndimage.shift(clipped[k], (-dy, -dx), order=1, mode="constant")
            cnt += ndimage.shift(vmaps[k], (-dy, -dx), order=1, mode="constant")
        ok = cnt >= min_cover * len(idx)
        st = np.where(ok, acc / np.sqrt(np.maximum(cnt, 1)), 0)
        v = st[ok]
        if v.size > 100:
            med = float(np.median(v)); sig = 1.4826 * float(np.median(np.abs(v - med)))
            st = np.where(ok, (st - med) / max(sig, 1e-3), 0)
        if at is not None:
            x0, y0, r = at
            win = st[max(0, int(y0 - r)):int(y0 + r) + 1, max(0, int(x0 - r)):int(x0 + r) + 1]
            return float(win.max()) if win.size else 0.0
        mx = ndimage.maximum_filter(st, size=5)
        ys, xs = np.where((st == mx) & (st >= thresh))
        for x, y in zip(xs, ys):
            key = (int(x) // 2, int(y) // 2)
            if key not in best or st[y, x] > best[key]["snr"]:
                ra, dec = wcs.to_world(x, y)
                best[key] = {"x": float(x), "y": float(y), "ra": float(ra), "dec": float(dec), "mjd": t0,
                             "snr": float(st[y, x]), "d_au": float(dau), "n": int(cnt[y, x])}
    # peaks that only appear at one trial distance among many neighbours are kept; merge duplicates within 2 px
    peaks = sorted(best.values(), key=lambda p: -p["snr"])
    out = []
    for p in peaks:
        if all(np.hypot(p["x"] - q["x"], p["y"] - q["y"]) > MERGE_PX for q in out):
            out.append(p)
    return out


def confirm(doc, snr, P, tracks, peaks, thresh, frac=0.8, r_px=1.5):
    """A real body is a stacked peak at the distance of the whole track in every pass; a static residual or a
    chance alignment peaks at some other trial distance. Re-stack each member's pass at the linked distance
    (and drift) and keep tracks whose members all stay >= frac * thresh there."""
    out = []
    for t in tracks:
        d = float(t["d_au"])
        if all(stack_pass(doc, snr, P[peaks[m]["pass"]], [d], thresh=0.0, at=(peaks[m]["x"], peaks[m]["y"], r_px))
               >= frac * thresh for m in t["members"]):
            out.append(t)
    return out


def star_mask(fdir, doc, step=8):
    """Pixels within 2 px of a bright star core (median sky image): stacked peaks there are subtraction
    residuals far more often than real bodies. Returns (mask, masked fraction)."""
    ext = doc.get("frame_ext", "png")
    frames = []
    for e in doc["exposures"][::step]:
        with Image.open(Path(fdir) / "sci" / f"{e['i']:04d}.{ext}") as im:
            frames.append(np.asarray(im.convert("L"), dtype=np.float32)[::-1])
    m = _star_mask_of(np.median(np.stack(frames), 0))
    return m, float(m.mean())


def drop_static(groups, dets, log=print, tol_px=2.0, pix_arcsec=PIX):
    """A real body beyond our distance range still moves >= 20 px between passes half a year apart
    (parallax); a peak that sits on another peak of such a pass is a static residual (star, artefact)."""
    keep = []
    if groups:
        gra = np.array([g["ra"] for g in groups])
        gdec = np.array([g["dec"] for g in groups])
        gmjd = np.array([g["mjd"] for g in groups])
    for k, g in enumerate(groups):
        dt = np.abs(gmjd - g["mjd"])
        other = (STATIC_DT_D[0] <= dt) & (dt <= STATIC_DT_D[1])
        other[k] = False
        static = False
        if other.any():
            x, y = link._tangent(gra[other], gdec[other], g["ra"], g["dec"])
            static = bool((np.hypot(x, y) <= tol_px * pix_arcsec).any())
        if not static:
            keep.append(g)
    log(f"  {len(groups) - len(keep)} of {len(groups)} stacked peaks are static residuals")
    new_dets = []
    for g in keep:
        new_dets.append(dets[g["members"][0]])
        g["members"] = [len(new_dets) - 1]
    return keep, new_dets


def search(fdir, d_grid=None, thresh=7.0, log=print):
    """Shift-and-stack every pass of a field, then link the stacked peaks across passes."""
    d_grid = _d_grid(d_grid)
    doc, snr = load_field(fdir)
    mjd = np.array([e["mjd"] for e in doc["exposures"]])
    groups, dets = [], []
    P = passes_of(mjd)
    for k, idx in enumerate(P):
        if len(idx) < MIN_PASS_IMAGES:
            continue
        pk = stack_pass(doc, snr, idx, d_grid, thresh)
        log(f"  pass {k}: {len(idx)} images, {len(pk)} stacked peaks >= {thresh}")
        for p in pk:
            dets.append({"ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "p": p["snr"]})
            groups.append({"pass": k, "members": [len(dets) - 1], "ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "peak": p})
    mask, frac = star_mask(fdir, doc)
    before = len(groups)
    groups = [g for g in groups if not mask[int(round(g["peak"]["y"])), int(round(g["peak"]["x"]))]]
    dets = [dets[g["members"][0]] for g in groups]
    for k, g in enumerate(groups):
        g["members"] = [k]
    log(f"  star mask covers {100 * frac:.1f}% of the field; {before - len(groups)} peaks on it dropped")
    groups, dets = drop_static(groups, dets, log)
    peaks = [g["peak"] | {"pass": g["pass"]} for g in groups]
    tracks = link.link_groups(groups, dets, tol_arcsec=LINK_TOL) if groups else []
    n_link = len(tracks)
    tracks = confirm(doc, snr, P, tracks, peaks, thresh)
    log(f"  {n_link} linked, {len(tracks)} confirmed at the track distance")
    return {"peaks": peaks, "tracks": tracks, "n_passes": len(P), "n_linked": n_link,
            "masked_fraction": round(frac, 4)}


def search_arrays(exposures, wcs, snr, sci_median, d_grid=None, thresh=7.0, windows=None, log=print):
    """Same search on in-memory arrays (injection tests). exposures: [{mjd}], wcs: {crval, crpix, cdelt},
    snr: (N, H, W) difference S/N, sci_median: (H, W) median sky for the star mask. windows: optional
    [(mjd0, mjd1)] to stack only those passes (fields that follow a moving target)."""
    d_grid = _d_grid(d_grid)
    doc = {"wcs": wcs, "exposures": [{"mjd": e["mjd"]} for e in exposures]}
    mjd = np.array([e["mjd"] for e in exposures])
    m = _star_mask_of(sci_median)
    groups, dets = [], []
    P = passes_of(mjd) if windows is None else [np.where((mjd >= a) & (mjd <= b))[0] for a, b in windows]
    for k, idx in enumerate(P):
        if len(idx) < MIN_PASS_IMAGES:
            continue
        for p in stack_pass(doc, snr, idx, d_grid, thresh):
            if m[int(round(p["y"])), int(round(p["x"]))]:
                continue
            dets.append({"ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "p": p["snr"]})
            groups.append({"pass": k, "members": [len(dets) - 1], "ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"], "peak": p})
    groups, dets = drop_static(groups, dets, log)
    peaks = [g["peak"] | {"pass": g["pass"]} for g in groups]
    tracks = link.link_groups(groups, dets, tol_arcsec=LINK_TOL) if groups else []
    n_link = len(tracks)
    tracks = confirm(doc, snr, P, tracks, peaks, thresh)
    return {"peaks": peaks, "tracks": tracks, "n_linked": n_link, "masked_fraction": float(m.mean())}
