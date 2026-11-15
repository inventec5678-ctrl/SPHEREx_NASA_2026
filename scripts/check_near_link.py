"""Completeness of the blind linear-drift linker for unknown bodies at 35-100 au on circular and eccentric orbits,
for the referee. Detections are simulated at the exposure times of the Makemake fields (three windows, about 25
detections per window, 0.7" astrometric noise), assuming the body stays in the field (i.e. fields that follow the
parallactic path); no other sources are added, so this is an upper bound on the linking completeness.
A body counts as recovered if search_distant returns a track spanning three windows with a distance within 5%.
    python scripts/check_near_link.py   -> paper_aas/near_link.json   (any working directory)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, PAPER_AAS, read_json, write_json  # noqa: E402

N_PER_WINDOW = 25
NOISE_ARCSEC = 0.7
N_TRIALS = 40
DISTANCES = (35, 45, 55, 65, 80, 100)        # au
ECCENTRICITIES = (0.0, 0.2)
D_TOL = 0.05
MAX_INC_DEG = 30
OBLIQUITY = np.radians(23.439281)
R_EQ = np.array([[1, 0, 0], [0, np.cos(OBLIQUITY), -np.sin(OBLIQUITY)],
                 [0, np.sin(OBLIQUITY), np.cos(OBLIQUITY)]])        # ecliptic -> equatorial
GM = 4 * np.pi ** 2                                                 # au^3 / yr^2
KEPLER_ITER = 50


def _rz(t):
    return np.array([[np.cos(t), -np.sin(t), 0], [np.sin(t), np.cos(t), 0], [0, 0, 1]])


def _rx(t):
    return np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])


def epochs(rng):
    cov = read_json(OUTPUTS / "dwarf_coverage.json")["Makemake"]["passes"]
    T = []
    for k, p in enumerate(cov):
        ex = read_json(OUTPUTS / "dwarf" / f"dw_Makemake_{k}" / "field.json")["exposures"]
        t = np.array(sorted(e["mjd"] for e in ex if p["mjd0"] - 1 <= e["mjd"] <= p["mjd1"] + 1))
        T.append(rng.choice(t, size=min(N_PER_WINDOW, len(t)), replace=False))
    return np.sort(np.concatenate(T))


def body(rng, tt, d, e):
    """Heliocentric positions (equatorial, au) at tt for a random orbit with r = d at the middle epoch."""
    nu0 = rng.uniform(0, 2 * np.pi)
    a = d * (1 + e * np.cos(nu0)) / (1 - e ** 2)
    E0 = 2 * np.arctan2(np.sqrt(1 - e) * np.sin(nu0 / 2), np.sqrt(1 + e) * np.cos(nu0 / 2))
    M = E0 - e * np.sin(E0) + np.sqrt(GM / a ** 3) * (tt - np.median(tt)) / 365.25
    Ek = M.copy()
    for _ in range(KEPLER_ITER):
        Ek = Ek - (Ek - e * np.sin(Ek) - M) / (1 - e * np.cos(Ek))
    x, y = a * (np.cos(Ek) - e), a * np.sqrt(1 - e ** 2) * np.sin(Ek)
    i, O, w = np.radians(rng.uniform(0, MAX_INC_DEG)), rng.uniform(0, 2 * np.pi), rng.uniform(0, 2 * np.pi)
    return (R_EQ @ _rz(O) @ _rx(i) @ _rz(w) @ np.vstack([x, y, np.zeros_like(x)])).T


def main():
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time
    import astropy.units as u
    from sxlib import link

    rng = np.random.default_rng(5)
    tt = epochs(rng)
    tm = Time(tt, format="mjd")
    E = get_body_barycentric("earth", tm).xyz.to(u.au).value.T
    S = get_body_barycentric("sun", tm).xyz.to(u.au).value.T
    sig = NOISE_ARCSEC / np.sqrt(2) / 3600
    res = {}
    for e in ECCENTRICITIES:
        for d in DISTANCES:
            ok = 0
            for _ in range(N_TRIALS):
                g = body(rng, tt, d, e) + S - E
                ra = np.degrees(np.arctan2(g[:, 1], g[:, 0])) % 360
                dec = np.degrees(np.arcsin(g[:, 2] / np.linalg.norm(g, axis=1)))
                dec = dec + rng.normal(0, sig, len(tt))
                ra = ra + rng.normal(0, sig, len(tt)) / np.cos(np.radians(dec))
                dets = [{"ra": float(a_), "dec": float(b_), "mjd": float(t_), "p": 1.0} for a_, b_, t_ in zip(ra, dec, tt)]
                ok += any(t["n_passes"] >= 3 and abs(t["d_au"] - d) / d <= D_TOL for t in link.search_distant(dets))
            res[f"e={e} d={d}"] = ok / N_TRIALS
            print(f"e={e:.1f} d={d:3d} au: linked with distance within 5% in {ok}/{N_TRIALS}", flush=True)
    write_json(PAPER_AAS / "near_link.json", res)


if __name__ == "__main__":
    main()
