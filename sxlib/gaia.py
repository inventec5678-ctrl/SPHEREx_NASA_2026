"""Gaia DR3: one way in, ESA's Gaia archive first, MAST as the fallback.

The challenge's Resources point to Gaia DR3 at MAST. ESA's archive answers fastest from here, so it stays first;
when it fails (down, maintenance page, timeout) the same ADQL goes to MAST.

  query(adql)   ADQL on the full Gaia DR3 schema, tables written as gaiadr3.<table> (gaia_source, vari_summary,
                vari_classifier_result, ...).
                  1. ESA Gaia archive TAP (gea.esac.esa.int), CSV;
                  2. MAST's Gaia DR3 TAP (mast.stsci.edu/vo-tap/api/v0.1/gaiadr3), VOTable; there the tables are
                     dbo.<table>, which query() rewrites.
  cone(...)     a gaia_source cone (optionally G-limited, sorted, TOP n). If both TAP services fail it asks MAST's
                catalog service Mast.Catalogs.GaiaDR3.Cone and filters and sorts here.
  star(ra, dec) the Gaia DR3 source a click on a SPHEREx image most likely means, its neighbours and, for a
                variable, its Gaia variability summary and class (the field lab's star card).

Every function returns rows as dicts of strings exactly as ESA's CSV writes them ('' for null, 'true'/'false',
float32 columns at float32 precision), whichever service answered, so callers parse one format.
"""
import csv
import io
import json
import math
import re
import threading
import time

import numpy as np

ESA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
MAST_TAP = "https://mast.stsci.edu/vo-tap/api/v0.1/gaiadr3/sync"
MAST_API = "https://mast.stsci.edu/api/v0/invoke"
HEADERS = {"User-Agent": "spherex-sky-change/1.0 (python-requests)"}
CONNECT_TIMEOUT = 15          # s: a service that does not answer this fast is skipped
EPOCH = 2016.0                # Gaia DR3 reference epoch (Julian year)
PIX = 6.15                    # SPHEREx pixel, arcsec
MAS_PER_DEG = 3.6e6
MAST_POLL_TRIES, MAST_POLL_S = 30, 2   # MAST's catalog service may answer EXECUTING first: ask again

# gaia_source columns stored as 64-bit floats; every other float column is 32-bit. Used only to format the JSON of
# MAST's catalog service, which does not say (the TAP services do).
DOUBLE_COLS = {"ra", "dec", "parallax", "pmra", "pmdec", "l", "b", "ecl_lon", "ecl_lat", "ref_epoch",
               "phot_g_mean_flux", "phot_bp_mean_flux", "phot_rp_mean_flux", "mean_obs_time_g_fov", "time_duration_g_fov"}

# VOTable datatype -> _fmt kind
_VOT_KIND = {"float": "f4", "double": "f8", "boolean": "b", "bit": "b",
             "short": "i", "int": "i", "long": "i", "unsignedByte": "i"}

last = {"service": None}      # which service answered the latest query: "esa", "mast" or "mast-catalog"


class GaiaError(RuntimeError):
    """No Gaia service could answer; the message lists each service's error."""


_local = threading.local()


def _requests():
    """A keep-alive HTTP session (one per thread) with .get/.post; TLS warnings off (verify=False below)."""
    s = getattr(_local, "session", None)
    if s is None:
        import requests
        import urllib3
        urllib3.disable_warnings()
        s = _local.session = requests.Session()
    return s


# ---- formatting: every service's values as ESA's CSV text --------------------------------------------------------
def _fmt(v, kind):
    """kind: 'f4', 'f8', 'i', 'b', 's'."""
    if v is None or v is np.ma.masked:
        return ""
    if kind == "b":
        return "true" if bool(v) else "false"
    if kind in ("f4", "f8"):
        x = float(v)
        if not math.isfinite(x):
            return ""
        return str(np.float32(x)) if kind == "f4" else repr(x)
    if kind == "i":
        return str(int(v))
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return str(v).strip()


def _parse_csv(text):
    lines = text.strip().splitlines()
    if not lines or lines[0].startswith("<"):
        raise RuntimeError(text[:200] if text.strip() else "empty reply")
    rd = csv.reader(lines)
    head = next(rd)
    return [dict(zip(head, r)) for r in rd]


def _squash(s):
    return re.sub(r"\s+", " ", s)[:200]


