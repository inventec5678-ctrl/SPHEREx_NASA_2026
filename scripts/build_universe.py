"""Turn one SPHEREx field into a 3D "universe" description for the three.js front end.

For every bright static source we measure a 0.75-5.0 um spectrum from all exposures (forced
photometry at each exposure's own wavelength), fit physical models and derive appearance presets:
  star    blackbody temperature T  -> colour; main-sequence radius(T) + angular size -> distance
  galaxy  power law fits better than any blackbody (or source is extended) -> placed far away
For every moving track (from field.json) we measure the moving source's flux in the difference
image at each detection and fit a reflectance slope; known asteroids get real physical parameters
(H, diameter, albedo, rotation period, taxonomy) from the JPL SBDB API.

Writes web/data/fields/<id>/universe.json and deep_rgb.webp (D1/D3/D5 median stacks).
  python scripts/build_universe.py cybele planetx taurus
"""
import functools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, read_json, write_json  # noqa: E402

H_PL, K_B, C = 6.62607015e-34, 1.380649e-23, 2.99792458e8
T_SUN, R_SUN_PC = 5772.0, 2.2546e-8
LAM_BINS = np.geomspace(0.75, 5.0, 61)
T_GRID = np.geomspace(2300, 40000, 160)         # blackbody temperatures tried (K)
BETA_GRID = np.linspace(-3, 3, 61)              # power-law slopes tried
PIX_ARCSEC = 6.15
TO_UJY = (PIX_ARCSEC / 206264.806) ** 2 * 1e12  # MJy/sr * sr(pixel) -> MJy -> uJy
MAX_SOURCES = 260
PEAK_SNR, PEAK_BOX, EDGE = 15, 7, 8
SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
SBDB_FIELDS = ("H", "diameter", "albedo", "rot_per", "spec_T", "spec_B")


def bnu(lam_um, T):
    nu = C / (lam_um * 1e-6)
    x = np.clip(H_PL * nu / (K_B * T), 1e-6, 700)
    return nu ** 3 / np.expm1(x)


def _best_scale(models, f, w):
    """Least-squares scale of every row of ``models`` to the fluxes ``f`` (weights ``w``) at once; returns
    (chi2, row index, scale) of the best positive scale (the first one on ties), or (inf, None, None)."""
    s = np.sum(w * models * f, 1) / np.maximum(np.sum(w * models * models, 1), 1e-300)
    chi = np.sum(w * (f - s[:, None] * models) ** 2, 1)
    chi = np.where((s > 0) & np.isfinite(chi), chi, np.inf)
    j = int(np.argmin(chi))
    return (np.inf, None, None) if not np.isfinite(chi[j]) else (float(chi[j]), j, float(s[j]))


def bin_spectrum(lam, flux, err):
    out = []
    for lo, hi in zip(LAM_BINS[:-1], LAM_BINS[1:]):
        m = (lam >= lo) & (lam < hi) & np.isfinite(flux)
        if m.sum() >= 2:
            out.append([float(np.sqrt(lo * hi)), float(np.median(flux[m])),
                        float(1.253 * np.median(err[m]) / np.sqrt(m.sum()))])
    return out


def fit_star(spec):
    if len(spec) < 8:
        return None
    lam, f, e = (np.array(x) for x in zip(*spec))
    w = 1 / np.maximum(e, 0.03 * np.abs(f) + 1e-9) ** 2
    chi_bb, jt, s = _best_scale(bnu(lam[None, :], T_GRID[:, None]), f, w)
    T = None if jt is None else T_GRID[jt]
    chi_pl, jb, _ = _best_scale(lam[None, :] ** BETA_GRID[:, None], f, w)
    pl = (chi_pl, None if jb is None else BETA_GRID[jb])
    dof = max(len(lam) - 2, 1)
    # F_nu [uJy] = pi * B_nu(T) * theta^2   ->   angular radius theta (rad)
    # F_nu[W m^-2 Hz^-1] = s*1e-32*m = pi*(2h/c^2)*m*theta^2  ->  theta^2 = s*1e-32*c^2/(2*pi*h)
    theta = np.sqrt(s * 1e-32 * C ** 2 / (2 * np.pi * H_PL)) if s else None
    return {"T": float(T), "chi2r_bb": float(chi_bb / dof), "chi2r_pl": float(pl[0] / dof), "beta": float(pl[1]),
            "theta_rad": float(theta) if theta else None, "model_scale": float(s)}


def star_distance_pc(T, theta):
    """Main-sequence assumption: R ~ T^1.6 (R in solar units). A rough photometric distance."""
    r_sun = float(np.clip((T / T_SUN) ** 1.6, 0.1, 12))
    return r_sun * R_SUN_PC / theta, r_sun


