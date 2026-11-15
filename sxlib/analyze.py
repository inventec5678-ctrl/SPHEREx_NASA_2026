"""Full analysis of one sky patch for the web app.

fetch -> align -> difference -> detect -> CNN score -> known-object match ->
fast-mover tracks (per pass) -> distant-body (parallax) search -> PNG frames + field.json
"""
import json
import time
from pathlib import Path

import numpy as np
from astropy.time import Time
from PIL import Image
from scipy.spatial import cKDTree

from . import detect, link, pipeline
from .inject import DistantBody
from .stack import FEAT_OUTLIER

REF_KW = {"lam_tol": 0.03, "eps": 0.1}
P_KEEP = 0.05          # candidates stored for display
P_LINK = 0.5           # candidates used for tracking
FRAME_EXT = "webp"
KNOWN_MATCH_PX = 2.0   # a detection within this of a catalogued body's predicted position is that body
ABSORB_ARCSEC = 8.0    # detections this close to a fitted distant path join the track
MAX_DISTANT_POOL = 4000   # the parallax search is skipped for more confident unidentified detections than this
SIM_MATCH_PX = 2.5     # a detection this close to the injected body's position is the simulation
PASS_DAYS = 90.0
MIN_EXPOSURES = 10
DIFF_ZERO, DIFF_GAIN = 128, 16     # difference frames: 8-bit value = 128 + 16 S/N
STRETCH_SOFT, STRETCH_MAX = 3.0, 300.0     # sci/ref frames: asinh(img / (3 noise)) / asinh(300)


def _known_by_exposure(field, half_width, log):
    from .known import known_for_field
    return known_for_field(field, half_width, kinds=("a", "c"), log=log, with_status=True)


def _frame(arr, path):
    """8-bit frame, FITS y-up -> image y-down. Lossless WebP (~30% smaller than PNG)."""
    Image.fromarray(arr[::-1]).save(path, lossless=True, quality=100, method=4)   # method 6 is ~300x slower


def _sim_track(doc, tr):
    """A distant track that follows an injected body is the simulation."""
    truth = {t["i"]: t for t in doc.get("simulated_truth") or []}
    if tr["kind"] != "distant" or not truth:
        return False
    cand = {c["id"]: c for c in doc["candidates"]}
    hits = sum(1 for m in tr["members"]
               if (t := truth.get(cand[m]["i"])) and np.hypot(cand[m]["x"] - t["x"], cand[m]["y"] - t["y"]) < SIM_MATCH_PX)
    return hits >= 0.5 * len(tr["members"])


def summary_of(doc):
    """Small per-field record for the landing page (avoids loading the full field.json).
    Known objects are counted by name (one asteroid can give two track segments); 'unknown' counts only
    unidentified fast movers; a simulated planet is counted as simulated, never as unidentified."""
    tr = doc.get("tracks", [])
    fast = [t for t in tr if t["kind"] == "fast"]
    sim = [t for t in tr if _sim_track(doc, t)]
    return {"id": doc["id"], "name": doc["name"], "description": doc.get("description", ""),
            "ra": doc["ra"], "dec": doc["dec"], "size_deg": doc["size_deg"],
            "n_exposures": len(doc["exposures"]), "n_tracks": len(tr),
            "n_known": len({t["known"] for t in fast if t.get("known")}),
            "n_unknown": sum(1 for t in fast if not t.get("known")),
            "n_distant": sum(1 for t in tr if t["kind"] == "distant") - len(sim), "n_simulated": len(sim),
            "n_known_bodies": len(doc.get("known_bodies", [])),
            "simulated": bool(doc.get("simulated")), "user": doc["id"].startswith("q"),
            "first": doc["exposures"][0]["iso"][:10], "last": doc["exposures"][-1]["iso"][:10],
            "frame_ext": doc.get("frame_ext", "png"),
            "thumb": next((e["i"] for e in doc["exposures"] if e["detector"] == 2), 0),
            "target": (_target_summary(doc["target"]) if doc.get("target") else None)}


def _target_summary(tg):
    """The target's identity plus the one-line result the #/targets table shows: the measured motion against the
    catalogue's prediction (movers), or the brightness ratio between passes (variables)."""
    out = {k: tg[k] for k in ("id", "name", "kind")}
    if tg.get("motion"):
        out["motion"] = {k: tg["motion"].get(k) for k in ("measured_arcsec", "predicted_arcsec", "err_arcsec", "days", "band")}
    if tg.get("pm_total") is not None:
        out["pm_total"] = tg["pm_total"]
    if tg.get("vsx"):
        out["vsx"] = {k: tg["vsx"].get(k) for k in ("type", "period_d")}
    if tg.get("pass_ratio"):
        out["pass_ratio"] = tg["pass_ratio"]
    return out


