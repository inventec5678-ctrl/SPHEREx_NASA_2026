"""Brown-dwarf spectral score for every named target (stored in doc["target"]["bd_score"]).

    python scripts/bd_targets.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, read_json  # noqa: E402

TARGETS = ("barnard", "epsindi", "wise0855", "rwaur", "rdra")
BAD_FLAGS = 5                    # flag bits that exclude a point from the spectrum


def main():
    from sxlib.analyze import write_doc
    from sxlib.specclass import score_points
    for tid in TARGETS:
        out = FIELDS / tid
        doc = read_json(out / "field.json")
        pts = [p for p in doc["target"]["points"]
               if p.get("f") is not None and p.get("e") and not ((p.get("flag") or 0) & BAD_FLAGS)]
        s = score_points([p["lam"] for p in pts], [p["f"] for p in pts], [p["e"] for p in pts])
        doc["target"]["bd_score"] = None if s is None else round(s, 3)
        write_doc(out, doc)
        print(tid, doc["target"]["bd_score"], len(pts))


if __name__ == "__main__":
    main()
