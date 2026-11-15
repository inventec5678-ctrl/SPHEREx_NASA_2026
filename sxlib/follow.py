"""Follow one asteroid or comet through every SPHEREx image that caught it.

  1. JPL's Small-Body Database turns what the visitor typed ("Cybele", "C/2025 A6", "29P") into one object and its
     JPL SPK-ID (or a list to choose from when the name is ambiguous).
  2. IRSA's Moving Object Search Tool (MOST, catalog=spherex) lists every SPHEREx image whose footprint contained the
     object's predicted position, with that position, its distances from the Sun and the observer, phase angle and
     predicted V. MOST has no documented API: the call below was worked out from its web form (2026-11-13); the
     "Brief" output is an IPAC table whose `uri` column is the image's path on IRSA (the same file SIA returns).
  3. A cutout of each image (IRSA's cutout service, sxlib.archive.fetch_cutout) centred on the predicted position:
       - resampled north-up onto a small grid centred on the object -> one movie frame (the object stays in the
         middle while the background stars stream past);
       - forced aperture photometry in the native frame at the predicted position, and the wavelength of the pixel
         it falls on (each SPHEREx image samples a different wavelength there, so the frames together are a spectrum).
  4. A light curve: the brightness left after removing the distance change and the spectrum (a running median over
     wavelength), against time; and the strongest repeat in it (Lomb-Scargle), reported only when it is significant.

Run as a job:  python -m sxlib.follow <slug> <spkid> <name> [t0 t1]   (web/api_follow.py starts it)
"""
import bisect
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MOST_URL = "https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most"
SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
IRSA = "https://irsa.ipac.caltech.edu/"
MISSION_START = "2025-04-24"          # first SPHEREx survey images
UA = {"User-Agent": "spherex-sky-change/1.0 (asteroid follow)"}
CAP = 150                             # images per object (sampled evenly in time beyond this)
CUT_DEG = 0.12                        # cutout side: a 49-pixel north-up frame fits inside it at any roll angle
NPIX = 49                             # movie frame side, SPHEREx pixels (6.15" each: about 5')
PIX_ARCSEC = 6.15
FOLLOW_VERSION = 1

# SPHEREx FLAGS bits that matter for a point measurement (sxlib/archive.py FLAG_NAMES)
BIT_OVERFLOW, BIT_SOURCE, BIT_PERSIST = 1 << 1, 1 << 21, 1 << 17
RETRY_STATUS = (429, 500, 502, 503, 504)
MIN_COVER = 0.3                       # a movie frame must cover at least this share of its grid
CENTROID_SNR = 15                     # the light centroid is measured above this S/N
LC_MIN_FRAMES, LC_MIN_PERIODIC, LC_MIN_SPAN_H = 12, 20, 6
PERIOD_MIN_H, PERIOD_MAX_H = 2.0, 48.0
FAP_LIMIT = 0.01
MJD0 = _dt.datetime(1858, 11, 17)     # MJD 0, UTC


