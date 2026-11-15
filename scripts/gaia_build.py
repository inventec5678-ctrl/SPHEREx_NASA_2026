"""Gaia DR3 products for the web app (ESA's archive first, MAST as the fallback; sxlib/gaia.py).

  python scripts/gaia_build.py [cmd] [targets] [variables] [field ids ...]     (no argument: all three, every field)

cmd        web/data/gaia/cmd.json: the colour-magnitude diagram of the Sun's neighbourhood, a 2-D histogram of every
           Gaia DR3 star within 100 pc with a good parallax and clean colours (binned on the server: no star list is
           downloaded).
targets    web/data/gaia/targets.json: G, BP-RP, parallax and absolute G of the challenge's targets (WISE 0855 is
           not in Gaia; it is listed with that reason).
variables  web/data/validation/gaia.json: Gaia DR3's variable stars against our automatic variable search
           (sxlib/varsearch.py). For every analysed field the search is run again without catalogues to get every
           measured source (var_candidates.json keeps only the candidates); its candidates must equal the published
           ones. Each Gaia variable in the footprint then goes through a funnel: bright enough for our source
           finder -> it is the star we measured (the brightest Gaia source at that spot) -> searched (not blended,
           not on a saturated star's wings) -> flagged. And each of our candidates: does Gaia flag it, as what?
"""
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATA, FIELDS, VALIDATION, read_json, write_json  # noqa: E402
from sxlib import gaia  # noqa: E402
from sxlib.targets import TARGETS  # noqa: E402

OUT = DATA / "gaia"
VAL = VALIDATION / "gaia.json"
STEPS = ("cmd", "targets", "variables")
OWNER_PX = 1.0           # a Gaia star is "the star of" a measured source within this distance (field pixels)
OUTSHINE_PX = 1.5        # a brighter Gaia star this close takes a variable's place; also the candidate match radius
EDGE_PX = 3              # Gaia stars this close to the field edge are left out
G_LIMIT_DEFAULT = 16.0   # when the completeness curve never reaches one half

# ---- the colour-magnitude diagram ---------------------------------------------------------------------------------
CMD_X0, CMD_DX, CMD_NX = -0.6, 0.05, 112          # BP-RP from -0.6 to 5.0
CMD_Y0, CMD_DY, CMD_NY = -2.0, 0.2, 110           # absolute G from -2 to 20
CMD_WHERE = ("parallax > 10 AND parallax_over_error > 10 AND phot_bp_mean_flux_over_error > 10 "
             "AND phot_rp_mean_flux_over_error > 10 AND ruwe < 1.4 "
             "AND phot_bp_rp_excess_factor > 1.0 + 0.015*bp_rp*bp_rp AND phot_bp_rp_excess_factor < 1.3 + 0.06*bp_rp*bp_rp")


def build_cmd():
    q = (f"SELECT cx, cy, COUNT(*) AS n FROM (SELECT FLOOR((bp_rp - ({CMD_X0}))/{CMD_DX}) AS cx, "
         f"FLOOR((phot_g_mean_mag + 5*LOG10(parallax) - 10 - ({CMD_Y0}))/{CMD_DY}) AS cy FROM gaiadr3.gaia_source "
         f"WHERE {CMD_WHERE}) AS t GROUP BY cx, cy")
    t0 = time.time()
    rows = gaia.query(q, timeout=600, log=print)
    grid = np.zeros((CMD_NY, CMD_NX), int)
    rows = [r for r in rows if r["cx"] != "" and r["cy"] != ""]
    cx = np.array([int(float(r["cx"])) for r in rows], int)
    cy = np.array([int(float(r["cy"])) for r in rows], int)
    n = np.array([int(r["n"]) for r in rows], int)
    inside = (cx >= 0) & (cx < CMD_NX) & (cy >= 0) & (cy < CMD_NY)
    np.add.at(grid, (cy[inside], cx[inside]), n[inside])
    n_all, n_out = int(n.sum()), int(n[~inside].sum())
    doc = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "service": gaia.last["service"], "query_s": round(time.time() - t0, 1),
           "selection": f"Gaia DR3 gaia_source: {CMD_WHERE}", "n_stars": n_all, "n_outside": n_out,
           "x0": CMD_X0, "dx": CMD_DX, "nx": CMD_NX, "y0": CMD_Y0, "dy": CMD_DY, "ny": CMD_NY,
           "counts": grid.ravel().tolist()}           # row-major: counts[iy * nx + ix], iy = 0 at the brightest
    write_json(OUT / "cmd.json", doc, compact=True)
    print(f"cmd: {n_all} stars within 100 pc ({n_out} outside the grid), {int((grid > 0).sum())} filled bins, "
          f"{time.time() - t0:.1f} s via {gaia.last['service']}")


