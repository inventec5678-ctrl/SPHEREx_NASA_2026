"""Can SPHEREx find again the brown dwarfs that Backyard Worlds: Planet 9 volunteers discovered in WISE images?

  python scripts/byw_validate.py list        # fetch the catalogues (VizieR, CfA mirror), apply the selection rule
  python scripts/byw_validate.py run [--only ID ...]   # download, stack, search blind, measure (resumable)
  python scripts/byw_validate.py web         # thumbnails + web/data/validation/byw.json for the validation page

The list (frozen before any SPHEREx data of these objects was looked at; RULE below):
  - Kirkpatrick et al. 2021, ApJS 253, 7 (VizieR J/ApJS/253/7): table1 = new L, T, Y dwarf candidates with a
    discoverer code per person, joined on PName to tablea1 (CatWISE2020 position at MJD 57170, best proper motion
    and parallax, W2). Kept: at least one discoverer is a Backyard Worlds volunteer (the paper lists codes
    B C E G H I L M P S T V W X Z with the affiliation "Backyard Worlds: Planet 9"; A Andersen, D Caselden and
    R Rothermich are Backyard Worlds volunteers listed there under their other affiliations).
  - Meisner et al. 2020, ApJ 899, 123 (J/ApJ/899/123): Spitzer follow-up of brown dwarfs discovered by Backyard
    Worlds; table2 (W2, motion confirmed) + table6 (position at MJD and motion) + table9 (photometric distance).
  - cuts: W2 <= 15.0 mag and total proper motion >= 0.30"/yr. WISE 0855 (W2 ~ 14.0) is detected in our long-band
    stacks, so 15.0 reaches a magnitude (2.5x in flux) fainter, across the expected limit.

Per object, like scripts/validate_pm.py (its stacks_of() is reused) but with the long-wavelength detectors where cold
brown dwarfs are bright: a 0.2 deg field centred on the object at 2026.0; per survey pass, up to PICK cutouts of
each of D4, D5, D6 (spread in time, so also over wavelength); per-pass, per-detector median stacks; then
  - covered: SPHEREx images and survey passes containing the position (DR1 + QR3, whatever IRSA serves);
  - detected: forced aperture photometry (sxlib.products.phot) at the catalogue-predicted position (proper motion +
    parallax) on every exposure, inverse-variance mean per detector; noise measured empirically from the same
    photometry on 48 parallel tracks offset by 5-15 px. S/N >= 5 in D5 or D6 = detected;
  - blind: sxlib.pmsearch.search_all (pass-to-pass search + cross-epoch check against CatWISE2020, sxlib/xepoch.py)
    with no knowledge of the object; recovered when a candidate's track lies within 2 px of the predicted position;
  - motion: the candidate's measured proper motion against the catalogue's;
  - spectrum: sxlib.specclass.score_points on the forced photometry (needs >= 5 of its 16 wavelength bins with
    points at S/N > 3, otherwise no score).
Results: outputs/byw_validation.json (rewritten after every object). Cutouts are cached in cache/byw/ so the analysis
can be re-run without downloading again; the download total is counted and capped (BUDGET_GB).
"""
import argparse
import json
import math
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE as _CACHE_ROOT, DATA, FIELDS, OUTPUTS, VALIDATION, read_json, read_text, write_json, write_text  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = OUTPUTS / "byw_validation.json"
CACHE = _CACHE_ROOT / "byw"
WEB = DATA / "byw"
VAL = VALIDATION / "byw.json"
VIZIER = "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; generic-client)"}

SIZE = 0.2                     # deg: field side (cutouts are 1.5x this so a rotated exposure still covers it)
PICK = {4: 2, 5: 7, 6: 7}      # cutouts per survey pass per detector (each cutout is ~4.3 MB: it carries the ePSF table)
BUDGET_GB = 5.8                # stop downloading beyond this (the task's budget is 6 GB)
MATCH_PX = 2.0                 # a blind candidate within this of the predicted position is the object
SNR_DET = 5.0                  # forced-photometry S/N for "detected at the predicted position"
W2_MAX, PM_MIN = 15.0, 0.30
PIX_ARCSEC = 6.15              # SPHEREx pixel scale, arcsec
DETS_LONG = (4, 5, 6)          # long-wavelength detectors used for forced photometry
DETS_DEEP = (5, 6)             # the detectors where cold brown dwarfs are brightest
N_DOWNLOAD_THREADS = 8
BYW_CODES = set("BCEGHILMPSTVWXZ")   # K21 affiliation "Backyard Worlds: Planet 9"
BYW_OTHER = set("ADR")               # Andersen, Caselden, Rothermich: volunteers listed under other affiliations
PLX_ASSUMED = 50.0                   # mas, when no parallax or distance is published (K21 candidates are < ~20 pc)