class FollowError(Exception):
    """code: 'unknown' (no such object), 'ambiguous' (choices holds the candidates), 'no_images', 'most_down'."""

    def __init__(self, code, choices=None, detail=""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code, self.choices = code, choices or []


# ---- small helpers --------------------------------------------------------------------------------------------
_local = threading.local()


def _session():
    """A keep-alive session per thread (the job fetches from a thread pool)."""
    s = getattr(_local, "session", None)
    if s is None:
        import requests
        s = _local.session = requests.Session()
        s.headers.update(UA)
    return s


def _verify():
    return os.environ.get("SX_INSECURE") != "1"


def _get(url, params, timeout=120, tries=3):
    import requests
    verify = _verify()
    if not verify:
        requests.packages.urllib3.disable_warnings()
    last = None
    for k in range(tries):
        try:
            r = _session().get(url, params=params, timeout=timeout, verify=verify)
            if r.status_code in RETRY_STATUS:
                raise requests.HTTPError(str(r.status_code))
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise FollowError("most_down", detail=str(last))


def slugify(name, t0=None, t1=None):
    """'65 Cybele (A861 EB)' -> '65-cybele-a861-eb'; a date window is appended ('..._2025-12-01_2025-12-31')."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "object"
    if t0 or t1:
        s += f"_{t0 or 'start'}_{t1 or 'now'}"
    return s


def short_name(fullname):
    """'65 Cybele (A861 EB)' -> '65 Cybele'; 'C/2025 A6 (Lemmon)' stays; '(2024 YR4)' -> '2024 YR4'."""
    m = re.match(r"^(\d+ [^(]+?)\s*\(", fullname)
    if m:
        return m.group(1)
    if fullname.startswith("(") and fullname.endswith(")"):
        return fullname[1:-1]
    return fullname


def kind_of(sbdb_kind):
    """SBDB object kind ('an', 'au', 'cn', 'cu') -> 'asteroid' / 'comet'."""
    return "comet" if str(sbdb_kind or "").startswith("c") else "asteroid"


# ---- JPL Small-Body Database ------------------------------------------------------------------------------------
def parse_sbdb(js):
    """SBDB JSON -> {'status': 'ok', name, spkid, kind, cls} | {'status': 'ambiguous', choices} | {'status': 'unknown'}."""
    if js.get("list"):
        return {"status": "ambiguous", "choices": [x.get("name") or x.get("pdes") for x in js["list"]][:20]}
    o = js.get("object")
    if not o or not o.get("spkid"):
        return {"status": "unknown"}
    return {"status": "ok", "name": o.get("fullname", "").strip(), "short": short_name(o.get("fullname", "").strip()),
            "spkid": str(o["spkid"]), "kind": kind_of(o.get("kind")), "cls": (o.get("orbit_class") or {}).get("name")}


def sbdb_query(q):
    """SBDB refuses parentheses: '65 Cybele (A861 EB)' -> '65 Cybele', 'C/2025 A6 (Lemmon)' -> 'C/2025 A6',
    'Lemmon (C/2025 A6)' -> 'C/2025 A6', '(2024 YR4)' -> '2024 YR4', '366162 (2012 FU25)' -> '366162'."""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", q)
    if not m:
        return q
    out, ins = m.group(1).strip(), m.group(2).strip()
    if not out:
        return ins
    if re.match(r"^(\d+\b|[CPDXIA]/|\d+[PICD](/|\b))", out):
        return out
    return ins or out


def sbdb_resolve(q, cache_dir=None, max_age_s=7 * 86400):
    q = " ".join(str(q).split())
    f = None
    if cache_dir:
        f = Path(cache_dir) / "sbdb" / (hashlib.sha1(q.lower().encode()).hexdigest()[:20] + ".json")
        if f.exists() and time.time() - f.stat().st_mtime < max_age_s:
            return json.loads(f.read_text())
    r = _get(SBDB_URL, {"sstr": sbdb_query(q)}, timeout=30)
    if r.status_code >= 500:
        raise FollowError("most_down", detail=f"sbdb {r.status_code}")
    try:
        out = parse_sbdb(r.json())
    except ValueError:
        out = {"status": "unknown"}
    if f:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out))
    return out


PHYS_KEYS = {"diameter": "diam_km", "rot_per": "rot_h", "albedo": "albedo", "spec_T": "tholen", "spec_B": "smass",
             "extent": "extent_km", "H": "H", "M1": "M1"}


def parse_phys(js):
    """SBDB phys_par -> {diam_km, rot_h, albedo, tholen, smass, extent_km, H, M1, rot_ref} (whatever JPL lists)."""
    out = {}
    for p in js.get("phys_par") or []:
        k = PHYS_KEYS.get(p.get("name"))
        if not k or p.get("value") in (None, ""):
            continue
        v = p["value"]
        if k not in ("tholen", "smass", "extent_km"):
            v = _f(v)
            if v is None:
                continue
        out[k] = v
        if k == "rot_h" and p.get("ref"):
            out["rot_ref"] = str(p["ref"])[:80]
    return out


def sbdb_phys(spkid, cache_dir=None, max_age_s=30 * 86400):
    """Size, spin period, albedo and spectral type that JPL's Small-Body Database lists for one object ({} if none)."""
    f = Path(cache_dir) / "sbdb" / f"phys_{spkid}.json" if cache_dir else None
    if f and f.exists() and time.time() - f.stat().st_mtime < max_age_s:
        return json.loads(f.read_text())
    try:
        r = _get(SBDB_URL, {"spk": str(spkid), "phys-par": "1"}, timeout=30, tries=2)
        out = parse_phys(r.json()) if r.status_code == 200 else {}
    except (FollowError, ValueError):
        return {}
    if f:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out))
    return out


