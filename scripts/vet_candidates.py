"""Vet every distant-body candidate of the survey and collect all discovery-test results for the website.

  python scripts/vet_candidates.py      # -> paper_evidence/discovery.json and web/app/public/discovery/discovery.json

Inputs (pulled from the VM): outputs/survey/<id>/{search.json, field.json}, paper_evidence/{survey,stack_grid,
planetx_grid}.json, outputs/dwarf/{result,stack}_<name>.json.

A candidate survives only if it passes every automatic check:
  1. seen in >= 3 survey passes (two passes cannot separate distance from orbital motion);
  2. the parallax + orbital-motion fit is good (rms <= 4");
  3. its motion is that of a bound orbit at the fitted distance;
  4. it is not static: no confident detection sits at the same sky position in another pass;
  5. no known asteroid or comet (JPL sb_ident, V < 24) is within 30" at any of its times;
  6. the fitted distance is not stuck at the edge of the search range (30 / 3000 au);
  7. (stacked) the brightness agrees between passes within the noise;
  8. (stacked, survey-wide) the survey yields clearly more stacked tracks than with time-relabelled passes
     (stack_null.py); otherwise every stacked track is consistent with chance alignments.
Survivors are only "candidates that need follow-up observations", never discoveries.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from math import erf, sqrt
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import OUTPUTS, PAPER_EVIDENCE, PUBLIC, read_json, write_json  # noqa: E402
from sxlib import archive, link  # noqa: E402
from sxlib.analyze import P_LINK  # noqa: E402

SV = OUTPUTS / "survey"
DW = OUTPUTS / "dwarf"
PE = PAPER_EVIDENCE
WEB = PUBLIC / "discovery"
RMS_MAX = 4.0                   # arcsec, parallax + orbit fit
MIN_PASSES = 3
D_RANGE_OK = (31, 2900)         # au; the search range is 30-3000 au
FUTURE = {"2027-01-01": 61406.0, "2027-07-01": 61587.0}
KNOWN_RADIUS_DEG, KNOWN_VMAX, KNOWN_KINDS = 0.35, 24.0, ("a", "c")
PASS_DAYS = 90                  # survey pass spacing used to tell passes apart
FIELD_AREA_DEG2 = 0.25
P9_V, P9_SIG_BRIGHT, P9_SIG_FAINT = 22.0, 1.4, 1.1     # Brown, Holman & Batygin 2024
DWARFS = ("Makemake", "Haumea", "Eris")
CHECKS = ("passes", "fit", "bound", "not_static", "range", "flux", "not_known")


def _load(p):
    return read_json(p) if p.exists() else None


_KNOWN = {}


def _known_bodies(field, mjd):
    """JPL sb_ident for the whole field at one pass mid-time (cached per field and pass)."""
    key = (field["id"], round(mjd))
    if key not in _KNOWN:
        try:
            _KNOWN[key] = archive.known_small_bodies(field["ra"], field["dec"], mjd, KNOWN_RADIUS_DEG, KNOWN_VMAX, KNOWN_KINDS)
        except Exception:  # noqa: BLE001
            _KNOWN[key] = None
    return _KNOWN[key]


def _known_near(field, points, r_arcsec=30.0):
    """Name of a known small body within r of any (ra, dec, mjd), or None. Failed lookups -> 'lookup_failed'."""
    for ra, dec, mjd in points:
        kb = _known_bodies(field, mjd)
        if kb is None:
            return "lookup_failed"
        for b in kb:
            bra, bdec = archive.known_position(b, mjd)
            x, y = link._tangent(np.array([bra]), np.array([bdec]), ra, dec)
            if np.hypot(x[0], y[0]) <= r_arcsec:
                return b["name"]
    return None


def _points_single(doc, track):
    ex = doc["exposures"]
    by_id = {c["id"]: c for c in doc["candidates"]}
    mem = [by_id[m] for m in track["members"] if m in by_id]
    return [{"ra": c["ra"], "dec": c["dec"], "mjd": ex[c["i"]]["mjd"], "p": c["p"], "x": c["x"], "y": c["y"]} for c in mem]


def _static(doc, pts, tol_px=1.5):
    """True if any member's position lights up (p >= P_LINK) in a pass the track is not in."""
    ex = doc["exposures"]
    t0 = ex[0]["mjd"]
    own = np.unique(np.rint((np.array([p["mjd"] for p in pts]) - t0) / PASS_DAYS))
    hi = [c for c in doc["candidates"] if c["p"] >= P_LINK]
    if not hi or not pts:
        return False
    hz = np.rint((np.array([ex[c["i"]]["mjd"] for c in hi]) - t0) / PASS_DAYS)
    other = ~np.isin(hz, own)
    if not other.any():
        return False
    hx = np.array([c["x"] for c in hi])[other]; hy = np.array([c["y"] for c in hi])[other]
    px = np.array([p["x"] for p in pts])[:, None]; py = np.array([p["y"] for p in pts])[:, None]
    return bool(((hx - px) ** 2 + (hy - py) ** 2 <= tol_px ** 2).any())


