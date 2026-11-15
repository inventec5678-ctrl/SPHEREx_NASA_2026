"""Is this SPHEREx spectrum a cold (T or Y) brown dwarf? A small self-trained classifier.

SPHEREx's 0.75-5 µm spectrum covers the bands that make T and Y dwarfs unmistakable: methane at 1.6, 2.2 and 3.3 µm,
water at 1.15, 1.4, 1.9 and 2.7 µm, CO near 4.6 µm, and the bright 4-4.2 µm window where they put out most of their
light. Training spectra are synthetic (no labelled SPHEREx brown dwarfs exist yet): blackbodies with molecular bands
of random depth for T/Y dwarfs, and for everything else ordinary and reddened stars, M giants and Miras (which also
have deep water bands: the hard negatives), L dwarfs, and young stars with warm-dust excess. Every spectrum then gets
the SPHEREx treatment: a neighbour's light leaking in, per-band noise, and missing bands (saturation, S/N cuts).
The model never sees real data in training; it is tested on real SPHEREx spectra of Epsilon Indi B and WISE 0855
and of hundreds of Gaia stars in the analysed fields (scripts/train_specclass.py).

Inference is plain numpy (weights in models/bd_spec.npz), so the web server does not need torch.
"""
import math
from pathlib import Path

import numpy as np

EDGES = np.geomspace(0.74, 5.0, 17)            # 16 log-spaced bins over SPHEREx's range
CENTRES = np.sqrt(EDGES[:-1] * EDGES[1:])
NB = len(CENTRES)
MODEL = Path(__file__).resolve().parent.parent / "models" / "bd_spec.npz"


def bin_spectrum(lam, flux, err=None, min_snr=3.0):
    """Per-bin median of the good points. Returns (x, mask): log10 flux relative to the brightest bin, and which
    bins have data. This is the model input (2 * NB values)."""
    lam, flux = np.asarray(lam, float), np.asarray(flux, float)
    ok = np.isfinite(lam) & np.isfinite(flux) & (flux > 0)
    if err is not None:
        err = np.asarray(err, float)
        ok &= np.isfinite(err) & (flux > min_snr * err)
    k = np.searchsorted(EDGES, lam[ok], side="right") - 1          # EDGES[k] <= lam < EDGES[k + 1]
    inside = (k >= 0) & (k < NB)
    k, f = k[inside], flux[ok][inside]
    v = np.full(NB, np.nan)
    if k.size:
        order = np.argsort(k, kind="stable")
        k, f = k[order], f[order]
        bins, start, count = np.unique(k, return_index=True, return_counts=True)
        for b, a, n in zip(bins, start, count):
            if n >= 2:
                v[b] = np.median(f[a:a + n])
    return _encode(v)


def _encode(v):
    mask = np.isfinite(v) & (v > 0)
    x = np.zeros(NB)
    if mask.any():
        x[mask] = np.log10(v[mask] / v[mask].max())
    return np.clip(x, -4, 0), mask.astype(float)


# ---- synthetic spectra ----------------------------------------------------------------------------------------
H_K = 14387.77                                   # hc/k in µm K


def _bb(T, lam):
    """Blackbody in f_nu (arbitrary units)."""
    return lam ** -3 / np.expm1(np.minimum(H_K / (lam * T), 700))


def _band(lam, c, w, depth):
    return depth * np.exp(-0.5 * ((lam - c) / w) ** 2)


def _brown_dwarf(rng, lam, T):
    tau = np.zeros_like(lam)
    cold = np.clip((1300 - T) / 900, 0, 1)                         # 0 at T=1300 K, 1 below ~400 K
    for c, w, d in ((1.15, .05, (.3, 1.5)), (1.4, .08, (.8, 2.5)), (1.9, .12, (.8, 2.5)), (2.7, .25, (1.0, 3.0))):
        tau += _band(lam, c, w, rng.uniform(*d))                     # water
    for c, w, d in ((1.65, .06, (.3, 1.5)), (2.25, .15, (.5, 2.0)), (3.3, .25, (1.0, 3.5))):
        tau += _band(lam, c, w, rng.uniform(*d) * (0.3 + 0.7 * cold))  # methane
    tau += _band(lam, 4.6, .15, rng.uniform(.1, 1.0) * (1 - 0.5 * cold))   # CO (non-equilibrium)
    tau += _band(lam, 4.3, .05, rng.uniform(0, .6))                  # CO2
    tau += _band(lam, 3.0, .15, rng.uniform(0, 1.0) * cold)          # NH3 in Y dwarfs
    tau += _band(lam, 2.1, .35, rng.uniform(0, 1.0))                 # collision-induced H2 (K-band suppression)
    return _bb(T, lam) * np.exp(-tau)