# ---- IRSA MOST ---------------------------------------------------------------------------------------------------
def parse_ipac(text):
    """IPAC table text -> (keywords {name: value}, rows [dict]). Columns are cut at the '|' positions of the header."""
    meta, rows, bars = {}, [], None
    names = None
    for line in text.splitlines():
        if line.startswith("\\"):
            m = re.match(r"^\\\s*(\w+)\s*=\s*(.*)$", line)
            if m:
                meta[m.group(1)] = m.group(2).strip().strip('"').strip()
            continue
        if line.startswith("|"):
            if names is None:
                bars = [i for i, ch in enumerate(line) if ch == "|"]
                names = [line[a + 1:b].strip() for a, b in zip(bars[:-1], bars[1:])]
            continue
        if names is None or not line.strip():
            continue
        vals = [line[a + 1:b + 1].strip() for a, b in zip(bars[:-1], bars[1:])]
        vals[-1] = line[bars[-2] + 1:].strip()                 # the last column (the image path) may overrun
        rows.append(dict(zip(names, vals)))
    return meta, rows


def parse_most_error(text):
    """MOST's 400 page -> FollowError. 'Multiple matches' lists the candidates (name, type, NAIF ID)."""
    if "Multiple matches" in text:
        ch = []
        for m in re.finditer(r"^\s*(.+?), Object Type=([^,]+), NAIF ID=(\d+)", text, re.M):
            ch.append({"name": m.group(1).strip(), "type": m.group(2).strip(), "naif": m.group(3)})
        return FollowError("ambiguous", [c["name"] for c in ch])
    if "lookup failed" in text or "Object Name Error" in text:
        return FollowError("unknown")
    return FollowError("most_down", detail=" ".join(text.split())[:200])


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def most_images(rows):
    """MOST rows -> one dict per (exposure, detector), time ordered, with the cutout metadata fetch_cutout needs.

    MOST's position is JPL Horizons' position seen from SPHEREx at the START of the exposure (checked against Horizons
    for 65 Cybele, 2025-12: 0.001" median; at mid-exposure it is 0.48" off). Images record the object around the
    middle of their ~2-minute exposure, so `ra`/`dec` here are moved to mid-exposure along the motion that MOST's own
    positions of neighbouring exposures show; MOST's values are kept as `ra0`/`dec0`."""
    out = {}
    for r in rows:
        uri = r.get("uri", "")
        if not uri or "spherex" not in uri:
            continue
        det = re.search(r"D(\d)", r.get("productid", "") or "") or re.search(r"\dD(\d)_spx", uri)
        if not det:
            continue
        rel = re.search(r"/spherex/([a-z]+\d*)/", uri)
        mj0, mj1 = _f(r.get("mjd_start")), _f(r.get("mjd_end"))
        if mj0 is None or mj1 is None:
            continue
        key = (r.get("observationid"), int(det.group(1)))
        ra, dec = _f(r.get("ra_obj")), _f(r.get("dec_obj"))
        out[key] = {"url": IRSA + uri.lstrip("/"), "obs_id": r.get("observationid"), "detector": int(det.group(1)),
                    "band": f"SPHEREx-D{det.group(1)}", "mjd": 0.5 * (mj0 + mj1), "mjd_start": mj0, "release": rel.group(1) if rel else "",
                    "ra": ra, "dec": dec, "ra0": ra, "dec0": dec, "vmag": _f(r.get("vmag")),
                    "r_au": _f(r.get("sun_dist")), "d_au": _f(r.get("geo_dist")), "phase": _f(r.get("phase")), "pos": "start"}
    ims = sorted((v for v in out.values() if v["ra"] is not None and v["dec"] is not None), key=lambda v: v["mjd"])
    to_mid(ims)
    return ims


