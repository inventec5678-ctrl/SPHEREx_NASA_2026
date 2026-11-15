"""Our target spectra against IRSA's SPHEREx Spectrophotometry Tool.

  python scripts/irsa_spectro_compare.py run [ids]       submit the IRSA jobs that are not cached, wait, then compare
  python scripts/irsa_spectro_compare.py compare [ids]   compare only, from the cached IRSA results (no network)
      ids: target ids (default: the five challenge targets); 'barnard.new' reads web/data/fields/barnard.new
      --refresh   resubmit even when a cached result exists

The tool (https://irsa.ipac.caltech.edu/applications/spherex/tool-spectrophotometry, help: onlinehelp/spherex/#sp)
fits the SPHEREx PSF with The Tractor at a fixed position in every spectral image (forced photometry; the position is
not re-centred) and returns one flux per image in µJy. It has a web form only. The form's Submit button POSTs the
Data Explorer's own (Firefly) endpoint CmdSrv/async with cmd=tableSearch and id=SpectrophotometryProcessor; that
server forwards the job to an IVOA UWS service (api/spherex/spectrophotometry/async, parameters POINT and TIME). A
direct POST to the UWS service is refused (403), but the job record and its result VOTable are public GETs. This
script sends exactly the form's request, without a browser; there is no login or bot check. IRSA allows two running
jobs per user, so the script never has more than two in flight.

Moving targets: one job per survey pass (a time window around the pass, the position at mid-pass from
sxlib.targets.position_at). Variable targets: one job for the whole span. Every IRSA measurement is matched to ours
by exposure (obs_id + detector), so the per-exposure ratio is immune to the star's own variability.

Writes web/data/validation/spectro.json; caches each job record and result under cache/irsa_spectro/<target>/.
"""
import hashlib
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE as _CACHE_ROOT, FIELDS, VALIDATION, insecure as _insecure, read_json, rel, write_json  # noqa: E402,F401

CACHE = _CACHE_ROOT / "irsa_spectro"
OUT = VALIDATION / "spectro.json"
APP = "https://irsa.ipac.caltech.edu/applications/spherex/"
TOOL_URL = APP + "tool-spectrophotometry"
HELP_URL = "https://irsa.ipac.caltech.edu/onlinehelp/spherex/#sp"
UA = "Mozilla/5.0 (X11; Linux x86_64) research-client"
DEFAULT_IDS = ["barnard", "epsindi", "wise0855", "rwaur", "rdra"]
MAX_RUNNING = 2              # IRSA's throttle: two spectrophotometry jobs per user at a time
PASS_GAP_D = 20.0            # frames further apart than this belong to different survey passes
PAD_D = 0.5                  # time window padding (days)
SNR_MIN = 10.0               # both measurements must have S/N above this to enter the ratio
BIT_BAD, BIT_FITERR = 1 << 32, 1 << 33     # IRSA output flags: CONTAINS_BAD_PIXEL, FIT_ERROR
VO_NS = "{http://www.ivoa.net/xml/VOTable/v1.3}"
UWS_NS = {"uws": "http://www.ivoa.net/xml/UWS/v1.0", "xlink": "http://www.w3.org/1999/xlink"}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
POLL_S = 30                  # seconds between UWS status polls
DIRECT_EVERY = 4             # every this many polls, also try the result's usual address directly
MAD_SIGMA = 1.4826           # MAD -> Gaussian sigma

# why a target's comparison needs care; the page turns the code into words
CAVEAT = {"barnard": "saturated", "rwaur": "variable", "rdra": "variable", "wise0855": "faint", "epsindi": "pair"}


# ---------------------------------------------------------------------------------------------- IRSA side
def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    if _insecure():
        requests.packages.urllib3.disable_warnings()
    return s


def job_key(point, window):
    """Cache key of one job: the position to 1e-6 deg and the window to 0.01 d."""
    s = f"{point[0]:.6f},{point[1]:.6f}|{window[0]:.2f},{window[1]:.2f}"
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def split_passes(mjds, gap=PASS_GAP_D):
    """Group observation times into survey passes: [(first, last), ...] in time order."""
    t = np.sort(np.asarray(mjds, float))
    if not len(t):
        return []
    cut = np.where(np.diff(t) > gap)[0]
    starts, ends = np.r_[0, cut + 1], np.r_[cut, len(t) - 1]
    return [(float(t[a]), float(t[b])) for a, b in zip(starts, ends)]


