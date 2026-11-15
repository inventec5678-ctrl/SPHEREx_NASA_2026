"""IRSA SPHEREx access: image search, cutouts (cached), known small bodies."""
import csv
import hashlib
import io
import json
import os
import random
import re
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import requests
from astropy import log as _astropy_log
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning

warnings.filterwarnings("ignore", category=FITSFixedWarning)
warnings.filterwarnings("ignore", message=".*SIP.*")
_astropy_log.setLevel("ERROR")

SIA = "https://irsa.ipac.caltech.edu/SIA"
SB_IDENT = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
# used only when IRSA cannot be asked; IRSA retired QR2 when DR1 came out (2026), and QR3 continues after DR1
DEFAULT_COLLECTIONS = ["spherex_dr1", "spherex_qr3"]
_REL = re.compile(r"^spherex_(qr|dr)(\d+)$")       # science releases; *_cal and *_deep are other products


def _release_rank(name):
    m = _REL.match(name)
    return (1 if m.group(1) == "dr" else 0, int(m.group(2))) if m else (-1, 0)


_COLL_MEMO = {"t": 0.0, "v": None}


def collections(max_age_s=86400):
    """Every SPHEREx science release IRSA serves, oldest first, asked from IRSA's TAP service once a day, so a new
    quick release (spherex_qr4 ...) or data release (spherex_dr1 ...) is used without a code change.
    The list is also kept in memory for a minute, so a burst of searches reads the cache file once."""
    now = time.time()
    if _COLL_MEMO["v"] is not None and now - _COLL_MEMO["t"] < min(60.0, max_age_s):
        return list(_COLL_MEMO["v"])
    names = _collections(max_age_s)
    _COLL_MEMO.update(t=now, v=list(names))
    return names


def _collections(max_age_s):
    f = CACHE / "collections.json"
    try:
        if f.exists() and time.time() - f.stat().st_mtime < max_age_s:
            return json.loads(f.read_text())
        q = "SELECT DISTINCT obs_collection FROM ivoa.obscore WHERE obs_collection LIKE 'spherex%'"
        r = _session.get(TAP, params={"QUERY": q, "FORMAT": "csv", "LANG": "ADQL"}, timeout=60, verify=VERIFY)
        r.raise_for_status()
        names = sorted({ln.strip() for ln in r.text.splitlines()[1:] if _REL.match(ln.strip())}, key=_release_rank)
        if names:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(names))
            return names
    except Exception:  # noqa: BLE001 - fall back to the last known list
        if f.exists():
            return json.loads(f.read_text())
    return DEFAULT_COLLECTIONS


COLLECTIONS = DEFAULT_COLLECTIONS                    # kept for scripts that import it
VERIFY = os.environ.get("SX_INSECURE") != "1"
CACHE = Path(os.environ.get("SX_CACHE", Path(__file__).resolve().parent.parent / "cache"))

# FLAGS bits (from the L2 FLAGS header)
HARD_BAD = [0, 1, 2, 4, 5, 6, 9, 10, 11, 14, 15, 17, 26, 28]  # transient, overflow, hot, persist, bloom...
SOURCE_BITS = [21]                 # pixel mapped to a known (catalogued) source
GHOST_BITS = [22, 23, 24]
OUTLIER_BITS = [19]                # may also fire on genuine movers -> feature, not mask
# bit names as written in the L2 FLAGS extension header (MP_* keywords; read from a live IRSA cutout 2026-11-12)
FLAG_NAMES = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 4: "PHANTOM", 5: "REFERENCE", 6: "NONFUNC", 7: "DICHROIC",
              9: "MISSING_DATA", 10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST",
              19: "OUTLIER", 21: "SOURCE", 22: "GHOST", 23: "GHOST", 24: "GHOST"}
OVERFLOW_BITS, PERSIST_BITS = [1], [17]
# name -> mask, for the per-exposure flag summary (FULLSAMPLE is information, not contamination)
FLAG_MASKS = {nm: sum(1 << b for b, n in FLAG_NAMES.items() if n == nm) for nm in dict.fromkeys(FLAG_NAMES.values()) if nm != "FULLSAMPLE"}


def bitmask(bits):
    return int(sum(1 << b for b in bits))


if not VERIFY:
    requests.packages.urllib3.disable_warnings()