def to_mid(ims, near_d=0.25, far_d=3.0):
    """Move each start-of-exposure position to mid-exposure with the sky motion between it and the nearest other
    exposure (within near_d days if possible, else far_d). Sets pos='mid' and rate_arcsec_h."""
    starts = {}
    for im in ims:
        starts.setdefault(im["obs_id"], (im["mjd_start"], im["ra0"], im["dec0"]))
    pts = sorted(starts.values())
    t = np.array([p[0] for p in pts])
    for im in ims:
        if len(pts) < 2:
            break
        k = int(np.searchsorted(t, im["mjd_start"]))
        k = min(max(k, 0), len(pts) - 1)
        cands = [j for j in (k - 1, k, k + 1) if 0 <= j < len(pts) and abs(t[j] - im["mjd_start"]) > 1e-6]
        if not cands:
            continue
        j = min(cands, key=lambda j: abs(t[j] - im["mjd_start"]))
        dt = t[j] - im["mjd_start"]
        if abs(dt) > far_d:
            continue
        cd = math.cos(math.radians(im["dec0"]))
        dra = ((pts[j][1] - im["ra0"] + 180) % 360 - 180) * cd / dt          # deg (on the sky) per day
        ddec = (pts[j][2] - im["dec0"]) / dt
        h = im["mjd"] - im["mjd_start"]
        im["ra"] = (im["ra0"] + dra * h / cd) % 360
        im["dec"] = im["dec0"] + ddec * h
        im["pos"] = "mid" if abs(dt) <= near_d else "mid~"
        im["rate_arcsec_h"] = round(math.hypot(dra, ddec) * 3600 / 24, 2)


def most_query(spkid=None, name=None, t0=None, t1=None, cache_dir=None, max_age_s=86400):
    """Every SPHEREx image MOST says contains the object. Returns (keywords, images). Cached for a day."""
    t0 = t0 or MISSION_START
    t1 = t1 or time.strftime("%Y-%m-%d", time.gmtime())
    p = {"catalog": "spherex", "output_mode": "Brief", "obs_begin": t0, "obs_end": t1}
    if spkid:
        p.update(input_type="naifid_input", obj_naifid=str(spkid))
    else:
        p.update(input_type="name_input", obj_name=name)
    f = None
    if cache_dir:
        key = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:20]
        f = Path(cache_dir) / "most" / f"{key}.txt"
        if f.exists() and time.time() - f.stat().st_mtime < max_age_s:
            meta, rows = parse_ipac(f.read_text())
            return meta, most_images(rows)
    # MOST asks JPL Horizons for the orbit on every call; that hand-off fails now and then ("Error connecting to
    # HORIZONS"), so a server-side failure is retried a few times before giving up
    for k in range(4):
        r = _get(MOST_URL, p, timeout=240)
        err = None
        if r.status_code == 400:
            err = parse_most_error(r.text)
        elif r.status_code != 200:
            err = FollowError("most_down", detail=str(r.status_code))
        else:
            meta, rows = parse_ipac(r.text)
            if "object_name" not in meta and not rows:
                err = parse_most_error(r.text)
        if err is None:
            break
        if err.code != "most_down" or k == 3:
            raise err
        time.sleep(3 * (k + 1))
    if f:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text)
    return meta, most_images(rows)