@functools.lru_cache(maxsize=None)
def sbdb(name):
    """JPL SBDB physical parameters of a known small body (one request per name per run; {} on failure)."""
    import requests
    key = name.split()[0] if name.split()[0].isdigit() else name.split("(")[0].strip()
    try:
        js = requests.get(SBDB_URL, params={"sstr": key, "phys-par": "1"}, timeout=60).json()
    except Exception:  # noqa: BLE001
        return {}
    out = {"orbit_class": (js.get("object") or {}).get("orbit_class", {}).get("name")}
    for p in js.get("phys_par") or []:
        if p.get("name") in SBDB_FIELDS:
            out[p["name"]] = p.get("value")
    return out


def stars_preset(T, d_pc, kind):
    if kind == "galaxy":
        return {"type": "galaxy", "color_T": T, "arms": 2, "tilt": 0.6}
    return {"type": "star", "temperature": round(T), "corona": 0.6 if T > 7000 else 0.35, "granulation": 0.5,
            "spots": 0.3 if T < 4500 else 0.05}


def rocky_preset(slope, albedo, diameter, rot_h, spec, name):
    if albedo is None:      # dark/flat spectra -> carbonaceous-like; red -> stony-like (rough heuristic)
        albedo = 0.06 if slope is not None and slope < 0.1 else 0.2
    tax = spec or ("C-like" if albedo < 0.1 else "S-like")
    tint = {"C": [0.36, 0.34, 0.32], "S": [0.62, 0.52, 0.42], "X": [0.5, 0.5, 0.52], "D": [0.45, 0.30, 0.25],
            "V": [0.58, 0.55, 0.48]}.get(str(tax)[:1], [0.5, 0.46, 0.42])
    is_comet = name and (name.startswith("C/") or "P/" in name)
    return {"type": "comet" if is_comet else "rocky", "albedo": albedo, "taxonomy": tax, "tint": tint,
            "craters": 0.65 if albedo < 0.1 else 0.45, "irregularity": 0.35 if (diameter or 50) < 80 else 0.12,
            "diameter_km": diameter, "rotation_h": rot_h or 8.0, "coma": 0.8 if is_comet else 0.0}


