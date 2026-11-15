"""Reference spectra for the lab's spectrum chart (web/app/src/spec_templates.json).

They come from the same synthetic model the spectral classifier is trained on (sxlib/specclass.py), with every
random band depth set to the middle of its range, so a visitor compares a measured spectrum with what the classifier
itself takes a brown dwarf, an L dwarf or an ordinary star to look like. f_nu, normalised to a peak of 1, on
0.75–5.0 µm (SPHEREx's range).

    python scripts/spectrum_templates.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import APP, write_json  # noqa: E402
from sxlib import specclass as sc  # noqa: E402

DST = APP / "src" / "spec_templates.json"
WATER = ((1.4, .08), (1.9, .12), (2.7, .25))      # (centre, width) of the water bands, µm


class Mid:
    """A stand-in for numpy's Generator that always answers the middle of the range."""
    def uniform(self, a, b):
        return (a + b) / 2

    def random(self):
        return 0.5


def star(lam, T, water):
    tau = sc._band(lam, 2.3, .1, .15) + sc._band(lam, 4.6, .15, .15)
    if water:
        tau += sum(sc._band(lam, c, w, .25) for c, w in WATER)
    return sc._bb(T, lam) * np.exp(-tau)


def ldwarf(lam, T):
    tau = sum(sc._band(lam, c, w, .7) for c, w in WATER)
    tau += sc._band(lam, 2.3, .1, .5) + sc._band(lam, 4.6, .15, .5) + sc._band(lam, 3.3, .2, .25) * (T < 1600)
    return sc._bb(T, lam) * np.exp(-tau)


def main():
    lam = np.round(np.arange(0.75, 5.0001, 0.02), 3)
    rows = [
        ("Y", "Y 型棕矮星（400 K）", "Y dwarf (400 K)", sc._brown_dwarf(Mid(), lam, 400)),
        ("T", "T 型棕矮星（900 K）", "T dwarf (900 K)", sc._brown_dwarf(Mid(), lam, 900)),
        ("L", "L 型棕矮星（1,800 K）", "L dwarf (1,800 K)", ldwarf(lam, 1800)),
        ("M", "M 型紅矮星（3,000 K）", "M dwarf (3,000 K)", star(lam, 3000, True)),
        ("G", "太陽型恆星（5,800 K）", "Sun-like star (5,800 K)", star(lam, 5800, False)),
    ]
    out = {"lam": lam.tolist(),
           "source": "sxlib/specclass.py synthetic model, band depths at mid-range (scripts/spectrum_templates.py)",
           "templates": [{"id": k, "zh": zh, "en": en, "f": np.round(f / f.max(), 5).tolist()}
                         for k, zh, en, f in rows]}
    # ensure_ascii (json's default) keeps the file byte-identical to earlier builds
    write_json(DST, out, compact=True)
    print(DST, DST.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