def sample(images, cap=CAP):
    """At most `cap` images, evenly spread in time. Both detectors of one exposure (they see the same sky at two
    wavelengths at the same moment) are kept or dropped together."""
    groups = {}
    for im in images:
        groups.setdefault(im["obs_id"], []).append(im)
    order = sorted(groups.values(), key=lambda g: g[0]["mjd"])
    total = sum(len(g) for g in order)
    if total <= cap:
        return [im for g in order for im in g]
    per = total / len(order)
    k = max(1, int(cap // per))
    idx = np.unique(np.round(np.linspace(0, len(order) - 1, k)).astype(int))
    out = [im for j in idx for im in order[j]]
    return out[:cap] if len(out) > cap + 2 else out


# ---- measurements on one cutout ---------------------------------------------------------------------------------
def frame_wcs(ra, dec, n=NPIX):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIX_ARCSEC / 3600, PIX_ARCSEC / 3600]
    return w


def render(exp, ra, dec, n=NPIX):
    """The cutout resampled north-up (east left) onto an n x n grid centred on (ra, dec): float image (MJy/sr, NaN
    where there are no data), its noise (median sqrt variance), and the share of the grid covered."""
    from reproject import reproject_interp
    w = frame_wcs(ra, dec, n)
    bad = exp.bad_mask()
    # image and variance in one call: the pixel mapping (the costly part) is computed once for both planes
    both = np.stack([np.where(bad, np.nan, exp.img), np.where(bad, np.nan, exp.var)])
    out, fp = reproject_interp((both, exp.wcs.celestial), w, (n, n), order="bilinear")
    img, var, cov = out[0], out[1], fp[0]
    inside = cov > 0.5
    ok = np.isfinite(img) & inside
    img = np.where(ok, img, np.nan)
    if ok.sum() > 20:
        img = img - np.nanmedian(img)
    noise = float(np.nanmedian(np.sqrt(var[ok & np.isfinite(var) & (var > 0)]))) if ok.any() else float("nan")
    return img, noise, float(ok.mean())


def fill_holes(img):
    """Flagged pixels inside the frame shown as their neighbours' median (display only; photometry skips them)."""
    from scipy.ndimage import median_filter
    hole = ~np.isfinite(img)
    if not hole.any() or hole.all():
        return img
    med = float(np.nanmedian(img))
    sm = median_filter(np.where(hole, med, img), 5)
    out = img.copy()
    out[hole] = sm[hole]
    return out


def to8(img, noise):
    """asinh stretch in units of the noise (faint sky grey, bright stars not burnt out); holes black."""
    if not (noise and math.isfinite(noise) and noise > 0):
        noise = float(np.nanstd(img)) or 1.0
    s = np.arcsinh(np.nan_to_num(img, nan=0.0) / (2.0 * noise)) / np.arcsinh(250)
    out = np.clip(28 + s * 227, 0, 255).astype(np.uint8)
    out[~np.isfinite(img)] = 0
    return out


def save_webp(arr8, path):
    from PIL import Image
    path = Path(path)
    tmp = path.with_name("." + path.name)
    Image.fromarray(arr8[::-1]).save(tmp, format="WEBP", lossless=True, quality=100, method=4)
    os.replace(tmp, path)


def centroid(img, var, bad, x, y, r=2.5):
    """Background-subtracted first moment within r pixels of (x, y); None when too faint or flagged."""
    n0, n1 = img.shape
    x0, x1, y0, y1 = max(0, int(x - 6)), min(n1, int(x + 7)), max(0, int(y - 6)), min(n0, int(y + 7))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    im, bd = img[y0:y1, x0:x1], bad[y0:y1, x0:x1] | ~np.isfinite(img[y0:y1, x0:x1])
    rr = np.hypot(xx - x, yy - y)
    sky = (rr > 4) & ~bd
    if sky.sum() < 10:
        return None
    w = np.where((rr <= r) & ~bd, im - np.median(im[sky]), 0.0)
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        return None
    return float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())


def measure(exp, ra, dec):
    """Forced photometry at the predicted position in the native frame: flux and error (µJy), the wavelength of that
    pixel, which SPHEREx flags touch the aperture, and the light centroid's offset from the prediction (arcsec)."""
    from .products import R_AP, phot
    x, y = exp.wcs.celestial.world_to_pixel_values(ra, dec)
    x, y = float(x), float(y)
    n0, n1 = exp.img.shape
    if not (2 <= x < n1 - 2 and 2 <= y < n0 - 2):
        return None
    bad = exp.bad_mask()
    p = phot(exp.img, exp.var, bad, x, y)
    # (called with 1-element arrays: archive.Exposure.wavelength_um's scalar path does float() of a 1-d array, which
    # numpy 2 refuses)
    lam = float(np.ravel(exp.wavelength_um(np.array([x]), np.array([y])))[0])
    h = int(math.ceil(R_AP + 0.5)) + 1                     # the aperture lies inside this window
    xa, xb, ya, yb = max(0, int(x) - h), min(n1, int(x) + h + 2), max(0, int(y) - h), min(n0, int(y) + h + 2)
    yy, xx = np.mgrid[ya:yb, xa:xb]
    ap = np.hypot(xx - x, yy - y) <= R_AP + 0.5
    fl = int(np.bitwise_or.reduce(np.asarray(exp.flags[ya:yb, xa:xb])[ap].astype(np.int64))) if ap.any() else 0
    # SPHEREx marks pixels near catalogued stars (SOURCE); only the pixel under the object itself is a warning
    fc = int(exp.flags[int(round(y)), int(round(x))])
    out = {"x": round(x, 2), "y": round(y, 2), "lam": round(lam, 4),
           "flux": None if p is None else round(p[0], 2), "err": None if p is None else round(p[1], 2),
           "sat": bool(fl & BIT_OVERFLOW), "star": bool(fc & BIT_SOURCE), "persist": bool(fl & BIT_PERSIST)}
    if p is not None and p[1] > 0 and p[0] / p[1] >= CENTROID_SNR:
        c = centroid(exp.img, exp.var, bad, x, y)
        if c is not None:
            cra, cdec = exp.wcs.celestial.pixel_to_world_values(c[0], c[1])
            out["dra"] = round((float(cra) - ra) * math.cos(math.radians(dec)) * 3600, 2)
            out["ddec"] = round((float(cdec) - dec) * 3600, 2)
    return out