TABLES = {"k21_t1": "J/ApJS/253/7/table1", "k21_a1": "J/ApJS/253/7/tablea1",
          "m20_t2": "J/ApJ/899/123/table2", "m20_t6": "J/ApJ/899/123/table6", "m20_t9": "J/ApJ/899/123/table9"}
CITES = [
    {"ref": "Kirkpatrick et al. 2021, ApJS 253, 7", "vizier": "J/ApJS/253/7", "tables": ["table1", "tablea1"],
     "bibcode": "2021ApJS..253....7K"},
    {"ref": "Meisner et al. 2020, ApJ 899, 123", "vizier": "J/ApJ/899/123", "tables": ["table2", "table6", "table9"],
     "bibcode": "2020ApJ...899..123M"},
]
RULE = ("Backyard Worlds discoveries: Kirkpatrick et al. 2021 table 1 objects with at least one volunteer discoverer "
        "(codes B C E G H I L M P S T V W X Z, affiliation 'Backyard Worlds: Planet 9', plus A Andersen, D Caselden, "
        "R Rothermich), and the motion-confirmed objects of Meisner et al. 2020 (ApJ 899, 123). Kept: W2 <= 15.0 and "
        "total proper motion >= 0.30 arcsec/yr; duplicates within 10 arcsec merged (Kirkpatrick astrometry kept). "
        "Fixed on 2026-11-13 before any SPHEREx data of these objects was looked at.")


