"""Add the honesty annotations (blind-link flags, distant-search status, simulated tracks) and the
corrected summary counts to existing fields without re-linking (track ids stay, so universe.json stays valid).

  python scripts/annotate_fields.py [--jpl] [field_id ...]     # --jpl: JPL Horizons offsets as seen from SPHEREx
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, field_ids, read_json  # noqa: E402


def main(argv):
    from sxlib.analyze import annotate, write_doc
    from sxlib.known import jpl_residuals
    jpl = "--jpl" in argv
    for fid in field_ids(a for a in argv if not a.startswith("--")):
        p = FIELDS / fid / "field.json"
        doc = read_json(p)
        annotate(doc)
        if jpl:
            jpl_residuals(doc)
        write_doc(p.parent, doc)
        tr = doc["tracks"]
        print(f"{fid}: {len(tr)} tracks, {sum(t['blind'] for t in tr)} found blind; blind linking -> "
              f"{doc['blind_link']}; distant search {doc['distant_search']}")


if __name__ == "__main__":
    main(sys.argv[1:])