_session = requests.Session()
# quick looks fetch ~20 cutouts at once: keep that many connections alive (the default pool holds 10)
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=48))


RETRY_STATUS = (429, 500, 502, 503, 504)
FATAL_STATUS = (400, 404, 422)
THROTTLE_WAIT_S = 30.0            # after an HTTP 429 without a Retry-After header
MAX_WAIT_S = 120.0


def _get(url, params=None, timeout=300, tries=6):
    """GET with retries (exponential back-off with jitter) on throttling, server errors and dropped connections;
    client errors (400/404/422) are raised at once."""
    for k in range(tries):
        wait = min(2 ** k, 20) * (0.5 + random.random())           # jitter: parallel fetches must not retry in lockstep
        try:
            r = _session.get(url, params=params, timeout=timeout, verify=VERIFY)
            if r.status_code in RETRY_STATUS:
                ra = r.headers.get("Retry-After", "")
                if r.status_code == 429:                            # throttled: wait as long as the server asks
                    wait = max(wait, float(ra) if ra.isdigit() else THROTTLE_WAIT_S)
                raise requests.HTTPError(f"{r.status_code}")
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            if "422" in str(e) or (hasattr(e, "response") and e.response is not None
                                   and e.response.status_code in FATAL_STATUS):
                raise
            if k == tries - 1:
                raise
        except requests.ConnectionError:
            if k == tries - 1:
                raise
        time.sleep(min(wait, MAX_WAIT_S))


def search_images(ra, dec, radius=0.001, mjd_range=None):
    """Science images whose footprint contains (ra, dec) [within radius deg]."""
    params = {"POS": f"circle {ra} {dec} {radius}", "RESPONSEFORMAT": "CSV", "COLLECTION": collections()}
    if mjd_range:
        params["TIME"] = f"{mjd_range[0]} {mjd_range[1]}"
    rows = [r for r in csv.DictReader(io.StringIO(_get(SIA, params).text))
            if r["dataproduct_subtype"] == "science"]
    # the same exposure can be served by several releases (e.g. a quick release and a later data release):
    # keep the newest processing of each (obs_id, detector)
    rows.sort(key=lambda r: _release_rank(r.get("obs_collection", "")))
    out = {}
    for r in rows:
        out[(r["obs_id"], r["energy_bandpassname"])] = {
            "url": r["access_url"], "obs_id": r["obs_id"], "band": r["energy_bandpassname"],
            "detector": int(r["energy_bandpassname"][-1]),
            "mjd": 0.5 * (float(r["t_min"]) + float(r["t_max"])),
            "s_region": r["s_region"], "collection": r.get("obs_collection", ""),
        }
    return sorted(out.values(), key=lambda x: x["mjd"])


