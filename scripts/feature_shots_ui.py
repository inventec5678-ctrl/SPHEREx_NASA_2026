"""Screenshots of the redesigned pages for the features page -> web/app/public/media/features/<name>.webp
(1440x836, below the top bar). Companion of feature_shots.py, which makes the viewer / 3D / object shots.

  python scripts/feature_shots_ui.py [base_url]

Uses data already on the server (the test targets and the kept quick look of Kapteyn's Star). Rebuild the site
afterwards (the images live in public/ and are copied into dist/ by the build).
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MEDIA  # noqa: E402

OUT = MEDIA / "features"
BASE = "http://127.0.0.1:8791"
VIEWPORT = {"width": 1440, "height": 900}
CLIP = {"x": 0, "y": 64, "width": 1440, "height": 836}
QUALITY = 84
INIT = ("try { localStorage.setItem('sx:tour:lab', '1'); localStorage.setItem('sx:tour:quick', '1'); "
        "localStorage.setItem('sx:hint:v2', '3') } catch (e) {}")
SCROLL_TO = ("([s, o]) => { document.querySelectorAll('.reveal').forEach(e => e.classList.add('in')); "
             "const e = document.querySelector(s); if (e) { e.scrollIntoView({ block: 'start' }); scrollBy(0, -o) } }")


def save(pg, name):
    from PIL import Image
    Image.open(io.BytesIO(pg.screenshot(clip=CLIP))).convert("RGB").save(OUT / f"{name}.webp", quality=QUALITY)
    print("shot", name)


def top(pg, sel, off=80):
    pg.evaluate(SCROLL_TO, [sel, off])
    pg.wait_for_timeout(1500)


def main(base):
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()      # default flags (see tests/e2e/conftest.py)
        ctx = b.new_context(viewport=VIEWPORT)
        ctx.add_init_script(INIT)
        pg = ctx.new_page()
        pg.goto(f"{base}/#/sky/77.96%20-45.02?fov=0.15"); pg.wait_for_timeout(9000); save(pg, "quick")
        pg.goto(f"{base}/#/movers"); pg.wait_for_timeout(6000); save(pg, "movers")
        pg.goto(f"{base}/#/field/cybele/track/0"); pg.wait_for_timeout(7000); save(pg, "object")
        pg.goto(f"{base}/#/guide/trust"); pg.wait_for_timeout(6000); top(pg, "#g-trust"); save(pg, "guide")
        pg.goto(f"{base}/#/target/wise0855"); pg.wait_for_timeout(7000); save(pg, "lab")
        top(pg, "#sec-measure", 70); save(pg, "spectrum")
        pg.goto(f"{base}/#/discovery"); pg.wait_for_timeout(5000); top(pg, "main", 0); save(pg, "discovery")
        pg.goto(f"{base}/#/"); pg.wait_for_timeout(4000); top(pg, "#explore", 70); pg.wait_for_timeout(2500)
        save(pg, "explore")
        pg.goto(f"{base}/#/story"); pg.wait_for_timeout(4000); top(pg, ".story", 0); pg.wait_for_timeout(2500)
        save(pg, "story")
        # the embedded player as another site would show it: 640 px wide, centred on a plain page
        pg.set_content('<body style="margin:0;background:#11151d;display:grid;place-items:center;height:100vh">'
                       f'<iframe src="{base}/?target=barnard&embed=1" width="640" height="820" '
                       'style="border:0;border-radius:12px"></iframe></body>')
        pg.wait_for_timeout(8000); save(pg, "embed")
        b.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else BASE)