def _flux_consistent(pts, chi2_max=13.8):
    """A body has one brightness: its per-frame flux (stacked S/N / sqrt(frames)) must agree between passes
    within the noise (chi-square, 2 dof, p > 0.001). Residuals and chance alignments usually do not."""
    f = np.array([p["snr"] / np.sqrt(p["n"]) for p in pts]); sig = 1 / np.sqrt([p["n"] for p in pts])
    w = 1 / sig ** 2; fb = float((f * w).sum() / w.sum())
    return float((((f - fb) / sig) ** 2).sum()) <= chi2_max


def vet(field, method, track, pts, doc):
    d = track["d_au"]; pm = track.get("pm_arcsec_yr") or (0.0, 0.0)
    checks = {
        "passes": track["n_passes"] >= MIN_PASSES,
        "fit": track["rms_arcsec"] <= RMS_MAX,
        "bound": float(np.hypot(*pm)) <= link.PM_BOUND * link.circular_pm(d) * 1.01,
        "not_static": not _static(doc, pts) if method == "single" else True,   # stacked peaks: drop_static already ran
        "range": D_RANGE_OK[0] <= d <= D_RANGE_OK[1],
        "flux": _flux_consistent(pts) if method == "stack" else True,
    }
    checks = {k: bool(v) for k, v in checks.items()}
    checks["not_known"] = None
    if all(v for k, v in checks.items() if k != "not_known"):
        name = _known_near(field, [(p["ra"], p["dec"], p["mjd"]) for p in pts])
        checks["not_known"] = None if name == "lookup_failed" else name is None
        known = name
    else:
        known = None
    ok = all(v for v in checks.values())
    ref = min(pts, key=lambda p: p["mjd"])
    pred = {}
    if ok:
        for k, m in FUTURE.items():
            ra, dec = link.predict_distant(ref["ra"], ref["dec"], ref["mjd"], d, np.array([m]), pm=tuple(pm))
            pred[k] = [round(float(ra[0]), 5), round(float(dec[0]), 5)]
    return {"field": field["id"], "region": field["region"], "method": method, "d_au": round(d, 1), "pm_arcsec_yr": [round(v, 1) for v in pm],
            "rms_arcsec": round(track["rms_arcsec"], 2), "n_passes": track["n_passes"], "n_points": len(pts),
            "ra": round(ref["ra"], 5), "dec": round(ref["dec"], 5), "mjd": round(ref["mjd"], 3),
            "snr": round(float(np.mean([p.get("snr", p.get("p", 0)) for p in pts])), 2),
            "checks": checks, "known": known, "survives": ok, "predicted": pred,
            "points": [{k: (round(v, 5) if isinstance(v, float) else v) for k, v in p.items() if k in ("ra", "dec", "mjd", "snr", "p", "n")} for p in pts]}


def prefetch(plan):
    jobs = []
    for f in plan["fields"]:
        s = _load(SV / f["id"] / "search.json")
        for t in (s or {}).get("stack_tracks", []):
            jobs += [(f, p["mjd"]) for p in t["peaks"]]
    jobs = list({(f["id"], round(m)): (f, m) for f, m in jobs}.values())
    print(f"JPL lookups: {len(jobs)}", flush=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda a: _known_bodies(*a), jobs))


def survey():
    plan = _load(SV / "plan.json") or {"fields": []}
    prefetch(plan)
    fields, cands = [], []
    for f in plan["fields"]:
        s, doc = _load(SV / f["id"] / "search.json"), _load(SV / f["id"] / "field.json")
        if not s or not doc:
            continue
        fields.append({k: s[k] for k in ("id", "region", "ra", "dec", "n_exposures", "n_passes", "masked_fraction")}
                      | {"distant_skipped": bool((s.get("distant_search") or {}).get("skipped"))})
        for t in doc["tracks"]:
            if t["kind"] == "distant" and not t.get("simulated"):
                cands.append(vet(f, "single", t, _points_single(doc, t), doc))
        for t in s["stack_tracks"]:
            cands.append(vet(f, "stack", t, t["peaks"], doc))
        print(f["id"], len(cands), flush=True)
    return fields, cands


def dwarfs():
    out = []
    for n in DWARFS:
        r, s = _load(DW / f"result_{n}.json"), _load(DW / f"stack_{n}.json")
        if r or s:
            out.append({"name": n, "single": r, "stack": s})
    return out


