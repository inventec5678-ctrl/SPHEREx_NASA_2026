"""Streak (trail) search: fast near-Earth asteroids that leave a line inside one SPHEREx exposure.

Stages (each caches its slow remote results under cache/streak/ and can be re-run):

  neos    JPL close-approach list (CAD API) for the SPHEREx years -> IRSA MOST: which SPHEREx exposures caught each
          fly-by -> cache/streak/hits.json
  real    for every caught fly-by bright enough to matter: JPL Horizons geocentric vectors + the spacecraft position in
          the image header give the exact start/end of the trail; download the cutout and same-detector exposures of
          the same spot (reference), difference, run sxlib.streak -> cache/streak/real.json + web/data/streaks/neo/*.webp
  all     neos, then real

  python scripts/streak_search.py all          (SX_INSECURE=1 behind a TLS-intercepting proxy)

The stage names fields / synth / write are accepted for compatibility but have no step here (planned: the detector
on every analysed field, synthetic-streak completeness, and web/data/validation/streak.json).
"""
import argparse
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE as _CACHE_ROOT, DATA, VERIFY, read_json, read_text, write_json, write_text  # noqa: E402

CACHE = _CACHE_ROOT / "streak"
OUT = DATA / "streaks"
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-script)"}
CAD = "https://ssd-api.jpl.nasa.gov/cad.api"
MOST = "https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
AU_KM = 1.495978707e8
SURVEY = ("2025-04-20", "2026-11-01")          # SPHEREx science survey began 2025-05-01
RETRY_STATUS = (429, 500, 502, 503, 504)
HORIZONS_CHUNK = 40                            # times per Horizons TLIST request

if not VERIFY:
    requests.packages.urllib3.disable_warnings()
_S = requests.Session()
_S.headers.update(UA)


def _get(url, params=None, tries=4, timeout=180):
    for k in range(tries):
        try:
            r = _S.get(url, params=params, timeout=timeout, verify=VERIFY)
            if r.status_code in RETRY_STATUS:
                raise requests.HTTPError(str(r.status_code))
            r.raise_for_status()
            return r
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout):
            if k == tries - 1:
                raise
            time.sleep(2 + 3 * k)


# ------------------------------------------------------------------------------------------------ stage: neos
def close_approaches(dist_max=0.05, h_max=28.0):
    f = CACHE / "cad.json"
    if not f.exists():
        js = _get(CAD, {"date-min": SURVEY[0], "date-max": SURVEY[1], "dist-max": dist_max, "h-max": h_max,
                        "sort": "dist", "fullname": "true"}).json()
        write_json(f, js, indent=None)
    else:
        js = read_json(f)
    return [dict(zip(js["fields"], r)) for r in js["data"]]


def v_at_ca(r):
    """Rough V at closest approach: H + 5 log10(r * delta) + ~1.5 mag for the phase angle (r ~ 1 au)."""
    return float(r["h"]) + 5 * math.log10(float(r["dist"])) + 1.5


def window_days(r, v_lim=17.5):
    """Half-width (days) of the time around closest approach in which the asteroid is brighter than v_lim."""
    d_ca = float(r["dist"])
    d_max = min(d_ca * 10 ** ((v_lim - v_at_ca(r)) / 5), 0.12)
    if d_max <= d_ca:
        return 0.3
    t = math.sqrt(d_max ** 2 - d_ca ** 2) * AU_KM / max(float(r["v_rel"]), 1.0) / 86400
    return float(np.clip(t, 0.3, 6.0))


def parse_most(txt):
    """MOST 'Brief' output: IPAC table with a | header line of names, then fixed-width rows."""
    lines = txt.splitlines()
    hdr = [ln for ln in lines if ln.startswith("|")]
    if not hdr:
        return []
    names = [s.strip() for s in hdr[0].strip("|").split("|")]
    out = []
    for ln in lines:
        if not ln.strip() or ln.startswith("|") or ln.startswith("\\"):
            continue
        vals = ln.split()
        if len(vals) < len(names):          # start/end dates contain a space: re-join them
            continue
        # columns: dates are "YYYY-MM-DD HH:MM:SS.sss" -> two tokens each
        rec, k = {}, 0
        for nm in names:
            if nm in ("start_date", "end_date"):
                rec[nm] = vals[k] + " " + vals[k + 1]
                k += 2
            else:
                rec[nm] = vals[k]
                k += 1
        out.append(rec)
    return out


