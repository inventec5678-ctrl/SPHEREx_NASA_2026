"""Add the per-pass contamination-flag maps (pass/flags.bin, sxlib/products.pass_flags) to analysed fields that were
built before the maps existed, from their stored flag cube. New fields and quick looks get them from products.build.

    python scripts/pass_flags.py [field ids...]      # default: every field with a cube
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, field_ids, read_json  # noqa: E402

EDGE = 1e-6                    # days: pass boundaries are inclusive
HEADER = "<4i"                 # (P, 1, n, n), little-endian int32


def one(d):
    from sxlib.analyze import write_doc
    from sxlib.products import pass_flags
    doc = read_json(d / "field.json")
    pr = doc.get("products")
    if not pr or not (d / "cube" / "flag.npy").exists():
        return None
    flag = np.load(d / "cube" / "flag.npy")
    mjd = np.array([e["mjd"] for e in doc["exposures"][:flag.shape[0]]])
    lab = np.full(len(mjd), -1)
    for p in pr["passes"]:                         # the passes as the products defined them
        lab[(mjd >= p["mjd0"] - EDGE) & (mjd <= p["mjd1"] + EDGE)] = p["k"]
    P, n = len(pr["passes"]), flag.shape[1]
    out = pass_flags(flag, lab, P)
    with open(d / "pass" / "flags.bin", "wb") as fh:
        fh.write(struct.pack(HEADER, P, 1, n, n))
        fh.write(out.tobytes())
    if pr.get("pass_flags") != "pass/flags.bin":
        pr["pass_flags"] = "pass/flags.bin"
        write_doc(d, doc)
    return P, [round(float((out[p] > 0).mean()), 3) for p in range(P)]


if __name__ == "__main__":
    for fid in field_ids(sys.argv[1:], marker="cube/flag.npy", skip_dotted=True):
        print(fid, one(FIELDS / fid))