# ---- spectrum and light curve -----------------------------------------------------------------------------------
def sun_fnu(lam_um, T=5778.0):
    """Sunlight's shape in F_nu (arbitrary units): a 5,778 K blackbody, close to the real Sun from 0.7 to 5 µm."""
    lam = np.asarray(lam_um, float) * 1e-6
    x = 6.62607e-34 * 2.99792458e8 / (lam * 1.380649e-23 * T)
    return (1 / lam ** 3) / np.expm1(x)


def running_median(lam, val, half=0.04, min_n=5):
    """Median of val over neighbours within +-half in ln(lambda) (at least min_n neighbours, widening if needed)."""
    lam, val = np.asarray(lam, float), np.asarray(val, float)
    ll = np.log(lam)
    dist = np.abs(ll[:, None] - ll[None, :])                # every pair once (a few hundred frames at most)
    out = np.full(len(lam), np.nan)
    for i in range(len(lam)):
        h = half
        while True:
            m = dist[i] <= h
            if m.sum() >= min_n or h > 0.5:
                break
            h *= 1.5
        out[i] = np.median(val[m]) if m.sum() >= 3 else np.nan
    return out


def lightcurve(frames, min_snr=10, periodic=True, known_h=None):
    """Adds to each usable frame `rel`: brightness relative to the spectrum (mag, + = fainter) after the distance
    change is removed; returns the periodogram's strongest repeat when it is significant (else None).
    Frames with a star in the aperture, saturation or persistence are left out."""
    use = [f for f in frames if f.get("flux") and f.get("err") and f["flux"] > 0 and f["flux"] / f["err"] >= min_snr
           and not f.get("sat") and not f.get("persist") and f.get("r_au") and f.get("d_au")]
    if len(use) < LC_MIN_FRAMES:
        return None
    r0 = np.median([f["r_au"] * f["d_au"] for f in use])
    g = np.array([(f["r_au"] * f["d_au"] / r0) ** 2 for f in use])
    flux = np.array([f["flux"] for f in use]) * g
    lam = np.array([f["lam"] for f in use])
    model = running_median(lam, flux)
    rel = -2.5 * np.log10(flux / model)
    err = 1.0857 * np.array([f["err"] / f["flux"] for f in use])
    # a star or a cosmic ray inside the aperture makes a point far off the rest: clipped at 4 robust sigmas
    fin = np.isfinite(rel)
    mad = 1.4826 * np.median(np.abs(rel[fin] - np.median(rel[fin]))) if fin.any() else 0
    clip = fin & (np.abs(rel - np.median(rel[fin])) > max(4 * mad, 0.02)) if fin.any() else fin
    for f, v, e, c in zip(use, rel, err, clip):
        if np.isfinite(v):
            f["rel"], f["rel_e"] = round(float(v), 4), round(float(e), 4)
            if c:
                f["clip"] = True
    t = np.array([f["mjd"] for f in use])
    ok = fin & ~clip
    span_h = (t[ok].max() - t[ok].min()) * 24 if ok.sum() else 0
    res = {"n": int(ok.sum()), "rms_mag": round(float(np.std(rel[ok])), 4), "period_h": None}
    if ok.sum() < LC_MIN_PERIODIC or span_h < LC_MIN_SPAN_H or not periodic:
        return res
    try:
        from astropy.timeseries import LombScargle
        ls = LombScargle(t[ok], rel[ok], err[ok])
        fmin, fmax = 24 / PERIOD_MAX_H, 24 / PERIOD_MIN_H   # repeats between 2 h and 2 days (cycles per day)
        freq, power = ls.autopower(minimum_frequency=fmin, maximum_frequency=fmax, samples_per_peak=20)
        j = int(np.argmax(power))
        fap = float(ls.false_alarm_probability(power[j], minimum_frequency=fmin, maximum_frequency=fmax))
        res.update(peak_h=round(24 / float(freq[j]), 3), fap=fap, power=round(float(power[j]), 3))
        # an asteroid's light curve usually has two maxima per turn: the rotation is twice the strongest repeat
        if fap < FAP_LIMIT:
            res["period_h"] = round(2 * 24 / float(freq[j]), 3)
        if known_h:
            # JPL's listed spin: is there a repeat at half of it (two maxima per turn)? One frequency tested, so the
            # chance of a false alarm is the single-frequency one
            fk = 2 * 24 / known_h
            pk = float(ls.power(fk))
            res["known"] = {"rot_h": known_h, "power": round(pk, 4), "fap": float(ls.false_alarm_probability(pk, method="single"))}
        step = max(1, len(freq) // 400)
        res["pgram"] = [[round(24 / float(a), 3), round(float(b), 4)] for a, b in zip(freq[::step], power[::step])]
    except Exception as e:  # noqa: BLE001 - the light curve is still shown
        res["error"] = str(e)[:120]
    return res


# ---- the job ----------------------------------------------------------------------------------------------------
class Doc:
    """doc.json, rewritten atomically at most every `every` seconds (and on demand); the page polls it."""

    def __init__(self, out, doc, every=1.5):
        self.out, self.doc, self.every, self.t = Path(out), doc, every, 0.0
        self.lock = threading.Lock()

    def save(self, force=False):
        with self.lock:
            now = time.time()
            if not force and now - self.t < self.every:
                return
            self.t = now
            self.doc["heartbeat"] = now
            tmp = self.out / ".doc.json"
            tmp.write_text(json.dumps(self.doc, separators=(",", ":")))
            os.replace(tmp, self.out / "doc.json")


def _iso(mjd):
    """'YYYY-MM-DD HH:MM' (UTC) of an MJD, as astropy's Time(mjd, format='mjd').iso[:16] (rounded to the
    millisecond first, like astropy's iso), without astropy's per-call overhead."""
    t = MJD0 + _dt.timedelta(milliseconds=round(float(mjd) * 86400000.0))
    return t.strftime("%Y-%m-%d %H:%M")


def _path_points(images, nmax=1200):
    """The sky path from every MOST position (one per exposure), thinned evenly to at most nmax points."""
    seen, pts = set(), []
    for im in images:
        if im["obs_id"] in seen:
            continue
        seen.add(im["obs_id"])
        pts.append([round(im["mjd"], 4), round(im["ra"], 5), round(im["dec"], 5)])
    if len(pts) > nmax:
        idx = np.unique(np.round(np.linspace(0, len(pts) - 1, nmax)).astype(int))
        pts = [pts[i] for i in idx]
    return pts


def run(slug, spkid, name, t0=None, t1=None, out_root=None, cache=None, workers=12, cap=CAP, log=print, fetch=None, kind=None):
    """Find, download and measure every SPHEREx image of one object; frames and doc.json appear as they arrive."""
    from . import archive
    out = Path(out_root or ROOT / "web" / "data" / "follow") / slug
    (out / "f").mkdir(parents=True, exist_ok=True)
    cache = Path(cache or ROOT / "cache" / "follow")
    fetch = fetch or (lambda m, ra, dec: archive.fetch_cutout(m, ra, dec, CUT_DEG, keep_psf=False, cache=cache))
    D = Doc(out, {"slug": slug, "v": FOLLOW_VERSION, "name": name, "short": short_name(name), "spkid": spkid, "kind": kind,
                  "t0": t0, "t1": t1, "status": "searching", "n_total": 0, "n_done": 0, "n_failed": 0, "n_most": 0,
                  "frames": [], "path": [], "npix": NPIX, "pix_arcsec": PIX_ARCSEC, "started": time.time(), "pid": os.getpid()})
    D.doc["phys"] = sbdb_phys(spkid, cache)
    D.save(True)
    stop = threading.Event()

    def beat():                       # the page and the server tell a live job from a dead one by this
        while not stop.wait(20):
            D.save(True)
    threading.Thread(target=beat, daemon=True).start()
    try:
        meta, images = most_query(spkid=spkid, t0=t0, t1=t1, cache_dir=cache)
        if not images:
            raise FollowError("no_images")
        pick = sample(images, cap)
        D.doc.update(status="running", object_name=meta.get("object_name", name), n_most=len(images), n_total=len(pick),
                     path=_path_points(images), first=_iso(images[0]["mjd"]), last=_iso(images[-1]["mjd"]),
                     releases=sorted({im["release"] for im in images}),
                     elements={k: meta.get(k) for k in ("eccentricity", "inclination", "semimajor_axis", "perihelion_distance") if meta.get(k)})
        D.save(True)
        log(f"{slug}: MOST lists {len(images)} images, fetching {len(pick)}")
        stack = []                     # (filled in this thread only: as_completed yields here)

        def one(j, im):
            # the cutout is centred on MOST's own position (so a re-run finds it in the cache); measured at mid-exposure
            e = fetch(im, im["ra0"], im["dec0"])
            if e is None:
                return j, im, None, None, None
            ms = measure(e, im["ra"], im["dec"])
            img, noise, cov = render(e, im["ra"], im["dec"])
            return j, im, ms, (img, noise, cov), e

        with ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(one, j, im) for j, im in enumerate(pick)]
            for fu in as_completed(futs):
                try:
                    j, im, ms, fr, _e = fu.result()
                except Exception as e:  # noqa: BLE001 - a few failed cutouts are normal
                    log(f"{slug}: cutout failed: {e}")
                    D.doc["n_failed"] += 1; D.save(); continue
                if ms is None or fr is None or fr[2] < MIN_COVER:
                    D.doc["n_failed"] += 1; D.save(); continue
                img, noise, cov = fr
                save_webp(to8(fill_holes(img), noise), out / "f" / f"{j:04d}.webp")
                if math.isfinite(noise) and noise > 0:
                    stack.append((im["mjd"], img / noise))
                rec = {"f": j, "mjd": round(im["mjd"], 5), "iso": _iso(im["mjd"]), "det": im["detector"], "obs": im["obs_id"],
                       "rls": im["release"], "ra": round(im["ra"], 5), "dec": round(im["dec"], 5), "vmag": im["vmag"],
                       "r_au": im["r_au"], "d_au": im["d_au"], "phase": im["phase"], "cov": round(cov, 3), **ms}
                if rec.get("flux") is not None and rec.get("err"):
                    rec["snr"] = round(rec["flux"] / rec["err"], 1)
                frames = D.doc["frames"]                   # kept in time order
                frames.insert(bisect.bisect_right([r["mjd"] for r in frames], rec["mjd"]), rec)
                D.doc["n_done"] = len(D.doc["frames"])
                D.save()
        if not D.doc["frames"]:
            raise FollowError("no_images", detail="no cutout could be measured")
        # the object-centred stack: stars are at a different place in every frame and vanish in the median
        if len(stack) >= 5:
            st = np.nanmedian(np.stack([s for _, s in stack]), axis=0)
            fin = np.isfinite(st)
            nz = 1.4826 * float(np.median(np.abs(st[fin] - np.median(st[fin])))) if fin.any() else 1.0
            save_webp(to8(fill_holes(st), nz or 1.0), out / "stack.webp")
            D.doc["stack"] = len(stack)
        lc = lightcurve(D.doc["frames"], periodic=kind != "comet", known_h=(D.doc.get("phys") or {}).get("rot_h"))
        D.doc["lc"] = lc
        cen = [f for f in D.doc["frames"] if "dra" in f]
        if cen:
            D.doc["offset"] = {"n": len(cen), "median_arcsec": round(float(np.median([math.hypot(f["dra"], f["ddec"]) for f in cen])), 2),
                               "dra_med": round(float(np.median([f["dra"] for f in cen])), 2),
                               "ddec_med": round(float(np.median([f["ddec"] for f in cen])), 2)}
        D.doc.update(status="done", finished=time.time(), seconds=round(time.time() - D.doc["started"], 1))
        D.save(True)
        log(f"{slug}: done, {D.doc['n_done']} frames, {D.doc['n_failed']} failed, {D.doc['seconds']} s")
    except FollowError as e:
        D.doc.update(status="error", error=e.code, choices=e.choices)
        D.save(True)
        log(f"{slug}: {e}")
    except Exception as e:  # noqa: BLE001
        D.doc.update(status="error", error="failed", detail=str(e)[:300])
        D.save(True)
        log(f"{slug}: failed: {e}")
        raise
    finally:
        stop.set()
    return D.doc


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    a = sys.argv[1:]
    if len(a) < 3:
        sys.exit("usage: python -m sxlib.follow <slug> <spkid> <name> [t0 t1 [kind]]")
    try:
        os.nice(5)                     # a background job: below the web server (POSIX only)
    except (AttributeError, OSError):
        pass
    run(a[0], a[1], a[2], (a[3] or None) if len(a) > 3 else None, (a[4] or None) if len(a) > 4 else None,
        kind=a[5] if len(a) > 5 else None)
