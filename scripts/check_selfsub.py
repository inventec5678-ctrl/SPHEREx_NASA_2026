"""Reference epochs and self-subtraction: for each survey exposure, the references of Stack.reference (same detector,
|dt| >= 3 h, the 36 closest in wavelength, within 3%) and the fraction of them in which a body on a circular orbit at
distance d lies within one pixel of its position in the exposure (8 orbit orientations). Runs from any directory."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, read_json  # noqa: E402

DS = [250, 500, 1000, 1500, 3000]          # au
N_ORIENT = 8
MIN_DT_H = 3.0                             # Stack.reference: |dt| >= 3 h
N_REF = 36                                 # the closest references in wavelength
LAM_TOL = 0.03
PIX_ARCSEC = 6.15


def references(mjd, det, lam):
    """Per exposure, the indices of its reference exposures."""
    refs = []
    for i in range(len(mjd)):
        cand = np.where((det == det[i]) & (np.abs(mjd - mjd[i]) * 24 >= MIN_DT_H))[0]
        cand = cand[np.argsort(np.abs(lam[cand] - lam[i]))][:N_REF]
        cand = cand[np.abs(lam[cand] - lam[i]) <= LAM_TOL * lam[i]]   # field-centre wavelength for the pixel test
        refs.append(cand)
    return refs


def main():
    from astropy.coordinates import SkyCoord, get_body_barycentric
    from astropy.time import Time
    import astropy.units as u

    fr = {d: [] for d in DS}
    maj = {d: [] for d in DS}
    ndt, nref = [], []
    for fn in sorted((OUTPUTS / "survey").glob("*/field.json")):
        D = read_json(fn)
        ex = D["exposures"]
        mjd = np.array([e["mjd"] for e in ex]); det = np.array([e["detector"] for e in ex])
        lam = np.array([e["lam_um"] for e in ex])
        t = Time(mjd, format="mjd")
        E = get_body_barycentric("earth", t).xyz.to(u.au).value.T
        Sn = get_body_barycentric("sun", t).xyz.to(u.au).value.T
        uv = SkyCoord(D["ra"] * u.deg, D["dec"] * u.deg).cartesian.xyz.value
        e1 = np.cross([0, 0, 1], uv); e1 /= np.linalg.norm(e1); e2 = np.cross(uv, e1)   # tangent-plane basis
        refs = references(mjd, det, lam)
        for i, cand in enumerate(refs):
            ndt.extend(np.abs(mjd[cand] - mjd[i])); nref.append(len(cand))
        # every (exposure, reference) pair at once; per-exposure fractions by bincount
        cnt = np.array([len(c) for c in refs])
        I = np.repeat(np.arange(len(refs)), cnt)
        J = np.concatenate(refs) if len(I) else np.zeros(0, int)
        has = cnt > 0
        for d in DS:
            mu = 2 * np.pi * d ** -1.5            # rad/yr, circular
            for th in np.linspace(0, 2 * np.pi, N_ORIENT, endpoint=False):
                v = d * mu * (np.cos(th) * e1 + np.sin(th) * e2)   # au/yr tangential
                P = Sn + d * uv + np.outer((mjd - mjd[0]) / 365.25, v)
                A = P - E; A /= np.linalg.norm(A, axis=1)[:, None]
                sep = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", A[J], A[I]), -1, 1))) * 3600
                f = np.bincount(I, weights=(sep < PIX_ARCSEC).astype(float), minlength=len(refs))[has] / cnt[has]
                fr[d].extend(f); maj[d].extend(f >= 0.5)
    for d in DS:
        print(f"{d} au: mean frac of refs within 1px {np.mean(fr[d]):.3f}; "
              f"exposures with >=half refs within 1px {100 * np.mean(maj[d]):.2f}%")
    ndt = np.array(ndt)
    print(f"references per exposure: median {np.median(nref):.0f}; |dt| median {np.median(ndt):.0f} d, "
          f"10th pct {np.percentile(ndt, 10):.1f} d, <1 d {100 * np.mean(ndt < 1):.1f}%, <3 d {100 * np.mean(ndt < 3):.1f}%")


if __name__ == "__main__":
    main()
