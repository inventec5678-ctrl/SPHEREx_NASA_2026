"""Synthetic movers injected with the exposure's own (10x oversampled) PSF.

Two motion models:
  * LinearMover  - main-belt / NEO-like: constant sky rate, active for a few days.
  * DistantBody  - "Planet X": fixed barycentric position at distance d (AU) plus a
                   tiny proper motion; geocentric parallax from Earth's orbit makes it
                   loop by ~(206265/d) arcsec over a year.
"""
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord, get_body_barycentric
from astropy.time import Time
from scipy.ndimage import shift as ndshift

OVERSAMP = 10                 # the PSF grid of archive.load_psf: 101 x 101 samples at 10 per pixel
ARCSEC_PER_RAD = 206264.806
AB_ZP_JY = 3631.0
DISTANT_AU = (150.0, 800.0)   # random_movers: distance range of simulated distant bodies


def ab_to_jy(mag_ab):
    return AB_ZP_JY * 10 ** (-0.4 * np.asarray(mag_ab))


def psf_stamp(psf_os, fx, fy, half=5, sample=False):
    """A 101x101 10x-oversampled PSF (centre index 50) as a (2*half+1)^2 pixel stamp whose centre pixel is offset by
    (fx, fy) in [-0.5, 0.5] px from the source: integrated over each pixel for an optical PSF, sampled at the pixel
    centres for an effective PSF (sample=True; the DR1/QR3 ePSF already includes the pixel)."""
    p = np.pad(psf_os, ((5, 4), (5, 4)))                    # 110x110, centre at 55
    p = ndshift(p, (fy * OVERSAMP, fx * OVERSAMP), order=1, mode="constant")
    nb = p.shape[0] // OVERSAMP                              # 11 detector pixels, centre at 5
    blocks = p.reshape(nb, OVERSAMP, nb, OVERSAMP)
    b = blocks[:, OVERSAMP // 2, :, OVERSAMP // 2] if sample else blocks.sum((1, 3))
    s = b.sum()
    b = b / s if s > 0 else b
    c = nb // 2
    return b[c - half:c + half + 1, c - half:c + half + 1]


def add_point_source(exp, ra, dec, flux_jy):
    """Add a point source to exp.img (MJy/sr). Returns True if it landed on the cutout."""
    x, y = exp.wcs.celestial.world_to_pixel(SkyCoord(ra, dec, unit="deg"))
    x, y = float(x), float(y)
    h, w = exp.img.shape
    if not (2 <= x < w - 2 and 2 <= y < h - 2):
        return False
    ix, iy = round(x), round(y)
    if exp.psf is None:  # cached without a PSF: use the newest ePSF (else optical PSF) of the detector
        from .archive import load_psf
        exp.psf, exp.psf_hdr = load_psf(None, exp.detector)
        if exp.psf is None:
            return False
    stamp = psf_stamp(exp.psf_at(x, y), x - ix, y - iy, sample=exp.psf_is_epsf)
    omega = (exp.pixel_scale_arcsec / ARCSEC_PER_RAD) ** 2
    stamp = stamp * flux_jy * 1e-6 / omega
    half = stamp.shape[0] // 2
    y0, y1, x0, x1 = iy - half, iy + half + 1, ix - half, ix + half + 1
    sy0, sx0 = max(0, -y0), max(0, -x0)
    sy1, sx1 = stamp.shape[0] - max(0, y1 - h), stamp.shape[1] - max(0, x1 - w)
    exp.img[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] += stamp[sy0:sy1, sx0:sx1]
    return True


class LinearMover:
    """Constant sky rate (arcsec/h) along position angle pa_deg, visible for active_days around mjd0."""
    kind = "linear"

    def __init__(self, ra0, dec0, mjd0, rate_arcsec_h, pa_deg, mag_ab, active_days=4.0):
        self.ra0, self.dec0, self.mjd0 = ra0, dec0, mjd0
        self.rate, self.pa, self.mag, self.active = rate_arcsec_h, pa_deg, mag_ab, active_days

    def position(self, mjd):
        dt_h = (np.asarray(mjd) - self.mjd0) * 24
        d = self.rate * dt_h / 3600
        pa = np.radians(self.pa)
        dec = self.dec0 + d * np.cos(pa)
        ra = self.ra0 + d * np.sin(pa) / np.cos(np.radians(self.dec0))
        return ra % 360, dec

    def is_active(self, mjd):
        return abs(mjd - self.mjd0) <= self.active

    def describe(self):
        return {"kind": self.kind, "ra0": self.ra0, "dec0": self.dec0, "mjd0": self.mjd0,
                "rate_arcsec_h": self.rate, "pa_deg": self.pa, "mag_ab": self.mag}


class DistantBody:
    """Planet-X-like body: barycentric position fixed at reference epoch, distance d_au,
    plus a small linear proper motion (its own orbital motion)."""
    kind = "distant"

    def __init__(self, ra0, dec0, d_au, mag_ab, mjd_ref, pm_arcsec_yr=(0.0, 0.0)):
        self.ra0, self.dec0, self.d, self.mag, self.mjd_ref = ra0, dec0, d_au, mag_ab, mjd_ref
        self.pm = pm_arcsec_yr
        # (ra0, dec0) is the *geocentric* direction at mjd_ref -> barycentric position
        t = Time(mjd_ref, format="mjd")
        e = get_body_barycentric("earth", t).xyz.to(u.au).value
        dirv = SkyCoord(ra0, dec0, unit="deg").cartesian.xyz.value
        # solve |e + s*dir| = d for s>0
        b = e @ dirv
        s = -b + np.sqrt(b * b - (e @ e - d_au ** 2))
        self.r_bary = e + s * dirv

    def position(self, mjd):
        mjd = np.atleast_1d(mjd)
        t = Time(mjd, format="mjd")
        e = get_body_barycentric("earth", t).xyz.to(u.au).value.T     # (n, 3)
        r = self.r_bary[None, :] - e
        c = SkyCoord(x=r[:, 0], y=r[:, 1], z=r[:, 2], representation_type="cartesian").spherical
        dt_yr = (mjd - self.mjd_ref) / 365.25
        dec = c.lat.deg + self.pm[1] * dt_yr / 3600
        ra = c.lon.deg + self.pm[0] * dt_yr / 3600 / np.cos(np.radians(dec))
        return np.squeeze(ra % 360), np.squeeze(dec)

    def is_active(self, mjd):
        return True

    def describe(self):
        return {"kind": self.kind, "ra0": self.ra0, "dec0": self.dec0, "d_au": self.d,
                "mag_ab": self.mag, "mjd_ref": self.mjd_ref, "pm_arcsec_yr": list(self.pm)}


def random_movers(rng, field, mjds, n_linear, n_distant=0, mag_range=(15.0, 20.5),
                  rate_range=(2.0, 120.0), margin_deg=0.05):
    """Random injections spread over the field and the available exposure times."""
    half = field.size / 2 - margin_deg
    out = []
    for _ in range(n_linear):
        mjd0 = float(rng.choice(mjds))
        ra = field.ra + rng.uniform(-half, half) / np.cos(np.radians(field.dec))
        dec = field.dec + rng.uniform(-half, half)
        rate = float(np.exp(rng.uniform(np.log(rate_range[0]), np.log(rate_range[1]))))
        out.append(LinearMover(ra, dec, mjd0, rate, float(rng.uniform(0, 360)),
                               float(rng.uniform(*mag_range))))
    for _ in range(n_distant):
        ra = field.ra + rng.uniform(-half, half) / np.cos(np.radians(field.dec))
        dec = field.dec + rng.uniform(-half, half)
        out.append(DistantBody(ra, dec, float(rng.uniform(*DISTANT_AU)), float(rng.uniform(*mag_range)),
                               float(np.median(mjds))))
    return out


def injector(movers, log):
    """Build an inject_fn for Field.add that adds every active mover; logs truth."""
    def fn(exp):
        for k, m in enumerate(movers):
            if not m.is_active(exp.mjd):
                continue
            ra, dec = m.position(exp.mjd)
            if add_point_source(exp, float(ra), float(dec), float(ab_to_jy(m.mag))):
                log.append({"mover": k, "obs_id": exp.meta["obs_id"], "detector": exp.detector,
                            "mjd": float(exp.mjd), "ra": float(ra), "dec": float(dec)})
    return fn