def plan(tid):
    """The jobs for one target: [{k, point, window, key}]. Asks IRSA (SIA) when the target was observed."""
    from sxlib import archive, targets
    t = targets.TARGETS[tid]
    ra0, dec0 = targets.centre_2026(t)
    mjds = [r["mjd"] for r in archive.search_images(ra0, dec0, radius=0.01)]
    passes = split_passes(mjds)
    if t["kind"] != "pm" and passes:                  # barely moves: one job for the whole span
        passes = [(passes[0][0], passes[-1][1])]
    jobs = []
    for k, (a, b) in enumerate(passes):
        ra, dec = targets.position_at(t, [(a + b) / 2])
        point, window = (round(float(ra[0]), 7), round(float(dec[0]), 7)), (round(a - PAD_D, 3), round(b + PAD_D, 3))
        jobs.append({"k": k, "point": point, "window": window, "key": job_key(point, window)})
    return jobs


def submit(sess, tid, job):
    """Send the web form's request (Firefly CmdSrv/async, SpectrophotometryProcessor). Returns IRSA's job record."""
    tbl = f"Spec-photo-tbl-{tid}-{job['key']}"
    req = {"startIdx": 0, "pageSize": 100, "META_INFO": {"title": f"{tid} window {job['k'] + 1}", "tbl_id": tbl}, "tbl_id": tbl,
           "id": "SpectrophotometryProcessor", "UserTargetWorldPt": f"{job['point'][0]:.7f};{job['point'][1]:.7f};EQ_J2000",
           "CONE_AREA_KEY_RESERVED": "CONE", "shapeFit": "false", "useDeep": "",
           "startTime": job["window"][0], "endTime": job["window"][1], "exposureTimeMode": "mjd"}
    sess.get(APP, timeout=60, verify=not _insecure())
    r = sess.post(APP + "CmdSrv/async", data={"cmd": "tableSearch", "request": json.dumps(req)}, timeout=120, verify=not _insecure())
    r.raise_for_status()
    js = r.json()
    if not js.get("jobInfo", {}).get("jobUrl"):
        raise RuntimeError(f"IRSA did not accept the job: {str(js)[:300]}")
    return js


def uws_status(sess, url):
    """(phase, [result hrefs], error message) from the public UWS job record."""
    r = sess.get(url, timeout=60, verify=not _insecure())
    r.raise_for_status()
    x = ET.fromstring(r.content)
    phase = (x.findtext("uws:phase", "", UWS_NS) or "").strip()
    hrefs = [e.get(XLINK_HREF) for e in x.findall("uws:results/uws:result", UWS_NS)]
    err = " ".join((e.text or "").strip() for e in x.findall("uws:errorSummary/uws:message", UWS_NS))
    return phase, [h for h in hrefs if h], err