def annotate(doc, log=print):
    """Honesty annotations that do not change the displayed tracks:
    - each track gets "blind": would linking on the AI score alone (no catalogue help) have found it?
    - doc["blind_link"]: what blind linking finds in this field (tracks, known names recovered, unknown);
    - doc["distant_search"]: whether the parallax search ran;
    - distant tracks that follow an injected body get "simulated": True."""
    cands = [dict(c) for c in doc["candidates"]]          # flat dicts: a shallow copy each is enough
    info = {}
    blind = build_tracks(cands, [e["mjd"] for e in doc["exposures"]], log=lambda m: None, blind=True, info=info)
    in_blind = {c["id"]: c["track"] for c in cands}
    names = {c["id"]: c["known"] for c in doc["candidates"]}
    for t in doc["tracks"]:
        hits = [in_blind.get(m) for m in t["members"]]
        best = max((hits.count(b) for b in set(hits) if b is not None), default=0)
        t["blind"] = best >= 0.5 * len(t["members"])
        if t["kind"] == "distant":
            t["simulated"] = _sim_track(doc, t)
    bk = set()
    n_unk = 0
    for b in blind:
        nm = [names[m] for m in b["members"] if names[m]]
        if nm and len(nm) >= len(b["members"]) / 3:
            bk.add(max(set(nm), key=nm.count))
        elif b["kind"] == "fast":
            n_unk += 1
    doc["blind_link"] = {"n_tracks": len(blind), "n_known": len(bk), "n_unknown_fast": n_unk,
                         "n_distant": sum(1 for b in blind if b["kind"] == "distant")}
    doc["distant_search"] = info.get("distant_search")
    return doc


def write_doc(out, doc):
    (out / "field.json").write_text(json.dumps(doc))
    (out / "summary.json").write_text(json.dumps(summary_of(doc)))


def planet_x_injection(field_ra, field_dec, mjds, d_au=420.0, mag=15.5, pm_pa_deg=35.0):
    """A simulated distant body placed so that its parallax loop stays inside the field. It moves on a
    circular orbit (~150"/yr at 420 au, position angle pm_pa_deg), as a real distant planet would."""
    v = link.circular_pm(d_au)
    pm = (v * np.sin(np.radians(pm_pa_deg)), v * np.cos(np.radians(pm_pa_deg)))
    t0 = float(np.median(mjds))
    b = DistantBody(field_ra, field_dec, d_au, mag, t0, pm_arcsec_yr=pm)
    ra, dec = b.position(np.asarray(mjds))
    cosd = np.cos(np.radians(field_dec))
    dra, ddec = (np.mean(ra) - field_ra) * cosd, np.mean(dec) - field_dec
    return DistantBody(field_ra - dra / cosd, field_dec - ddec, d_au, mag, t0, pm_arcsec_yr=pm)


STATIC_R_PX = 1.6       # same sky position: within this many pixels
STATIC_GAP_D = 1.5      # ... over more than this many days
STATIC_EPOCHS = 3       # ... in at least this many distinct half-hour epochs


def static_repeaters(cands, mjd_all, p_min=P_LINK):
    """Ids of detections that sit where the sky keeps producing detections for longer than a fast mover could
    stay there: star residuals, saturation and ghosts near bright stars. Measured on the nine web fields
    (2026-11-12): unidentified fast tracks went R Dra 14 -> 0, Eps Ind 21 -> 0, Barnard 2 -> 0, while all five
    known asteroids in the 65 Cybele field (three of them blind) and its one unidentified track were kept."""
    hi = [c for c in cands if c["p"] >= p_min]
    if len(hi) < STATIC_EPOCHS:
        return set()
    mjd_all = np.asarray(mjd_all)
    xy = np.array([[c["x"], c["y"]] for c in hi]); t = mjd_all[[c["i"] for c in hi]]
    out = set()
    for k, nb in enumerate(cKDTree(xy).query_ball_point(xy, STATIC_R_PX)):
        tt = t[nb]
        if len(np.unique(np.round(tt * 48))) >= STATIC_EPOCHS and tt.max() - tt.min() > STATIC_GAP_D:
            out.add(hi[k]["id"])
    return out