def most_query(name, d0, d1):
    safe = name.replace(" ", "_").replace("/", "_")
    f = CACHE / "most" / f"{safe}_{d0}_{d1}.txt"
    if not f.exists():
        url = (f"{MOST}?catalog=spherex&input_type=name_input&obj_name={quote(name)}"
               f"&obs_begin={d0}&obs_end={d1}&output_mode=Brief")
        write_text(f, _get(url, timeout=300).text)
    return parse_most(read_text(f))


def stage_neos(v_cut=18.0, workers=4):
    from astropy.time import Time
    rows = close_approaches()
    sel = [r for r in rows if v_at_ca(r) <= v_cut]
    print(f"{len(rows)} close approaches <= 0.05 au; {len(sel)} with V(CA) <= {v_cut}")

    def one(r):
        jd = float(r["jd"])
        w = window_days(r)
        d0 = Time(jd - w, format="jd").iso[:10]
        d1 = Time(jd + w + 1, format="jd").iso[:10]
        try:
            hits = most_query(r["des"], d0, d1)
        except Exception as e:  # noqa: BLE001
            return r, None, str(e)
        return r, hits, None

    out = []
    with ThreadPoolExecutor(workers) as ex:
        for k, (r, hits, err) in enumerate(ex.map(one, sel)):
            if err:
                print("  MOST failed", r["des"], err)
                continue
            if hits:
                out.append({"des": r["des"], "fullname": r["fullname"].strip(), "cd": r["cd"], "jd_ca": float(r["jd"]),
                            "dist_ca_au": float(r["dist"]), "v_rel": float(r["v_rel"]), "h": float(r["h"]),
                            "v_ca_est": round(v_at_ca(r), 2), "hits": hits})
                print(f"  {r['des']:>12s} CA {r['cd']} {float(r['dist']):.4f} au: {len(hits)} exposures")
            if k % 50 == 0:
                print(f"  ... {k}/{len(sel)}")
    write_json(CACHE / "hits.json", out, indent=1)
    print(f"{len(out)} fly-bys with SPHEREx exposures -> {CACHE / 'hits.json'}")
    return out


# ------------------------------------------------------------------------------------------------ stage: real
def horizons(des, jds):
    """Astrometric RA/Dec (deg), rates ("/h), V and distance (au) of `des` seen FROM SPHEREx at each JD (UTC).
    Horizons returns a TLIST in time order, so the times are sorted and de-duplicated here and mapped back."""
    want = list(jds)
    jds = sorted({round(float(t), 7) for t in want})
    from sxlib.known import SPHEREX_HORIZONS
    cmd = f"'{des};'" if des.strip().isdigit() else f"'DES={des.strip()};'"     # '2025 FA22' is not asteroid 2025
    key = f"{des.replace(' ', '_')}_{len(jds)}_{min(jds):.5f}_{max(jds):.5f}"
    f = CACHE / "horizons" / f"{key}.json"
    if f.exists():
        return _by_time(read_json(f), want)
    out = []
    for k in range(0, len(jds), HORIZONS_CHUNK):
        chunk = jds[k:k + HORIZONS_CHUNK]
        q = {"format": "json", "COMMAND": cmd, "EPHEM_TYPE": "OBSERVER",
             "CENTER": f"'500@{SPHEREX_HORIZONS}'", "TLIST_TYPE": "JD", "TIME_TYPE": "UT", "QUANTITIES": "'1,3,9,20'",
             "ANG_FORMAT": "DEG", "EXTRA_PREC": "YES", "CSV_FORMAT": "YES", "OBJ_DATA": "NO",
             "TLIST": "'" + " ".join(f"{t:.7f}" for t in chunk) + "'"}
        res = _get(HORIZONS, q, timeout=180).json()["result"]
        rows = res[res.index("$$SOE") + 5:res.index("$$EOE")].strip().splitlines()
        for row in rows:
            p_ = [x.strip() for x in row.split(",")]
            # date, (blank), (blank), RA, DEC, dRA*cosD, dDEC, APmag, S-brt, delta, deldot
            out.append({"ra": float(p_[3]), "dec": float(p_[4]), "dra": float(p_[5]), "ddec": float(p_[6]),
                        "V": _num(p_[7]), "delta": float(p_[9])})
    if len(out) != len(jds):
        raise RuntimeError(f"Horizons returned {len(out)} rows for {len(jds)} times")
    for t, o in zip(jds, out):
        o["jd"] = t
    write_json(f, out, indent=None)
    return _by_time(out, want)