def _parse_votable(content):
    """A TAP VOTable (MAST answers only in VOTable) -> rows of strings."""
    import warnings
    from astropy.io.votable import parse
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    m = re.search(r'<INFO name="QUERY_STATUS" value="(\w+)"\s*/?>(.*?)(?:</INFO>|$)', text, re.S)
    if m and m.group(1) != "OK":
        raise RuntimeError(_squash(m.group(2)) or m.group(1))
    if "<TABLE" not in text:
        raise RuntimeError(_squash(text) or "empty reply")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vt = parse(io.BytesIO(text.encode("utf-8")), verify="ignore")
    tab = vt.get_first_table()
    arr = tab.array
    names = [f.name for f in tab.fields]
    cols = []                                       # formatted column by column (no per-record field lookups)
    for f in tab.fields:
        kind = _VOT_KIND.get(f.datatype, "s")
        col = arr[f.name]
        data, mask = np.ma.getdata(col), np.ma.getmaskarray(col)
        cols.append([_fmt(None if mk else v, kind) for v, mk in zip(data, mask)])
    return [dict(zip(names, vals)) for vals in zip(*cols)] if cols else []


# ---- services -------------------------------------------------------------------------------------------------
def _esa(adql, timeout):
    r = _requests().get(ESA_TAP, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
                        headers=HEADERS, verify=False, timeout=(CONNECT_TIMEOUT, timeout))
    r.raise_for_status()
    return _parse_csv(r.text)


def mast_adql(adql):
    """ESA's table names -> MAST's (gaiadr3.gaia_source -> dbo.gaia_source)."""
    return re.sub(r"\bgaiadr3\.", "dbo.", adql)


def _mast(adql, timeout):
    r = _requests().post(MAST_TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": mast_adql(adql)},
                         headers=HEADERS, verify=False, timeout=(CONNECT_TIMEOUT, timeout))
    r.raise_for_status()
    return _parse_votable(r.content)


SERVICES = {"esa": _esa, "mast": _mast}


def query(adql, timeout=200, services=("esa", "mast"), log=None):
    """Run ADQL (tables as gaiadr3.<table>) on the first service that answers. Rows: dicts of strings."""
    errors = []
    for s in services:
        try:
            rows = SERVICES[s](adql, timeout)
        except Exception as e:  # noqa: BLE001 - try the next service
            errors.append(f"{s}: {str(e)[:160]}")
            continue
        last["service"] = s
        if errors and log:
            log(f"  Gaia: {'; '.join(errors)}; answered by {s}")
        return rows
    raise GaiaError("; ".join(errors))


def _catalog_kind(field):
    t, name = field["type"], field["name"]
    if t == "boolean":
        return "b"
    if t == "int":
        return "i"
    if t == "float":
        return "f8" if name in DOUBLE_COLS else "f4"
    return "s"


def _mast_catalog_cone(ra, dec, radius_deg, timeout, pagesize=50000, max_pages=10):
    """Mast.Catalogs.GaiaDR3.Cone: every gaia_source column, as ESA-style strings."""
    req = _requests()
    rows = []
    for page in range(1, max_pages + 1):
        body = json.dumps({"service": "Mast.Catalogs.GaiaDR3.Cone", "params": {"ra": ra, "dec": dec, "radius": radius_deg},
                           "format": "json", "pagesize": pagesize, "page": page})
        for _ in range(MAST_POLL_TRIES):
            r = req.post(MAST_API, data={"request": body}, headers=HEADERS, verify=False, timeout=(CONNECT_TIMEOUT, timeout))
            r.raise_for_status()
            d = r.json()
            if d.get("status") != "EXECUTING":
                break
            time.sleep(MAST_POLL_S)
        if d.get("status") != "COMPLETE":
            raise RuntimeError(f"MAST catalog status {d.get('status')}: {str(d.get('msg'))[:120]}")
        kinds = {f["name"]: _catalog_kind(f) for f in d["fields"]}
        rows += [{k: _fmt(v, kinds.get(k, "s")) for k, v in rec.items() if k != "distance"} for rec in d["data"]]
        if page >= ((d.get("paging") or {}).get("pagesFiltered") or 1):
            break
    return rows


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _rd(v, n):
    return None if v is None else round(v, n)


