"""The challenge's named test targets: catalogue astrometry and where each one is at any moment.

Positions come from Gaia DR3 (epoch 2016.0). WISE 0855 is too faint for Gaia; it uses the coordinates
the challenge page gives (AllWISE, epoch taken as 2010.5) with the Luhman & Esplin (2016) proper motion
and parallax. Predicted positions include proper motion and the parallax seen from Earth (SPHEREx is in
low Earth orbit, 0.0001 au from the geocentre), so a fast nearby object's track can be drawn on every frame.
"""
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, get_body_barycentric
from astropy.time import Time

TARGETS = {
    "barnard": {
        "name": "Barnard's Star", "kind": "pm",
        "about": "The fastest-moving star in the sky: a red dwarf 1.8 parsecs away that moves 10.4 arcseconds a year.",
        "source": "Gaia DR3 4472832130942575872",
        "ra": 269.44850252543836, "dec": 4.739420051112412, "pmra": -801.551, "pmdec": 10362.394, "plx": 546.976, "epoch": 2016.0,
    },
    "epsindi": {
        "name": "Epsilon Indi B", "kind": "pm",
        "about": "A pair of brown dwarfs orbiting the star Epsilon Indi, 3.7 parsecs away; together they move 4.7 arcseconds a year.",
        "source": "Gaia DR3 6412596012146801152",
        "ra": 331.07645259656397, "dec": -56.79381206688221, "pmra": 3981.977, "pmdec": -2466.832, "plx": 270.658, "epoch": 2016.0,
    },
    "wise0855": {
        "name": "WISE 0855−0714", "kind": "pm",
        "about": "The coldest brown dwarf known (about −25 °C), 2.3 parsecs away. Almost invisible below 3 µm, it shows up only in SPHEREx's longest bands.",
        "source": "Challenge coordinates (AllWISE); motion from Luhman & Esplin 2016",
        "ra": 133.795129, "dec": -7.245147, "pmra": -8118.0, "pmdec": 680.0, "plx": 439.0, "epoch": 2010.5,
    },
    "rwaur": {
        "name": "RW Aurigae", "kind": "var",
        "about": "A young T Tauri star 160 parsecs away whose brightness jumps irregularly as dust in its disk passes in front of it.",
        "source": "Gaia DR3 156430822114424576",
        "ra": 76.95608119552952, "dec": 30.401204589097233, "pmra": 2.641, "pmdec": -27.398, "plx": 6.406, "epoch": 2016.0,
    },
    "rdra": {
        "name": "R Draconis", "kind": "var",
        "about": "A Mira variable: a pulsating red giant about 800 parsecs away that brightens and fades over 246 days.",
        "source": "Gaia DR3 1648328016354496384",
        "ra": 248.1673783672889, "dec": 66.75500674547219, "pmra": -20.643, "pmdec": 6.149, "plx": 1.251, "epoch": 2016.0,
    },
}


CENTRE_EPOCH = 2026.0     # Julian year of the field centres: the middle of SPHEREx's first three passes


def coord(t):
    """SkyCoord of a target with its proper motion and distance (from the parallax), at its catalogue epoch."""
    return SkyCoord(ra=t["ra"] * u.deg, dec=t["dec"] * u.deg, pm_ra_cosdec=t["pmra"] * u.mas / u.yr,
                    pm_dec=t["pmdec"] * u.mas / u.yr, distance=(1000.0 / t["plx"]) * u.pc,
                    obstime=Time(t["epoch"], format="jyear"))


def position_at(t, mjd):
    """Astrometric (ra, dec) in degrees seen from Earth at each MJD: proper motion plus parallax.
    No aberration: SPHEREx's WCS is tied to Gaia, so its frames are already astrometric."""
    mjd = np.atleast_1d(np.asarray(mjd, float))
    obs = Time(mjd, format="mjd")
    moved = coord(t).apply_space_motion(new_obstime=obs)
    star = moved.cartesian.xyz.to(u.au).value                  # (3, n) barycentric
    earth = get_body_barycentric("earth", obs).xyz.to(u.au).value
    v = star - earth                                           # geocentric
    ra = np.degrees(np.arctan2(v[1], v[0])) % 360
    dec = np.degrees(np.arcsin(v[2] / np.linalg.norm(v, axis=0)))
    return ra, dec


def centre_2026(t):
    """Barycentric position at 2026.0, the middle of SPHEREx's first three passes (the field centre)."""
    c = coord(t).apply_space_motion(new_obstime=Time(CENTRE_EPOCH, format="jyear"))
    return float(c.ra.deg), float(c.dec.deg)
