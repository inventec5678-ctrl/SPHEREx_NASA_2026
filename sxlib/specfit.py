"""Blackbody / power-law fit of a SPHEREx spectrum: star (temperature, rough main-sequence distance) or galaxy-like.
The same model as scripts/build_universe.py (fit_star, star_distance_pc), here for one point on request.
The temperature and slope grids are evaluated as arrays (one row per trial value)."""
import numpy as np

H_PL, K_B, C = 6.62607015e-34, 1.380649e-23, 2.99792458e8
T_SUN, R_SUN_PC = 5772.0, 2.2546e-8
LAM_BINS = np.geomspace(0.75, 5.0, 61)
T_GRID = np.geomspace(2300, 40000, 160)
BETA_GRID = np.linspace(-3, 3, 61)
MIN_POINTS = 8
ERR_FLOOR = 0.03              # fractional error floor of the fit weights
GALAXY_CHI_RATIO = 0.7        # power law this much better than a blackbody -> galaxy-like
MEDIAN_ERR = 1.253            # error of a median relative to a mean


def bnu(lam_um, T):
    nu = C / (lam_um * 1e-6)
    x = np.clip(H_PL * nu / (K_B * T), 1e-6, 700)
    return nu ** 3 / np.expm1(x)


def fit_scale(model, f, w):
    s = np.sum(w * model * f) / max(np.sum(w * model * model), 1e-300)
    return s, float(np.sum(w * (f - s * model) ** 2))


def _fit_scale_rows(models, f, w):
    """fit_scale for every row of models (k, n): (scales, chi2) arrays."""
    s = np.sum(w * models * f, axis=1) / np.maximum(np.sum(w * models * models, axis=1), 1e-300)
    return s, np.sum(w * (f - s[:, None] * models) ** 2, axis=1)


def _best_positive(s, chi):
    """Index of the lowest chi2 among positive scales (first one on ties), or None."""
    c = np.where((s > 0) & ~np.isnan(chi), chi, np.inf)
    i = int(np.argmin(c))
    return i if c[i] < np.inf else None


def bin_spectrum(lam, flux, err):
    lam, flux, err = np.asarray(lam, float), np.asarray(flux, float), np.asarray(err, float)
    out = []
    fin = np.isfinite(flux)
    for lo, hi in zip(LAM_BINS[:-1], LAM_BINS[1:]):
        m = (lam >= lo) & (lam < hi) & fin
        k = int(m.sum())
        if k >= 2:
            out.append([float(np.sqrt(lo * hi)), float(np.median(flux[m])), float(MEDIAN_ERR * np.median(err[m]) / np.sqrt(k))])
    return out


def fit_star(spec):
    if len(spec) < MIN_POINTS:
        return None
    lam, f, e = (np.array(x) for x in zip(*spec))
    w = 1 / np.maximum(e, ERR_FLOOR * np.abs(f) + 1e-9) ** 2
    s_bb, chi_bb = _fit_scale_rows(bnu(lam[None, :], T_GRID[:, None]), f, w)
    i = _best_positive(s_bb, chi_bb)
    if i is None:
        return None
    T, s, chi_bb = float(T_GRID[i]), s_bb[i], float(chi_bb[i])
    s_pl, chi_pl = _fit_scale_rows(lam[None, :] ** BETA_GRID[:, None], f, w)
    j = _best_positive(s_pl, chi_pl)
    pl_chi = float(chi_pl[j]) if j is not None else np.inf
    dof = max(len(lam) - 2, 1)
    theta = np.sqrt(s * 1e-32 * C ** 2 / (2 * np.pi * H_PL)) if s else None
    out = {"T": T, "chi2r_bb": float(chi_bb / dof), "chi2r_pl": float(pl_chi / dof)}
    out["kind"] = "galaxy" if out["chi2r_pl"] < GALAXY_CHI_RATIO * out["chi2r_bb"] else "star"
    if theta and out["kind"] == "star":
        r_sun = float(np.clip((T / T_SUN) ** 1.6, 0.1, 12))       # main-sequence assumption: R ~ T^1.6
        out["distance_pc"] = float(r_sun * R_SUN_PC / theta)
    return out
