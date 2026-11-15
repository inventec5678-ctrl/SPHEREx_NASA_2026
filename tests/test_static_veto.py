"""Bright-star residuals must not be linked into "moving object" tracks; real movers must still be linked."""
import numpy as np

from sxlib.analyze import STATIC_GAP_D, build_tracks, static_repeaters


def _cand(i, cid, x, y, ra0=180.0, dec0=0.0, p=0.9):
    pix = 6.15 / 3600
    return {"id": cid, "i": i, "x": x, "y": y, "ra": ra0 - (x - 88) * pix, "dec": dec0 + (y - 88) * pix, "p": p,
            "known": None, "snr": 10.0, "l2": False, "track": None}


def _field(rng, n_exp=60, days=6.0):
    """Exposures over `days`; one star residual that recurs at a fixed place, one asteroid at 20"/h, scattered noise."""
    mjd = 60000 + np.sort(rng.uniform(0, days, n_exp))
    cands, cid = [], 0
    for i in range(n_exp):
        if rng.random() < 0.7:                                    # residual of a bright star, jittering by < 1 px
            cands.append(_cand(i, cid, 40 + rng.normal(0, 0.3), 120 + rng.normal(0, 0.3))); cid += 1
        t_h = (mjd[i] - mjd[0]) * 24
        if 24 <= t_h <= 60:                                       # a real mover: 20"/h for a day and a half
            cands.append(_cand(i, cid, 20 + 20 * (t_h - 24) / 6.15, 60 + 0.5 * (t_h - 24))); cid += 1
        for _ in range(2):                                        # unrelated single detections
            cands.append(_cand(i, cid, rng.uniform(0, 176), rng.uniform(0, 176), p=0.6)); cid += 1
    return mjd, cands


def test_recurring_position_is_vetoed_and_mover_is_not():
    rng = np.random.default_rng(1)
    mjd, cands = _field(rng)
    static = static_repeaters(cands, mjd)
    star = [c["id"] for c in cands if abs(c["x"] - 40) < 1.5 and abs(c["y"] - 120) < 1.5]
    mover = [c["id"] for c in cands if abs(c["y"] - 60) < 20 and c["x"] < 140 and c["p"] == 0.9 and c["id"] not in star]
    assert len(star) > 20 and len(mover) >= 4
    assert sum(c in static for c in star) >= 0.9 * len(star)
    assert sum(c in static for c in mover) == 0


def test_linking_keeps_the_mover_and_drops_star_tracks():
    rng = np.random.default_rng(2)
    mjd, cands = _field(rng)
    tracks = build_tracks(cands, mjd, log=lambda m: None)
    fast = [t for t in tracks if t["kind"] == "fast"]
    by_id = {c["id"]: c for c in cands}
    assert any(15 < t["rate_arcsec_h"] < 25 for t in fast), "the 20 arcsec/h mover must be linked"
    for t in fast:                                                # no track may be built from the star's residuals
        near_star = sum(abs(by_id[m]["x"] - 40) < 1.5 and abs(by_id[m]["y"] - 120) < 1.5 for m in t["members"])
        assert near_star == 0


def test_short_lived_repeat_is_not_static():
    """Detections at one place within a few hours are what a slow mover looks like; only a long stay is vetoed."""
    mjd = 60000 + np.array([0.0, 0.05, 0.1, 0.15])
    cands = [_cand(i, i, 50.0, 50.0) for i in range(4)]
    assert mjd[-1] - mjd[0] < STATIC_GAP_D
    assert static_repeaters(cands, mjd) == set()