def _extinct(rng, lam, f, av_max):
    ak = 0.11 * rng.uniform(0, av_max)
    return f * 10 ** (-0.4 * ak * (lam / 2.2) ** -1.75)


def _negative(rng, lam):
    kind = rng.choice(["star", "star", "mgiant", "ldwarf", "yso", "galaxy"])
    if kind == "star":
        T = np.exp(rng.uniform(np.log(2600), np.log(30000)))
        tau = _band(lam, 2.3, .1, rng.uniform(0, .3)) + _band(lam, 4.6, .15, rng.uniform(0, .3))
        if T < 4000:
            tau += sum(_band(lam, c, w, rng.uniform(0, .5)) for c, w in ((1.4, .08), (1.9, .12), (2.7, .25)))
        return _extinct(rng, lam, _bb(T, lam) * np.exp(-tau), 15), kind
    if kind == "mgiant":                                             # M giants and Miras: deep water, strong CO
        T = rng.uniform(2200, 3600)
        tau = sum(_band(lam, c, w, rng.uniform(.3, 1.8)) for c, w in ((1.4, .08), (1.9, .12), (2.7, .25), (1.15, .05)))
        tau += _band(lam, 2.3, .1, rng.uniform(.2, 1.0)) + _band(lam, 4.6, .15, rng.uniform(.2, 1.0))
        tau += _band(lam, 3.3, .2, rng.uniform(0, .4))               # weak OH/H2O near 3 µm, not methane depth
        f = _bb(T, lam) * np.exp(-tau)
        if rng.random() < .4:
            f = f + rng.uniform(.05, 1.0) * f.max() * _bb(rng.uniform(600, 1200), lam) / _bb(rng.uniform(600, 1200), lam).max()
        return _extinct(rng, lam, f, 10), kind
    if kind == "ldwarf":
        T = rng.uniform(1300, 2400)
        tau = sum(_band(lam, c, w, rng.uniform(.2, 1.2)) for c, w in ((1.4, .08), (1.9, .12), (2.7, .25)))
        tau += _band(lam, 2.3, .1, rng.uniform(.2, .8)) + _band(lam, 4.6, .15, rng.uniform(.2, .8))
        tau += _band(lam, 3.3, .2, rng.uniform(0, .5)) * (T < 1600)  # weak methane only in the latest L dwarfs
        return _bb(T, lam) * np.exp(-tau), kind
    if kind == "yso":                                                # young star + warm dust
        T = rng.uniform(3000, 9000)
        f = _bb(T, lam)
        dust = _bb(rng.uniform(250, 1500), lam)
        f = f + rng.uniform(.2, 30) * f[np.argmin(abs(lam - 2.2))] * dust / dust[np.argmin(abs(lam - 4.5))]
        return _extinct(rng, lam, f, 30), kind
    # galaxy: an old stellar population (1.6 µm bump), PAH 3.3 µm emission, a little hot dust
    T = rng.uniform(3500, 5000)
    f = _bb(T, lam) * (1 + _band(lam, 1.6, .3, rng.uniform(0, .3)))
    f = f + rng.uniform(0, .3) * f.max() * (_band(lam, 3.3, .05, 1) + _bb(rng.uniform(300, 800), lam) / _bb(500, 4.5))
    return f, kind