# ---- the list -----------------------------------------------------------------------------------------------------
def parse_tsv(text):
    """VizieR asu-tsv -> list of dicts (strings, stripped). After the # comments come the column names, a units line
    (often blank), a line of dashes, then the rows."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    i = next((k for k, ln in enumerate(lines) if ln.strip()), None)
    if i is None:
        return []
    head = [h.strip() for h in lines[i].split("\t")]
    j = next((k for k in range(i + 1, len(lines)) if lines[k].strip() and set(lines[k]) <= set("-\t ")), None)
    if j is None:
        return []
    rows = []
    for ln in lines[j + 1:]:
        if not ln.strip():
            continue
        v = [x.strip() for x in ln.split("\t")]
        rows.append(dict(zip(head, v + [""] * (len(head) - len(v)))))
    return rows


def _f(s):
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def vizier(key, refresh=False):
    """One VizieR table, all columns, all rows; cached in cache/byw/vizier/."""
    p = CACHE / "vizier" / f"{key}.tsv"
    if p.exists() and not refresh:
        return parse_tsv(read_text(p))
    import requests
    import urllib3
    urllib3.disable_warnings()
    for k in range(4):
        r = requests.get(VIZIER, params={"-source": TABLES[key], "-out.all": "", "-out.max": "unlimited"}, headers=UA,
                         verify=False, timeout=180)
        r.raise_for_status()
        rows = parse_tsv(r.text)
        if rows and "VOTable Error" not in r.text and "#Table" in r.text:
            break
        time.sleep(10 * (k + 1))                            # the mirror's database is sometimes briefly unreachable
    else:
        raise RuntimeError(f"VizieR returned no rows for {TABLES[key]}: {r.text[:200]}")
    write_text(p, r.text)
    return rows


def mjd_to_jyear(mjd):
    return 2000.0 + (mjd - 51544.5) / 365.25


def select(k21_t1, k21_a1, m20_t2, m20_t6, m20_t9, w2_max=W2_MAX, pm_min=PM_MIN):
    """The selection rule (RULE) on parsed VizieR rows. Returns (objects sorted by W2, counts per step)."""
    counts = {}
    a1 = {}
    for r in k21_a1:
        a1.setdefault(r["PName"], r)                        # one row per system: the first component
    objs = []
    t1_byw = 0
    for r in k21_t1:
        codes = {c.strip() for c in r.get("Disc", "").split(",") if c.strip()}
        if not codes & (BYW_CODES | BYW_OTHER):
            continue
        t1_byw += 1
        a = a1.get(r["PName"])
        if a is None:
            continue
        ra, dec, pmra, pmdec = _f(a["RACdeg"]), _f(a["DECdeg"]), _f(a["pmRA"]), _f(a["pmDE"])
        w2 = _f(a["W2mag"]) or _f(a["W2magC2"])
        if None in (ra, dec, pmra, pmdec, w2):
            continue
        plx = _f(a["plx"])
        objs.append({"id": r["PName"], "name": "CWISE " + r["CWISE"], "ref": "K21", "disc": ",".join(sorted(codes)),
                     "ra": ra, "dec": dec, "epoch": round(mjd_to_jyear(57170.0), 4), "pmra": pmra, "pmdec": pmdec,
                     "plx": plx if plx and plx > 0 else PLX_ASSUMED, "plx_src": "K21" if plx and plx > 0 else "assumed",
                     "w2": round(w2, 3), "pm": round(math.hypot(pmra, pmdec) / 1000, 3), "sptype": _sptype(_f(a["SpAd"]))})
    counts["k21_table1"] = len(k21_t1)
    counts["k21_volunteer"] = t1_byw
    t6 = {r["Source"]: r for r in m20_t6}
    t9 = {r["Source"]: r for r in m20_t9}
    m20 = 0
    for r in m20_t2:
        if r.get("Motion") != "yes" or r["Source"] not in t6:
            continue
        m20 += 1
        s = t6[r["Source"]]
        ra, dec, pmra, pmdec, w2 = _f(s["RA_ICRS"]), _f(s["DE_ICRS"]), _f(s["pmRA"]), _f(s["pmDE"]), _f(r["W2mag"])
        if None in (ra, dec, pmra, pmdec, w2):
            continue
        d = _f(t9.get(r["Source"], {}).get("Dist"))
        short = r["Source"].split("J")[-1]
        objs.append({"id": short[:4] + short[short.find("+") if "+" in short else short.find("-"):][:5], "name": r["Source"],
                     "ref": "M20", "disc": "BYW", "ra": ra, "dec": dec, "epoch": round(mjd_to_jyear(_f(s["MJD"])), 4),
                     "pmra": pmra, "pmdec": pmdec, "plx": round(1000 / d, 2) if d else PLX_ASSUMED,
                     "plx_src": "M20 phot. distance" if d else "assumed", "w2": round(w2, 3),
                     "pm": round(math.hypot(pmra, pmdec) / 1000, 3), "sptype": None})
    counts["m20_motion_confirmed"] = m20
    keep = [o for o in objs if o["w2"] <= w2_max and o["pm"] >= pm_min]
    counts["after_cuts"] = len(keep)
    out = []
    for o in sorted(keep, key=lambda o: (o["ref"] != "K21", o["w2"])):   # K21 first: it wins a duplicate
        if any(_sep_arcsec(_at2016(o), _at2016(q)) < 10 for q in out):
            continue
        out.append(o)
    counts["selected"] = len(out)
    return sorted(out, key=lambda o: o["w2"]), counts


def _at2016(o):
    """Linear proper motion to 2016.0 (enough to tell two entries of one object apart)."""
    dt = 2016.0 - o["epoch"]
    c = max(math.cos(math.radians(o["dec"])), 1e-6)
    return {"ra": o["ra"] + o["pmra"] * dt / 3.6e6 / c, "dec": o["dec"] + o["pmdec"] * dt / 3.6e6}


def _sep_arcsec(a, b):
    c = math.cos(math.radians(a["dec"]))
    return math.hypot((a["ra"] - b["ra"]) * c, a["dec"] - b["dec"]) * 3600


def _sptype(v):
    """K21 numeric type: L0 = 0 ... T0 = 10 ... Y0 = 20."""
    if v is None:
        return None
    for lo, s in ((20, "Y"), (10, "T"), (0, "L")):
        if v >= lo:
            return f"{s}{v - lo:g}"
    return f"M{v + 10:g}"


# ---- choosing exposures ---------------------------------------------------------------------------------------------
def pick_exposures(metas, lab, per=PICK):
    """Per survey pass and detector, up to per[d] exposures evenly spread in time (and so over the detector's
    wavelength range). metas: archive.search_images rows; lab: pass label of each. Returns [(meta, pass)]."""
    out = []
    for p in sorted(set(int(x) for x in lab)):
        for d, k in sorted(per.items()):
            g = sorted((m for m, l in zip(metas, lab) if int(l) == p and m["detector"] == d), key=lambda m: m["mjd"])
            if not g or k <= 0:
                continue
            idx = sorted(set(np.linspace(0, len(g) - 1, min(k, len(g))).round().astype(int).tolist()))
            out += [(g[i], p) for i in idx]
    return out


# ---- download accounting ------------------------------------------------------------------------------------------
_BYTES = {"n": 0, "files": 0}
_LOCK = threading.Lock()


def _count_downloads():
    """Wrap sxlib.archive._get so every downloaded byte is counted (cached cutouts are not fetched again)."""
    from sxlib import archive
    if getattr(archive._get, "_byw", False):
        return
    orig = archive._get

    def counted(*a, **k):
        r = orig(*a, **k)
        with _LOCK:
            _BYTES["n"] += len(r.content)
            _BYTES["files"] += 1
        return r
    counted._byw = True
    archive._get = counted


# ---- one object ---------------------------------------------------------------------------------------------------
def weighted(f, e):
    """Inverse-variance mean and its error."""
    f, e = np.asarray(f, float), np.asarray(e, float)
    ok = np.isfinite(f) & np.isfinite(e) & (e > 0)
    if ok.sum() == 0:
        return None, None
    w = 1 / e[ok] ** 2
    return float(np.sum(w * f[ok]) / w.sum()), float(1 / np.sqrt(w.sum()))


def forced(f, obj, offsets=None, dets=DETS_LONG):
    """Forced photometry along the predicted track (shifted by `offsets` px for the noise tracks).
    Returns {d: [(lam, flux, err), ...]} for the zero offset, and per detector the weighted means of every offset."""
    from sxlib.products import phot
    from sxlib.targets import position_at
    ra, de = position_at(obj, f.mjd)
    x, y = f.world_to_pix(ra, de)
    offsets = [(0.0, 0.0)] + list(offsets or [])
    pts = {d: [] for d in dets}
    means = {d: [] for d in dets}
    n0, n1 = f.shape
    for j, (ox, oy) in enumerate(offsets):
        acc = {d: ([], []) for d in dets}
        for k, e in enumerate(f.exps):
            d = int(e["detector"])
            if d not in acc:
                continue
            xx, yy = float(x[k] + ox), float(y[k] + oy)
            if not (3 <= xx < n1 - 3 and 3 <= yy < n0 - 3):
                continue
            p = phot(f.img[k], f.var[k], f.bad[k], xx, yy)
            if p is None:
                continue
            acc[d][0].append(p[0]); acc[d][1].append(p[1])
            if j == 0:
                lam = f.lam[k][int(round(yy)), int(round(xx))]
                pts[d].append((float(lam) if np.isfinite(lam) else e["lam_um"], p[0], p[1]))
        for d in dets:
            means[d].append(weighted(*acc[d]))
    return pts, means, (x, y)


def noise_offsets(n=48, rmin=5.0, rmax=15.0, seed=0):
    rng = np.random.default_rng(seed)
    r = np.sqrt(rng.uniform(rmin ** 2, rmax ** 2, n))
    a = rng.uniform(0, 2 * np.pi, n)
    return list(zip(r * np.cos(a), r * np.sin(a)))


def detection(means):
    """Per detector: flux, formal error, empirical sigma (robust scatter of the offset tracks) and S/N against it."""
    out = {}
    for d, m in means.items():
        f0, e0 = m[0] if m and m[0][0] is not None else (None, None)
        off = np.array([v[0] for v in m[1:] if v[0] is not None])
        if f0 is None or off.size < 10:
            out[d] = None
            continue
        med = float(np.median(off))
        sig = float(1.4826 * np.median(np.abs(off - med)))
        sig = max(sig, e0)
        out[d] = {"flux_ujy": round(f0 - med, 2), "err_formal": round(e0, 2), "sigma_emp": round(sig, 2),
                  "snr": round((f0 - med) / sig, 2), "n_noise": int(off.size)}
    return out


def seeded_motion(f, obj, ov, snr, deep, allb, dets=DETS_DEEP):
    """Not blind: where the object is in `deep`, the stack of every D5 + D6 exposure (fitted starting from where the
    catalogue says it should be), registered on Gaia stars found in `allb`, the stack of every exposure
    (sxlib.xepoch.register), and compared with the catalogue position at the catalogue's own epoch (CatWISE 2015.4,
    or Meisner's 2018-2019): a 7-11 year baseline, like the cross-epoch stage. Returns the measured motion (east,
    north, arcsec/yr), the one the catalogue predicts for the same exposures (proper motion + parallax), and the
    positions in the stack's pixels for the thumbnail. The position error is at least PSF sigma (~1 px) / S/N: a
    Gaussian fit's formal error is too small for a faint source."""
    from sxlib import xepoch as X
    from sxlib.pmsearch import _sources, fit_position
    from sxlib.targets import position_at
    sel = np.isin(f.det, dets)
    if sel.sum() < 4:
        return {"reason": "too_few_exposures"}
    t = float(np.mean(f.mjd[sel]))
    ra, de = position_at(obj, f.mjd[sel])
    xs, ys = f.world_to_pix(ra, de)
    xp, yp = float(np.mean(xs)), float(np.mean(ys))           # predicted mean position over these exposures
    x0, y0 = f.world_to_pix(obj["ra"], obj["dec"])            # the catalogue position at its epoch
    x0, y0 = float(x0), float(y0)
    C, info = X.register(_sources(allb), ov.get("gaia", []), t)
    if C is None:
        return {"reason": "no_registration", "n_ref": info.get("n", 0)}
    A, b = C[:2].T, C[2]                                       # catalogue frame -> stack pixels, for the drawing
    inv = lambda X_, Y_: [round(float(v), 2) for v in np.linalg.solve(A, np.array([X_, Y_]) - b)]  # noqa: E731
    out = {"cat_xy": inv(x0, y0), "pred_xy": inv(xp, yp), "n_ref": info.get("n"), "rms_px": info.get("rms_px")}
    fit = fit_position(deep, *out["pred_xy"])
    if fit is None or np.hypot(fit[0] - out["pred_xy"][0], fit[1] - out["pred_xy"][1]) > 2.0:
        return out | {"reason": "no_fit"}
    Xm, Ym = X.apply(C, fit[0], fit[1])
    Xm, Ym = float(Xm[0]), float(Ym[0])
    dt = (t - (51544.5 + (obj["epoch"] - 2000.0) * 365.25)) / 365.25
    cdelt = list(map(float, f.wcs.wcs.cdelt))
    me, mn = X._east_north((Xm - x0) / dt, (Ym - y0) / dt, cdelt)
    pe, pn = X._east_north((xp - x0) / dt, (yp - y0) / dt, cdelt)
    err_px = float(np.hypot(max(fit[2], 1.0 / snr if snr and snr > 0 else 0.0), info.get("rms_px") or 0.0))
    return out | {"fit_xy": [round(fit[0], 2), round(fit[1], 2)], "pmra": round(float(me), 3), "pmdec": round(float(mn), 3),
                  "pm": round(float(np.hypot(me, mn)), 3), "pm_err": round(err_px * PIX_ARCSEC / dt, 3), "pred_pmra": round(float(pe), 3),
                  "pred_pmdec": round(float(pn), 3), "pred_pm": round(float(np.hypot(pe, pn)), 3), "baseline_yr": round(dt, 2),
                  "mjd": round(t, 2), "offset_arcsec": round(float(np.hypot(Xm - xp, Ym - yp) * PIX_ARCSEC), 2)}