def run_jobs(tids, refresh=False, log=print, give_up_s=4 * 3600):
    """Submit, wait for and download every job of these targets that is not cached yet (two running at a time)."""
    sess = _session()
    todo = []
    for tid in tids:
        d = CACHE / tid
        d.mkdir(parents=True, exist_ok=True)
        for j in plan(tid):
            j["tid"] = tid
            rec = d / f"{j['key']}.json"
            if rec.exists() and not refresh:
                old = read_json(rec)
                if old.get("result") and (d / old["result"]).exists():
                    continue
                if old.get("job_url") and old.get("phase") not in ("ERROR", "ABORTED"):
                    j.update({k: old[k] for k in ("job_id", "job_url", "submitted") if k in old})
            todo.append(j)
    log(f"{len(todo)} IRSA jobs to run")
    save = lambda j: write_json(CACHE / j["tid"] / f"{j['key']}.json", j)  # noqa: E731
    name = lambda j: f"{j['tid']} window {j['k'] + 1}"  # noqa: E731
    waiting, running, polls = list(todo), [], {}
    t_start = time.time()
    while (waiting or running) and time.time() - t_start < give_up_s:
        while waiting and len(running) < MAX_RUNNING:
            j = waiting.pop(0)
            if not j.get("job_url"):
                js = submit(sess, j["tid"], j)
                j.update({"job_id": js["jobId"], "job_url": js["jobInfo"]["jobUrl"],
                          "submitted": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                log(f"{name(j)}: submitted {j['job_id']} mjd {j['window']}")
            save(j)
            running.append(j)
        time.sleep(POLL_S)
        for j in list(running):
            polls[j["key"]] = polls.get(j["key"], 0) + 1
            try:
                phase, hrefs, err = uws_status(sess, j["job_url"])
            except Exception as e:  # noqa: BLE001 - a transient error: ask again next round
                log(f"{name(j)}: status check failed ({e})"); continue
            # the job record is served by several hosts and one can lag behind: every few rounds also try the
            # result's usual address directly
            if not hrefs and polls[j["key"]] % DIRECT_EVERY == 0:
                hrefs = [j["job_url"] + "/results/phot-tool-result.vot"]
            if hrefs:
                r = sess.get(hrefs[0], timeout=300, verify=not _insecure())
                if r.ok and r.content.lstrip().startswith(b"<?xml") and b"VOTABLE" in r.content[:2000]:
                    f = f"{j['key']}.vot"
                    (CACHE / j["tid"] / f).write_bytes(r.content)
                    j.update({"phase": "COMPLETED", "result": f, "result_url": hrefs[0],
                              "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    save(j)
                    running.remove(j)
                    log(f"{name(j)}: done, {len(r.content) // 1024} kB")
                    continue
            if phase in ("ERROR", "ABORTED"):
                j["phase"], j["error"] = phase, err
                save(j)
                running.remove(j)
                log(f"{name(j)}: {phase} {err}")
    for j in waiting + running:
        log(f"{name(j)}: not finished; run again later to pick it up")


# ---------------------------------------------------------------------------------------------- parsing
def _split_fixed(text, width):
    """A VOTable char array with arraysize 'Nx*': fixed-width strings, one after another."""
    text = text or ""
    return [text[i:i + width].strip() for i in range(0, len(text), width)]


def parse_result(xml_bytes):
    """IRSA's result VOTable -> list of sources, each {ra, dec, n_meas, rows: [{lam, width, flux, err, mjd, coll, det,
    flags, fit_ql, bkg, obs_id}]}. Parsed by hand: astropy refuses the 'Nx*' char arrays the service writes."""
    root = ET.fromstring(xml_bytes)
    out = []
    for table in root.iter(f"{VO_NS}TABLE"):
        fields = [f.attrib for f in table.findall(f"{VO_NS}FIELD")]
        names = [f["name"] for f in fields]
        if "flux" not in names:
            continue
        for tr in table.iter(f"{VO_NS}TR"):
            cells = {}
            for f, td in zip(fields, tr.findall(f"{VO_NS}TD")):
                txt, size = td.text or "", f.get("arraysize") or ""
                if f.get("datatype") == "char":
                    cells[f["name"]] = _split_fixed(txt, int(size.split("x")[0])) if "x" in size else txt.strip()
                elif "*" in size:
                    cells[f["name"]] = txt.split()
                else:
                    cells[f["name"]] = txt.strip()
            n = len(cells.get("flux", []))
            num = lambda k, cast=float: [cast(v) if v not in ("NaN", "") else math.nan for v in cells.get(k, [])] or [math.nan] * n  # noqa: E731
            lam, wid, flux, err, mjd = num("lambda"), num("lambda_width"), num("flux"), num("flux_err"), num("mjd")
            flags, det = [int(v) for v in cells.get("flags", [0] * n)], [int(v) for v in cells.get("det_id", [0] * n)]
            qual, bkg = num("fit_ql"), num("flux_bkg")
            coll = cells.get("data_collection") or [""] * n
            did = cells.get("obs_publisher_did") or [""] * n
            rows = []
            for i in range(n):
                obs = did[i].split("?", 1)[-1].split("/")[0] if did[i] else ""
                rows.append({"lam": lam[i], "width": wid[i], "flux": flux[i], "err": err[i], "mjd": mjd[i], "coll": coll[i],
                             "det": det[i], "flags": flags[i], "fit_ql": qual[i], "bkg": bkg[i], "obs_id": obs})
            out.append({"ra": float(cells.get("ra") or "nan"), "dec": float(cells.get("dec") or "nan"),
                        "n_meas": int(cells.get("n_meas") or n), "rows": rows})
    return out


# ---------------------------------------------------------------------------------------------- comparison
def robust(values):
    """Median and robust scatter (1.4826 x MAD) of a list; None when empty."""
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], float)
    if not len(v):
        return None
    med = float(np.median(v))
    return {"median": round(med, 4), "scatter": round(float(MAD_SIGMA * np.median(np.abs(v - med))), 4), "n": int(len(v))}


def pass_of(mjd, passes):
    for q in passes:
        if q["mjd0"] - 1 <= mjd <= q["mjd1"] + 1:
            return int(q["k"])
    return -1


def irsa_ok(r):
    return not (r["flags"] & (BIT_BAD | BIT_FITERR)) and np.isfinite(r["flux"]) and np.isfinite(r["err"]) and r["err"] > 0


def match(doc, irsa_rows):
    """Pair every IRSA measurement with our point of the same exposure (obs_id, detector)."""
    exps = doc["exposures"]
    ours = {}
    for p in doc["target"]["points"]:
        e = exps[p["i"]]
        ours[(e["obs_id"], int(p["det"]))] = (p, e)
    pairs, irsa_only = [], 0
    for r in irsa_rows:
        hit = ours.pop((r["obs_id"], int(r["det"])), None)
        if hit is None:
            irsa_only += 1
        else:
            pairs.append((r, hit[0], hit[1]))
    return pairs, irsa_only, len(ours)


def compare_target(tid, field_dir=None, cache=CACHE):
    """The comparison for one target, from field.json and the cached IRSA results. None if either is missing."""
    base = tid.split(".")[0]
    fdir = field_dir or FIELDS / tid
    try:
        doc = read_json(fdir / "field.json")
    except OSError:
        return None
    if not doc.get("target"):
        return None
    jobs, rows = [], []
    for rec in sorted((cache / base).glob("*.json")):
        j = read_json(rec)
        if not j.get("result") or not (cache / base / j["result"]).exists():
            continue
        src = parse_result((cache / base / j["result"]).read_bytes())
        got = [r for s in src for r in s["rows"]]
        rows += got
        jobs.append({"window": j["k"] + 1, "job_id": j.get("job_id"), "submitted": j.get("submitted"), "point": j["point"],
                     "mjd": j["window"], "n": len(got)})
    if not rows:
        return None
    # the same exposure can appear in two overlapping windows: keep one
    seen, uniq = set(), []
    for r in rows:
        k = (r["obs_id"], r["det"])
        if k not in seen:
            seen.add(k); uniq.append(r)
    rows = uniq
    passes = doc["products"]["passes"]
    pairs, irsa_only, ours_only = match(doc, rows)
    pts, r_ap, r_psf, dlam = [], [], [], []
    per = {}
    rnd = lambda v: None if v is None or not np.isfinite(v) else float(f"{v:.4g}")  # noqa: E731
    for r, p, e in sorted(pairs, key=lambda x: x[0]["lam"]):
        k = pass_of(p["mjd"], passes)
        i_ok = irsa_ok(r)
        o_ok = (p.get("flag") or 0) == 0
        snr_i = r["flux"] / r["err"] if i_ok else 0
        ap = p.get("f") if (p.get("f") is not None and p.get("e")) else None
        psf = p.get("psf") if (p.get("psf") is not None and p.get("psf_e")) else None
        use_ap = i_ok and o_ok and ap is not None and snr_i > SNR_MIN and ap / p["e"] > SNR_MIN
        use_psf = i_ok and psf is not None and not p.get("psf_sat") and snr_i > SNR_MIN and psf / p["psf_e"] > SNR_MIN
        if use_ap:
            r_ap.append(ap / r["flux"]); per.setdefault(("ap", "det", r["det"]), []).append(ap / r["flux"])
            per.setdefault(("ap", "pass", k), []).append(ap / r["flux"])
        if use_psf:
            r_psf.append(psf / r["flux"]); per.setdefault(("psf", "det", r["det"]), []).append(psf / r["flux"])
            per.setdefault(("psf", "pass", k), []).append(psf / r["flux"])
        if np.isfinite(r["lam"]) and p.get("lam"):
            dlam.append(p["lam"] - r["lam"]); per.setdefault(("dlam", "det", r["det"]), []).append(p["lam"] - r["lam"])
        # compact row for the chart: lam, IRSA flux, IRSA error, our aperture flux, our PSF flux, pass, detector, bits
        bits = (1 if i_ok else 0) | (2 if o_ok else 0) | (4 if use_ap else 0) | (8 if use_psf else 0) | (16 if p.get("psf_sat") else 0)
        pts.append([round(r["lam"], 4), rnd(r["flux"]), rnd(r["err"]), rnd(ap), rnd(psf), k, int(r["det"]), bits])
    stats = {key: robust(v) for key, v in per.items()}
    split = lambda kind, by: [{by: key[2], **st} for key, st in sorted(stats.items(), key=lambda kv: kv[0][2])  # noqa: E731
                              if key[0] == kind and key[1] == by and st]
    exps = doc["exposures"]
    rel = Counter(e.get("release") or "not recorded" for e in exps)
    return {
        "id": base, "name": doc["target"]["name"], "kind": doc["target"]["kind"], "caveat": CAVEAT.get(base),
        "meaningful": base != "barnard",
        "irsa": {"jobs": jobs, "n": len(rows), "collections": dict(Counter(r["coll"] for r in rows)),
                 "flagged_bad": sum(1 for r in rows if not irsa_ok(r))},
        "ours": {"field": fdir.name, "field_created": doc.get("created"), "n": len(doc["target"]["points"]),
                 "releases": dict(rel), "aperture_px": doc["target"].get("aperture_px"),
                 "psf_fitted": (doc["target"].get("psf_check") or {}).get("n_fitted")},
        "n_matched": len(pairs), "irsa_only": irsa_only, "ours_only": ours_only,
        "ratio_aperture": robust(r_ap), "ratio_psf": robust(r_psf),
        "ratio_aperture_by_det": split("ap", "det"), "ratio_psf_by_det": split("psf", "det"),
        "ratio_aperture_by_pass": split("ap", "pass"), "ratio_psf_by_pass": split("psf", "pass"),
        "dlam_um": robust(dlam), "dlam_um_by_det": split("dlam", "det"),
        "points": pts,
    }


def compare(ids, log=print):
    res = []
    for tid in ids:
        c = compare_target(tid)
        if c is None:
            log(f"{tid}: no field or no cached IRSA result"); continue
        res.append(c)
        a, p, w = c["ratio_aperture"], c["ratio_psf"], c["dlam_um"]
        log(f"{tid}: matched {c['n_matched']} (IRSA only {c['irsa_only']}, ours only {c['ours_only']}); "
            f"aperture/IRSA {a and a['median']} ±{a and a['scatter']} (n {a and a['n']}); "
            f"PSF/IRSA {p and p['median']} ±{p and p['scatter']} (n {p and p['n']}); λ ours−IRSA {w and w['median']} µm")
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": {"name": "IRSA SPHEREx Spectrophotometry Tool", "url": TOOL_URL, "help": HELP_URL,
                 "method": "The Tractor forced PSF photometry at a fixed position, local background fitted, µJy via the pixel solid-angle map",
                 "interface": "the Data Explorer's web-form request (Firefly CmdSrv/async, SpectrophotometryProcessor), "
                              "forwarded by IRSA to its UWS service api/spherex/spectrophotometry/async; results read from the public UWS job record",
                 "bad_bits": "CONTAINS_BAD_PIXEL (bit 32) or FIT_ERROR (bit 33) set -> left out"},
        "ours": {"aperture": "2-pixel (12.3″) radius aperture, sky from a 5-9 pixel annulus, no aperture correction (sxlib/products.py phot)",
                 "psf": "SPHEREx PSF fitted on the resampled field grid, position refined by up to 0.6 pixel (sxlib/psfphot.py)"},
        "selection": {"snr_min": SNR_MIN, "ours_flag": "0 (no bad, ghost or outlier pixel)", "ratio": "ours / IRSA, same exposure"},
        "targets": res,
    }
    if res:
        old = None
        if OUT.exists():
            try:
                old = read_json(OUT)
            except ValueError:
                pass
        if old:                                       # keep targets compared earlier that were not redone this time
            have = {t["id"] for t in res}
            doc["targets"] = res + [t for t in old.get("targets", []) if t["id"] not in have]
            order = {k: j for j, k in enumerate(DEFAULT_IDS)}
            doc["targets"].sort(key=lambda t: order.get(t["id"], 99))
        write_json(OUT, doc, compact=True)
        log(f"wrote {rel(OUT)} ({OUT.stat().st_size // 1024} kB)")
    return doc


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or args[0] not in ("run", "compare"):
        print(__doc__); sys.exit(1)
    ids = args[1:] or DEFAULT_IDS
    if args[0] == "run":
        run_jobs(list(dict.fromkeys(t.split(".")[0] for t in ids)), refresh="--refresh" in sys.argv)
    compare(ids)