def _by_time(rows, want):
    """The row nearest in time to each wanted JD (one vectorised nearest-neighbour lookup)."""
    tt = np.array([r["jd"] for r in rows])
    idx = np.argmin(np.abs(tt[None, :] - np.asarray(want, float)[:, None]), axis=1)
    return [rows[int(i)] for i in idx]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _jd(iso):
    from astropy.time import Time
    return float(Time(iso.replace(" ", "T"), scale="utc").jd)


def plan_groups(v_cut):
    """Fly-by exposures brighter than v_cut, grouped by (asteroid, observation sequence): the 2-4 exposures of a
    sequence look at nearly the same sky with nearly the same wavelengths, so they are each other's references."""
    hits = read_json(CACHE / "hits.json")
    groups = {}
    for o in hits:
        for h in o["hits"]:
            if float(h["vmag"]) > v_cut:
                continue
            seq = h["observationid"].rsplit("_", 1)[0]
            g = groups.setdefault((o["des"], seq), {"des": o["des"], "seq": seq, "obj": {k: v for k, v in o.items() if k != "hits"},
                                                    "hits": []})
            g["hits"].append({"obs_id": h["observationid"], "detector": int(h["productid"][1:]),
                              "url": "https://irsa.ipac.caltech.edu/" + h["uri"], "vmag": float(h["vmag"]),
                              "jd0": _jd(h["start_date"]), "jd1": _jd(h["end_date"]),
                              "geo_dist": float(h["geo_dist"]), "phase": float(h["phase"])})
    return sorted(groups.values(), key=lambda g: min(h["vmag"] for h in g["hits"]))


def _seg_px(f, pos0, pos1):
    x0, y0 = f.world_to_pix(pos0["ra"], pos0["dec"])
    x1, y1 = f.world_to_pix(pos1["ra"], pos1["dec"])
    return float(x0), float(y0), float(x1), float(y1)


def forced_snr(snr, valid, xc, yc, L, theta, rng, n_rand=300):
    """Matched-filter S/N of a trail of known geometry, calibrated on the same kernel at random places."""
    from sxlib import streak as S
    k = S.line_kernel(max(L, 1.0), theta)
    hy, hx = k.shape[0] // 2, k.shape[1] // 2
    z = np.where(valid, np.nan_to_num(snr), 0.0)
    ny, nx = z.shape

    def at(x, y):
        ix, iy = int(round(x)), int(round(y))
        if iy - hy < 0 or ix - hx < 0 or iy + hy + 1 > ny or ix + hx + 1 > nx:
            return np.nan, 0.0
        w = valid[iy - hy:iy + hy + 1, ix - hx:ix + hx + 1]
        kk = k * w
        n2 = (kk * kk).sum()
        return float((kk * z[iy - hy:iy + hy + 1, ix - hx:ix + hx + 1]).sum() / np.sqrt(max(n2, 1e-9))), float(n2)

    val, cov = at(xc, yc)
    rs = []
    for _ in range(n_rand):
        x, y = rng.uniform(hx, nx - hx - 1), rng.uniform(hy, ny - hy - 1)
        if np.hypot(x - xc, y - yc) < L / 2 + 6:
            continue
        v, c = at(x, y)
        if np.isfinite(v) and c > 0.6:
            rs.append(v)
    if len(rs) < 30:
        return val, cov, np.nan
    rs = np.array(rs)
    sd = 1.4826 * np.median(np.abs(rs - np.median(rs)))
    return val / sd if sd > 0 else np.nan, cov, sd


def _stretch8(a, scale):
    return np.clip(np.arcsinh(np.nan_to_num(a) / scale) / np.arcsinh(40) * 127 + 128, 0, 255).astype(np.uint8)


def _save_webp(arr8, path):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr8[::-1]).save(path, format="WEBP", lossless=True)


