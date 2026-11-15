"""Record the 30-second captioned demo of the site (one per language) with Playwright, then encode with ffmpeg.

    python scripts/demo_short.py [base_url]      -> demo/spherex_demo_<lang>.mp4 and web/app/public/media/demo_<lang>.webm

Uses data that is already on the server (the five targets and the finished quick look of Kapteyn's Star), so nothing
new is downloaded while recording. Needs ffmpeg on PATH (ffmpeg.exe on Windows)."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import APP, MEDIA, ROOT, run  # noqa: E402

BASE = "http://127.0.0.1:8791"
SIZE = {"width": 1280, "height": 720}
SECONDS = "30"
CAP = {
    "en": ["1 · Type a position or a name and press Enter: the SPHEREx images play",
           "2 · Difference: steady stars vanish, only what changed remains",
           "3 · Coordinates in the URL: WISE 0855, the coldest brown dwarf, in two survey passes",
           "4 · Click any point: light curve, 102-band spectrum, AI brown-dwarf check",
           "5 · Moving and variable stars are found automatically, then checked against catalogues",
           "6 · Everyone can help judge the candidates"],
    "zh-Hant": ["1 · 輸入座標或名稱，按 Enter：SPHEREx 影像開始播放",
                "2 · 差分：不變的星消失，只留下變化",
                "3 · 網址帶座標：最冷的棕矮星 WISE 0855，兩輪巡天的差分",
                "4 · 點任何一點：光變曲線、102 波段光譜、AI 判斷是不是棕矮星",
                "5 · 程式自動找出移動的星和變星，再和星表比對",
                "6 · 大家都能幫忙判斷候選"],
}
T = {"en": {"diff": "Difference", "blink": "Blink"}, "zh-Hant": {"diff": "差分", "blink": "輪播"}}
SAY_JS = """t => { let d = document.getElementById('demo-cap'); if (!d) { d = document.createElement('div'); d.id = 'demo-cap';
  d.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;background:rgba(5,7,13,.9);color:#fff;font:700 22px Manrope,system-ui,sans-serif;padding:12px 22px;border-radius:14px;box-shadow:0 0 0 1px rgba(255,255,255,.18);max-width:92vw;text-align:center;pointer-events:none';
  document.body.appendChild(d) } d.textContent = t }"""
MP4_ARGS = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", "-movflags", "+faststart"]
WEBM_ARGS = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "38", "-an"]


def record(base, lang, out_dir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()      # default flags: see tests/e2e/conftest.py for why not --use-angle=vulkan
        ctx = b.new_context(viewport=SIZE, record_video_dir=out_dir, record_video_size=SIZE)
        ctx.add_init_script(f"try{{localStorage.setItem('sx:language:v1','{lang}');localStorage.setItem('sx:tour:lab','1');"
                            "localStorage.setItem('sx:tour:quick','1')}catch(e){}")
        pg = ctx.new_page()
        cap = lambda t: pg.wait_for_timeout(int(t * 1000))   # noqa: E731
        say = lambda k: pg.evaluate(SAY_JS, CAP[lang][k])    # noqa: E731
        # 1. the home page: a position in, an image sequence out
        pg.goto(base + "/"); cap(0.8); say(0); cap(1.0)
        pg.click("#hero-q"); pg.keyboard.type("77.96 -45.02", delay=30)
        pg.select_option(".ss-fov select", "0.15")
        pg.press("#hero-q", "Enter"); cap(0.9); say(0); cap(3.0)
        # 2. differences (keep the image on screen while the control below it is pressed)
        pg.evaluate("document.querySelectorAll('.qp .toolbar .seg button')[1].click(); window.scrollTo(0, 120)")
        say(1); cap(3.0)
        # 3. coordinates in the URL -> WISE 0855, difference of two passes
        pg.goto(base + "/?ra=133.795&dec=-7.245"); cap(1.0); say(2); cap(1.0)
        pg.locator(".tool-stage .toolbar button", has_text=T[lang]["diff"]).first.click(); cap(2.4)
        # 4. click the target -> light curve + spectrum + AI check
        box = pg.locator(".lab-canvas canvas").first.bounding_box()
        pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); say(3); cap(3.8)
        # 5. automatic searches: the moving star here, the variable in R Draconis
        pg.locator(".mv-list").first.scroll_into_view_if_needed(); say(4); cap(1.8)
        pg.goto(base + "/#/target/rdra"); cap(0.9); say(4)
        pg.locator(".mv-list").last.scroll_into_view_if_needed(); cap(2.2)
        # 6. the review queue
        pg.goto(base + "/#/movers"); cap(0.8); say(5)
        pg.locator(".mv-grid").first.scroll_into_view_if_needed(); cap(3.0)
        ctx.close(); b.close()
    return next(Path(out_dir).glob("*.webm"))


def ffmpeg(src, args, dst):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", SECONDS, *args, dst])


def main(base):
    demo = ROOT / "demo"
    demo.mkdir(exist_ok=True)
    for lang in ("en", "zh-Hant"):
        with tempfile.TemporaryDirectory() as tmp:
            src = record(base, lang, tmp)
            mp4 = demo / f"spherex_demo_{lang}.mp4"
            ffmpeg(src, MP4_ARGS, mp4)
            web = MEDIA / f"demo_{'en' if lang == 'en' else 'zh'}.webm"
            ffmpeg(src, WEBM_ARGS, web)
        dist = APP / "dist" / "media" / web.name
        if dist.parent.exists():
            shutil.copy(web, dist)
        print(lang, mp4, mp4.stat().st_size // 1024, "KB;", web, web.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else BASE)
