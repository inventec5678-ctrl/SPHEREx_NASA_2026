"""Screenshots for the paper / project page and PDFs of the paper pages (Playwright, headless).

  python scripts/paper_media.py shots    # figures/universe_{en,zh}.webp, figures/viewer_{en,zh}.webp
  python scripts/paper_media.py pdf      # static/pdfs/spherex_movers_{en,zh}.pdf from the rendered HTML
Needs the web app running at --base (default http://127.0.0.1:8791).
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PUBLIC  # noqa: E402

PUB = PUBLIC / "paper"
QUALITY = 88
INIT = "localStorage.setItem('sx:coach:v1', '1'); localStorage.setItem('sx:hint:v2', '3')"
PDF_MARGIN = {"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"}
PDFS = (("paper-en.html", "spherex_movers_en.pdf"), ("paper.html", "spherex_movers_zh.pdf"))


def _webp(png, path):
    from PIL import Image
    Image.open(io.BytesIO(png)).save(path, quality=QUALITY)


def shots(base):
    from playwright.sync_api import sync_playwright
    fig = PUB / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for lang in ("en", "zh"):
            q = "?lang=en" if lang == "en" else "?lang=zh-Hant"
            ctx = b.new_context(viewport={"width": 1500, "height": 900}, device_scale_factor=1)
            ctx.add_init_script(INIT)
            pg = ctx.new_page()
            pg.goto(f"{base}/{q}#/"); pg.wait_for_timeout(3000)
            # the home story at its space-time cube step (the noise has faded, the asteroids are streaks)
            pg.evaluate("document.querySelectorAll('.step')[3].scrollIntoView({block: 'center'})")
            pg.wait_for_timeout(9000)
            _webp(pg.screenshot(), fig / f"universe_{lang}.webp")
            pg.goto(f"{base}/{q}#/field/cybele"); pg.wait_for_timeout(2500)
            label = "Images" if lang == "en" else "影像"
            pg.click(f".vmodes .seg button:has-text('{label}')")     # the image view opens on "change"
            pg.locator(".tcard .thead", has_text="Cybele").first.click(); pg.wait_for_timeout(2500)   # track 65 Cybele
            pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(1500)
            _webp(pg.query_selector(".viewer").screenshot(), fig / f"viewer_{lang}.webp")
            ctx.close()
            print("shots", lang)
        b.close()


def pdf(base):
    from playwright.sync_api import sync_playwright
    dst = PUB / "static" / "pdfs"
    dst.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for page, out in PDFS:
            pg = b.new_page()
            pg.goto(f"{base}/paper/{page}"); pg.wait_for_timeout(2500)
            pg.pdf(path=str(dst / out), format="A4", print_background=True, margin=PDF_MARGIN)
            print("pdf", out)
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["shots", "pdf"])
    ap.add_argument("--base", default="http://127.0.0.1:8791")
    a = ap.parse_args()
    (shots if a.what == "shots" else pdf)(a.base)