def limits(stack_grid, area):
    """50% completeness of the stacked search (interpolated) and what it means for a Planet Nine-like body."""
    if not stack_grid:
        return None
    t = stack_grid["table"]
    mags = np.array([r["mag"] for r in t]); frac = np.array([r["recovered"] / max(r["n"], 1) for r in t])
    m50 = None
    for k in range(len(t) - 1):
        if frac[k] >= 0.5 > frac[k + 1]:
            m50 = float(mags[k] + (frac[k] - 0.5) / (frac[k] - frac[k + 1]) * (mags[k + 1] - mags[k])); break
    if m50 is None and frac[-1] >= 0.5:
        m50 = float(mags[-1])
    # Brown, Holman & Batygin 2024: V = 22.0 (+1.1 / -1.4), an asymmetric normal; fraction brighter than m50
    p9 = None
    if m50 is not None:
        sig = P9_SIG_BRIGHT if m50 < P9_V else P9_SIG_FAINT
        p9 = round(0.5 * (1 + erf((m50 - P9_V) / (sig * sqrt(2)))), 3)
    return {"m50_ab": round(m50, 2) if m50 is not None else None, "area_deg2": round(area, 2), "completeness": [
        {"mag": float(m), "frac": round(float(f), 3)} for m, f in zip(mags, frac)], "p9_fraction_brighter": p9,
        "note": "AB in a single SPHEREx channel; Planet Nine's V-band brightness distribution is used as a rough guide only "
                "(its near-infrared colour is unknown, methane would make it fainter)"}


def ades_draft(c, k):
    """An MPC ADES (PSV) DRAFT for one surviving candidate. Not submittable as is: SPHEREx (code 288) is a
    space observatory, so every row also needs the spacecraft position (sys/ctr/pos1-3), and third-party
    measurements of SPHEREx data must be cleared with the MPC first."""
    from astropy.time import Time
    head = ["# version=2017", "# observatory", "! mpcCode 288", "# submitter", "! name TO BE FILLED", "# observers", "! name SPHEREx Project",
            "# measurers", "! name TO BE FILLED", "# telescope", "! name SPHEREx", "! aperture 0.2", "! design reflector",
            "# comment", "! line DRAFT - spacecraft position (sys ctr pos1 pos2 pos3) must be added; contact the MPC before submitting",
            "trkSub|mode|stn|obsTime|ra|dec|rmsRA|rmsDec|astCat|remarks"]
    rows = [f"SPX{k + 1:04d}|CCD|288|{Time(p['mjd'], format='mjd').isot[:22]}Z|{p['ra']:.6f}|{p['dec']:+.6f}|1.500|1.500|Gaia3|NEW TNO candidate, needs follow-up"
            for p in sorted(c["points"], key=lambda p: p["mjd"])]
    return "\n".join(head + rows) + "\n"


def chance_excess(null):
    """Do the stacked tracks clearly outnumber those from time-relabelled passes (chance alignments)?
    Requires an excess above 2 sigma of the Poisson scatter of the null count."""
    if not null:
        return None
    return bool(null["total_true"] > null["total_null_mean"] + 2 * np.sqrt(max(null["total_null_mean"], 1)))


def main():
    fields, cands = survey()
    null = _load(PE / "stack_null.json")
    excess = chance_excess(null)
    for c in cands:
        if c["method"] == "stack":
            c["checks"]["excess"] = excess
            c["survives"] = bool(c["survives"] and excess is not False)
    sv = _load(PE / "survey.json") or {}
    area = sum(FIELD_AREA_DEG2 * (1 - f["masked_fraction"]) for f in fields if not f["distant_skipped"])
    sg = _load(PE / "stack_grid.json")
    px = _load(PE / "planetx_grid.json")
    out = {"generated": "2026-10-21", "survey": {"n_fields": len(fields), "area_deg2": round(area, 2), "fields": fields,
                                                 "by_region": {g: sum(1 for f in fields if f["region"] == g) for g in "ABD"},
                                                 "phan_2025_extrapolated": sv.get("phan_2025_extrapolated")},
           "candidates": sorted(cands, key=lambda c: (not c["survives"], -c["snr"])),
           "n_raw": len(cands), "n_survive": sum(c["survives"] for c in cands),
           "rejected_by": {k: sum(1 for c in cands if c["checks"].get(k) is False) for k in CHECKS},
           "n_pass_checks": sum(1 for c in cands if all(v for k, v in c["checks"].items() if k != "excess")), "chance_excess": excess,
           "dwarfs": dwarfs(), "stack_grid": sg and {k: sg[k] for k in ("table", "false_tracks_total", "fields", "d_grid")},
           "planetx_grid": px and {k: px.get(k) for k in ("table", "false_distant_tracks_total", "fields") if k in px},
           "limits": limits(sg, area), "null": null and {k: v for k, v in null.items() if k != "fields"}}
    WEB.mkdir(parents=True, exist_ok=True)
    for k, c in enumerate(out["candidates"]):
        if c["survives"]:
            with open(WEB / f"ades_{k + 1}.psv", "w", encoding="utf-8", newline="\n") as fh:
                fh.write(ades_draft(c, k))
            c["ades"] = f"/discovery/ades_{k + 1}.psv"
    for p in (PE / "discovery.json", WEB / "discovery.json"):
        write_json(p, out, default=float)
    print(f"{len(fields)} fields, {out['n_raw']} raw candidates, {out['n_survive']} survive; rejected by {out['rejected_by']}")


if __name__ == "__main__":
    main()
