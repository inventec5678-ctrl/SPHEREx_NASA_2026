"""Landing-page media made from real frames of the 65 Cybele field (no artwork, no simulation).

  hero_blink.webp   animated, ~20 frames of one detector while Cybele crosses (2 fps)
  hero_poster.webp  first frame (shown without JS / before the animation loads)
  step_sky/diff/ai  16:10 crops: calibrated image, colour difference image, AI marks

  python scripts/make_media.py
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MEDIA, read_json  # noqa: E402

FIELD = FIELDS / "cybele"
OUT = MEDIA
HERO_SIZE = 512
HERO_FRAMES = 22             # about this many frames in the animation
HERO_PAD = 30                # pixels around the track
HERO_MS = 500                # 2 fps
MIN_COVERAGE = 0.9
STEP_W, STEP_H = 96, 60      # 16:10 crop (pixels)
STEP_OUT = (480, 300)
P_MARK = 0.5                 # classifier score above which a candidate is circled
MARK_R = 16
COL_KNOWN, COL_TRACK, COL_OTHER = (110, 195, 255), (255, 181, 71), (255, 255, 255)


def frame(f, kind, i):
    ext = f.get("frame_ext", "png")
    return Image.open(FIELD / kind / f"{i:04d}.{ext}").convert("L")


def lut():
    """256-entry colour map for the difference frames (grey level 128 = 0, 16 levels per sigma)."""
    v = np.arange(256)
    snr = (v - 128) / 16
    a = np.clip((np.abs(snr) - 1.5) / 6.5, 0, 1) ** 0.8
    pos = np.stack([14 + 241 * a, 16 + 170 * a, 24 + 30 * a], 1)
    neg = np.stack([14 + 40 * a, 16 + 120 * a, 24 + 230 * a], 1)
    return np.where((snr >= 0)[:, None], pos, neg).astype(np.uint8)


def hero(f, mem, H):
    ex = f["exposures"]
    cnt = Counter(ex[c["i"]]["detector"] for c in mem)
    det = max(sorted(cnt), key=cnt.__getitem__)     # most frequent detector; ties -> lowest number (as before)
    xs = [c["x"] for c in mem]
    ys = [H - 1 - c["y"] for c in mem]      # image rows (y down)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = int(max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + HERO_PAD)
    box = (int(cx - half), int(cy - half), int(cx + half), int(cy + half))
    mj = [ex[c["i"]]["mjd"] for c in mem]
    t0, t1 = min(mj) - 0.3, max(mj) + 0.3
    seq = [e["i"] for e in ex if e["detector"] == det and t0 <= e["mjd"] <= t1 and e["coverage"] > MIN_COVERAGE]
    seq = seq[:: max(1, len(seq) // HERO_FRAMES)]
    frames = [frame(f, "sci", i).crop(box).resize((HERO_SIZE, HERO_SIZE), Image.NEAREST).convert("RGB") for i in seq]
    frames[0].save(OUT / "hero_poster.webp", quality=88)
    frames[0].save(OUT / "hero_blink.webp", save_all=True, append_images=frames[1:], duration=HERO_MS, loop=0,
                   quality=85, method=6)
    print("hero:", len(frames), "frames, detector", det, "box", box)


def steps(f, mem, H):
    """Step images: a 16:10 window around the middle detection."""
    c = mem[len(mem) // 2]
    i = c["i"]
    x0, y0 = int(c["x"] - STEP_W / 2), int(H - 1 - c["y"] - STEP_H / 2)
    crop = (x0, y0, x0 + STEP_W, y0 + STEP_H)
    sci = frame(f, "sci", i).crop(crop).resize(STEP_OUT, Image.NEAREST).convert("RGB")
    sci.save(OUT / "step_sky.webp", quality=88)
    d = np.array(frame(f, "diff", i).crop(crop))
    Image.fromarray(lut()[d]).resize(STEP_OUT, Image.NEAREST).save(OUT / "step_diff.webp", quality=88)
    ai = sci.copy()
    g = ImageDraw.Draw(ai)
    k = STEP_OUT[0] / STEP_W
    for cc in f["candidates"]:
        if cc["i"] != i or cc["p"] < P_MARK:
            continue
        px, py = (cc["x"] - x0 + 0.5) * k, (H - 1 - cc["y"] - y0 + 0.5) * k
        col = COL_KNOWN if cc["known"] else COL_TRACK if cc["track"] is not None else COL_OTHER
        g.ellipse([px - MARK_R, py - MARK_R, px + MARK_R, py + MARK_R], outline=col, width=3)
    ai.save(OUT / "step_ai.webp", quality=88)
    print("steps from exposure", i, f["exposures"][i]["iso"])


def main():
    f = read_json(FIELD / "field.json")
    H = f["shape"][0]
    cand = {c["id"]: c for c in f["candidates"]}
    tr = next(t for t in f["tracks"] if t.get("known", "") and "Cybele" in t["known"])
    mem = sorted((cand[m] for m in tr["members"]), key=lambda c: f["exposures"][c["i"]]["mjd"])
    OUT.mkdir(parents=True, exist_ok=True)
    hero(f, mem, H)
    steps(f, mem, H)


if __name__ == "__main__":
    sys.exit(main())