def _atomic_savez(path, **arrays):
    """Write .npz via a temp file + rename so concurrent readers never see partial files."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp.npz")
    np.savez_compressed(tmp, **arrays)
    try:
        os.replace(tmp, path)
    except FileNotFoundError:      # another thread already published the same file
        if not path.exists():
            raise


def _cache_key(url, ra, dec, size):
    return hashlib.sha1(f"{url}|{ra:.6f}|{dec:.6f}|{size:.5f}".encode()).hexdigest()[:20]


class Exposure:
    """One SPHEREx cutout in its native detector frame."""

    def __init__(self, meta, img, var, flags, header, psf=None, psf_hdr=None):
        self.meta, self.img, self.var, self.flags, self.header = meta, img, var, flags, header
        self.wcs = WCS(header)
        self.psf, self.psf_hdr = psf, psf_hdr
        self.mjd = header.get("MJD-AVG", meta.get("mjd"))
        self.detector = int(header.get("DETECTOR", meta.get("detector", 0)))

    @property
    def pixel_scale_arcsec(self):
        return float(np.sqrt(abs(np.linalg.det(self.wcs.celestial.pixel_scale_matrix))) * 3600)

    def wavelength_um(self, x=None, y=None):
        """Central wavelength (um) at cutout pixel(s) (x, y); default: cutout centre."""
        if x is None:
            y, x = (np.array(self.img.shape) - 1) / 2
        v = self._lam_interp(np.stack(np.broadcast_arrays(y, x), -1))
        return float(v) if np.ndim(v) == 0 or v.size == 1 and np.ndim(x) == 0 else v

    def wavelength_map(self):
        yy, xx = np.mgrid[:self.img.shape[0], :self.img.shape[1]]
        return self.wavelength_um(xx, yy)

    @property
    def _lam_interp(self):
        if not hasattr(self, "_li"):
            from scipy.interpolate import RegularGridInterpolator
            gy, gx, lam = self.meta["_lam"]
            self._li = RegularGridInterpolator((gy, gx), lam, bounds_error=False, fill_value=None)
        return self._li

    def detector_xy(self, x, y):
        """0-based active detector pixel coordinates for cutout pixel (x, y) (WCS key 'A')."""
        h = self.header
        return x + 1 - h["CRPIX1A"] + h.get("CRVAL1A", 0), y + 1 - h["CRPIX2A"] + h.get("CRVAL2A", 0)

    @property
    def psf_is_epsf(self):
        """True for the DR1/QR3 effective PSF (pixel-convolved: sample it at pixel centres, don't integrate it)."""
        return self.psf_hdr is not None and self.psf_hdr.get("PSFTYPE") == "EPSF"

    def psf_at(self, x, y):
        """10x oversampled PSF (101x101) for the detector zone nearest cutout pixel (x, y), matched on the parent
        image's 0-based pixel coordinates as IRSA's PSF tutorial does."""
        if self.psf is None:
            raise ValueError("no PSF stored for this exposure")
        dx, dy = self.detector_xy(x, y)
        h = self.psf_hdr
        zc = getattr(self, "_zc", None)
        if zc is None or zc[0] is not h:          # zone centres, parsed once per PSF header
            n = self.psf.shape[0]
            zc = (h, np.array([h[f"XCTR_{i + 1}"] for i in range(n)]), np.array([h[f"YCTR_{i + 1}"] for i in range(n)]))
            self._zc = zc
        _, cx, cy = zc
        return self.psf[int(np.argmin((cx - dx) ** 2 + (cy - dy) ** 2))]

    def bad_mask(self):
        return ((self.flags & bitmask(HARD_BAD)) != 0) | ~np.isfinite(self.img)


def _lam_grid(hdul, hdr, shape, step=8):
    """Per-pixel wavelength from the WAVE-TAB WCS, sampled every `step` px."""
    w = WCS(hdr, fobj=hdul, key="W")
    gy = np.unique(np.r_[np.arange(0, shape[0], step), shape[0] - 1]).astype(float)
    gx = np.unique(np.r_[np.arange(0, shape[1], step), shape[1] - 1]).astype(float)
    yy, xx = np.meshgrid(gy, gx, indexing="ij")
    lam, _bw = w.pixel_to_world_values(xx, yy)
    return gy, gx, np.asarray(lam, float)


def fetch_cutout(meta, ra, dec, size_deg, keep_psf=True, cache=CACHE):
    """Download (or load cached) cutout. Returns Exposure, or None if outside the image."""
    key = _cache_key(meta["url"], ra, dec, size_deg)
    d = cache / "cutouts"
    f_npz, f_hdr = d / f"{key}.npz", d / f"{key}.json"
    psf_dir = cache / "psf"
    if f_npz.exists():
        with np.load(f_npz) as z:          # read every member once and close the file (Windows keeps it locked)
            a = {k: z[k] for k in ("img", "var", "flags", "lam_y", "lam_x", "lam")}
        hdrs = json.loads(f_hdr.read_text())
        meta = {**meta, "_lam": (a["lam_y"], a["lam_x"], a["lam"])}
        psf = psf_hdr = None
        if keep_psf:
            psf, psf_hdr = load_psf(hdrs.get("psf_key"), int(meta.get("detector", 0)), cache)
        return Exposure(meta, a["img"].astype(float), a["var"].astype(float), a["flags"],
                        fits.Header.fromstring(hdrs["header"], sep="\n"), psf, psf_hdr)
    try:
        r = _get(meta["url"], {"center": f"{ra},{dec}", "size": size_deg})
    except requests.HTTPError:
        return None
    with fits.open(io.BytesIO(r.content)) as h:
        hdr = h["IMAGE"].header
        img = h["IMAGE"].data.astype(np.float32) - h["ZODI"].data.astype(np.float32)
        var = h["VARIANCE"].data.astype(np.float32)
        flags = h["FLAGS"].data.astype(np.int32)
        if min(img.shape) < 8:
            return None
        lam = _lam_grid(h, hdr, img.shape)
        # DR1 and QR3 files carry the effective PSF (EPSF table: 21x21 zones, 5x oversampled, one calibration file
        # per detector); stored once per calibration file. Older (QR2) files carry an optical PSF cube instead:
        # one per (detector, observing week). IRSA advises using the ePSF.
        psf_key = None
        if "EPSF" in h:
            psf_key = _store_epsf(h["EPSF"], int(hdr["DETECTOR"]), psf_dir)
        elif "PSF" in h:
            psf_key = f"D{hdr['DETECTOR']}_{meta['obs_id'].split('_')[0]}"
            p = psf_dir / f"{psf_key}.npz"
            if not p.exists():
                psf_dir.mkdir(parents=True, exist_ok=True)
                _atomic_savez(p, psf=h["PSF"].data.astype(np.float16),
                              header=h["PSF"].header.tostring(sep="\n"))
        psf, psf_hdr = (load_psf(psf_key, int(hdr["DETECTOR"]), cache) if keep_psf else (None, None))
    d.mkdir(parents=True, exist_ok=True)
    _atomic_savez(f_npz, img=img, var=var, flags=flags, lam_y=lam[0], lam_x=lam[1], lam=lam[2])
    f_hdr.write_text(json.dumps({"header": hdr.tostring(sep="\n"), "psf_key": psf_key}))
    return Exposure({**meta, "_lam": lam}, img.astype(float), var.astype(float), flags, hdr, psf, psf_hdr)


PSF_OVERSAMP, PSF_SIZE = 10, 101     # common PSF grid: 101 x 101 samples at 10 per pixel (centre index 50)
_PSF_MEMO = {}                       # psf file -> (cube on the common grid, header)


def _store_epsf(hdu, detector, psf_dir):
    """Save a file's EPSF table (zones x 33 x 33 at 5x) once per calibration file; returns its key."""
    hist = " ".join(str(v) for v in hdu.header.get("HISTORY", []))
    m = re.search(r"epsf_(\d+)_(\d+)\.fits", hist)
    tag = m.group(2) if m else hashlib.sha1(hdu.data["EPSF"][len(hdu.data) // 2].tobytes()).hexdigest()[:10]
    key = f"E{detector}_{tag}"
    p = psf_dir / f"{key}.npz"
    if not p.exists():
        psf_dir.mkdir(parents=True, exist_ok=True)
        d = hdu.data
        _atomic_savez(p, epsf=np.asarray(d["EPSF"], np.float32), xc=np.asarray(d["XCENTER"], np.float32),
                      yc=np.asarray(d["YCENTER"], np.float32), header=hdu.header.tostring(sep="\n"))
    return key


def epsf_to_grid(epsf, ovs, os_out=PSF_OVERSAMP, n_out=PSF_SIZE):
    """Resample ePSF stamps (zones x m x m at `ovs` per pixel, centre at the middle sample) onto the optical-PSF
    grid the rest of the code uses (n_out x n_out at os_out per pixel, centre index n_out // 2), sum 1."""
    from scipy.ndimage import map_coordinates
    epsf = epsf if epsf.ndim == 3 else epsf[None]
    m = epsf.shape[-1]
    j = (np.arange(n_out) - n_out // 2) * ovs / os_out + (m - 1) / 2
    yy, xx = np.meshgrid(j, j, indexing="ij")
    out = np.stack([map_coordinates(e.astype(np.float64), [yy, xx], order=1, mode="constant", cval=0.0) for e in epsf])
    out = np.clip(out, 0, None)
    s = out.sum(axis=(1, 2), keepdims=True)
    return (out / np.where(s > 0, s, 1)).astype(np.float32)


def load_psf(psf_key, detector, cache=CACHE):
    """PSF cube + header for psf_key; without one (or if it is missing), the newest cached ePSF of the same detector,
    else any cached optical PSF cube of that detector. An ePSF comes back on the optical-PSF grid (zones x 101 x 101
    at 10x) with PSFTYPE = 'EPSF' and zone centres XCTR_i/YCTR_i in its header."""
    d = cache / "psf"
    first = d / f"{psf_key}.npz" if psf_key else None
    if first is not None and first in _PSF_MEMO:       # the common case: no directory listing needed
        return _PSF_MEMO[first]
    cands = ([first] if first else []) + sorted(d.glob(f"E{detector}_*.npz"), reverse=True) \
        + sorted(d.glob(f"D{detector}_*.npz"))
    for p in cands:
        if p in _PSF_MEMO:
            return _PSF_MEMO[p]
        if p.exists():
            try:
                with np.load(p) as z:
                    if "header" not in z:
                        continue
                    h = fits.Header.fromstring(str(z["header"]), sep="\n")
                    if "epsf" in z:
                        ovs = int(h.get("OVSMPX", 5))
                        cube = epsf_to_grid(z["epsf"], ovs)
                        hh = fits.Header()
                        hh["PSFTYPE"], hh["OVERSAMP"], hh["SRC_OVS"], hh["DETECTOR"] = "EPSF", PSF_OVERSAMP, ovs, detector
                        for i, (a, b) in enumerate(zip(z["xc"], z["yc"])):
                            hh[f"XCTR_{i + 1}"], hh[f"YCTR_{i + 1}"] = float(a), float(b)
                        _PSF_MEMO[p] = (cube, hh)
                    else:
                        _PSF_MEMO[p] = (z["psf"].astype(np.float32), h)
            except Exception:  # noqa: BLE001 - a damaged cache file: try the next candidate
                continue
            return _PSF_MEMO[p]
    return None, None


def known_small_bodies(ra, dec, mjd, half_width_deg, vmag_lim=22.0, kinds=("a", "c")):
    """JPL sb_ident: known asteroids/comets in a box at time mjd, with sky rates."""
    t = Time(mjd, format="mjd").datetime
    ra_h = ra / 15
    h, m = int(ra_h), int((ra_h % 1) * 60)
    s = ((ra_h * 60) % 1) * 60
    sign = "-" if dec < 0 else ""
    ad = abs(dec)
    dd, dm = int(ad), int((ad % 1) * 60)
    ds = ((ad * 60) % 1) * 60
    params = {"sb-kind": "a", "mpc-code": "500", "obs-time": t.strftime("%Y-%m-%d_%H:%M:%S"),
              "fov-ra-center": f"{h:02d}-{m:02d}-{s:05.2f}", "fov-dec-center": f"{sign}{dd:02d}-{dm:02d}-{ds:04.1f}",
              "fov-ra-hwidth": half_width_deg, "fov-dec-hwidth": half_width_deg,
              "two-pass": "true", "suppress-first-pass": "true", "vmag-lim": vmag_lim}
    out = []
    for kind in kinds:
        params["sb-kind"] = kind
        # a failure must reach the caller: swallowing it here made a field look like "no known bodies"
        js = _get(SB_IDENT, params, timeout=300).json()
        if "summary" not in js:          # a valid reply always echoes the query; an error reply carries code/message
            raise RuntimeError(f"sb_ident ({kind}): unexpected reply {str(js)[:200]}")
        fields = js.get("fields_second") or []
        for row in js.get("data_second_pass") or []:
            rec = dict(zip(fields, row))
            out.append({"name": rec["Object name"], "kind": kind,
                        "ra": _hms(rec["Astrometric RA (hh:mm:ss)"]) * 15,
                        "dec": _dms(rec['Astrometric Dec (dd mm\'ss")']),
                        "V": _num(rec.get("Visual magnitude (V)")),
                        "dra_h": _num(rec.get('RA rate ("/h)')), "ddec_h": _num(rec.get('Dec rate ("/h)')),
                        "mjd": mjd})
    return out


def known_position(body, mjd):
    """Linear propagation of an sb_ident position (good to ~arcsec over a few days)."""
    dt_h = (mjd - body["mjd"]) * 24
    dec = body["dec"] + body["ddec_h"] * dt_h / 3600
    ra = body["ra"] + body["dra_h"] * dt_h / 3600 / np.cos(np.radians(body["dec"]))
    return ra % 360, dec


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _hms(s):
    h, m, sec = [float(v) for v in re.split(r"[: ]+", s.strip())]
    return h + m / 60 + sec / 3600


def _dms(s):
    s = s.strip()
    sign = -1 if s.startswith("-") else 1
    d, m, sec = [abs(float(v)) for v in re.findall(r"[-+]?\d+\.?\d*", s)[:3]]
    return sign * (d + m / 60 + sec / 3600)
