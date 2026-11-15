"""Quick-look runner, started by the web server as a detached process: python -m web.quick <qid> <ra> <dec> <size>"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NICE = 5                        # below the web server, which must keep answering while a look downloads


def main(argv):
    from sxlib.archive import CACHE
    from sxlib.quicklook import run
    qid, ra, dec, size = argv[0], float(argv[1]), float(argv[2]), float(argv[3])
    if hasattr(os, "nice"):     # POSIX only; on Windows the process keeps normal priority
        os.nice(NICE)
    run(qid, ra, dec, size, ROOT / "web" / "data" / "quick" / qid, ROOT / "var" / "quickcache" / qid, keep_cache=CACHE)


if __name__ == "__main__":
    main(sys.argv[1:])
