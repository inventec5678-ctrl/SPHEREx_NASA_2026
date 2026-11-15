"""Precompute the "follow an asteroid" showcases and the MOST-vs-pipeline validation.

  python scripts/follow_build.py showcases   # 3 objects -> web/data/follow/<slug>/ (~1.5 GB of cutouts)
  python scripts/follow_build.py validate    # -> web/data/validation/follow.json (no image downloads)
  (set SX_INSECURE=1 behind a TLS-intercepting proxy)

Validation: in the 65 Cybele field (web/data/fields/cybele) IRSA MOST says which
SPHEREx exposures contained each known asteroid and where. For every such exposure that our field also used, we ask
whether our pipeline found a detection within 2 pixels (12") of MOST's position, whether the neural network accepted
it, and whether it was linked into a track; and we measure our position minus MOST's (arcsec). This gives the
detection completeness for known bodies (against predicted brightness) and an independent check of positions.
"""
import argparse
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE as _CACHE_ROOT, DATA, FIELDS, VALIDATION, write_json, read_json  # noqa: E402
from sxlib import follow as F  # noqa: E402

OUT = DATA / "follow"
CACHE = _CACHE_ROOT / "follow"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
SPHEREX_CENTER = "500@-163182"        # Horizons observer code of the SPHEREx spacecraft
EDGE_PX = 10                          # MOST positions closer than this to the field edge are not compared
HALF_EXPOSURE_S = 56.8                # half of SPHEREx's ~113.6 s exposure
V_BINS = [(0, 14), (14, 16), (16, 17), (17, 18), (18, 19), (19, 20), (20, 21), (21, 99)]
MOST_MAX_AGE_S = 30 * 86400           # MOST answers are cached for 30 days

# (query, t0, t1, note): 65 Cybele while it crossed our analysed field; the near-Earth asteroid 433 Eros; the
# bright comet of autumn 2025, C/2025 A6 (Lemmon). Eros: February 2026, about 0.45 AU from Earth. Each is capped at ~150 images (sampled evenly in time).
SHOWCASES = [
    ("65 Cybele", "2025-12-01", "2025-12-31", "cybele"),
    ("433 Eros", "2026-02-01", "2026-02-28", "nea"),
    ("C/2025 A6", None, None, "comet"),
]


def showcases(only=None):
    order = []
    for q, t0, t1, note in SHOWCASES:
        r = F.sbdb_resolve(q, CACHE)
        if r["status"] != "ok":
            print(f"{q}: SBDB says {r}")
            continue
        slug = F.slugify(r["name"], t0, t1)
        order.append({"slug": slug, "note": note, "q": q})
        if only and note not in only:
            continue
        d = F.run(slug, r["spkid"], r["name"], t0, t1, out_root=OUT, cache=CACHE, kind=r["kind"])
        (OUT / slug / "keep").touch()
        print(f"{slug}: {d['status']} {d.get('n_done')} frames, lc={json.dumps({k: v for k, v in (d.get('lc') or {}).items() if k != 'pgram'})}")
    if not only:
        write_json(OUT / "showcases.json", order, indent=1)


# ---- validation -------------------------------------------------------------------------------------------------
def tan_xy(wcs, ra, dec):
    """Field pixel (0-based) of (ra, dec) on the field's TAN grid (field.json wcs: crval, crpix, cdelt)."""
    d2r = math.pi / 180
    a, d = ra * d2r, dec * d2r
    a0, d0 = wcs["crval"][0] * d2r, wcs["crval"][1] * d2r
    cosc = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
    xi = math.cos(d) * math.sin(a - a0) / cosc / d2r
    eta = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(a - a0)) / cosc / d2r
    return xi / wcs["cdelt"][0] + wcs["crpix"][0] - 1, eta / wcs["cdelt"][1] + wcs["crpix"][1] - 1


def query_name(name):
    """'5591 Koyo (1990 VF2)' -> '5591'; '(2012 FU25)' / '366162 (2012 FU25)' -> number or designation."""
    m = re.match(r"^\s*(\d+)\b", name)
    if m:
        return m.group(1)
    m = re.search(r"\(([^)]+)\)", name)
    return m.group(1) if m else name.strip()