def one(obj, log=print):
    from sxlib import archive
    from sxlib.pmsearch import fit_position, search_all
    from sxlib.products import overlays, passes_of
    from sxlib.specclass import bin_spectrum, score_points
    from sxlib.stack import Field
    from sxlib.targets import centre_2026, position_at
    from validate_pm import _safe, stacks_of
    ra0, dec0 = centre_2026(obj)
    metas = archive.search_images(ra0, dec0)
    if not metas:
        return {"covered": False, "n_images": 0, "n_pass": 0}
    lab = passes_of(np.array([m["mjd"] for m in metas]))
    cover = {"covered": True, "n_images": len(metas), "n_pass": int(lab.max()) + 1,
             "by_detector": {str(d): sum(m["detector"] == d for m in metas) for d in range(1, 7)},
             "releases": sorted({m["collection"] for m in metas})}
    pick = pick_exposures(metas, lab)
    if len({p for _, p in pick}) < 2:
        return cover | {"skip": "one_pass"}
    cache = CACHE / "cutouts" / obj["id"]
    with ThreadPoolExecutor(N_DOWNLOAD_THREADS) as ex:
        exps = [e for e in ex.map(lambda m: _safe(archive.fetch_cutout, m[0], ra0, dec0, SIZE * 1.5, False, cache), pick)
                if e is not None]
    f = Field(ra0, dec0, SIZE)
    for e in exps:
        f.add(e)
    if len(f.exps) < 6:
        return cover | {"skip": "too_few_exposures", "n_exp": len(f.exps)}
    f.freeze()
    st, mid = stacks_of(f)
    plab = passes_of(f.mjd)
    P = len(mid)
    # forced photometry at the catalogue-predicted position, and on parallel tracks for the noise
    pts, means, (xp, yp) = forced(f, obj, noise_offsets())
    det = detection(means)
    best = max([(det[d] or {}).get("snr") for d in DETS_DEEP if (det[d] or {}).get("snr") is not None], default=None)
    # spectrum score from every forced point (the classifier drops points below S/N 3 itself)
    allp = [p for d in pts for p in pts[d]]
    L, F, E = [p[0] for p in allp], [p[1] for p in allp], [p[2] for p in allp]
    _x, msk = bin_spectrum(L, F, E)
    bd = score_points(L, F, E)
    # blind search: the pass-to-pass search plus the cross-epoch stage, no knowledge of the object
    if P < 2:
        return cover | {"skip": "one_pass"}
    ov = overlays(f, log=lambda m: None)
    pass_times = {b: [f.mjd[(plab == k) & ((f.det == b) if b else True)] for k in range(P)] for b in (0, 5, 6)}
    res = search_all(st, mid, ov, cdelt=list(map(float, f.wcs.wcs.cdelt)), ra=ra0, dec=dec0, pass_times=pass_times,
                     log=lambda m: None)
    ra_p, dec_p = position_at(obj, np.array(mid))
    px, py = f.world_to_pix(ra_p, dec_p)
    pred_track = [{"k": k, "x": round(float(px[k]), 3), "y": round(float(py[k]), 3)} for k in range(P)]

    def dist(c):
        return min(np.hypot(t["x"] - px[t["k"]], t["y"] - py[t["k"]]) for t in c["track"])
    hit = min(res["candidates"], key=dist, default=None)
    found = hit is not None and dist(hit) <= MATCH_PX
    # direct: fit the object at its predicted positions in the first and last pass (D6, D5, all bands)
    pred = np.array([px[-1] - px[0], py[-1] - py[0]])
    direct = None
    for b in (6, 5, 0):
        fa, fz = fit_position(st[0, b], px[0], py[0]), fit_position(st[-1, b], px[-1], py[-1])
        if fa and fz and np.hypot(fa[0] - px[0], fa[1] - py[0]) < 1.5 and np.hypot(fz[0] - px[-1], fz[1] - py[-1]) < 1.5:
            band_stats = next((s for s in res["stats"]["per_band"] if s.get("band") == b and "offset_px" in s), None) \
                or res["stats"]["per_band"][0]
            meas = np.array([fz[0] - fa[0], fz[1] - fa[1]]) - np.array(band_stats.get("offset_px", [0, 0]))
            direct = {"band": b, "meas_px": [round(float(v), 3) for v in meas], "err_px": round(float(np.hypot(fa[2], fz[2])), 3),
                      "resid_arcsec": round(float(np.linalg.norm(meas - pred) * PIX_ARCSEC), 3)}
            break
    rec = {"n_exp": len(f.exps), "n_exp_by_det": {str(d): int((f.det == d).sum()) for d in DETS_LONG},
           "n_pass_used": P, "dt_yr": round((mid[-1] - mid[0]) / 365.25, 3), "pass_mjd": [round(m, 3) for m in mid],
           "pred_track": pred_track, "pred_shift_arcsec": round(float(np.linalg.norm(pred) * PIX_ARCSEC), 3),
           "detect": {str(d): v for d, v in det.items()}, "snr_best": best, "detected": bool(best is not None and best >= SNR_DET),
           "found": bool(found), "method": hit.get("method") if found else None, "status": hit["status"] if found else None,
           "sig": hit["sig"] if found else None, "det_band": hit["det_band"] if found else None,
           "meas_pm": hit["pm_arcsec_yr"] if found else None, "meas_pmra": hit["pmra"] if found else None,
           "meas_pmdec": hit["pmdec"] if found else None, "meas_pm_err": hit.get("pm_err_arcsec_yr") if found else None,
           "xepoch": hit.get("xepoch") if found else None,
           "nearest_px": round(float(dist(hit)), 2) if hit is not None else None,
           "n_candidates": len(res["candidates"]), "n_new_other": sum(1 for c in res["candidates"] if c["status"] == "new" and not (found and c is hit)),
           "search_stats": {"floor_px": res["stats"].get("floor_px"), "per_band": [{k: s.get(k) for k in ("band", "n_pairs", "reason", "floor_px")} for s in res["stats"]["per_band"]],
                            "xepoch": {k: (res["stats"].get("xepoch") or {}).get(k) for k in ("n_measured", "n_isolated", "floor_arcsec_yr", "rejected", "limit_arcsec_yr", "reason")}},
           "overlay_errors": ov.get("errors") or None,
           "bd_score": None if bd is None else round(bd, 3), "bd_bins": int(msk.sum()), "bd_points": len(F),
           "direct": direct}
    img = np.where(f.bad, np.nan, f.img)
    with np.errstate(all="ignore"):
        deep = np.nanmedian(img[np.isin(f.det, DETS_DEEP)], axis=0)
        allb = np.nanmedian(img, axis=0)
    try:
        rec["seeded"] = seeded_motion(f, obj, ov, best, deep, allb)
    except Exception as e:  # noqa: BLE001 - the rest of the record stands
        rec["seeded"] = {"reason": f"error: {str(e)[:120]}"}
    _thumbs(obj["id"], f, st, pred_track, deep, rec["seeded"])
    return cover | rec


