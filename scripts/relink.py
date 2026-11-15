"""Recompute moving-object tracks for existing web fields: python scripts/relink.py [field ids]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, field_ids  # noqa: E402


def main(argv):
    from sxlib.analyze import relink
    for fid in field_ids(argv):
        d = relink(FIELDS / fid / "field.json")
        print(fid, len(d["tracks"]), "tracks:", sum(1 for t in d["tracks"] if t.get("known")), "known")


if __name__ == "__main__":
    main(sys.argv[1:])
