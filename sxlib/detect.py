"""Candidate detection on difference images and CNN input stamps."""
import numpy as np
from scipy.ndimage import maximum_filter

from .stack import FEAT_GHOST, FEAT_SOURCE

STAMP = 21           # px (~2.2 arcmin)
# The L2 MP_OUTLIER bit fires on real moving objects but never on injected ones, so it is
# deliberately NOT a CNN input (it would be a simulation-only shortcut).
CHANNELS = ["sci", "ref", "snr", "src_ghost"]
ASINH_SOFT = 3.0     # stamps are arcsinh(value / 3) in noise units

_D3 = np.arange(-1, 2)


def find_candidates(d, thr=5.0, edge=STAMP // 2 + 1, footprint=5):
    snr = np.nan_to_num(d["snr"], nan=-np.inf)
    peak = (snr == maximum_filter(snr, size=footprint)) & (snr >= thr)
    peak[:edge] = peak[-edge:] = False
    peak[:, :edge] = peak[:, -edge:] = False
    ys, xs = np.nonzero(peak)
    if not len(ys):
        return []
    # sub-pixel centroid from the 3x3 positive part of the difference (all peaks at once)
    win = np.clip(np.nan_to_num(d["diff"][ys[:, None, None] + _D3[None, :, None], xs[:, None, None] + _D3[None, None, :]]),
                  0, None)
    s = win.sum((1, 2))
    pos = s > 0
    ss = np.where(pos, s, 1.0)
    dy = np.where(pos, (win * _D3[None, :, None]).sum((1, 2)) / ss, 0.0)
    dx = np.where(pos, (win * _D3[None, None, :]).sum((1, 2)) / ss, 0.0)
    sv = snr[ys, xs]
    return [{"x": float(x + ddx), "y": float(y + ddy), "ix": int(x), "iy": int(y), "snr": float(v)}
            for x, y, ddx, ddy, v in zip(xs, ys, dx, dy, sv)]


def stamps(field, i, d, cands, size=STAMP):
    """(N, C, size, size) float32 stamps in noise units, asinh-compressed."""
    h = size // 2
    out = np.zeros((len(cands), len(CHANNELS), size, size), np.float32)
    if not cands:
        return out
    # gather every stamp window at once (index arrays), then transform only those pixels
    off = np.arange(-h, h + 1)
    iy = np.array([c["iy"] for c in cands])[:, None, None] + off[None, :, None]
    ix = np.array([c["ix"] for c in cands])[:, None, None] + off[None, None, :]
    with np.errstate(all="ignore"):
        noise = np.sqrt(field.var[i][iy, ix])
        out[:, 0] = np.arcsinh(np.nan_to_num(field.img[i][iy, ix] / noise) / ASINH_SOFT)
        out[:, 1] = np.arcsinh(np.nan_to_num(d["ref"][iy, ix] / noise) / ASINH_SOFT)
    out[:, 2] = np.arcsinh(np.nan_to_num(d["snr"][iy, ix]) / ASINH_SOFT)
    out[:, 3] = (field.feat[i][iy, ix] & (FEAT_SOURCE | FEAT_GHOST)) != 0
    return out


def match(cands, xs, ys, radius):
    """Index of nearest truth (xs, ys) within radius px for each candidate, else -1."""
    if len(xs) == 0 or len(cands) == 0:
        return np.full(len(cands), -1)
    cx = np.array([c["x"] for c in cands])[:, None]
    cy = np.array([c["y"] for c in cands])[:, None]
    d = np.hypot(cx - np.asarray(xs)[None], cy - np.asarray(ys)[None])
    j = d.argmin(1)
    return np.where(d[np.arange(len(cands)), j] <= radius, j, -1)