def _thumbs(oid, f, st, track, deep, seeded, half=24):
    """Pictures for the page, cut around the object (the lab's stretch and orientation, sxlib.products):
      web/data/byw/<id>/pass/p{k}_d56.webp  each survey pass's stack of D5 + D6 (a blink)
      web/data/byw/<id>/deep_d56.webp       every D5 + D6 exposure stacked (the deepest picture)
      web/data/byw/<id>/track.json          predicted position per pass, and in the deep stack: the catalogue position
                                            at its epoch, the predicted and the fitted position (crop pixels)."""
    from sxlib.products import _save, _stretch
    P = st.shape[0]
    cx = int(round(np.mean([t["x"] for t in track]))); cy = int(round(np.mean([t["y"] for t in track])))
    n0, n1 = f.shape
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(n1, cx + half + 1), min(n0, cy + half + 1)
    with np.errstate(all="ignore"):
        crops = [np.nanmean(np.stack([st[k, 5, y0:y1, x0:x1], st[k, 6, y0:y1, x0:x1]]), axis=0) for k in range(P)]
    out = WEB / oid / "pass"
    out.mkdir(parents=True, exist_ok=True)
    s = _stretch(crops)
    for k, c in enumerate(crops):
        _save(s(c), out / f"p{k}_d56.webp")
    dc = deep[y0:y1, x0:x1]
    _save(_stretch([dc])(dc), WEB / oid / "deep_d56.webp")
    rel = lambda xy: None if xy is None else [round(xy[0] - x0, 2), round(xy[1] - y0, 2)]  # noqa: E731
    sd = seeded or {}
    write_json(WEB / oid / "track.json", {
        "track": [{"k": t["k"], "x": round(t["x"] - x0, 2), "y": round(t["y"] - y0, 2)} for t in track], "shape": [y1 - y0, x1 - x0],
        "cat": rel(sd.get("cat_xy")), "pred": rel(sd.get("pred_xy")), "fit": rel(sd.get("fit_xy"))}, indent=None)