def build_tracks(cands, mjd_all, log=print, blind=False, info=None):
    """Distant-body (parallax) search first, then fast-mover tracks per survey pass on what is
    left. (Order matters: at quadrature a body at a few hundred AU drifts 1-3"/h within a pass
    and would otherwise be chopped into several slow 'asteroid' tracks.) Sets c["track"].
    By default catalogue-matched detections join linking whatever their AI score (so known objects
    are tracked for display); blind=True links on the AI score alone, which is the honest pipeline
    number. info, if given, receives {"distant_search": {...}}."""
    mjd_all = np.asarray(mjd_all)
    for c in cands:
        c["track"] = None
    hi = [c for c in cands if c["p"] >= P_LINK or (c["known"] and not blind)]
    for c in hi:
        c["mjd"] = float(mjd_all[c["i"]])
    tracks = []

    def add(kind, mem, **kw):
        tid = len(tracks)
        for c in mem:
            c["track"] = tid
        tracks.append({"id": tid, "kind": kind, "members": [c["id"] for c in mem],
                       "mean_p": round(float(np.mean([c["p"] for c in mem])), 3),
                       "l2_frac": round(float(np.mean([c.get("l2", False) for c in mem])), 2),
                       "start": Time(min(c["mjd"] for c in mem), format="mjd").iso[:16], **kw})

    pool = [c for c in hi if not c["known"] and c["p"] >= P_LINK]
    crowded = len(pool) >= MAX_DISTANT_POOL
    if info is not None:
        info["distant_search"] = {"skipped": crowded, "pool": len(pool)}
    if crowded:
        log(f"  distant search skipped: {len(pool)} candidates is too crowded")
    for dt in link.search_distant(pool) if not crowded else []:
        mem = [pool[k] for k in dt["members"]]
        # absorb every other detection that sits on the fitted parallax path
        ref = min(mem, key=lambda c: c["mjd"])
        in_mem = {id(c) for c in mem}
        free = [c for c in pool if c["track"] is None and id(c) not in in_mem]
        if free:
            pra, pdec = link.predict_distant(ref["ra"], ref["dec"], ref["mjd"], dt["d_au"],
                                             np.array([c["mjd"] for c in free]), pm=dt.get("pm_arcsec_yr", (0, 0)))
            x, y = link._tangent(np.array([c["ra"] for c in free]), np.array([c["dec"] for c in free]), pra, pdec)
            mem += [c for c, r in zip(free, np.hypot(x, y)) if r <= ABSORB_ARCSEC]
        d_fit, rms, pm = link.fit_distant(mem)
        ref = min(mem, key=lambda c: c["mjd"])
        tt = np.linspace(min(c["mjd"] for c in mem), max(c["mjd"] for c in mem), 160)
        mra, mdec = link.predict_distant(ref["ra"], ref["dec"], ref["mjd"], d_fit, tt, pm=pm)
        add("distant", mem, d_au=round(d_fit, 1), rms_arcsec=round(rms, 2), n_passes=dt["n_passes"], known=None,
            pm_arcsec_yr=list(pm),
            model={"mjd": [round(float(v), 4) for v in tt], "ra": [round(float(v), 6) for v in mra],
                   "dec": [round(float(v), 6) for v in mdec]})
    n_dist = len(tracks)
    # Residuals of bright or saturated stars recur at one sky position for days; chained together they look like
    # slow "movers". Nothing in the Solar System fast enough for this stage (>= 0.5"/h) stays within 1.6 px for
    # 1.5 days, so those detections are left out of fast linking (catalogue-matched ones stay unless blind).
    static = static_repeaters(cands, mjd_all)
    if info is not None:
        info["static_veto"] = {"n": len(static), "r_px": STATIC_R_PX, "gap_d": STATIC_GAP_D}
    passes = np.round((mjd_all - mjd_all.min()) / PASS_DAYS).astype(int)
    for pz in np.unique(passes):
        sub = [c for c in hi if passes[c["i"]] == pz and c["track"] is None
               and (c["id"] not in static or (c["known"] and not blind))]
        for tr in link.link_linear(sub):
            mem = [sub[k] for k in tr["members"]]
            names = [c["known"] for c in mem if c["known"]]
            top = max(set(names), key=names.count) if names else None
            known_name = top if names and names.count(top) >= len(mem) / 2 else None
            # straight-line model: least squares in RA/Dec vs time (for the motion plot)
            tm = np.array([c["mjd"] for c in mem]); A = np.vstack([np.ones_like(tm), tm - tm.mean()]).T
            cra, *_ = np.linalg.lstsq(A, np.array([c["ra"] for c in mem]), rcond=None)
            cde, *_ = np.linalg.lstsq(A, np.array([c["dec"] for c in mem]), rcond=None)
            add("fast", mem, rate_arcsec_h=round(tr["rate_arcsec_h"], 2), pa_deg=round(tr["pa_deg"], 1),
                rms_arcsec=round(tr["rms_arcsec"], 2), span_h=round(tr["span_h"], 1), known=known_name,
                model={"mjd0": round(float(tm.mean()), 6), "ra0": round(float(cra[0]), 7), "dec0": round(float(cde[0]), 7),
                       "dra_dt": float(cra[1]), "ddec_dt": float(cde[1])})
    log(f"  {n_dist} distant-body tracks, {len(tracks) - n_dist} fast tracks")
    for c in cands:
        c.pop("mjd", None)
    return tracks


