"""PSF-fit photometry for the named targets from the stored cube (no re-download): python scripts/psf_targets.py [ids]

Adds p["psf"], p["psf_e"], p["psf_sat"] to every target point and doc["target"]["psf_check"]: for unsaturated
exposures, the PSF flux over the 2-pixel aperture flux (a constant aperture correction if the PSF model is right)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, read_json  # noqa: E402

TARGETS = ["barnard", "epsindi", "wise0855", "rwaur", "rdra"]
MIN_SNR = 10            # aperture S/N above which a point enters the PSF/aperture ratio
MIN_PER_DET = 3         # points per detector needed to report its median ratio


def run(tid):
    from sxlib.analyze import write_doc
    from sxlib.psfphot import fit
    out = FIELDS / tid
    doc = read_json(out / "field.json")
    cube = out / "cube"
    img = np.load(cube / "img.npy", mmap_mode="r")
    var = np.load(cube / "var.npy", mmap_mode="r")
    fl = np.load(cube / "flag.npy", mmap_mode="r")
    pts = doc["target"]["points"]
    ratios = {}
    n_ok = 0
    for p in pts:
        for k in ("psf", "psf_e", "psf_sat"):
            p.pop(k, None)
        i = p["i"]
        r = fit(img[i], var[i], (fl[i] & 1).astype(bool), p["x"], p["y"], p["det"])
        if r is None:
            continue
        p["psf"], p["psf_e"], p["psf_sat"] = round(r[0], 2), round(r[1], 2), r[3]
        n_ok += 1
        if not r[3] and p.get("f") and p.get("e") and p["f"] > MIN_SNR * p["e"]:
            ratios.setdefault(p["det"], []).append(r[0] / p["f"])
    chk = {f"D{d}": round(float(np.median(v)), 3) for d, v in sorted(ratios.items()) if len(v) >= MIN_PER_DET}
    doc["target"]["psf_check"] = {"psf_over_aperture": chk, "n_fitted": n_ok, "n_points": len(pts)}
    write_doc(out, doc)
    print(tid, "fitted", n_ok, "/", len(pts), "PSF/aperture", chk)


if __name__ == "__main__":
    for t in sys.argv[1:] or TARGETS:
        run(t)
