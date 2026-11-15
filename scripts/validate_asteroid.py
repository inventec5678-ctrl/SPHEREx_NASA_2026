"""Step-0 validation: can we see a known asteroid move in SPHEREx images?

1. SkyBoT: pick a known asteroid (V in range) near a sky position at a reference time.
2. JPL Horizons: ephemeris over the time window.
3. IRSA SIA: SPHEREx images that cover the asteroid's path.
4. IRSA cutouts: "tracked" (centered on predicted position at each image time)
   and "fixed" (same sky spot for every image) stamps.
5. Measure whether a source sits at the predicted position (offset, S/N), and save
   a PNG grid + blink GIF.

  python scripts/validate_asteroid.py --ra 90 --dec 23 --start 2025-12-15 --days 8 --insecure
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import OUTPUTS, write_json  # noqa: E402

SIA = "https://irsa.ipac.caltech.edu/SIA"
SKYBOT = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
COLLECTIONS = ["spherex_qr2", "spherex_qr3"]
VERIFY = _common.VERIFY         # --insecure (or SX_INSECURE=1) turns certificate checks off
PIX_ARCSEC = 6.15
DET_SNR, DET_OFFSET_PX = 5, 1.5  # detection rule
_S = requests.Session()


def get(url, **params):
    r = _S.get(url, params=params, timeout=300, verify=VERIFY)
    r.raise_for_status()
    return r


def pick_asteroid(ra, dec, t: Time, radius, vmin, vmax):
    txt = get(SKYBOT, **{"-ep": f"{t.jd:.5f}", "-ra": ra, "-dec": dec, "-rd": radius,
                         "-mime": "text", "-output": "basic", "-loc": "500"}).text
    rows = []
    for line in txt.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        f = [x.strip() for x in line.split("|")]
        num, name, mv = f[0], f[1], float(f[5])
        if vmin <= mv <= vmax:
            rows.append({"num": num, "name": name, "class": f[4], "V": mv,
                         "rate_arcsec_h": float(np.hypot(float(f[8]), float(f[9])))})
    rows.sort(key=lambda r: r["V"])
    return rows


def ephemeris(target, start: Time, stop: Time, step="30m"):
    cmd = f"'{target};'"  # trailing ';' = small-body lookup (else '65' could hit a major-body id)
    js = get(HORIZONS, format="json", COMMAND=cmd, EPHEM_TYPE="OBSERVER", CENTER="'500@399'",
             START_TIME=f"'{start.iso[:16]}'", STOP_TIME=f"'{stop.iso[:16]}'", STEP_SIZE=f"'{step}'",
             QUANTITIES="'1,9'", ANG_FORMAT="DEG", CSV_FORMAT="YES", CAL_FORMAT="JD").json()
    body = js["result"].split("$$SOE")[1].split("$$EOE")[0]
    jd, ra, dec, vmag = [], [], [], []
    for row in csv.reader(io.StringIO(body)):
        if len(row) < 5:
            continue
        jd.append(float(row[0])); ra.append(float(row[3])); dec.append(float(row[4]))
        vmag.append(float(row[5]) if row[5].strip() not in ("", "n.a.") else np.nan)
    return {"mjd": np.array(jd) - 2400000.5, "ra": np.unwrap(np.radians(ra)), "dec": np.array(dec),
            "V": np.array(vmag)}


def position_at(eph, mjd):
    ra = np.degrees(np.interp(mjd, eph["mjd"], eph["ra"])) % 360
    return ra, float(np.interp(mjd, eph["mjd"], eph["dec"]))


def images_on_path(eph, every_h=6):
    seen = {}
    t0, t1 = eph["mjd"][0], eph["mjd"][-1]
    for mjd in np.arange(t0, t1, every_h / 24):
        ra, dec = position_at(eph, mjd)
        r = get(SIA, POS=f"circle {ra} {dec} 0.002", TIME=f"{mjd - every_h / 24} {mjd + every_h / 24}",
                RESPONSEFORMAT="CSV", COLLECTION=COLLECTIONS)
        for row in csv.DictReader(io.StringIO(r.text)):
            if row["dataproduct_subtype"] == "science":
                seen[row["access_url"]] = row
    return sorted(seen.values(), key=lambda x: float(x["t_min"]))


def in_polygon(ra, dec, s_region):
    nums = [float(x) for x in re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", s_region)]
    pr, pd = np.array(nums[0::2]), np.array(nums[1::2])
    # local tangent-plane test is fine for a 3.5 deg field
    x = ((pr - ra + 180) % 360 - 180) * np.cos(np.radians(dec)); y = pd - dec
    xj, yj = np.roll(x, 1), np.roll(y, 1)          # previous vertex (j = i - 1, wrapping)
    cross = (y > 0) != (yj > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        hit = cross & (0 < x + (0 - y) * (xj - x) / (yj - y))
    return bool(np.count_nonzero(hit) % 2)  # ray casting: odd number of crossings = inside


def cutout(url, ra, dec, size_deg):
    r = get(url, center=f"{ra},{dec}", size=size_deg)
    with fits.open(io.BytesIO(r.content)) as h:
        img = h["IMAGE"].data.astype(float) - h["ZODI"].data
        var = h["VARIANCE"].data.astype(float)
        flags = h["FLAGS"].data
        hdr = h["IMAGE"].header
        return img, var, flags, WCS(hdr), hdr


def measure(img, var, wcs, ra, dec, search_px=3):
    """S/N and offset of the brightest pixel within search_px of the predicted position."""
    x0, y0 = wcs.world_to_pixel(SkyCoord(ra, dec, unit="deg"))
    bkg = np.nanmedian(img)
    snr = (img - bkg) / np.sqrt(np.where(var > 0, var, np.nan))
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    near = (np.hypot(xx - x0, yy - y0) <= search_px) & np.isfinite(snr)
    if not near.any():
        return None
    k = np.nanargmax(np.where(near, snr, -np.inf))
    py, px = np.unravel_index(k, img.shape)
    return {"snr": float(snr[py, px]), "offset_px": float(np.hypot(px - x0, py - y0)),
            "x_pred": float(x0), "y_pred": float(y0)}


def stretch(a):
    a = a - np.nanmedian(a)
    s = np.nanpercentile(np.abs(a), 99) or 1
    return np.clip(np.arcsinh(a / (0.1 * s)) / np.arcsinh(10), -0.2, 1)


def main():
    global VERIFY
    ap = argparse.ArgumentParser(description="Step-0 check: see a known asteroid move in SPHEREx images")
    ap.add_argument("--ra", type=float, required=True)
    ap.add_argument("--dec", type=float, required=True)
    ap.add_argument("--start", required=True, help="ISO date, start of window")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--radius", type=float, default=2.0, help="SkyBoT search radius (deg)")
    ap.add_argument("--vmin", type=float, default=12.0)
    ap.add_argument("--vmax", type=float, default=15.5)
    ap.add_argument("--target", help="skip SkyBoT and use this asteroid (number or name)")
    ap.add_argument("--max-images", type=int, default=24)
    ap.add_argument("--size", type=float, default=0.05, help="cutout size (deg)")
    ap.add_argument("--out", default=str(OUTPUTS / "validate_asteroid"))
    ap.add_argument("--insecure", action="store_true")
    a = ap.parse_args()
    VERIFY = VERIFY and not a.insecure
    if not VERIFY:
        requests.packages.urllib3.disable_warnings()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    t0 = Time(a.start); t1 = Time(t0.mjd + a.days, format="mjd")
    tmid = Time((t0.mjd + t1.mjd) / 2, format="mjd")
    if a.target:
        target = a.target
    else:
        cands = pick_asteroid(a.ra, a.dec, tmid, a.radius, a.vmin, a.vmax)
        print(f"SkyBoT: {len(cands)} asteroids with {a.vmin}<=V<={a.vmax}")
        for c in cands[:5]:
            print("  ", c)
        if not cands:
            raise SystemExit("no candidate; widen --radius or --vmax")
        c = cands[0]
        target = c["num"] if c["num"] != "-" else c["name"]
    print("target:", target)

    eph = ephemeris(target, t0, t1)
    imgs = images_on_path(eph)
    imgs = [r for r in imgs if in_polygon(*position_at(eph, (float(r["t_min"]) + float(r["t_max"])) / 2),
                                          r["s_region"])]
    print(f"{len(imgs)} SPHEREx images contain the predicted path")
    if not imgs:
        raise SystemExit("asteroid path not covered in this window")
    step = max(1, len(imgs) // a.max_images)
    imgs = imgs[::step][:a.max_images]

    ref_mjd = (float(imgs[0]["t_min"]) + float(imgs[0]["t_max"])) / 2
    ref_ra, ref_dec = position_at(eph, ref_mjd)
    results, tracked, fixed = [], [], []
    for r in imgs:
        mjd = (float(r["t_min"]) + float(r["t_max"])) / 2
        ra, dec = position_at(eph, mjd)
        try:
            img, var, flags, wcs, hdr = cutout(r["access_url"], ra, dec, a.size)
            fimg, *_ = cutout(r["access_url"], ref_ra, ref_dec, a.size)
        except Exception as e:  # off-edge or service error
            print("  skip", r["obs_id"], e)
            continue
        m = measure(img, var, wcs, ra, dec)
        lam = 0.5 * (float(r["em_min"]) + float(r["em_max"])) * 1e6
        rec = {"obs_id": r["obs_id"], "band": r["energy_bandpassname"], "lambda_um": round(lam, 2),
               "mjd": mjd, "iso": Time(mjd, format="mjd").iso[:19], "ra": ra, "dec": dec,
               "V_pred": float(np.interp(mjd, eph["mjd"], eph["V"])), **(m or {})}
        results.append(rec)
        tracked.append((rec, stretch(img)))
        fixed.append((rec, stretch(fimg)))
        print(f"  {rec['iso']} {rec['band']} {lam:4.2f}um  S/N={rec.get('snr', float('nan')):6.1f} "
              f"offset={rec.get('offset_px', float('nan')):.2f}px")

    det = [r for r in results if r.get("snr", 0) >= DET_SNR and r["offset_px"] <= DET_OFFSET_PX]
    summary = {"target": str(target), "n_images": len(results), "n_detected": len(det),
               "detection_rule": "peak S/N>=5 within 1.5 px of prediction",
               "median_offset_arcsec": float(np.median([r["offset_px"] for r in det]) * PIX_ARCSEC) if det else None,
               "images": results}
    write_json(out / "summary.json", summary)
    print(f"detected in {len(det)}/{len(results)} images")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    n = len(tracked)
    fig, ax = plt.subplots(2, n, figsize=(1.6 * n, 3.6), squeeze=False)
    for i, ((rec, t), (_, f)) in enumerate(zip(tracked, fixed)):
        for row, im in ((0, t), (1, f)):
            ax[row, i].imshow(im, origin="lower", cmap="gray")
            ax[row, i].axis("off")
        ax[0, i].set_title(f"{rec['iso'][5:16]}\n{rec['lambda_um']}um", fontsize=6)
        ax[0, i].plot(rec.get("x_pred", 0), rec.get("y_pred", 0), "r+", ms=6)
    ax[0, 0].text(-0.3, 0.5, "tracked", transform=ax[0, 0].transAxes, rotation=90, va="center", fontsize=7)
    ax[1, 0].text(-0.3, 0.5, "fixed sky", transform=ax[1, 0].transAxes, rotation=90, va="center", fontsize=7)
    fig.suptitle(f"{target}: tracked on ephemeris (top) vs fixed sky position (bottom)", fontsize=8)
    fig.savefig(out / "grid.png", dpi=180, bbox_inches="tight")

    frames = [Image.fromarray((np.nan_to_num((f + 0.2) / 1.2) * 255).astype(np.uint8)).resize((240, 240), 0)
              for _, f in fixed]
    frames[0].save(out / "blink_fixed.gif", save_all=True, append_images=frames[1:], duration=400, loop=0)
    print("wrote", out / "grid.png", out / "blink_fixed.gif")


if __name__ == "__main__":
    main()