def run_group(g, workers=8, download=True, log=print, debug_dir=None):
    from astropy.time import Time

    from sxlib import archive
    from sxlib import streak as S
    from sxlib.stack import FEAT_GHOST, Field
    hits = g["hits"]
    # JPL positions from SPHEREx at start / middle / end of every hit exposure
    jds = []
    for h in hits:
        jds += [h["jd0"], 0.5 * (h["jd0"] + h["jd1"]), h["jd1"]]
    eph = horizons(g["des"], jds)
    for k, h in enumerate(hits):
        h["eph"] = eph[3 * k:3 * k + 3]
    ras = np.array([e["ra"] for h in hits for e in h["eph"]])
    decs = np.array([e["dec"] for h in hits for e in h["eph"]])
    ra_c = float(np.degrees(np.arctan2(np.sin(np.radians(ras)).mean(), np.cos(np.radians(ras)).mean())) % 360)
    dec_c = float(decs.mean())
    ext = max(np.ptp(((ras - ra_c + 180) % 360 - 180) * np.cos(np.radians(dec_c))), np.ptp(decs))
    size = float(np.clip(ext + 0.14, 0.18, 0.7))
    # every exposure of the sequence that covers the spot (the hits and their neighbours)
    mjd0 = min(h["jd0"] for h in hits) - 2400000.5
    mjd1 = max(h["jd1"] for h in hits) - 2400000.5
    try:
        metas = archive.search_images(ra_c, dec_c, radius=0.0, mjd_range=(mjd0 - 0.012, mjd1 + 0.012))
    except Exception as e:  # noqa: BLE001
        log(f"  SIA failed: {e}")
        metas = []
    dets = {h["detector"] for h in hits}
    metas = [m for m in metas if m["detector"] in dets]
    have = {(m["obs_id"], m["detector"]) for m in metas}
    for h in hits:                                         # MOST's own URL if SIA missed it
        if (h["obs_id"], h["detector"]) not in have:
            metas.append({"url": h["url"], "obs_id": h["obs_id"], "band": f"D{h['detector']}", "detector": h["detector"],
                          "mjd": 0.5 * (h["jd0"] + h["jd1"]) - 2400000.5})
    if not download:
        return {"n_cutouts": len(metas)}
    def one(m):
        try:
            return archive.fetch_cutout(m, ra_c, dec_c, size, keep_psf=False, cache=CACHE)
        except Exception as e:  # noqa: BLE001
            log(f"  cutout failed {m['obs_id']} D{m['detector']}: {e}")
            return None
    with ThreadPoolExecutor(workers) as ex:
        exps = [e for e in ex.map(one, metas) if e is not None]
    f = Field(ra_c, dec_c, size)
    hdr_of, trailbits = {}, []
    for e in exps:
        cl = S.add_relaxed(f, e)              # SPHEREx flags fast trails TRANSIENT/SUR_ERROR/HALO: keep those pixels
        if cl is not None:
            hdr_of[(e.meta["obs_id"], e.detector)] = e.header
            trailbits.append((e.meta["mjd"], cl))
    if not f.exps:
        return {"des": g["des"], "seq": g["seq"], "error": "no usable cutouts", "results": []}
    f.freeze()
    trailbits = [cl for _, cl in sorted(trailbits, key=lambda t: t[0])]     # freeze() sorts by time
    idx = {(e["obs_id"], e["detector"]): i for i, e in enumerate(f.exps)}
    rng = np.random.default_rng(0)
    results = []
    for h in hits:
        i = idx.get((h["obs_id"], h["detector"]))
        rec = {"obs_id": h["obs_id"], "detector": h["detector"], "vmag_most": h["vmag"], "jd0": h["jd0"], "jd1": h["jd1"],
               "V": h["eph"][1]["V"], "delta_au": h["eph"][1]["delta"],
               "rate_arcsec_h": round(float(np.hypot(h["eph"][1]["dra"], h["eph"][1]["ddec"])), 1)}
        if i is None:
            rec["status"] = "no_cutout"
            results.append(rec)
            continue
        hdr = hdr_of.get((h["obs_id"], h["detector"]))
        xpos = float(hdr.get("XPOSURE", S.EXPTIME_S)) if hdr is not None else S.EXPTIME_S
        rec["xposure_s"] = xpos
        rec["lam_um"] = round(f.exps[i]["lam_um"], 3)
        x0, y0, x1, y1 = _seg_px(f, h["eph"][0], h["eph"][2])
        xm, ym = (float(v) for v in f.world_to_pix(h["eph"][1]["ra"], h["eph"][1]["dec"]))
        # the trail runs from DATE-BEG to DATE-END (MOST start/end, 115.1 s; measured on 2025 FA22's pixels)
        dx, dy = (x1 - x0), (y1 - y0)
        Lp = float(np.hypot(dx, dy))
        thp = float(np.arctan2(dy, dx) % np.pi)
        rec["pred"] = {"xc": round(float(xm), 2), "yc": round(float(ym), 2), "length": round(Lp, 2),
                       "angle_deg": round(float(np.degrees(thp)), 2),
                       "x0": round(float(xm - dx / 2), 2), "y0": round(float(ym - dy / 2), 2),
                       "x1": round(float(xm + dx / 2), 2), "y1": round(float(ym + dy / 2), 2)}
        d = f.difference(i, lam_tol=0.03, eps=0.1, min_dt_h=0.01)
        rec["nref"] = int(np.median(d["nref"][d["valid"]])) if d["valid"].any() else 0
        with np.errstate(all="ignore"):
            ref_snr = d["ref"] / np.sqrt(d["var_ref"])
        mask = S.veto_mask(f.shape, bad=~d["valid"], ghost=(f.feat[i] & FEAT_GHOST) != 0, ref_snr=ref_snr)
        valid = d["valid"] & ~mask
        # share of the predicted trail's pixels that SPHEREx flagged TRANSIENT/SUR_ERROR/HALO
        tt = np.linspace(-0.5, 0.5, max(int(Lp * 2), 3))
        px = np.clip(np.round(xm + tt * dx).astype(int), 0, f.shape[1] - 1)
        py = np.clip(np.round(ym + tt * dy).astype(int), 0, f.shape[0] - 1)
        rec["trail_flagged"] = round(float(trailbits[i][py, px].mean()), 3)
        on = (0 <= xm < f.shape[1]) and (0 <= ym < f.shape[0])
        rec["on_valid"] = bool(on and valid[int(ym), int(xm)])
        fs, cov, _ = forced_snr(d["snr"], valid, float(xm), float(ym), Lp, thp, rng)
        rec["forced_snr"] = round(float(fs), 2) if np.isfinite(fs) else None
        rec["forced_cov"] = round(cov, 2)
        dets_ = S.detect(d["snr"], d["diff"], mask)
        tol = max(4.0, 0.25 * Lp)
        best = None
        for dt in dets_:
            off = np.hypot(dt["xc"] - xm, dt["yc"] - ym)
            da = abs((dt["angle_deg"] - np.degrees(thp) + 90) % 180 - 90)
            if off <= tol and (Lp < 4 or da <= 20):
                if best is None or dt["snr"] > best["snr"]:
                    best = dict(dt, offset_px=round(float(off), 2), dangle_deg=round(float(da), 2))
        rec["detected"] = best is not None
        rec["det"] = best
        rec["other"] = [dt for dt in dets_ if best is None or dt is not best and
                        not (dt["xc"] == best["xc"] and dt["yc"] == best["yc"])]
        if best is not None:
            # the same trail fitted with a uniform brightness profile (instead of the on-board slope fit's)
            noise_map = np.abs(d["diff"] / d["snr"])
            noise_map = np.where(np.isfinite(noise_map) & (np.abs(d["snr"]) > 0.3), noise_map, np.nanmedian(noise_map))
            ff = S.fit_trail(d["diff"], noise_map, valid, best["xc"], best["yc"], best["length"],
                             np.radians(best["angle_deg"]), profile="flat")
            if ff:
                rec["det"]["length_flat"] = round(ff["length"], 2)
                rec["det"]["chi2_flat_minus_sur"] = round(ff["chi2"] - S.fit_trail(
                    d["diff"], noise_map, valid, best["xc"], best["yc"], best["length"], np.radians(best["angle_deg"]),
                    profile="sur")["chi2"], 1)
            rec["det"]["ab"] = round(float(S.ujy_to_ab(S.flux_ujy(best["flux"]))), 2) if best["flux"] > 0 else None
        # display crops: science, reference and difference around the predicted trail
        half = int(max(14, Lp / 2 + 10))
        cx, cy = int(round(xm)), int(round(ym))
        ylo, yhi = max(0, cy - half), min(f.shape[0], cy + half + 1)
        xlo, xhi = max(0, cx - half), min(f.shape[1], cx + half + 1)
        rec["crop"] = [xlo, ylo, xhi - xlo, yhi - ylo]
        noise = float(np.nanmedian(np.sqrt(f.var[i])))
        slug = f"{g['des'].replace(' ', '')}_{h['obs_id']}_D{h['detector']}"
        rec["slug"] = slug
        sl = (slice(ylo, yhi), slice(xlo, xhi))
        out = OUT / "neo"
        _save_webp(_stretch8(f.img[i][sl], 2 * noise), out / f"{slug}_sci.webp")
        _save_webp(_stretch8(d["ref"][sl], 2 * noise), out / f"{slug}_ref.webp")
        _save_webp(np.clip(128 + 16 * np.nan_to_num(d["snr"][sl]), 0, 255).astype(np.uint8), out / f"{slug}_diff.webp")
        _save_webp((trailbits[i][sl] * 255).astype(np.uint8), out / f"{slug}_flag.webp")
        rec["iso"] = Time(h["jd0"], format="jd").iso[:19]
        if debug_dir:
            _debug_png(d, dets_, rec, Path(debug_dir) / f"{slug}.png")
        results.append(rec)
        log(f"  {g['des']} {h['obs_id']} D{h['detector']} V={rec['V']} L={Lp:.1f}px nref={rec['nref']} "
            f"forced S/N={rec['forced_snr']} det={'yes' if best else 'no'}"
            + (f" L={best['length']:.1f} ang={best['angle_deg']:.1f} vs {np.degrees(thp):.1f}" if best else ""))
    return {"des": g["des"], "seq": g["seq"], "obj": g["obj"], "center": [ra_c, dec_c], "size_deg": size,
            "n_cutouts": len(f.exps), "shape": list(f.shape), "results": results}


