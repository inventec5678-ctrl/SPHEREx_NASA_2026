"""Calibration of the residual-profile diagnostic (link.distance_profile_ratio), for the referee: simulated distant
bodies at 500-3000 au with a random drift up to the circular speed, observed at the exposure times of a three-pass
survey field (25 detections per pass, 0.7" noise). Reports the distance error against the profile ratio, and the
ratio of the stacked survey tracks -> paper_aas/profile_check.json. Runs from any working directory."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, PAPER_AAS, PAPER_EVIDENCE, read_json, write_json  # noqa: E402

FIELD = OUTPUTS / "survey" / "svB_051p000+06p923" / "field.json"
SETUPS = ((25, 0.7), (4, 2.0))            # detections per pass, astrometric noise (arcsec)
DISTANCES = (500, 800, 1500, 3000)        # au
N_PER_DIST = 60
MAX_DRIFT = 1.4                           # drift up to this times the circular speed
BAD_ERR = 0.1                             # distance error counted as bad
RATIO_THRESHOLDS = (1.5, 2, 3, 5)


def main():
    from sxlib import link
    from sxlib.inject import DistantBody
    from sxlib.shiftstack import passes_of

    rng = np.random.default_rng(3)
    D = read_json(FIELD)
    mjd = np.array([e["mjd"] for e in D["exposures"]])
    out = {}
    for nper, sig in SETUPS:
        t = np.sort(np.concatenate([rng.choice(mjd[i], nper, replace=False) for i in passes_of(mjd)]))
        s = sig / np.sqrt(2) / 3600
        rows = []
        for d in DISTANCES:
            for _ in range(N_PER_DIST):
                mu = link.circular_pm(d) * rng.uniform(0, MAX_DRIFT)
                pa = rng.uniform(0, 2 * np.pi)
                b = DistantBody(D["ra"], D["dec"], d, 18.0, float(np.median(t)),
                                pm_arcsec_yr=(mu * np.sin(pa), mu * np.cos(pa)))
                ra, dec = b.position(t)
                dec = dec + rng.normal(0, s, len(t))
                ra = ra + rng.normal(0, s, len(t)) / np.cos(np.radians(dec))
                dets = [{"ra": float(a), "dec": float(c), "mjd": float(m)} for a, c, m in zip(ra, dec, t)]
                dfit = link.fit_distant(dets)[0]
                ratio = link.distance_profile_ratio(dets)[0]
                rows.append((d, abs(dfit - d) / d, ratio))
        rows = np.array(rows)
        bad = rows[:, 1] > BAD_ERR
        print(f"{nper} detections/pass, {sig}\" noise: {len(rows)} tracks, {bad.sum()} with distance error > 10%; "
              f"ratio median {np.median(rows[:, 2]):.1f}")
        for thr in RATIO_THRESHOLDS:
            fl = rows[:, 2] < thr
            print(f"  ratio < {thr}: flags {fl.sum()} tracks, {int((fl & bad).sum())} of the {bad.sum()} with error > 10%")
        print("  ratio of fits with error > 10%:", np.round(np.sort(rows[bad, 2]), 2))
        out[f"{nper}x{sig}"] = rows.tolist()
    surv = read_json(PAPER_EVIDENCE / "survey.json")["candidates"]
    r = [link.distance_profile_ratio([{"ra": p["ra"], "dec": p["dec"], "mjd": p["mjd"]} for p in c["peaks"]])[0]
         for c in surv if c["method"] == "stack"]
    print(f"survey stacked tracks: {len(r)}, ratio median {np.median(r):.2f}, "
          f"10-90% {np.percentile(r, 10):.2f}-{np.percentile(r, 90):.2f}")
    write_json(PAPER_AAS / "profile_check.json", {"sim": out, "survey_ratio": r}, indent=None)


if __name__ == "__main__":
    main()
