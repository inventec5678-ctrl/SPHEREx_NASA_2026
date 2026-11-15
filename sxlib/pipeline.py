"""End-to-end helpers: fetch exposures for a patch, build the aligned field, run detection."""
import copy
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import archive, detect
from .inject import injector
from .stack import Field

CUTOUT_MARGIN = 1.5      # the detector frame is rotated against the field: request a larger axis-aligned cutout


def load_exposures(ra, dec, size_deg, mjd_range=None, workers=8, max_exposures=None, log=print):
    metas = archive.search_images(ra, dec, mjd_range=mjd_range)
    if max_exposures:
        metas = metas[:max_exposures]
    log(f"[fetch] {len(metas)} exposures cover ({ra:.3f},{dec:.3f})")
    cut = size_deg * CUTOUT_MARGIN

    def one(m):
        try:
            return archive.fetch_cutout(m, ra, dec, cut)
        except Exception as e:  # noqa: BLE001 - keep going; a few failures are fine
            log(f"  fetch failed {m['obs_id']}: {e}")
            return None
    with ThreadPoolExecutor(workers) as ex:
        exps = [e for e in ex.map(one, metas) if e is not None]
    log(f"[fetch] {len(exps)} usable cutouts")
    return exps


def build_field(exps, ra, dec, size_deg, movers=None, truth_log=None):
    f = Field(ra, dec, size_deg)
    fn = injector(movers, truth_log) if movers else None
    for e in exps:
        if movers:                       # inject into a copy: the cached exposure stays clean
            e = copy.copy(e)
            e.img = e.img.copy()
        f.add(e, fn)
    return f.freeze()


def detect_all(field, thr=5.0, with_stamps=True, ref_kw=None):
    """Run difference + detection on every exposure. Returns list of per-exposure dicts."""
    out = []
    for i in range(len(field.exps)):
        d = field.difference(i, **(ref_kw or {}))
        cands = detect.find_candidates(d, thr=thr)
        st = detect.stamps(field, i, d, cands) if with_stamps and cands else None
        out.append({"i": i, "cands": cands, "stamps": st, "nref_med": float(np.median(d["nref"]))})
    return out