def compare(doc, body, images, radius_px=1.0, edge_px=EDGE_PX):
    """MOST images of one body inside the field vs the field's detections. One record per matched exposure.
    Positions are MOST's moved to mid-exposure (sxlib.follow.most_images); dra0/ddec0 are against MOST's own
    (start-of-exposure) values. `chance` is how many unrelated detections that exposure would put inside the search
    circle on average (its detections spread over the field)."""
    wcs, n = doc["wcs"], doc["shape"][0]
    exp = {(e["obs_id"], int(e["detector"])): e for e in doc["exposures"]}
    by_i = {}
    for c in doc["candidates"]:
        by_i.setdefault(c["i"], []).append(c)
    tracks = {t["id"]: t for t in doc["tracks"]}
    thr = doc.get("cnn_threshold_prob", 0.5)
    out = []
    for im in images:
        e = exp.get((im["obs_id"], im["detector"]))
        x, y = tan_xy(wcs, im["ra"], im["dec"])
        inside = edge_px <= x <= n - 1 - edge_px and edge_px <= y <= n - 1 - edge_px
        if not inside:
            continue
        rec = {"i": e["i"] if e else None, "obs": im["obs_id"], "det": im["detector"], "mjd": round(im["mjd"], 5),
               "V": im["vmag"], "x": round(x, 2), "y": round(y, 2), "in_field": e is not None}
        if e is None:
            out.append(rec)
            continue
        rec["nref"] = e.get("nref")
        rec["chance"] = len(by_i.get(e["i"], [])) * math.pi * radius_px ** 2 / float(n * n)
        # nearest detection of that exposure within the search radius
        near = min(((math.hypot(c["x"] - x, c["y"] - y), c) for c in by_i.get(e["i"], [])),
                   key=lambda t: t[0], default=None)
        if near and near[0] <= radius_px:
            dd, c = near
            tr = tracks.get(c["track"]) if c.get("track") is not None else None
            rec.update(found=True, snr=c.get("snr"), p=c.get("p"), nn=bool(c.get("p", 0) >= thr),
                       track=bool(tr is not None), track_known=(tr or {}).get("known"), label=c.get("known"),
                       dra=round((c["ra"] - im["ra"]) * math.cos(math.radians(im["dec"])) * 3600, 2),
                       ddec=round((c["dec"] - im["dec"]) * 3600, 2),
                       dra0=round((c["ra"] - im.get("ra0", im["ra"])) * math.cos(math.radians(im["dec"])) * 3600, 2),
                       ddec0=round((c["dec"] - im.get("dec0", im["dec"])) * 3600, 2))
        else:
            rec["found"] = False
        out.append(rec)
    return out


def horizons(command, mjds, center=SPHEREX_CENTER):
    """JPL Horizons astrometric RA/Dec (deg) of one body at the given MJDs (UT), seen from SPHEREx by default."""
    import urllib.parse
    import requests
    q = {"format": "json", "COMMAND": command, "EPHEM_TYPE": "OBSERVER", "CENTER": f"'{center}'", "TLIST_TYPE": "JD",
         "QUANTITIES": "'1'", "ANG_FORMAT": "DEG", "EXTRA_PREC": "YES", "CSV_FORMAT": "YES", "OBJ_DATA": "NO",
         "TLIST": "'" + " ".join(f"{m + 2400000.5:.7f}" for m in mjds) + "'"}
    r = requests.get(HORIZONS + "?" + urllib.parse.urlencode(q), timeout=120,
                     verify=F._verify(), headers=F.UA).json()["result"]
    rows = r[r.index("$$SOE") + 5:r.index("$$EOE")].strip().splitlines()
    return [(float(p[3]), float(p[4])) for p in (x.split(",") for x in rows)]