# ---- summary for the page -----------------------------------------------------------------------------------------
W2_BINS = [(13.9, 14.25), (14.25, 14.5), (14.5, 14.75), (14.75, 15.0)]


def summarise(rows, bins=W2_BINS):
    """rows: [{"w2", "covered", "detected", "found", ...}] -> totals and per-W2-bin fractions."""
    cov = [r for r in rows if r.get("covered") and not r.get("skip")]
    out = {"n_selected": len(rows), "n_covered": len(cov), "n_detected": sum(bool(r.get("detected")) for r in cov),
           "n_found": sum(bool(r.get("found")) for r in cov), "bins": []}
    for lo, hi in bins:
        g = [r for r in cov if lo <= r["w2"] < hi or (hi == bins[-1][1] and r["w2"] == hi)]
        out["bins"].append({"w2_lo": lo, "w2_hi": hi, "n": len(g), "detected": sum(bool(r.get("detected")) for r in g),
                            "found": sum(bool(r.get("found")) for r in g)})
    return out


def limit_w2(rows, snr=SNR_DET):
    """W2 where the detection S/N crosses `snr`: a straight line through log10(S/N) against W2 (sources with a
    positive S/N; S/N of a flux scales as 10^(-0.4 W2) at fixed noise). None with fewer than 4 points."""
    pts = [(r["w2"], r["snr_best"]) for r in rows if r.get("snr_best") is not None and r["snr_best"] > 0]
    if len(pts) < 4:
        return None
    w, s = np.array(pts).T
    a, b = np.polyfit(w, np.log10(s), 1)
    if a >= 0:
        return None
    return round(float((np.log10(snr) - b) / a), 2), round(float(a), 3)