def cone(ra, dec, radius_deg, columns, max_g=None, top=None, order="phot_g_mean_mag", timeout=200, log=None):
    """gaia_source within radius_deg of (ra, dec): ESA, then MAST TAP, then MAST's catalog service.
    columns: names of gaia_source columns. max_g: keep phot_g_mean_mag < max_g. order: a column (ascending)."""
    cols = list(columns)
    w = f"1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{radius_deg}))"
    if max_g is not None:
        w += f" AND phot_g_mean_mag<{max_g}"
    q = f"SELECT {f'TOP {top} ' if top else ''}{','.join(cols)} FROM gaiadr3.gaia_source WHERE {w}{f' ORDER BY {order}' if order else ''}"
    try:
        return query(q, timeout=timeout, log=log)
    except GaiaError as e:
        why = str(e)
    try:
        rows = _mast_catalog_cone(ra, dec, radius_deg, timeout)
    except Exception as e2:  # noqa: BLE001
        raise GaiaError(f"{why}; mast-catalog: {str(e2)[:160]}") from None
    if log:
        log(f"  Gaia: {why}; answered by MAST's catalog service")
    last["service"] = "mast-catalog"
    if max_g is not None:
        rows = [r for r in rows if (g := _f(r.get("phot_g_mean_mag"))) is not None and g < max_g]
    if order:
        def key(r):
            v = _f(r.get(order))
            return (v is None, v or 0.0)
        rows.sort(key=key)
    if top:
        rows = rows[:top]
    return [{c: r.get(c, "") for c in cols} for r in rows]


# ---- one star: the field lab's star card ------------------------------------------------------------------------
STAR_COLS = ("source_id", "ra", "dec", "pmra", "pmdec", "pm", "parallax", "parallax_error", "phot_g_mean_mag",
             "phot_bp_mean_mag", "phot_rp_mean_mag", "bp_rp", "ruwe", "phot_variable_flag", "radial_velocity",
             "teff_gspphot", "non_single_star", "classprob_dsc_combmod_star", "classprob_dsc_combmod_galaxy",
             "classprob_dsc_combmod_quasar")
FAST_PM = 300.0               # mas/yr: a star this fast can have left a 30" circle since 2016
FAST_R = 150.0                # arcsec: how far such a star is looked for (Barnard's Star moves ~10.4"/yr)
N_NEIGHBOURS = 40             # neighbours listed on the star card


def epoch_of_mjd(mjd):
    return 2000.0 + (mjd - 51544.5) / 365.25


def move_to(r, epoch):
    """(ra, dec) of a row at a Julian epoch, linear proper motion (no parallax: < 0.6" for every star)."""
    dt = epoch - EPOCH
    pa, pd = _f(r.get("pmra")) or 0.0, _f(r.get("pmdec")) or 0.0
    ra, dec = float(r["ra"]), float(r["dec"])
    return ra + pa * dt / MAS_PER_DEG / max(math.cos(math.radians(dec)), 1e-6), dec + pd * dt / MAS_PER_DEG


def sep_arcsec(ra, dec, ra2, dec2):
    c = math.cos(math.radians(dec))
    return math.hypot(((ra - ra2 + 180) % 360 - 180) * c, dec - dec2) * 3600


def abs_g(g, plx):
    """Absolute G magnitude from apparent G and parallax (mas); None without a positive parallax."""
    return None if g is None or plx is None or plx <= 0 else g + 5 * math.log10(plx) - 10


def _star_row(r, ra, dec, epoch):
    e_ra, e_dec = move_to(r, epoch)
    g, plx, pe = _f(r["phot_g_mean_mag"]), _f(r["parallax"]), _f(r["parallax_error"])
    good_plx = plx is not None and pe is not None and plx > 0 and plx > 5 * pe
    nss = (r.get("non_single_star") or "").strip()
    return {"source_id": r["source_id"], "ra": round(float(r["ra"]), 7), "dec": round(float(r["dec"]), 7),
            "ra_now": round(e_ra, 6), "dec_now": round(e_dec, 6), "sep": round(sep_arcsec(e_ra, e_dec, ra, dec), 2),
            "g": _rd(g, 3), "bp": _rd(_f(r["phot_bp_mean_mag"]), 3), "rp": _rd(_f(r["phot_rp_mean_mag"]), 3),
            "bp_rp": _rd(_f(r["bp_rp"]), 3),
            "plx": _rd(plx, 4), "plx_err": _rd(pe, 4), "dist_pc": round(1000 / plx, 2 if plx > 50 else 1) if good_plx else None,
            "abs_g": round(abs_g(g, plx), 3) if good_plx and g is not None else None,
            "pmra": _rd(_f(r["pmra"]), 2), "pmdec": _rd(_f(r["pmdec"]), 2), "pm": _rd(_f(r["pm"]), 2), "ruwe": _rd(_f(r["ruwe"]), 3),
            "variable": r["phot_variable_flag"] or None, "rv": _rd(_f(r["radial_velocity"]), 2), "teff": _rd(_f(r["teff_gspphot"]), 0),
            "nss": int(r["non_single_star"]) if nss not in ("", "0") else 0,
            "p_star": _rd(_f(r["classprob_dsc_combmod_star"]), 4), "p_galaxy": _rd(_f(r["classprob_dsc_combmod_galaxy"]), 4),
            "p_quasar": _rd(_f(r["classprob_dsc_combmod_quasar"]), 4)}