def most_check(spkid="20000065", command="'65;'", t0="2025-12-01", t1="2025-12-31", n=40):
    """Where in the exposure is MOST's position? Compared with JPL Horizons seen from SPHEREx and from Earth's centre,
    at the start and the middle of each exposure; and our mid-exposure correction against Horizons at mid-exposure."""
    _, ims = F.most_query(spkid=spkid, t0=t0, t1=t1, cache_dir=CACHE)
    one = list({im["obs_id"]: im for im in ims}.values())[:n]

    def med(pos, key_ra="ra0", key_dec="dec0"):
        d = [math.hypot((im[key_ra] - a) * math.cos(math.radians(b)) * 3600, (im[key_dec] - b) * 3600) for im, (a, b) in zip(one, pos)]
        return {"median": round(float(np.median(d)), 3), "max": round(float(np.max(d)), 3)}
    st, mid = [im["mjd_start"] for im in one], [im["mjd"] for im in one]
    out = {"n": len(one), "object": "65 Cybele", "window": [t0, t1]}
    h_mid = horizons(command, mid)                     # one request serves both mid-exposure comparisons
    out["spherex_start"] = med(horizons(command, st))
    out["spherex_mid"] = med(h_mid)
    out["earth_start"] = med(horizons(command, st, "500@399"))
    out["ours_mid"] = med(h_mid, "ra", "dec")
    print("MOST vs Horizons:", out)
    return out