def _debug_png(d, dets, rec, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 1, figsize=(9, 9))
    ax.imshow(np.clip(np.nan_to_num(d["snr"]), -5, 8), origin="lower", cmap="gray")
    p = rec["pred"]
    ax.plot([p["x0"], p["x1"]], [p["y0"], p["y1"]], "c-", lw=3, alpha=0.4)
    for dt in dets:
        ax.plot([dt["x0"], dt["x1"]], [dt["y0"], dt["y1"]], "r-", lw=1)
        ax.text(dt["x1"], dt["y1"], f"{dt['snr']:.0f}", color="y", fontsize=8)
    ax.set_title(f"{rec['obs_id']} D{rec['detector']} nref={rec['nref']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path.with_suffix(".npz"), diff=d["diff"], snr=d["snr"], valid=d["valid"])
    fig.savefig(path, dpi=70)
    plt.close(fig)


def stage_real(v_cut=17.0, only=None, workers=8, plan_only=False):
    groups = plan_groups(v_cut)
    if only:
        groups = [g for g in groups if g["des"] in only]
    print(f"{len(groups)} (asteroid, sequence) groups with V <= {v_cut}")
    out = []
    f_res = CACHE / "real.json"
    prev = {(r["des"], r["seq"]): r for r in read_json(f_res, [])}
    for k, g in enumerate(groups):
        if plan_only:
            print(g["des"], g["seq"], len(g["hits"]), run_group(g, download=False))
            continue
        print(f"[{k + 1}/{len(groups)}] {g['des']} {g['seq']} ({len(g['hits'])} hit exposures)")
        try:
            r = run_group(g, workers=workers, debug_dir=os.environ.get("STREAK_DEBUG"))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            r = {"des": g["des"], "seq": g["seq"], "error": str(e)[:300], "results": []}
        prev[(g["des"], g["seq"])] = r
        write_json(f_res, list(prev.values()), indent=None, default=float)
    return list(prev.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["neos", "real", "fields", "synth", "write", "all"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--vcut", type=float, default=17.0)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    if a.stage in ("neos", "all"):
        stage_neos(workers=a.workers)
    if a.stage in ("real", "all"):
        stage_real(a.vcut, a.only, plan_only=a.plan)
    if a.stage in ("fields", "synth", "write"):
        print(f"stage '{a.stage}' has no step in this script (see the module docstring)")


if __name__ == "__main__":
    main()