def relink(path, log=print):
    """Recompute tracks of an existing field.json in place (no re-download, no re-scoring)."""
    doc = json.loads(Path(path).read_text())
    info = {}
    old = {frozenset(t["members"]): t for t in doc.get("tracks", [])}
    doc["tracks"] = build_tracks(doc["candidates"], [e["mjd"] for e in doc["exposures"]], log, info=info)
    for t in doc["tracks"]:                      # an unchanged track keeps its JPL astrometry check
        o = old.get(frozenset(t["members"]))
        if o and "jpl" in o:
            t["jpl"] = o["jpl"]
    doc["static_veto"] = info.get("static_veto")
    annotate(doc, log)
    write_doc(Path(path).parent, doc)
    return doc


def analyze_field(fid, name, ra, dec, size, out_root, scorer, description="", simulate_planet_x=False,
                  mjd_range=None, log=print, workers=8, with_products=True):
    t0 = time.time()
    out = Path(out_root) / fid
    for sub in ("sci", "ref", "diff"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    log(f"[1/6] Searching SPHEREx images around RA {ra:.3f}, Dec {dec:.3f}")
    exps = pipeline.load_exposures(ra, dec, size, mjd_range=mjd_range, workers=workers, log=log)
    if len(exps) < MIN_EXPOSURES:
        raise RuntimeError(f"only {len(exps)} usable exposures here")
    sim = []
    movers = None
    if simulate_planet_x:
        mj = np.array([e.mjd for e in exps])
        movers = [planet_x_injection(ra, dec, mj)]
        sim = [m.describe() for m in movers]
    log(f"[2/6] Aligning {len(exps)} exposures onto a common {size}° grid")
    truth = []
    f = pipeline.build_field(exps, ra, dec, size, movers=movers, truth_log=truth)
    del exps
    log("[3/6] Looking up known asteroids and comets (JPL)")
    known, bodies, known_status = _known_by_exposure(f, size / 2 + 0.02, log)

    log("[4/6] Differencing, detecting and scoring candidates with the CNN")
    cands, exposures = [], []
    sci_scale = {int(d_): float(np.nanmedian(np.sqrt(f.var[f.det == d_]))) for d_ in np.unique(f.det)}
    asinh_max = np.arcsinh(STRETCH_MAX)
    for i, e in enumerate(f.exps):
        d = f.difference(i, **REF_KW)
        cs = detect.find_candidates(d)
        probs = scorer(detect.stamps(f, i, d, cs)) if cs else np.zeros(0)
        kn = [k[0] for k in known[i]]
        mk = []
        if cs:
            kx = ky = []
            if kn:                                     # one WCS call for every known body of this exposure
                kx, ky = f.world_to_pix(np.array([k[1] for k in known[i]], float), np.array([k[2] for k in known[i]], float))
                kx, ky = [float(v) for v in np.atleast_1d(kx)], [float(v) for v in np.atleast_1d(ky)]
            mk = detect.match(cs, kx, ky, KNOWN_MATCH_PX)
        keep = [k for k in range(len(cs)) if not (probs[k] < P_KEEP and mk[k] < 0)]
        if keep:                                       # one WCS call for every stored candidate
            cra, cdec = f.pix_to_world(np.array([cs[k]["x"] for k in keep]), np.array([cs[k]["y"] for k in keep]))
            cra, cdec = np.atleast_1d(cra), np.atleast_1d(cdec)
        for j, k in enumerate(keep):
            c = cs[k]
            l2 = bool((f.feat[i, c["iy"] - 1:c["iy"] + 2, c["ix"] - 1:c["ix"] + 2] & FEAT_OUTLIER).any())
            cands.append({"id": len(cands), "i": i, "x": round(c["x"], 2), "y": round(c["y"], 2), "l2": l2,
                          "ra": round(float(cra[j]), 6), "dec": round(float(cdec[j]), 6), "snr": round(c["snr"], 1),
                          "p": round(float(probs[k]), 4), "known": kn[mk[k]] if mk[k] >= 0 else None,
                          "track": None})
        # frames: science and reference share one asinh stretch (per-detector noise scale);
        # difference is S/N encoded as 128 + 16*S/N
        for sub, img in (("sci", f.img[i]), ("ref", d["ref"])):
            s = np.arcsinh(np.nan_to_num(img) / (STRETCH_SOFT * sci_scale[e["detector"]])) / asinh_max
            _frame(np.clip(s * 255, 0, 255).astype(np.uint8), out / sub / f"{i:04d}.{FRAME_EXT}")
        dd = np.nan_to_num(d["snr"], nan=0.0)
        _frame(np.clip(DIFF_ZERO + DIFF_GAIN * dd, 0, 255).astype(np.uint8), out / "diff" / f"{i:04d}.{FRAME_EXT}")
        exposures.append({"i": i, "obs_id": e["obs_id"], "mjd": round(e["mjd"], 5),
                          "iso": Time(e["mjd"], format="mjd").iso[:16], "detector": e["detector"],
                          "release": e.get("release", ""), "lam_um": round(e["lam_um"], 3), "alpha": round(float(d["alpha"]), 3),
                          "nref": int(np.median(d["nref"][d["valid"]])) if d["valid"].any() else 0,
                          "coverage": round(float(np.mean(~f.bad[i])), 3)})
        if i % 25 == 0:
            log(f"  exposure {i + 1}/{len(f.exps)}: {len(cs)} candidates")

    log("[5/6] Linking detections into moving-object tracks")
    link_info = {}
    tracks = build_tracks(cands, f.mjd, log, info=link_info)

    sim_truth = []
    if sim and truth:
        first = {}
        for k, e in enumerate(f.exps):
            first.setdefault((e["obs_id"], e["detector"]), k)
        tx, ty = f.world_to_pix(np.array([t["ra"] for t in truth]), np.array([t["dec"] for t in truth]))
        for t, x, y in zip(truth, np.atleast_1d(tx), np.atleast_1d(ty)):
            i = first.get((t["obs_id"], t["detector"]))
            if i is not None:
                sim_truth.append({"i": i, "x": round(float(x), 2), "y": round(float(y), 2)})

    log("[6/6] Writing results")
    w = f.wcs.wcs
    doc = {"id": fid, "name": name, "description": description, "ra": ra, "dec": dec, "size_deg": size,
           "shape": list(f.shape), "wcs": {"crval": list(map(float, w.crval)), "crpix": list(map(float, w.crpix)),
                                           "cdelt": list(map(float, w.cdelt))},
           "exposures": exposures, "candidates": cands, "tracks": tracks, "known_bodies": list(bodies.values()),
           "simulated": sim, "simulated_truth": sim_truth, "p_link": P_LINK,
           "cnn_threshold_prob": getattr(scorer, "thr_prob", 0.5), "frame_ext": FRAME_EXT,
           "processing_s": round(time.time() - t0, 1), "created": Time.now().iso[:19],
           "known_lookup": known_status, "static_veto": link_info.get("static_veto")}
    annotate(doc, log)
    try:
        from .known import jpl_residuals
        jpl_residuals(doc, log)
    except Exception as e:  # noqa: BLE001 - astrometry check is optional
        log(f"  JPL astrometry check skipped: {e}")
    if with_products:
        from .products import build as build_products
        try:
            build_products(f, doc, out, log)
        except Exception as e:  # noqa: BLE001 - the viewer works without the lab products
            log(f"  products skipped: {e}")
    write_doc(out, doc)
    if doc.get("products"):          # automatic variable-star search: needs the written field.json and cube
        try:
            from .varsearch import search as var_search
            res = var_search(out, log=log)
            (out / "var_candidates.json").write_text(json.dumps({"candidates": res["candidates"], "stats": res["stats"]}))
            doc["products"]["var"] = {"n_candidates": len(res["candidates"])}
            write_doc(out, doc)
        except Exception as e:  # noqa: BLE001 - the lab works without it
            log(f"  variable search skipped: {e}")
    log(f"done in {time.time() - t0:.0f}s: {len(exposures)} exposures, {len(cands)} candidates, {len(tracks)} tracks")
    return doc
