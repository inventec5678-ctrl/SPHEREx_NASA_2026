"""Records a ~40 s demo video of the web app (Playwright, 1280x720) -> web/app/public/media/demo_{lang}.webm

    python scripts/demo_video.py [base_url]
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MEDIA, OUTPUTS  # noqa: E402

BASE = "http://127.0.0.1:8791"
SIZE = {"width": 1280, "height": 720}
TMP = OUTPUTS / "video_tmp"
NO_TIPS = "localStorage.setItem('sx:coach:v1', '1'); localStorage.setItem('sx:hint:v2', '3')"   # no first-visit tips
STORY_STEPS = ((1, 3000), (2, 4000), (3, 6500), (4, 6000))   # subtract, link, space-time cube, parallax zig-zag


def record(pw, base, lang):
    b = pw.chromium.launch()
    ctx = b.new_context(viewport=SIZE, record_video_dir=str(TMP), record_video_size=SIZE)
    ctx.add_init_script(NO_TIPS)
    pg = ctx.new_page()
    pg.goto(f"{base}/?lang={lang}#/"); pg.wait_for_timeout(4500)          # story 1: the same sky, blinking
    for k, ms in STORY_STEPS:
        pg.evaluate(f"document.querySelectorAll('.step')[{k}].scrollIntoView({{behavior: 'smooth', block: 'center'}})")
        pg.wait_for_timeout(ms)
    pg.goto(f"{base}/?lang={lang}#/field/cybele"); pg.wait_for_timeout(3500)   # the sky in motion, objects named
    pg.locator(".tcard .thead", has_text="Cybele").first.click(); pg.wait_for_timeout(4000)   # its evidence opens
    pg.goto(f"{base}/?lang={lang}#/field/cybele/track/0"); pg.wait_for_timeout(4500)   # why believe it
    ctx.close(); b.close()


def main(base):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for lang in ("zh-Hant", "en"):
            shutil.rmtree(TMP, ignore_errors=True)
            record(pw, base, lang)
            vid = next(TMP.glob("*.webm"))
            out = MEDIA / f"demo_{'en' if lang == 'en' else 'zh'}.webm"
            shutil.move(str(vid), str(out))
            print(out, out.stat().st_size // 1024, "KB")
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else BASE)
