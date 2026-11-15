"""All-sky background picture of the home page's sky map.

Three wavelengths of the SPHEREx DR1 all-sky HiPS cube at NASA/IPAC IRSA (order 3: one Allsky_<frame>.png per frame,
768 tiles of 64 x 64 pixels, i.e. HEALPix nside 512, about 7 arcmin a pixel) are reprojected to the Hammer-Aitoff
projection the map places its markers in: RA increasing to the left, centre RA 180 deg, the ellipse filling the
picture exactly (the same maths as hammer() in web/app/src/landing.jsx). Outside the ellipse the picture is transparent.

    python scripts/allsky_map.py                 # -> web/app/public/media/allsky.webp (about 70 kB)
    python scripts/allsky_map.py --frames 88 46 16 --width 1600 --quality 60

Frame index = 17 * (detector - 1) + (channel - 1); the defaults are 4.53 um (red), 2.19 um (green), 1.10 um (blue).
The downloads are kept in cache/allsky/. Set SX_INSECURE=1 on networks that need TLS verification off (as in sxlib).
"""
import argparse
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CACHE, MEDIA, VERIFY  # noqa: E402

HIPS = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube"
ORDER, TILE, NCOL = 3, 64, 27             # the Allsky preview: order-3 tiles, 64 px each, 27 tiles a row
S2 = np.sqrt(2.0)
SS = 2                                    # sample 2 x 2 points per output pixel, then average
STRETCH = (50, 99.95)                     # percentiles: the empty sky goes to black, the Galactic plane to white
GAMMA = 0.8
COLOUR_MIX, GREY_MIX = 0.65, 0.35         # pull the colour towards grey a little
BLUR = 0.7


def allsky(frame, cache):
    """The order-3 all-sky preview of one frame of the cube, as a float array (grey levels 0..255)."""
    from PIL import Image
    p = cache / f"Allsky_{frame}.png"
    if not p.exists():
        import requests
        if not VERIFY:
            import urllib3
            urllib3.disable_warnings()
        r = requests.get(f"{HIPS}/Norder{ORDER}/Allsky{'' if frame == 0 else f'_{frame}'}.png", timeout=120,
                         verify=VERIFY, headers={"User-Agent": "allsky-map-script"})
        r.raise_for_status()
        cache.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    return np.asarray(Image.open(p).convert("L"), dtype=np.float32)


def inv_hammer(x, y):
    """Hammer-Aitoff plane (x in +-2*sqrt2, y in +-sqrt2) -> RA, Dec in degrees and the inside-the-ellipse mask."""
    ok = x * x / 8 + y * y / 2 <= 1
    z = np.sqrt(np.clip(1 - (x / 4) ** 2 - (y / 2) ** 2, 0, None))
    lon = 2 * np.arctan2(z * x, 2 * (2 * z * z - 1))
    lat = np.arcsin(np.clip(z * y, -1, 1))
    return (np.degrees(-lon) + 180) % 360, np.degrees(lat), ok


def compact(v):
    """Every second bit of v (the x or y index inside a tile, from the nested HEALPix index)."""
    out = np.zeros_like(v)
    for k in range(6):
        out |= ((v >> (2 * k)) & 1) << k
    return out


def main():
    import astropy.units as u
    from astropy_healpix import lonlat_to_healpix
    from PIL import Image, ImageFilter

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frames", type=int, nargs=3, default=[88, 46, 16], help="cube frames for red, green, blue")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=60)
    ap.add_argument("--out", type=Path, default=MEDIA / "allsky.webp")
    ap.add_argument("--cache", type=Path, default=CACHE / "allsky")
    a = ap.parse_args()

    w, h = a.width * SS, a.width // 2 * SS
    px, py = np.meshgrid((np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h)
    ra, dec, ok = inv_hammer((px - 0.5) * 4 * S2, (0.5 - py) * 2 * S2)
    idx = np.asarray(lonlat_to_healpix(ra * u.deg, dec * u.deg, 2 ** ORDER * TILE, order="nested"))
    tile, sub = idx >> 12, idx & 4095
    # inside a tile the HEALPix x index runs down the rows and the y index along the columns (checked against the
    # Galactic plane: this orientation, of the eight possible, is the one that makes the Milky Way continuous)
    row, col = (tile // NCOL) * TILE + compact(sub), (tile % NCOL) * TILE + compact(sub >> 1)

    box = lambda v: v.reshape(h // SS, SS, w // SS, SS).mean(axis=(1, 3))      # noqa: E731
    alpha = box(ok.astype(np.float32))
    inside = alpha > 0.99
    rgb = []
    for f in a.frames:
        c = box(allsky(f, a.cache)[row, col])
        lo, hi = np.percentile(c[inside], STRETCH)
        rgb.append(np.clip((c - lo) / (hi - lo), 0, 1) ** GAMMA)
    img = np.stack(rgb, -1)
    img = COLOUR_MIX * img + GREY_MIX * img.mean(axis=-1, keepdims=True)
    out = Image.fromarray(np.dstack([np.round(img * 255), np.round(alpha * 255)]).astype(np.uint8), "RGBA")
    r, g, b, al = out.split()
    out = Image.merge("RGBA", [*(ch.filter(ImageFilter.GaussianBlur(BLUR)) for ch in (r, g, b)), al])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(a.out, "WEBP", quality=a.quality, method=6)
    print(f"{a.out}: {out.size[0]} x {out.size[1]}, {a.out.stat().st_size / 1024:.0f} kB, frames {a.frames} (R, G, B)")


if __name__ == "__main__":
    main()