def variability(source_id, timeout=60, log=None):
    """Gaia's variability summary and its best classifier class for one source, or None."""
    sid = int(source_id)
    rows = query("SELECT s.source_id, s.num_selected_g_fov, s.time_duration_g_fov, s.range_mag_g_fov, s.std_dev_mag_g_fov, "
                 "s.trimmed_range_mag_g_fov, c.best_class_name, c.best_class_score FROM gaiadr3.vari_summary AS s "
                 "LEFT OUTER JOIN gaiadr3.vari_classifier_result AS c ON c.source_id = s.source_id "
                 f"WHERE s.source_id = {sid}", timeout=timeout, log=log)
    if not rows:
        return None
    r = rows[0]
    return {"n_obs": int(r["num_selected_g_fov"]) if r["num_selected_g_fov"] else None, "days": _rd(_f(r["time_duration_g_fov"]), 1),
            "range_mag": _rd(_f(r["range_mag_g_fov"]), 3), "trimmed_range_mag": _rd(_f(r["trimmed_range_mag_g_fov"]), 3),
            "std_mag": _rd(_f(r["std_dev_mag_g_fov"]), 3), "cls": r["best_class_name"] or None, "cls_score": _rd(_f(r["best_class_score"]), 3)}


def star(ra, dec, epoch=2025.8, r_match=1.5 * PIX, r_near=30.0, timeout=60, log=None):
    """The Gaia DR3 source a click at (ra, dec) on an image taken at `epoch` most likely means, and its neighbours.

    Gaia positions are moved to `epoch` with their proper motions first (Barnard's Star is ~100" from its 2016
    position by 2026). The match is the brightest source within r_match (1.5 SPHEREx pixels: the image cannot tell
    closer stars apart, and the bright one is what the eye sees); neighbours are all sources within r_near."""
    r_out = r_near + (FAST_R if abs(epoch - EPOCH) > 1 else 0)
    q = (f"SELECT {','.join(STAR_COLS)} FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{r_out / 3600})) "
         f"AND (1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{(r_near + 15) / 3600})) OR pm>{FAST_PM})")
    rows = query(q, timeout=timeout, log=log)
    stars = sorted((s for s in (_star_row(r, ra, dec, epoch) for r in rows) if s["sep"] <= r_near), key=lambda s: s["sep"])
    inside = [s for s in stars if s["sep"] <= r_match]
    best = min(inside, key=lambda s: (s["g"] is None, s["g"] or 0.0)) if inside else None
    if best and best["variable"] == "VARIABLE":
        try:
            best["vari"] = variability(best["source_id"], timeout=timeout, log=log)
        except GaiaError as e:
            best["vari"] = None
            best["vari_error"] = str(e)[:200]
    return {"ra": ra, "dec": dec, "epoch": round(epoch, 3), "r_match": round(r_match, 2), "r_near": r_near,
            "star": best, "neighbours": [s for s in stars if not best or s["source_id"] != best["source_id"]][:N_NEIGHBOURS],
            "n_near": len(stars), "service": last["service"]}


# ---- variables in a field -------------------------------------------------------------------------------------
def field_variables(ra, dec, radius_deg, max_g=None, timeout=200, log=None):
    """Every Gaia DR3 source flagged VARIABLE within radius_deg, with its variability summary and best class
    (vari_classifier_result; '' when Gaia did not classify it)."""
    w = f"1=CONTAINS(POINT(g.ra,g.dec),CIRCLE({ra},{dec},{radius_deg})) AND g.phot_variable_flag='VARIABLE'"
    if max_g is not None:
        w += f" AND g.phot_g_mean_mag<{max_g}"
    q = ("SELECT g.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, g.bp_rp, g.parallax, "
         "s.num_selected_g_fov, s.range_mag_g_fov, s.trimmed_range_mag_g_fov, s.std_dev_mag_g_fov, "
         "c.best_class_name, c.best_class_score FROM gaiadr3.gaia_source AS g "
         "JOIN gaiadr3.vari_summary AS s ON s.source_id = g.source_id "
         "LEFT OUTER JOIN gaiadr3.vari_classifier_result AS c ON c.source_id = g.source_id "
         f"WHERE {w}")
    return query(q, timeout=timeout, log=log)