def validate(field_id="cybele", workers=3, radius_px=1.0):
    doc = read_json(FIELDS / field_id / "field.json")
    mj = [e["mjd"] for e in doc["exposures"]]
    from astropy.time import Time
    t0 = Time(min(mj) - 1, format="mjd").iso[:10]
    t1 = Time(max(mj) + 1, format="mjd").iso[:10]
    names = [b["name"] for b in doc["known_bodies"]]
    vby = {b["name"]: b.get("V") for b in doc["known_bodies"]}
    print(f"{field_id}: {len(doc['exposures'])} exposures {t0}..{t1}, {len(names)} known bodies")

    def one(name):
        for k in range(3):
            try:
                r = F.sbdb_resolve(query_name(name), CACHE)
                if r["status"] != "ok":
                    return name, None, f"sbdb {r['status']}"
                meta, ims = F.most_query(spkid=r["spkid"], t0=t0, t1=t1, cache_dir=CACHE, max_age_s=MOST_MAX_AGE_S)
                return name, ims, meta.get("object_name")
            except F.FollowError as e:
                if e.code != "most_down":
                    return name, None, e.code
                time.sleep(5 * (k + 1))
        return name, None, "most_down"
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, names))
    bodies, allrec = [], []
    for name, ims, info in res:
        if ims is None:
            bodies.append({"name": name, "V": vby.get(name), "error": info})
            continue
        rec = compare(doc, name, ims, radius_px)
        for r in rec:
            r["body"] = name
        allrec += rec
        inf = [r for r in rec if r["in_field"]]
        f = [r for r in inf if r.get("found")]
        offs = [math.hypot(r["dra"], r["ddec"]) for r in f]
        bodies.append({"name": name, "V": vby.get(name), "most_name": info, "n_most": len(ims), "n_inside": len(rec),
                       "n_used": len(inf), "n_found": len(f), "n_nn": sum(r["nn"] for r in f), "n_track": sum(r["track"] for r in f),
                       "n_labelled": sum(r.get("label") == name for r in f),
                       "V_most": round(float(np.median([r["V"] for r in inf if r["V"] is not None])), 2) if inf else None,
                       "med_off_arcsec": round(float(np.median(offs)), 2) if offs else None})
        if inf:
            print(f"  {name}: MOST {len(ims)} images, {len(inf)} in our exposures inside the field, found {len(f)}, "
                  f"NN {bodies[-1]['n_nn']}, track {bodies[-1]['n_track']}, median offset {bodies[-1]['med_off_arcsec']}")
    used = [r for r in allrec if r["in_field"]]
    # completeness against MOST's predicted V
    by_v = []
    for lo, hi in V_BINS:
        s = [r for r in used if r["V"] is not None and lo <= r["V"] < hi]
        if s:
            by_v.append({"lo": lo, "hi": hi, "n": len(s), "found": sum(bool(r.get("found")) for r in s),
                         "chance": round(sum(r.get("chance", 0) for r in s), 1),
                         "nn": sum(bool(r.get("nn")) for r in s), "track": sum(bool(r.get("track")) for r in s)})
    found = [r for r in used if r.get("found")]
    offs = np.array([math.hypot(r["dra"], r["ddec"]) for r in found]) if found else np.array([])
    cy = [b for b in bodies if b["name"].startswith("65 Cybele")]
    cyrec = [r for r in used if r["body"].startswith("65 Cybele")]
    # along / across the direction of motion for Cybele: does MOST give the position at the start of the exposure?
    timing = None
    tr0 = next((t for t in doc["tracks"] if (t.get("known") or "").startswith("65 Cybele")), None)
    if tr0 and cyrec:
        m = tr0["model"]
        vx, vy = m["dra_dt"] * math.cos(math.radians(m["dec0"])) * 3600, m["ddec_dt"] * 3600     # arcsec / day
        sp = math.hypot(vx, vy)
        ux, uy = vx / sp, vy / sp
        fr = [r for r in cyrec if r.get("found")]
        al0 = [r["dra0"] * ux + r["ddec0"] * uy for r in fr]
        al = [r["dra"] * ux + r["ddec"] * uy for r in fr]
        cr = [-r["dra"] * uy + r["ddec"] * ux for r in fr]
        if al:
            timing = {"rate_arcsec_h": round(sp / 24, 2), "along_start_med": round(float(np.median(al0)), 2),
                      "along_mid_med": round(float(np.median(al)), 2), "across_med": round(float(np.median(cr)), 2),
                      "dt_s": round(float(np.median(al0)) / (sp / 86400), 1), "half_exposure_s": HALF_EXPOSURE_S,
                      "off_start_med": round(float(np.median([math.hypot(r["dra0"], r["ddec0"]) for r in fr])), 2),
                      "off_mid_med": round(float(np.median([math.hypot(r["dra"], r["ddec"]) for r in fr])), 2)}
    jpl = (tr0 or {}).get("jpl")
    out = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "field": field_id, "field_created": doc.get("created"),
           "radius_arcsec": round(radius_px * F.PIX_ARCSEC, 1), "edge_arcsec": round(EDGE_PX * F.PIX_ARCSEC, 1),
           "window": [t0, t1], "n_bodies": len(names),
           "n_bodies_in_most": sum(1 for b in bodies if b.get("n_used")),
           "totals": {"inside": len(allrec), "used": len(used), "found": len(found),
                      "nn": sum(bool(r.get("nn")) for r in found), "track": sum(bool(r.get("track")) for r in found),
                      "chance_expected": round(sum(r.get("chance", 0) for r in used), 1)},
           "cybele": cy[0] if cy else None, "cybele_frames": cyrec, "cybele_timing": timing,
           "cybele_jpl": {"median_arcsec": jpl.get("median_arcsec"), "n": jpl.get("n")} if jpl else None,
           "by_v": by_v, "bodies": sorted((b for b in bodies if b.get("n_used")), key=lambda b: (b["V_most"] or 99)),
           "offsets": {"n": int(len(offs)), "median_arcsec": round(float(np.median(offs)), 2) if len(offs) else None,
                       "p90_arcsec": round(float(np.percentile(offs, 90)), 2) if len(offs) else None,
                       "points": [[r["dra"], r["ddec"], r["body"][:40], r["V"]] for r in found]},
           "errors": [b for b in bodies if b.get("error")]}
    try:
        out["most_check"] = most_check()
    except Exception as e:  # noqa: BLE001 - the rest of the validation stands without it
        print(f"MOST vs Horizons check failed: {e}")
    write_json(VALIDATION / "follow.json", out, indent=1)
    print(json.dumps({k: out[k] for k in ("totals", "by_v", "cybele", "cybele_timing", "cybele_jpl")}, indent=1))
    print(f"offsets: {out['offsets']['n']} median {out['offsets']['median_arcsec']}\" p90 {out['offsets']['p90_arcsec']}\"")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["showcases", "validate"])
    ap.add_argument("--only", nargs="*", help="showcases: only these notes (cybele, nea, comet)")
    a = ap.parse_args()
    if a.what == "showcases":
        showcases(a.only)
    else:
        validate()