def main(ids):
    from PIL import Image
    from scipy.ndimage import maximum_filter
    from precompute_demo import DEMOS
    from sxlib import pipeline
    from sxlib.analyze import REF_KW, planet_x_injection
    for d in DEMOS:
        if ids and d["id"] not in ids:
            continue
        fid, size = d["id"], d["size"]
        out = FIELDS / fid
        doc = read_json(out / "field.json")
        exps = pipeline.load_exposures(d["ra"], d["dec"], size, workers=8, log=lambda s: None)
        movers = [planet_x_injection(d["ra"], d["dec"], np.array([e.mjd for e in exps]))] if d.get("simulate_planet_x") else None
        f = pipeline.build_field(exps, d["ra"], d["dec"], size, movers=movers, truth_log=[] if movers else None)
        del exps
        to_ujy = TO_UJY
        # deep per-detector stacks
        deep, noise = {}, {}
        for dd in range(1, 7):
            m = f.det == dd
            if m.sum() < 3:
                continue
            with np.errstate(all="ignore"):
                stack = np.where(f.bad[m], np.nan, f.img[m])
                deep[dd] = np.nanmedian(stack, 0)
            v = deep[dd][np.isfinite(deep[dd])]
            noise[dd] = 1.4826 * np.median(np.abs(v - np.median(v)))
        comb = sum(np.nan_to_num(deep[k] / noise[k]) for k in deep) / np.sqrt(len(deep))
        peak = (comb == maximum_filter(comb, PEAK_BOX)) & (comb > PEAK_SNR)
        peak[:EDGE] = peak[-EDGE:] = False; peak[:, :EDGE] = peak[:, -EDGE:] = False
        ys, xs = np.nonzero(peak)
        order = np.argsort(-comb[ys, xs])[:MAX_SOURCES]
        ys, xs = ys[order], xs[order]
        # forced 3x3 photometry in every exposure at that exposure's wavelength
        sources = []
        for k, (y, x) in enumerate(zip(ys, xs)):
            sl = (slice(None), slice(y - 1, y + 2), slice(x - 1, x + 2))
            flux = np.nansum(np.where(f.bad[sl], np.nan, f.img[sl]), (1, 2)) * to_ujy
            err = np.sqrt(np.nansum(f.var[sl], (1, 2))) * to_ujy
            lam = f.lam[:, y, x]
            ok = np.isfinite(lam) & np.isfinite(flux) & ~f.bad[:, y, x]
            spec = bin_spectrum(lam[ok], flux[ok], err[ok])
            fit = fit_star(spec)
            if not fit:
                continue
            kind = "galaxy" if fit["chi2r_pl"] < 0.7 * fit["chi2r_bb"] else "star"
            dist, r_sun = star_distance_pc(fit["T"], fit["theta_rad"]) if fit["theta_rad"] else (None, None)
            ra, dec = f.pix_to_world(float(x), float(y))
            sources.append({"id": k, "x": int(x), "y": int(y), "ra": round(float(ra), 6), "dec": round(float(dec), 6),
                            "snr": round(float(comb[y, x]), 1), "kind": kind, "fit": fit, "spectrum": spec,
                            "distance_pc": round(dist, 1) if dist else None, "radius_rsun": round(r_sun, 2) if r_sun else None,
                            "preset": stars_preset(fit["T"], dist, kind)})
        # moving objects: flux of the moving source in the difference image
        movers_out = []
        cand = {c["id"]: c for c in doc["candidates"]}
        diffs = {}
        for tr in doc["tracks"]:
            pts = []
            for mid in tr["members"]:
                c = cand[mid]; i = c["i"]
                if i not in diffs:
                    dd_ = f.difference(i, **REF_KW)
                    diffs[i] = dd_["diff"]
                ix, iy = int(round(c["x"])), int(round(c["y"]))
                fl = float(np.nansum(diffs[i][iy - 1:iy + 2, ix - 1:ix + 2])) * to_ujy
                pts.append([float(f.lam[i, iy, ix]), fl, f.exps[i]["mjd"], c["x"], c["y"]])
            lam = np.array([p[0] for p in pts]); fl = np.array([p[1] for p in pts])
            refl = fl / bnu(lam, T_SUN)
            nir = (lam < 2.6) & (refl > 0)
            slope = float(np.polyfit(lam[nir], refl[nir] / np.median(refl[nir]), 1)[0]) if nir.sum() >= 3 else None
            thermal = None
            if (lam > 3.5).sum() >= 2 and nir.sum() >= 3:
                thermal = float(np.median(refl[lam > 3.5]) / np.median(refl[nir]))
            phys = sbdb(tr["known"]) if tr.get("known") else {}

            def num(k, phys=phys):
                return float(phys[k]) if phys.get(k) not in (None, "") else None
            if tr["kind"] == "distant":
                preset = {"type": "ice_giant", "bands": 0.55, "hue": 0.55, "rings": 0.0, "atmosphere": 0.8,
                          "d_au": tr.get("d_au")}
            else:
                preset = rocky_preset(slope, num("albedo"), num("diameter"), num("rot_per"),
                                      phys.get("spec_B") or phys.get("spec_T"), tr.get("known") or "")
            movers_out.append({"track": tr["id"], "kind": tr["kind"], "known": tr.get("known"),
                               "simulated": bool(doc.get("simulated")) and tr["kind"] == "distant",
                               "path": [[round(p[2], 5), round(p[3], 2), round(p[4], 2)] for p in sorted(pts, key=lambda q: q[2])],
                               "photometry": [[round(p[0], 3), round(p[1], 2)] for p in pts],
                               "reflectance_slope": slope, "thermal_ratio": thermal, "sbdb": phys, "preset": preset})
        # deep colour composite for the backdrop (blue=D1, green=D3, red=D5)
        chans = []
        for dd in (5, 3, 1):
            a = np.nan_to_num(deep.get(dd, np.zeros(f.shape)) / noise.get(dd, 1))
            chans.append(np.clip(np.arcsinh(a / 3) / np.arcsinh(400) * 255, 0, 255))
        Image.fromarray(np.stack(chans, -1).astype(np.uint8)[::-1]).save(out / "deep_rgb.webp", quality=92)
        uni = {"id": fid, "shape": list(f.shape), "wcs": doc["wcs"], "sources": sources, "movers": movers_out,
               "notes": {"distance": "Star distances assume a main-sequence radius for the fitted temperature "
                                     "(R ~ T^1.6); they are rough and only set the depth of the 3D scene.",
                         "photometry": "3x3-pixel forced photometry per exposure, binned into 60 wavelength bins; "
                                       "no aperture correction.",
                         "movers": "Mover fluxes come from the difference image at each detection; known-asteroid "
                                   "physical parameters come from JPL SBDB."}}
        write_json(out / "universe.json", uni, indent=None)
        print(fid, len(sources), "sources", sum(s["kind"] == "star" for s in sources), "stars,",
              len(movers_out), "movers", flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
