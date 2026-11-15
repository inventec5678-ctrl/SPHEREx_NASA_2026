"""Common-grid alignment, per-pixel wavelength-matched references, difference images."""
import warnings

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from scipy.ndimage import binary_erosion

from .archive import FLAG_MASKS, GHOST_BITS, HARD_BAD, OUTLIER_BITS, OVERFLOW_BITS, PERSIST_BITS, SOURCE_BITS, bitmask

PIX_ARCSEC = 6.15
FEAT_SOURCE, FEAT_GHOST, FEAT_OUTLIER = 1, 2, 4
FEAT_OVERFLOW, FEAT_PERSIST = 8, 16     # also in the bad mask; kept so a display can say why

COVER_MIN = 0.99          # a field pixel counts as covered when the resampling footprint reaches this
EDGE_ERODE = 3            # px trimmed off the covered area: detector/cutout edges are noisy
MIN_COVER_FRAC = 0.05     # exposures covering less of the field are skipped
BRIGHT_SNR = 30.0         # reference pixels above this S/N set the flux scale alpha
ALPHA_RANGE = (0.7, 1.4)
MIN_BRIGHT_PIX = 20

_HARD_BAD = bitmask(HARD_BAD)
# (L2 FLAGS mask, feature bit) pairs for the per-pixel feature map
_FEATURES = ((bitmask(SOURCE_BITS), FEAT_SOURCE), (bitmask(GHOST_BITS), FEAT_GHOST), (bitmask(OUTLIER_BITS), FEAT_OUTLIER),
             (bitmask(OVERFLOW_BITS), FEAT_OVERFLOW), (bitmask(PERSIST_BITS), FEAT_PERSIST))


def field_wcs(ra, dec, size_deg, pix_arcsec=PIX_ARCSEC):
    n = int(round(size_deg * 3600 / pix_arcsec)) | 1  # odd -> centre on a pixel
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix_arcsec / 3600, pix_arcsec / 3600]
    return w, (n, n)


def _release_name(collection):
    """'spherex_dr1' -> 'DR1', 'spherex_qr3' -> 'QR3' (the data release an exposure came from; '' if unknown)."""
    return collection.replace("spherex_", "").upper() if collection else ""


def _feature_map(fl):
    feat = np.zeros(fl.shape, np.uint8)
    for mask, bit in _FEATURES:
        feat |= ((fl & mask) != 0).astype(np.uint8) * np.uint8(bit)
    return feat