# ---- the challenge's targets ----------------------------------------------------------------------------------------
def build_targets():
    ids = {k: t["source"].split()[-1] for k, t in TARGETS.items() if t["source"].startswith("Gaia DR3")}
    rows = gaia.query("SELECT source_id, phot_g_mean_mag, bp_rp, parallax, parallax_error, ruwe, phot_variable_flag "
                      f"FROM gaiadr3.gaia_source WHERE source_id IN ({','.join(ids.values())})", log=print)
    by = {r["source_id"]: r for r in rows}
    out = []
    for k, t in TARGETS.items():
        r = by.get(ids.get(k))
        if r is None:
            out.append({"id": k, "name": t["name"], "kind": t["kind"], "in_gaia": False, "ra": t["ra"], "dec": t["dec"],
                        "why": "too faint and cold for Gaia's visible-light camera (G > 21)"})
            continue
        g, c, p = gaia._f(r["phot_g_mean_mag"]), gaia._f(r["bp_rp"]), gaia._f(r["parallax"])
        out.append({"id": k, "name": t["name"], "kind": t["kind"], "in_gaia": True, "source_id": r["source_id"],
                    "g": round(g, 3), "bp_rp": None if c is None else round(c, 3), "plx": round(p, 3),
                    "abs_g": round(gaia.abs_g(g, p), 3), "dist_pc": round(1000 / p, 2 if p > 50 else 0),
                    "ruwe": round(gaia._f(r["ruwe"]), 3), "variable": r["phot_variable_flag"]})
    for v in out:
        if v.get("variable") == "VARIABLE":
            v["vari"] = gaia.variability(v["source_id"])
    write_json(OUT / "targets.json", {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": out}, indent=1)
    for v in out:
        print(f"  {v['id']}: " + (f"G {v['g']} BP-RP {v['bp_rp']} M_G {v['abs_g']} {v['dist_pc']} pc {v['variable']}"
                                  f"{' ' + str(v['vari']['cls']) if v.get('vari') else ''}" if v["in_gaia"] else "not in Gaia"))


# ---- variables ----------------------------------------------------------------------------------------------------------
def world2pix(wcs, ra, dec):
    """RA, Dec -> field pixel: the inverse of sxlib.varsearch.pix2world (gnomonic)."""
    d2r = math.pi / 180
    a0, d0 = wcs["crval"][0] * d2r, wcs["crval"][1] * d2r
    a, d = np.asarray(ra) * d2r, np.asarray(dec) * d2r
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / cosc
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return xi / d2r / wcs["cdelt"][0] + wcs["crpix"][0] - 1, eta / d2r / wcs["cdelt"][1] + wcs["crpix"][1] - 1


def g_limit(stars, step=0.5):
    """Faintest G at which our source finder picks up at least half of Gaia's stars: per 0.5-mag bin, the share of
    Gaia stars that are the brightest Gaia source within 1 px of a measured source."""
    gs = np.array([s["g"] for s in stars])
    hit = np.array([s["measured"] for s in stars])
    lim, curve = None, []
    for lo in np.arange(6.0, 19.5, step):
        sel = (gs >= lo) & (gs < lo + step)
        if sel.sum() >= 3:
            f = float(hit[sel].mean())
            curve.append({"g": round(float(lo + step / 2), 2), "n": int(sel.sum()), "frac": round(f, 3)})
            if f >= 0.5:
                lim = round(float(lo + step), 2)
    return lim, curve


def field_check(fid, log=print):
    from sxlib import varsearch as V
    d = FIELDS / fid
    doc = read_json(d / "field.json")
    pub = read_json(d / "var_candidates.json")
    t0 = time.time()
    res = V.search(d, with_catalogues=False, log=lambda *a: None)
    rows, cands = res["all"], res["candidates"]
    same = sorted((round(c["x"], 1), round(c["y"], 1)) for c in cands) == sorted((round(c["x"], 1), round(c["y"], 1)) for c in pub["candidates"])
    n = doc["shape"][0]
    epoch = gaia.epoch_of_mjd(float(np.median([e["mjd"] for e in doc["exposures"]])))
    rad = doc["size_deg"] * 0.75
    allg = gaia.cone(doc["ra"], doc["dec"], rad, ["source_id", "ra", "dec", "pmra", "pmdec", "phot_g_mean_mag"], max_g=19.5, top=20000, log=log)
    var = {r["source_id"]: r for r in gaia.field_variables(doc["ra"], doc["dec"], rad, log=log)}
    svc = gaia.last["service"]
    # every Gaia star at the field's epoch, in pixels
    stars = []
    for r in allg:
        g = gaia._f(r["phot_g_mean_mag"])
        if g is None:
            continue
        ra, dec = gaia.move_to(r, epoch)
        x, y = world2pix(doc["wcs"], ra, dec)
        if EDGE_PX <= x <= n - 1 - EDGE_PX and EDGE_PX <= y <= n - 1 - EDGE_PX:
            stars.append({"id": r["source_id"], "x": float(x), "y": float(y), "g": g})
    xy = np.array([[s["x"], s["y"]] for s in stars]) if stars else np.zeros((0, 2))
    # the measured source each Gaia star is "the star of": the brightest Gaia source within 1 px of a measured peak
    # (a k-d tree replaces the rows x stars distance matrix; ties go to the lower star index, as before)
    owner = {}
    if len(xy) and rows:
        from scipy.spatial import cKDTree
        gs = np.array([s["g"] for s in stars])
        hits = cKDTree(xy).query_ball_point(np.array([[q["x"], q["y"]] for q in rows]), r=OWNER_PX)
        for k, near in enumerate(hits):
            if near:
                near = sorted(near)
                j = near[int(np.argmin(gs[near]))]
                owner[stars[j]["id"]] = k
    for s in stars:
        s["measured"] = s["id"] in owner
    glim, curve = g_limit(stars)
    if glim is None:
        glim = G_LIMIT_DEFAULT
    thr = float(res["stats"]["threshold_unsat"])
    out_vars = []
    for s in stars:
        v = var.get(s["id"])
        if v is None:
            continue
        cls = v["best_class_name"] or "unclassified"
        k = owner.get(s["id"])
        q = rows[k] if k is not None else None
        # a variable that is not "the star of" a measured source: is a brighter star within 1.5 px taking its place?
        outshone = q is None and any(o["g"] < s["g"] for o in stars if o is not s and math.hypot(o["x"] - s["x"], o["y"] - s["y"]) <= OUTSHINE_PX)
        searched = q is not None and not q["blended"] and not q["near_saturated"]
        out_vars.append({"field": fid, "id": s["id"], "x": round(s["x"], 2), "y": round(s["y"], 2), "g": round(s["g"], 2),
                         "cls": cls, "cls_score": gaia._f(v["best_class_score"]),
                         "gaia_range": gaia._f(v["trimmed_range_mag_g_fov"]), "gaia_std": gaia._f(v["std_dev_mag_g_fov"]),
                         "in_range": s["g"] < glim, "measured": q is not None, "outshone": outshone, "searched": searched,
                         "flagged": bool(searched and q["candidate"]), "saturated": bool(q and q["saturated"]),
                         "our_amp": None if q is None else q["amp"], "our_sig": None if q is None else q["sig"],
                         "n_dets_agree": None if q is None else q["n_dets_agree"]})
    # our candidates: what Gaia says about the star at each
    cand_out = []
    for c in pub["candidates"]:
        dd = [(math.hypot(s["x"] - c["x"], s["y"] - c["y"]), s) for s in stars]
        near = sorted((t for t in dd if t[0] <= OUTSHINE_PX), key=lambda t: t[1]["g"])
        s = near[0][1] if near else None
        v = var.get(s["id"]) if s else None
        cand_out.append({"field": fid, "id": c["id"], "x": c["x"], "y": c["y"], "amp": c["amp"], "sig": c["sig"],
                         "status": c.get("status"), "match": c.get("match"),
                         "gaia_id": s["id"] if s else None, "gaia_g": round(s["g"], 2) if s else None,
                         "sep_px": round(near[0][0], 2) if s else None, "gaia_variable": v is not None,
                         "cls": (v["best_class_name"] or "unclassified") if v else None,
                         "gaia_range": gaia._f(v["trimmed_range_mag_g_fov"]) if v else None})
    st = {"field": fid, "service": svc, "epoch": round(epoch, 2), "n_gaia_stars": len(stars), "n_measured_sources": len(rows),
          "n_searched_sources": sum(1 for q in rows if not q["blended"] and not q["near_saturated"]),
          "g_limit": glim, "completeness": curve, "threshold_unsat": round(thr, 3), "threshold_sat": V.RING_MIN_AMP,
          "n_gaia_variables": len(out_vars), "candidates_match_published": same, "search_s": round(time.time() - t0, 1)}
    log(f"{fid}: {len(stars)} Gaia stars, {len(rows)} measured, G limit {glim}, Gaia variables {funnel(out_vars)}; "
        f"{len(cand_out)} candidates, published match {same}; {time.time() - t0:.0f} s via {svc}")
    return st, out_vars, cand_out


STAGES = ("footprint", "in_range", "measured", "searched", "flagged")


def funnel(vs):
    """Counts at each STAGES step (in_range and below count only the variables bright enough for our finder)."""
    inr = [v for v in vs if v["in_range"]]
    return {"footprint": len(vs), "in_range": len(inr), "measured": sum(v["measured"] for v in inr),
            "searched": sum(v["searched"] for v in inr), "flagged": sum(v["flagged"] for v in inr)}


def build_variables(ids):
    ids = ids or sorted(p.parent.name for p in FIELDS.glob("*/var_candidates.json")
                        if "." not in p.parent.name and (p.parent / "cube" / "img.npy").exists())
    fields, allv, cands = [], [], []
    for fid in ids:
        try:
            st, vs, cs = field_check(fid)
        except gaia.GaiaError as e:
            print(f"{fid}: Gaia unavailable: {e}")
            continue
        fields.append(st); allv += vs; cands += cs
    classes = Counter(v["cls"] for v in allv if v["in_range"])
    by_class = [{"cls": c, **funnel([v for v in allv if v["cls"] == c])} for c, _ in classes.most_common()]
    cand_cls = Counter(c["cls"] for c in cands if c["gaia_variable"])
    doc = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "about": "Gaia DR3 variables (phot_variable_flag = VARIABLE; class = vari_classifier_result.best_class_name) "
                    "inside each analysed field, against our automatic variable search. in_range: G brighter than the "
                    "field's g_limit, where our source finder measures at least half of Gaia's stars. measured: the "
                    "variable is the brightest Gaia source within 1 px of a measured source. searched: that source is "
                    "not blended and not on a saturated star's wings. flagged: the search made it a candidate.",
           "services": sorted({f["service"] for f in fields}),
           "fields": fields, "funnel": funnel(allv), "by_class": by_class,
           "outshone_in_range": sum(1 for v in allv if v["in_range"] and v["outshone"]),
           "candidates": cands,
           "cand_summary": {"n": len(cands), "gaia_variable": sum(c["gaia_variable"] for c in cands),
                            "no_gaia_source": sum(1 for c in cands if c["gaia_id"] is None), "by_class": dict(cand_cls)},
           "variables": [v for v in allv if v["in_range"]]}
    write_json(VAL, doc, indent=1)
    print("funnel:", doc["funnel"])
    print("by class:", [(b["cls"], b["in_range"], b["flagged"]) for b in by_class])
    print("candidates:", doc["cand_summary"])


def main(argv):
    steps = [a for a in argv if a in STEPS] or list(STEPS)
    ids = [a for a in argv if a not in STEPS]
    if "cmd" in steps:
        build_cmd()
    if "targets" in steps:
        build_targets()
    if "variables" in steps:
        build_variables(ids)


if __name__ == "__main__":
    main(sys.argv[1:])