# ---- main ---------------------------------------------------------------------------------------------------------
def load():
    return read_json(OUT, {})


def save(doc):
    doc["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_json(OUT, doc, atomic=True)


def cmd_list(refresh=False):
    tabs = {k: vizier(k, refresh) for k in TABLES}
    objs, counts = select(tabs["k21_t1"], tabs["k21_a1"], tabs["m20_t2"], tabs["m20_t6"], tabs["m20_t9"])
    doc = load()
    old = {o["obj"]["id"]: o for o in doc.get("objects", [])}
    doc.update(rule=RULE, sources=CITES, vizier_mirror=VIZIER, counts=counts, config={"size_deg": SIZE, "pick_per_pass": PICK,
               "match_px": MATCH_PX, "snr_detect": SNR_DET, "w2_max": W2_MAX, "pm_min": PM_MIN})
    doc["objects"] = [old.get(o["id"], {"obj": o}) | {"obj": o} for o in objs]
    save(doc)
    for o in objs:
        print(f"{o['id']:>10} {o['ref']} W2={o['w2']:.2f} pm={o['pm']:.2f}\"/yr {o['sptype'] or '':>5} disc={o['disc']} plx={o['plx']} ({o['plx_src']})")
    print(counts)


def cmd_run(only=None, redo=False):
    _count_downloads()
    doc = load()
    if not doc.get("objects"):
        sys.exit("run `list` first")
    for k, rec in enumerate(doc["objects"]):
        oid = rec["obj"]["id"]
        if only and oid not in only:
            continue
        if "result" in rec and not redo and not str(rec["result"].get("skip", "")).startswith("error"):
            continue
        spent = doc.get("bytes_downloaded", 0) + _BYTES["n"]
        if spent > BUDGET_GB * 1e9:
            print(f"download budget reached ({spent / 1e9:.2f} GB): stopping"); break
        t0, b0 = time.time(), _BYTES["n"]
        try:
            rec["result"] = one(rec["obj"])
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rec["result"] = {"skip": f"error: {str(e)[:160]}"}
        rec["seconds"] = round(time.time() - t0, 1)
        got = _BYTES["n"] - b0
        rec["bytes"] = rec.get("bytes", 0) + got                 # a re-run reads the cached cutouts: 0 more
        doc["bytes_downloaded"] = doc.get("bytes_downloaded", 0) + got
        _BYTES["n"] = 0
        r = rec["result"]
        o = rec["obj"]
        print(f"{k + 1}/{len(doc['objects'])} {oid} W2={o['w2']:.2f} pm={o['pm']:.2f} -> "
              f"{r.get('skip') or ''} passes={r.get('n_pass')} exp={r.get('n_exp')} S/N={r.get('snr_best')} "
              f"{'FOUND ' + str(r.get('method')) + ' ' + str(r.get('meas_pm')) if r.get('found') else 'not found'} "
              f"bd={r.get('bd_score')} ({rec['seconds']}s, {rec['bytes'] / 1e6:.0f} MB; total {doc['bytes_downloaded'] / 1e9:.2f} GB)", flush=True)
        save(doc)


def cmd_web():
    doc = load()
    rows = []
    for rec in doc.get("objects", []):
        o, r = rec["obj"], rec.get("result")
        if r is None:
            continue
        tr = WEB / o["id"] / "track.json"
        row = {"id": o["id"], "name": o["name"], "ref": o["ref"], "sptype": o["sptype"], "w2": o["w2"], "pm_cat": o["pm"],
               "pmra_cat": round(o["pmra"] / 1000, 3), "pmdec_cat": round(o["pmdec"] / 1000, 3), "ra": round(o["ra"], 3), "dec": round(o["dec"], 3),
               "epoch": o["epoch"], "disc": o["disc"],
               "covered": r.get("covered", False), "skip": r.get("skip"), "n_pass": r.get("n_pass"), "n_images": r.get("n_images"),
               "n_exp": r.get("n_exp"), "snr_best": r.get("snr_best"), "snr": {d: (v or {}).get("snr") for d, v in (r.get("detect") or {}).items()},
               "detected": r.get("detected", False), "found": r.get("found", False), "method": r.get("method"), "status": r.get("status"),
               "pm_meas": r.get("meas_pm"), "pmra_meas": r.get("meas_pmra"), "pmdec_meas": r.get("meas_pmdec"), "pm_meas_err": r.get("meas_pm_err"),
               "bd_score": r.get("bd_score"), "bd_bins": r.get("bd_bins"), "dt_yr": r.get("dt_yr"),
               "n_exp_by_det": r.get("n_exp_by_det"), "seeded": _seeded_row(r)}
        if row["found"] and row["pm_meas"] is not None:
            d = math.hypot(row["pmra_meas"] - row["pmra_cat"], row["pmdec_meas"] - row["pmdec_cat"])
            row["pm_agree"] = bool(d <= max(0.35 * row["pm_cat"], 3 * (row["pm_meas_err"] or 0)))
        if tr.exists() and not row["skip"]:
            row["img"] = {"base": f"/data/byw/{o['id']}", "det_band": "56", **read_json(tr)}
        rows.append(row)
    summ = summarise(rows)
    lim = limit_w2([r for r in rows if r["covered"] and not r["skip"]])
    val = {"title": "Backyard Worlds brown dwarfs found again by SPHEREx", "updated": doc.get("updated"), "rule": doc.get("rule"),
           "sources": doc.get("sources"), "counts": doc.get("counts"), "config": doc.get("config"), "summary": summ,
           "limit_w2_snr5": lim[0] if lim else None, "snr_slope_per_mag": lim[1] if lim else None,
           "bytes_downloaded": doc.get("bytes_downloaded"), "objects": rows,
           "reference": _wise0855()}
    write_json(VAL, val)
    print(json.dumps(summ), lim)


def _seeded_row(r):
    """The 7-11 year motion measured at the predicted position, for objects seen there (S/N >= SNR_DET) only."""
    sd = r.get("seeded") or {}
    if not r.get("detected") or sd.get("pm") is None:
        return None
    return {k: sd[k] for k in ("pm", "pm_err", "pmra", "pmdec", "pred_pm", "pred_pmra", "pred_pmdec", "baseline_yr", "offset_arcsec")}


def _wise0855():
    """The challenge target WISE 0855 (W2 ~ 14.0) as found by the site's own field run, for comparison (full depth)."""
    try:
        d = read_json(FIELDS / "wise0855" / "pm_candidates.json")
        c = next(c for c in d["candidates"] if (c.get("match") or {}).get("pm_cat", 0) > 5)
        return {"name": "WISE 0855−0714", "w2": 14.0, "pm_cat": 8.15, "pm_meas": c["pm_arcsec_yr"], "found": True,
                "note": "challenge target, full-depth 0.3 deg field (all exposures)"}
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "run", "web"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a.refresh)
    elif a.cmd == "run":
        cmd_run(a.only, a.redo)
    else:
        cmd_web()


if __name__ == "__main__":
    main()