class Field:
    """A square sky patch with every exposure resampled onto one TAN grid."""

    def __init__(self, ra, dec, size_deg):
        self.ra, self.dec, self.size = ra, dec, size_deg
        self.wcs, self.shape = field_wcs(ra, dec, size_deg)
        self.exps = []          # metadata dicts
        self._img, self._var, self._bad, self._feat, self._lam = [], [], [], [], []

    # ------------------------------------------------------------------ building
    def add(self, exp, inject_fn=None):
        """Resample an archive.Exposure onto the field grid. inject_fn(exp) may add
        synthetic sources to exp.img (native frame) before resampling."""
        from reproject import reproject_interp          # heavy import: only when a field is built
        if inject_fn is not None:
            inject_fn(exp)
        src = exp.wcs.celestial
        img, cov = reproject_interp((exp.img, src), self.wcs, self.shape, order="bilinear")
        var, _ = reproject_interp((exp.var, src), self.wcs, self.shape, order="bilinear")
        fl, _ = reproject_interp((exp.flags.astype(float), src), self.wcs, self.shape, order="nearest-neighbor")
        fl = np.nan_to_num(fl).astype(np.int64)
        cov = (cov > COVER_MIN) & np.isfinite(img) & np.isfinite(var) & (var > 0)
        cov = binary_erosion(cov, iterations=EDGE_ERODE)
        if cov.sum() < MIN_COVER_FRAC * cov.size:
            return False                              # (checked before the wavelength map, the costliest part)
        lam, _ = reproject_interp((exp.wavelength_map(), src), self.wcs, self.shape, order="bilinear")
        bad = ((fl & _HARD_BAD) != 0) | ~cov
        feat = _feature_map(fl)
        # share of the covered pixels carrying each SPHEREx flag (metadata shown with the frame)
        fc = fl[cov]
        flag_frac = {}
        for nm, m in FLAG_MASKS.items():
            v = float(((fc & m) != 0).mean())
            if v > 0:
                flag_frac[nm] = round(v, 4)
        good = cov & ~bad
        img = img - np.nanmedian(img[good])  # residual background after ZODI subtraction
        self.exps.append({"obs_id": exp.meta["obs_id"], "url": exp.meta["url"], "mjd": float(exp.mjd),
                          "detector": exp.detector, "lam_um": float(np.nanmedian(lam[good])),
                          "pix_arcsec": exp.pixel_scale_arcsec, "flag_frac": flag_frac,
                          "release": _release_name(exp.meta.get("collection", ""))})
        self._img.append(np.where(cov, img, np.nan).astype(np.float32))
        self._var.append(np.where(cov, var, np.nan).astype(np.float32))
        self._bad.append(bad)
        self._feat.append(feat)
        self._lam.append(np.where(cov, lam, np.nan).astype(np.float32))
        return True

    def freeze(self):
        order = np.argsort([e["mjd"] for e in self.exps])
        self.exps = [self.exps[i] for i in order]
        for name in ("img", "var", "bad", "feat", "lam"):
            lst = getattr(self, "_" + name)
            setattr(self, name, np.stack([lst[i] for i in order]))   # one copy instead of stack + reorder
            delattr(self, "_" + name)
        self.mjd = np.array([e["mjd"] for e in self.exps])
        self.det = np.array([e["detector"] for e in self.exps])
        return self

    # --------------------------------------------------------------- reference
    def reference(self, i, lam_tol=0.02, min_dt_h=3.0, max_ref=12):
        """Median of same-detector exposures whose wavelength *at each pixel* is within
        lam_tol (fractional) and that are >= min_dt_h away in time (so movers have left)."""
        cand = np.flatnonzero((self.det == self.det[i]) & (np.abs(self.mjd - self.mjd[i]) * 24 >= min_dt_h))
        cand = cand[cand != i]
        if len(cand) == 0:
            nan = np.full(self.shape, np.nan, np.float32)
            return nan, nan, np.zeros(self.shape, np.int16)
        # prefer the closest wavelengths (at field centre) when there are many
        dl = np.abs(np.array([self.exps[j]["lam_um"] for j in cand]) - self.exps[i]["lam_um"])
        cand = cand[np.argsort(dl)][: 3 * max_ref]
        lam_i = self.lam[i]
        ok = (~self.bad[cand]) & (np.abs(self.lam[cand] - lam_i) <= lam_tol * lam_i)
        vals = np.where(ok, self.img[cand], np.nan)
        n = ok.sum(0).astype(np.int16)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ref = np.nanmedian(vals, 0)
            v = np.nanmean(np.where(ok, self.var[cand], np.nan), 0)
        # variance of a median of n samples ~ (pi/2) var / n  (n>=3); mean-like for n<=2
        var_ref = np.where(n >= 3, np.pi / 2 * v / np.maximum(n, 1), v / np.maximum(n, 1))
        return ref.astype(np.float32), var_ref.astype(np.float32), n

    def difference(self, i, eps=0.1, scale=True, **kw):
        """sci - alpha*ref in noise units. eps adds a fractional systematic error
        (eps*ref_flux)^2: SPHEREx's PSF is undersampled (FWHM ~5" < 6.15" px), so resampled
        star peaks never subtract perfectly."""
        ref, var_ref, n = self.reference(i, **kw)
        sci = self.img[i]
        alpha = 1.0
        if scale:
            with np.errstate(all="ignore"):
                bright = (ref / np.sqrt(var_ref) > BRIGHT_SNR) & np.isfinite(sci) & (n >= 1) & ~self.bad[i]
            if bright.sum() >= MIN_BRIGHT_PIX:
                alpha = float(np.median(sci[bright] / ref[bright]))
                alpha = float(np.clip(alpha, *ALPHA_RANGE))
        diff = sci - alpha * ref
        with np.errstate(all="ignore"):
            # star residuals scale with the flux of what is in the REFERENCE; a mover is only in
            # sci, so using sci here would cap real movers at S/N ~ 1/eps
            sys2 = (eps * np.maximum(alpha * ref, 0)) ** 2
            snr = diff / np.sqrt(self.var[i] + alpha ** 2 * var_ref + sys2)
        valid = (n >= 1) & ~self.bad[i] & np.isfinite(snr)
        return {"diff": diff, "snr": np.where(valid, snr, np.nan), "ref": alpha * ref,
                "var_ref": alpha ** 2 * var_ref, "nref": n, "valid": valid, "alpha": alpha}

    # ----------------------------------------------------------------- helpers
    def world_to_pix(self, ra, dec):
        x, y = self.wcs.world_to_pixel(SkyCoord(ra, dec, unit="deg"))
        return np.asarray(x, float), np.asarray(y, float)

    def pix_to_world(self, x, y):
        c = self.wcs.pixel_to_world(x, y)
        return c.ra.deg, c.dec.deg
