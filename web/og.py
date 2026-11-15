"""Link-preview picture renderer for /api/og.jpg (web/server.py): pure Pillow, no server state."""
import io
from functools import lru_cache
from pathlib import Path

W, H = 1200, 630                       # the size every link-preview service expects
BG = (2, 4, 8)                         # the page colour
FADE_W = 260                           # width of the fade from the page colour into the sky picture
TEXT_W = 600                           # widest a title line may be
TITLE_MAX, TITLE_MIN, TITLE_STEP = 56, 30, 4
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "")
# DejaVu on Linux (the VM); Arial on Windows; Pillow's own font when neither exists
FONT_NAMES = {True: ("DejaVuSans-Bold.ttf", "arialbd.ttf"), False: ("DejaVuSans.ttf", "arial.ttf")}


@lru_cache(maxsize=16)
def font(bold, size):
    from PIL import ImageFont
    for name in FONT_NAMES[bold]:
        for d in FONT_DIRS:
            try:
                return ImageFont.truetype(str(Path(d) / name) if d else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(dr, title):
    """The largest font size at which the title fits in three lines of TEXT_W, and those lines."""
    size, lines = TITLE_MAX, []
    while size >= TITLE_MIN:
        f = font(True, size)
        lines, cur = [], ""
        for w in title.split():
            t = f"{cur} {w}".strip()
            if dr.textlength(t, font=f) <= TEXT_W or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= 3 and all(dr.textlength(ln, font=f) <= TEXT_W for ln in lines):
            break
        size -= TITLE_STEP
    return size, lines


def render(src, title, sub):
    """A 1200 x 630 JPEG: the sky picture on the right fading into the page colour, the place's name on the left."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), BG)
    with Image.open(src) as s:
        sky = s.convert("RGB").resize((H, H), Image.LANCZOS)
    im.paste(sky, (W - H, 0))
    fade = Image.linear_gradient("L").rotate(-90, expand=True).resize((FADE_W, H))      # 255 at the left edge -> 0
    im.paste(Image.new("RGB", (FADE_W, H), BG), (W - H, 0), fade)
    dr = ImageDraw.Draw(im)
    dr.text((56, 58), "SPHEREx Sky Change Explorer", font=font(True, 26), fill=(255, 181, 71))
    size, lines = _wrap(dr, title)
    f, y = font(True, size), 150
    for ln in lines[:3]:
        dr.text((56, y), ln, font=f, fill=(240, 242, 245))
        y += int(size * 1.2)
    dr.text((56, y + 18), sub, font=font(False, 26), fill=(201, 204, 211))
    dr.text((56, H - 74), "NASA SPHEREx · 0.75–5 µm all-sky infrared survey", font=font(False, 21), fill=(140, 146, 158))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=86, optimize=True, progressive=True)
    return buf.getvalue()
