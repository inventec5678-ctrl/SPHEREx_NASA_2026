"""Numbers quoted in the manuscript in reply to the third referee report (runs from any working directory).
1) trailing loss of parallax-only stacking at 250-500 au; 2) pixel-phase bias of the 3x3 first-moment centroid;
3) per-detector astrometric residuals of known asteroids; 4) fraction of pixels where eps*R exceeds the exposure noise.
The reference-epoch / self-subtraction statistics are in check_selfsub.py."""
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.special import erf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE, FIELDS, read_json  # noqa: E402

PIX, FWHM = 6.15, 5.0             # pixel (arcsec), PSF FWHM (arcsec)
SIG_PIX = FWHM / 2.355 / PIX      # PSF sigma in pixels
PASS_DAYS = 14                    # span of one survey pass
ARCSEC_PER_RAD = 206265
TRAIL_DISTANCES = (250, 300, 350, 400, 500)
RESID_MAX = 5.0                   # arcsec: residuals beyond this are reported as outliers
EPS = 0.1
MIN_PIXELS = 1000


def trail_peak(L, os_=20, n=400):
    """Peak pixel of a Gaussian PSF (FWHM 5") trailed over L pixels, integrated over 6.15" pixels, best phase."""
    img = np.zeros((n, n))
    xs = np.linspace(-L / 2, L / 2, max(2, int(L * os_) + 1)) * os_ + n / 2
    np.add.at(img[n // 2], np.rint(xs).astype(int), 1 / len(xs))
    img = gaussian_filter(img, SIG_PIX * os_)
    best = 0
    for ph in range(0, os_, 4):
        m = (n - ph) // os_ * os_
        b = img[ph:ph + m, ph:ph + m]
        best = max(best, b.reshape(m // os_, os_, m // os_, os_).sum((1, 3)).max())
    return best


def trailing_loss():
    p0 = trail_peak(0)
    for d in TRAIL_DISTANCES:
        L = 2 * np.pi * d ** -1.5 * ARCSEC_PER_RAD * PASS_DAYS / 365.25 / PIX
        print(f"trail {d} au: {L:.2f} px, loss {-2.5 * np.log10(trail_peak(L) / p0):.2f} mag")


def centroid_bias():
    c = np.linspace(-0.5, 0.5, 101)[:, None]
    k = np.arange(-3, 4)
    s2 = np.sqrt(2) * SIG_PIX
    v = 0.5 * (erf((k + 0.5 - c) / s2) - erf((k - 0.5 - c) / s2))       # (101, 7) pixel fluxes
    i0 = np.argmax(v, axis=1)
    win = i0[:, None] + np.arange(-1, 2)                                 # the 3 pixels around the peak
    w = np.take_along_axis(v, win, axis=1)
    errs = ((k[win] * w).sum(1) / w.sum(1) - c[:, 0]) * PIX
    print(f"centroid pixel-phase bias: 1-D max {abs(errs).max():.2f}\", 2-D rms {np.sqrt(2 * (errs ** 2).mean()):.2f}\"")


def astrometry():
    per, allr = {}, []
    for fn in sorted(FIELDS.glob("*/field.json")):
        doc = read_json(fn)
        ex, C = doc["exposures"], doc["candidates"]
        for t in doc["tracks"]:
            j = t.get("jpl")
            if not j or not j["consistent"]:
                continue
            for k, dx, dy in j["resid"]:
                r = float(np.hypot(dx, dy))
                allr.append(r)
                if r <= RESID_MAX:
                    per.setdefault(ex[C[int(k)]["i"]]["detector"], []).append(r)
    print(f"astrometry: {len(allr)} residuals, {sum(r > RESID_MAX for r in allr)} beyond 5\"")
    for d in sorted(per):
        print(f"  D{d}: n={len(per[d])} median {np.median(per[d]):.2f}\"")


def eps_fraction():
    fr = []
    for f in sorted((CACHE / "cutouts").glob("*.npz")):
        with np.load(f) as z:
            if "img" not in z or "var" not in z:
                continue
            img, var = z["img"], z["var"]
        ok = np.isfinite(img) & np.isfinite(var) & (var > 0)
        if ok.sum() < MIN_PIXELS:
            continue
        im = img[ok]
        fr.append(np.mean(EPS * (im - np.nanmedian(im)) > np.sqrt(var[ok])))
    print(f"eps*R > sigma_I: median {100 * np.median(fr):.1f}% of pixels (10-90%: {100 * np.percentile(fr, 10):.1f}-"
          f"{100 * np.percentile(fr, 90):.1f}%) over {len(fr)} exposures")


if __name__ == "__main__":
    trailing_loss()
    centroid_bias()
    astrometry()
    eps_fraction()
