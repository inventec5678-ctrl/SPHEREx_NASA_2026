"""The SPHEREx sky texture for the 3D cosmos on the home page.

Downloads the order-3 Allsky previews of three channels of the IRSA SPHEREx DR1 all-sky HiPS cube
(one 1728x1856 PNG per channel: 768 tiles of 64x64, i.e. HEALPix nside 512 nested) and reprojects them to one
equirectangular false-colour image, RA 0..360 left to right, Dec +90 at the top:

  blue 1.10 um (frame 16), green 2.19 um (frame 46), red 3.38 um (frame 64)

  python scripts/build_cosmos_sky.py            ->  web/app/public/cosmos/sky_4k.webp, sky_2k.webp

The HiPS is meant for viewing (IRSA's note), which is all this is for. Runs from any working directory.
"""
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PUBLIC, VERIFY  # noqa: E402

OUT = PUBLIC / "cosmos"
BASE = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube/Norder3"
FRAMES = {"b": 16, "g": 46, "r": 64}
TILE, ORDER, NCOL = 64, 3, 27                   # Allsky layout: 27 tiles per row, 64 px each
W, H = 4096, 2048                               # output size (equirectangular)
BIN = 4                                         # binning for the background map
BG_SIZE = 35                                    # median filter (binned pixels; ~12 deg)
STRETCH_LO, STRETCH_HI = 62, 99.85              # percentiles
ASINH = 10
QUALITY = 88


def allsky(frame):
    import requests
    from PIL import Image
    r = requests.get(f"{BASE}/Allsky_{frame}.png", timeout=120, verify=VERIFY)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    a = np.asarray(im.convert("LA") if im.mode in ("LA", "RGBA") else im.convert("L"), dtype=np.float32)
    return a[..., 0] if a.ndim == 3 else a


def deinterleave(v):
    """Morton code -> (a, b): a from the even bits, b from the odd bits."""
    a = np.zeros_like(v)
    b = np.zeros_like(v)
    for k in range(6):
        a |= ((v >> (2 * k)) & 1) << k
        b |= ((v >> (2 * k + 1)) & 1) << k
    return a, b


def mosaic_index():
    """(row, column) in the Allsky mosaic of every output pixel."""
    from astropy import units as u
    from astropy_healpix import HEALPix
    ra = (np.arange(W) + 0.5) / W * 360.0
    dec = 90.0 - (np.arange(H) + 0.5) / H * 180.0
    RA, DEC = np.meshgrid(ra, dec)
    hp = HEALPix(nside=2 ** (ORDER + 6), order="nested")
    ipix = hp.lonlat_to_healpix(RA * u.deg, DEC * u.deg).astype(np.int64)
    tile, sub = ipix >> 12, ipix & 4095
    even, odd = deinterleave(sub)
    # within a tile the column comes from the odd bits and the row from the even bits
    # (checked on the AllWISE HiPS: of the eight orientations this is the only one with a continuous Galactic plane)
    return (tile // NCOL) * TILE + even, (tile % NCOL) * TILE + odd


def main():
    from PIL import Image
    from scipy import ndimage
    py, px = mosaic_index()
    chans = {}
    for k, f in FRAMES.items():
        v = allsky(f)[py, px]
        # remove only the broad zodiacal-light glow (12 deg median on a 4x-binned map), keep stars and the Milky Way
        small = v.reshape(H // BIN, BIN, W // BIN, BIN).mean((1, 3))
        bg = ndimage.median_filter(small, size=(BG_SIZE, BG_SIZE), mode="wrap")
        r = v - ndimage.zoom(bg, BIN, order=1)
        if k == "b":
            r = ndimage.gaussian_filter(r, 0.7)                    # the 1.1 um channel is the noisiest
        lo, hi = np.percentile(r, [STRETCH_LO, STRETCH_HI])
        z = np.clip((r - lo) / (hi - lo), 0, 1)
        chans[k] = np.arcsinh(z * ASINH) / np.arcsinh(ASINH)
        print(f"frame {f}: stretch {lo:.1f}-{hi:.1f}", flush=True)
    rgb = np.stack([chans["r"], chans["g"], chans["b"]], -1)
    # faint pixels grey, bright ones in colour: the per-channel noise (scan stripes at 1.1 um) stays out of the dark sky
    lum = rgb.mean(-1, keepdims=True)
    sat = np.clip((lum - 0.12) / 0.35, 0, 1)
    rgb = np.clip(lum + sat * (rgb - lum), 0, 1) * np.clip(lum * 4, 0.35, 1)
    img = Image.fromarray((rgb * 255).astype(np.uint8))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "sky_4k.webp", quality=QUALITY, method=6)
    img.resize((W // 2, H // 2), Image.LANCZOS).save(OUT / "sky_2k.webp", quality=QUALITY, method=6)
    for p in sorted(OUT.glob("sky_*.webp")):
        print(p, p.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    sys.exit(main())
