"""Precompute the demo fields shown in the web app (needs models/rb_cnn.pt).

  python scripts/precompute_demo.py            # all demo fields
  python scripts/precompute_demo.py cybele     # just one

DEMOS is imported by scripts/build_universe.py; importing this module does not load the pipeline or torch.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MODELS  # noqa: E402

DEMOS = [
    {"id": "cybele", "name": "Asteroid lane in Virgo (65 Cybele)", "ra": 178.6, "dec": 1.1, "size": 0.5,
     "description": "A patch on the ecliptic. In December 2025 the large main-belt asteroid 65 Cybele "
                    "crossed it; fainter asteroids pass through every survey pass."},
    {"id": "planetx", "name": "Planet X test: a simulated distant planet", "ra": 181.6, "dec": -0.4, "size": 0.5,
     "simulate_planet_x": True,
     "description": "Real SPHEREx images with one simulated planet at ~420 AU added using the instrument's own "
                    "PSF. Can the pipeline find it from its parallax alone? (It is made bright, AB 15.5, so you "
                    "can see it in single images; a real Planet X would be far fainter and need image stacking.)"},
    {"id": "taurus", "name": "Ecliptic in Taurus (held-out test sky)", "ra": 57.8182, "dec": 20.1502, "size": 0.5,
     "description": "One of the sky patches the AI never saw during training."},
    {"id": "q183p200-01p400", "name": "RA 183.200, Dec -1.400", "ra": 183.2, "dec": -1.4, "size": 0.3,
     "description": "Analysed on request from the web app."},
]


def main():
    from sxlib.analyze import analyze_field
    from sxlib.rbnet import Scorer
    want = set(sys.argv[1:])
    scorer = Scorer(MODELS / "rb_cnn.pt")
    for d in DEMOS:
        if want and d["id"] not in want:
            continue
        analyze_field(d["id"], d["name"], d["ra"], d["dec"], d["size"], FIELDS, scorer,
                      description=d["description"], simulate_planet_x=d.get("simulate_planet_x", False))


if __name__ == "__main__":
    main()
