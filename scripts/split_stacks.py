"""Write pass/stacks_g{k}.bin (k = 0..6) next to every existing pass/stacks.bin under web/data, and check them.

stacks.bin is float16 [pass][7 band groups][n][n] after a 16-byte header (P, 7, n, n). Each group file holds one
band group, float16 C order (P, n, n), no header, so the field lab can download just the group it draws.
New fields and quick looks get these files from sxlib/products.build; this script covers the ones made before.

  python scripts/split_stacks.py            # every fields/*, quick/* (and any other) stacks.bin
  python scripts/split_stacks.py --check    # only verify, write nothing
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATA  # noqa: E402

F16 = 2          # bytes per float16


def _group_file(pass_dir, k):
    return pass_dir / f"stacks_g{k}.bin"


def verify(pass_dir, st):
    """True if every group file holds exactly the bytes of its group in stacks.bin."""
    P, B, n0, n1 = st.shape
    for k in range(B):
        p = _group_file(pass_dir, k)
        if not p.exists() or p.stat().st_size != P * n0 * n1 * F16:
            return False
        if p.read_bytes() != np.ascontiguousarray(st[:, k], dtype=np.float16).tobytes():   # bytewise: NaNs equal
            return False
    return True


def main():
    from sxlib.products import read_stacks, write_stack_groups
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify only")
    ap.add_argument("--root", default=str(DATA))
    a = ap.parse_args()
    root = Path(a.root)
    found = sorted(root.rglob("pass/stacks.bin"))
    n_written = n_ok = n_bad = 0
    added = 0
    for sb in found:
        st = read_stacks(sb)
        pd = sb.parent
        if verify(pd, st):
            n_ok += 1
            status = "ok"
        elif a.check:
            n_bad += 1
            status = "MISSING/DIFFERENT"
        else:
            write_stack_groups(st, pd)
            if verify(pd, st):
                n_written += 1
                status = "written"
            else:
                n_bad += 1
                status = "FAILED"
        size = sum(g.stat().st_size for g in (_group_file(pd, k) for k in range(st.shape[1])) if g.exists())
        added += size
        print(f"{sb.relative_to(root).as_posix()}  {tuple(st.shape)}  {sb.stat().st_size / 1e6:.2f} MB -> "
              f"7 x {size / 7 / 1e6:.2f} MB  {status}")
    print(f"{len(found)} stacks.bin: {n_written} split, {n_ok} already split, {n_bad} bad; "
          f"group files total {added / 1e6:.1f} MB")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