def synth(n, rng, p_pos=0.5):
    """n (x, mask, y) samples; y = 1 for T/Y dwarfs."""
    lam = np.geomspace(0.75, 5.0, 300)
    i1, i45 = np.argmin(abs(lam - 1.0)), np.argmin(abs(lam - 4.5))
    X, M, Y = np.zeros((n, NB)), np.zeros((n, NB)), np.zeros(n)
    for i in range(n):
        if rng.random() < p_pos:
            f = _brown_dwarf(rng, lam, np.exp(rng.uniform(np.log(250), np.log(1300)))); y = 1
        else:
            f, _ = _negative(rng, lam); y = 0
        f = f / f.max()
        if rng.random() < .45:                                       # a neighbour leaking into the aperture
            nb = _bb(rng.uniform(2800, 7000), lam)
            f = f + rng.uniform(0, 1.5) * nb / nb[i1] * f[i45] * rng.uniform(.02, 1)
        snr = 10 ** rng.uniform(0.6, 2.5)                            # S/N at the brightest point
        flux = f * (1 + rng.normal(0, 1 / snr + .03, f.size))
        err = np.full_like(f, f.max() / snr)
        sel = rng.random(f.size) > rng.uniform(0, .5)                # missing exposures
        if rng.random() < .2:                                        # a saturated or bad stretch of wavelengths
            a = rng.uniform(.75, 4.5); sel &= ~((lam > a) & (lam < a * rng.uniform(1.1, 1.8)))
        x, m = bin_spectrum(lam[sel], flux[sel], err[sel])
        X[i], M[i], Y[i] = x, m, y
    return X, M, Y


# ---- inference ------------------------------------------------------------------------------------------------
_W = None


def _weights():
    global _W
    if _W is None:
        with np.load(MODEL) as z:
            n = len(z.files) // 2
            _W = [z[f"w{k}"] for k in range(n)], [z[f"b{k}"] for k in range(n)]
    return _W


def logit(x, mask):
    """The network's raw output for one binned spectrum: the log-odds of a T/Y dwarf (score = 1 / (1 + exp(-logit))).
    None if too few bins (fewer than 5 with data). Unlike the score it does not saturate at 0 or 1, so it is what
    a plot of the score distribution uses (scripts/export_validation_detail.py)."""
    if mask.sum() < 5:
        return None
    Ws, bs = _weights()
    h = np.concatenate([x, mask])
    for k, (W, b) in enumerate(zip(Ws, bs)):
        h = h @ W + b
        if k < len(Ws) - 1:
            h = np.maximum(h, 0)
    return float(h[0])


def score(x, mask):
    """P(T/Y dwarf) for one binned spectrum; None if too few bins (fewer than 5 with data)."""
    z = logit(x, mask)
    return None if z is None else float(1 / (1 + np.exp(-z)))


def score_points(lam, flux, err):
    x, m = bin_spectrum(lam, flux, err)
    return score(x, m)


# Stamp half-size for forced photometry: products.phot only looks R_OUT + 2 (= 11) px around the position, so a
# stamp this large gives it exactly the pixels it would read from the whole frame (and reads ~0.2% of a frame).
_STAMP = 16


def phot_stamp(img, var, flag, x, y):
    """products.phot at field pixel (x, y) on one exposure (2-D arrays, possibly memory-mapped), reading only a
    stamp around (x, y); flag bits 1 and 4 (bad, ghost) mark unusable pixels as in the field lab."""
    from .products import phot
    n0, n1 = img.shape
    xa, ya = max(0, math.floor(x) - _STAMP), max(0, math.floor(y) - _STAMP)
    xb, yb = max(0, min(n1, math.floor(x) + _STAMP + 1)), max(0, min(n0, math.floor(y) + _STAMP + 1))
    sl = (slice(ya, yb), slice(xa, xb))
    bad = (np.asarray(flag[sl]) & 5).astype(bool)
    return phot(np.asarray(img[sl], np.float32), np.asarray(var[sl], np.float32), bad, x - xa, y - ya)


def track_score(img, var, flag, lam, ds, exposures, cand, pass_mjd):
    """Score a proper-motion candidate: forced photometry along its fitted track (linear in time between the
    first and last pass) in every exposure of a stored field cube. Returns (score, n_points)."""
    tr = cand["track"]
    a, z = tr[0], tr[-1]
    t0, t1 = pass_mjd[a["k"]], pass_mjd[z["k"]]
    span = max(t1 - t0, 1e-6)
    ny, nx = lam.shape[1] - 1, lam.shape[2] - 1
    L, F, E = [], [], []
    for e in exposures:
        i = e["i"]
        if i >= img.shape[0]:
            continue
        u = (e["mjd"] - t0) / span
        x = a["x"] + u * (z["x"] - a["x"]); y = a["y"] + u * (z["y"] - a["y"])
        p = phot_stamp(img[i], var[i], flag[i], x, y)
        if p is None:
            continue
        yy, xx = min(int(y) // ds, ny), min(int(x) // ds, nx)
        L.append(float(lam[i, max(yy, 0), max(xx, 0)])); F.append(p[0]); E.append(p[1])
    return score_points(L, F, E), len(F)
