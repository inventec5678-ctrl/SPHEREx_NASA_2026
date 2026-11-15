"""Rebuild analysed fields on the SPHEREx releases IRSA serves now, keeping the previous results for comparison.

IRSA retired the quick release QR2 when the first data release DR1 came out (2026); searches now return DR1 and QR3
only, and DR1/QR3 files carry the effective PSF (ePSF) instead of the old optical PSF.

  python scripts/rebuild_release.py snapshot <label>      copy every field's results and the validation outputs to
                                                          outputs/release_compare/<label>/ (e.g. label qr2qr3)
  python scripts/rebuild_release.py build <ids...>        re-run the full analysis of each field next to the live
                                                          one, swap it in (as the worker's refresh does), and
                                                          re-measure a named target (build_targets.annotate)
The steps after the builds (PSF photometry, external checks, searches, validation) are in scripts/rebuild_release.sh.
"""
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MODELS, OUTPUTS, read_json  # noqa: E402

OUT = OUTPUTS / "release_compare"
KEEP = ("field.json", "summary.json", "pm_candidates.json", "var_candidates.json")
VALIDATION = ("pm_validation.json", "xepoch_validation.json", "var_search.json", "var_targets.json")
CARRY = ("universe.json", "deep_rgb.webp")          # made once from a field and kept across rebuilds
TORCH_THREADS = 8


def snapshot(label):
    for d in sorted(FIELDS.iterdir()):
        if not (d / "field.json").exists() or d.name.endswith((".new", ".old")):
            continue
        dst = OUT / label / "fields" / d.name
        dst.mkdir(parents=True, exist_ok=True)
        for k in KEEP:
            if (d / k).exists():
                shutil.copy2(d / k, dst / k)
    for k in VALIDATION:
        if (OUTPUTS / k).exists():
            (OUT / label).mkdir(parents=True, exist_ok=True)
            shutil.copy2(OUTPUTS / k, OUT / label / k)
    print("snapshot ->", OUT / label)


def _swap(fid, new):
    """Replace the live field directory by the rebuilt one (rename is atomic per directory)."""
    old = FIELDS / fid
    bak = FIELDS / f"{fid}.old"
    shutil.rmtree(bak, ignore_errors=True)
    old.rename(bak)
    new.rename(old)
    shutil.rmtree(bak, ignore_errors=True)


def build(fid):
    import torch
    torch.set_num_threads(TORCH_THREADS)
    from sxlib.analyze import analyze_field, write_doc
    from sxlib.rbnet import Scorer
    old = FIELDS / fid
    prev = read_json(old / "field.json")
    tmp = f"{fid}.new"
    new = FIELDS / tmp
    shutil.rmtree(new, ignore_errors=True)
    t0 = time.time()
    scorer = Scorer(MODELS / "rb_cnn.pt")
    try:
        doc = analyze_field(tmp, prev["name"], prev["ra"], prev["dec"], prev["size_deg"], FIELDS, scorer,
                            description=prev.get("description", ""), simulate_planet_x=bool(prev.get("simulated")),
                            log=lambda m: print(fid, m, flush=True))
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        raise
    kl = doc.get("known_lookup") or {}
    if kl.get("failed"):            # keep the live field; the .new build stays on disk for inspection
        raise RuntimeError(f"{fid}: JPL lookup failed for {kl['failed']} of {kl.get('visits')} visits; not swapped in")
    doc["id"] = fid
    for k in CARRY:
        if (old / k).exists() and not (new / k).exists():
            shutil.copy2(old / k, new / k)
    write_doc(new, doc)
    _swap(fid, new)
    if prev.get("target"):
        from build_targets import annotate
        annotate(fid)
    rel = dict(Counter(e.get("release") or "?" for e in doc["exposures"]))
    print(fid, f"rebuilt in {time.time() - t0:.0f}s: {len(doc['exposures'])} exposures {rel}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("snapshot", "build"):
        sys.exit(__doc__)
    if sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    else:
        for fid in sys.argv[2:]:
            build(fid)
