"""Screenshots for the features page -> web/app/public/media/features/<name>.webp (1440x836, below the top bar).

  python scripts/feature_shots.py [base_url]
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIELDS, MEDIA, read_json  # noqa: E402

OUT = MEDIA / "features"
BASE = "http://127.0.0.1:8791"
VIEWPORT = {"width": 1440, "height": 900}
CLIP = {"x": 0, "y": 64, "width": 1440, "height": 836}
QUALITY = 84
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]   # WebGL without a GPU
INIT = ("localStorage.setItem('sx:coach:v1', '1'); localStorage.setItem('sx:hint:v2', '3'); "
        "localStorage.setItem('sx:mode:v1', 'story')")


def save(pg, name, clip=CLIP, el=None):
    from PIL import Image
    if el:     # clip to the element's box (an element screenshot waits for it to stop moving; the page has live effects)
        bb = el.bounding_box()
        clip = {"x": bb["x"], "y": bb["y"], "width": bb["width"], "height": bb["height"]}
    Image.open(io.BytesIO(pg.screenshot(clip=clip))).convert("RGB").save(OUT / f"{name}.webp", quality=QUALITY)
    print("shot", name)


def main(base):
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    px = read_json(FIELDS / "planetx" / "field.json")
    with sync_playwright() as p:
        b = p.chromium.launch(args=GL_ARGS)
        ctx = b.new_context(viewport=VIEWPORT)
        ctx.add_init_script(INIT)
        pg = ctx.new_page()
        pg.goto(f"{base}/#/"); pg.wait_for_timeout(4000); save(pg, "story")
        pg.goto(f"{base}/#/field/cybele")
        pg.wait_for_function("() => window.__sxScene && window.__sxScene.items.length > 0", timeout=90000)
        pg.wait_for_timeout(4000); save(pg, "viewer3d")
        # point check on the simulated planet
        pg.goto(f"{base}/#/field/planetx"); pg.wait_for_timeout(3500)
        pg.locator(".vmodes .seg button", has_text="影像").click(); pg.wait_for_timeout(600)   # image view, aim at a pixel
        pg.click(".vbar .playbtn"); pg.wait_for_timeout(400)
        i = pg.evaluate("window.__sxView.i")
        c = next(c for c in px["candidates"] if c["i"] == i and c["track"] == 0)
        pg.click(".probe-btn")
        xy = pg.evaluate(f"window.__sxView.toScreen({c['x']}, {c['y']})")
        pg.mouse.click(*xy); pg.wait_for_timeout(4000)
        save(pg, "probe")
        pg.goto(f"{base}/#/field/cybele/track/0"); pg.wait_for_timeout(4500); save(pg, "object")
        pg.goto(f"{base}/#/universe/cybele/s5"); pg.wait_for_timeout(7500); save(pg, "reconstruct")
        pg.goto(f"{base}/#/field/cybele"); pg.wait_for_timeout(3000)
        pg.keyboard.press("Escape"); pg.click(".vmodes .chip"); pg.wait_for_timeout(9000); save(pg, "cube")
        pg.goto(f"{base}/#/discovery"); pg.wait_for_timeout(2500)
        pg.evaluate("document.getElementById('h-map').scrollIntoView({block: 'start'}); scrollBy(0, -80)")
        pg.wait_for_timeout(2000)
        pg.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))")
        pg.wait_for_timeout(800); save(pg, "discovery")
        pg.evaluate("localStorage.setItem('sx:mode:v1', 'research')")
        pg.goto(f"{base}/#/field/cybele"); pg.wait_for_timeout(3000)
        pg.locator(".vmodes .seg button", has_text="影像").click(); pg.wait_for_timeout(2500); save(pg, "research")
        pg.evaluate("localStorage.setItem('sx:mode:v1', 'story')")
        pg.goto(f"{base}/#/"); pg.wait_for_timeout(2500)
        pg.evaluate("document.getElementById('explore').scrollIntoView({block: 'start'})"); pg.wait_for_timeout(1500)
        save(pg, "explore", el=pg.locator(".explore"))
        b.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else BASE)
