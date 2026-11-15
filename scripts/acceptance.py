"""P4 acceptance checks. Writes outputs/acceptance.json.

  python scripts/acceptance.py --tunnel https://<name>.trycloudflare.com
Latency numbers are reported separately for loopback and the Cloudflare path, with sample sizes;
they are not an SLA (headless Chromium, software WebGL, one machine).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import APP, OUTPUTS, dumps, write_json  # noqa: E402

AXE = APP / "node_modules" / "axe-core" / "axe.min.js"
ROUTES = ["/", "/#/field/cybele", "/#/field/cybele/track/0", "/paper/paper.html", "/paper/index.html", "/paper/paper-zh.html",
          "/#/features", "/#/universe/cybele", "/#/discovery"]
HTTP_PATHS = ("/api/fields", "/api/field/cybele", "/data/fields/cybele/sci/0000.webp", "/data/fields/cybele/universe.json")
VIEWPORT = {"width": 1400, "height": 900}
LAYOUT_WIDTHS = (360, 768, 1280, 1920)
N_TIMING = 5                # cold page loads per timing measurement
SETTLE_MS = 2500
SERIOUS = ("serious", "critical")

FIRST_FRAME_JS = ("() => (window.__sxScene && window.__sxScene.items.length > 0) || "
                  "performance.getEntriesByType('resource').some(e => /\\/(sci|diff)\\/\\d+\\.webp/.test(e.name))")
UNIVERSE_READY_JS = "() => (window.__sxScene && window.__sxScene.items.length > 0) || document.querySelector('.u-slow')"
HAN_JS = """() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n = 0, ex = [];
  while (w.nextNode()) { const t = w.currentNode; if (t.parentElement.closest('[lang="zh-Hant"]')) continue;
    const m = t.textContent.match(/[\\u3400-\\u9fff]/g); if (m) { n += m.length; if (ex.length < 5) ex.push(t.textContent.trim().slice(0, 40)) } } return [n, ex] }"""
AXE_JS = ("async () => (await axe.run(document, {resultTypes: ['violations']}))"
          ".violations.map(x => ({id: x.id, impact: x.impact, n: x.nodes.length}))")
LIT_JS = """() => { const c = document.querySelector('.stage canvas'); const g = c.getContext('2d');
  const d = g.getImageData(0, 0, c.width, c.height).data; let s = 0; for (let i = 0; i < d.length; i += 40) s += d[i] + d[i + 1] + d[i + 2];
  return [s, c.style.transform] }"""


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 3)


def http_bench(base, n=20):
    import requests
    out = {}
    for path in HTTP_PATHS:
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            r = requests.get(base + path, headers={"Accept-Encoding": "gzip"}, timeout=60)
            r.raise_for_status()
            ts.append(time.perf_counter() - t0)
        out[path] = {"n": n, "p50_s": pct(ts, 0.5), "p95_s": pct(ts, 0.95), "bytes": len(r.content)}
    return out


def _page(b, width=None):
    return b.new_page(bypass_csp=True, viewport={"width": width, "height": 900} if width else VIEWPORT)


def _timed(b, url, cond, timeout):
    """Seconds from navigation on a cold page until the JS condition holds."""
    pg = _page(b)
    t0 = time.perf_counter()
    pg.goto(url)
    pg.wait_for_function(cond, timeout=timeout)
    dt = time.perf_counter() - t0
    pg.close()
    return dt


def browser_checks(base):
    from playwright.sync_api import sync_playwright
    res = {"layout": [], "i18n": [], "axe": [], "timing": {}}
    with sync_playwright() as p:
        b = p.chromium.launch()
        # first picture: the 3D universe (the default view) built, or a first image frame drawn. The 3D universe
        # also has its own page; without hardware WebGL it shows the flat image and an "open 3D anyway" button.
        ff, ur = [], []
        for _ in range(N_TIMING):
            ff.append(_timed(b, base + "/#/field/cybele", FIRST_FRAME_JS, 60000))
            ur.append(_timed(b, base + "/#/universe/cybele", UNIVERSE_READY_JS, 90000))
        res["timing"] = {"viewer_first_frame_s": {"n": N_TIMING, "p50": pct(ff, .5), "max": round(max(ff), 3)},
                         "universe_ready_s": {"n": N_TIMING, "p50": pct(ur, .5), "max": round(max(ur), 3)}}
        for w in LAYOUT_WIDTHS:
            for r in ROUTES:
                pg = _page(b, w); pg.goto(base + r); pg.wait_for_timeout(SETTLE_MS)
                sw = pg.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
                res["layout"].append({"width": w, "route": r, "scrollWidth": sw[0], "innerWidth": sw[1], "ok": sw[0] <= sw[1]})
                pg.close()
        for r in ROUTES[:3]:
            pg = _page(b)
            pg.goto(base + "/?lang=en" + r.lstrip("/").replace("/#", "#") if r != "/" else base + "/?lang=en")
            pg.wait_for_timeout(3000)
            han = pg.evaluate(HAN_JS)
            res["i18n"].append({"route": r, "han_chars_in_english_mode": han[0], "examples": han[1]})
            pg.close()
        for r in ROUTES:
            pg = _page(b); pg.goto(base + r); pg.wait_for_timeout(SETTLE_MS)
            pg.add_script_tag(path=str(AXE))
            v = pg.evaluate(AXE_JS)
            res["axe"].append({"route": r, "serious_or_critical": [x for x in v if x["impact"] in SERIOUS],
                               "other": [x for x in v if x["impact"] not in SERIOUS]})
            pg.close()
        try:
            res["interaction"] = interaction_checks(b, base)
        except Exception as e:      # these checks target the October viewer; report rather than lose the other results
            res["interaction"] = {"error": f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"}
        b.close()
    return res


def interaction_checks(b, base):
    """Real-input checks for the bugs an independent review found (mouse clicks on stage controls,
    language switch inside the viewer, Space on a focused button, WebGL context churn)."""
    out = {}
    pg = _page(b)
    pg.add_init_script("localStorage.setItem('sx:hint:v2', '3')")   # no first-visit tour bubbles
    logs = []
    pg.on("console", lambda m: logs.append(m.text))
    pg.goto(base + "/?lang=zh-Hant#/field/cybele"); pg.wait_for_timeout(3500)   # start in Chinese so the switch to EN below is exercised
    # the 2D image checks run in the image view, "change" (the default is the 3D universe)
    pg.locator(".vmodes .seg button", has_text="影像").click(); pg.wait_for_timeout(800)

    def tf():
        return pg.evaluate("() => document.querySelector('.stage canvas').style.transform")
    before = tf()
    box = pg.locator(".zoomctl button").first.bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.wait_for_timeout(800)
    out["mouse_zoom_button"] = {"ok": tf() != before}
    # switch language from inside the viewer: the image must still be drawn and sized
    pg.locator(".lang button", has_text="EN").click(); pg.wait_for_timeout(2000)
    out["universe_default"] = {"ok": pg.evaluate("() => !!document.querySelector('.vmodes .seg button.m3d')")}
    lit = pg.evaluate(LIT_JS)
    out["lang_switch_image"] = {"ok": lit[0] > 0 and "scale(0)" not in lit[1], "transform": lit[1]}
    # Space on a focused list button selects that object instead of toggling playback
    btn = pg.locator(".tcard .thead").nth(1)
    was = btn.get_attribute("aria-pressed"); btn.focus(); pg.keyboard.press(" "); pg.wait_for_timeout(500)
    out["space_on_button"] = {"ok": btn.get_attribute("aria-pressed") != was}
    # toggle the 3D view repeatedly: no lost WebGL contexts
    for _ in range(12):     # 3D universe -> stacked time cube -> image, repeatedly
        pg.locator(".vmodes .seg button.m3d").click(); pg.wait_for_timeout(250)
        pg.locator(".vmodes .chip").click(); pg.wait_for_timeout(250)
        pg.locator(".vmodes .seg button:not(.m3d)").click(); pg.wait_for_timeout(150)
    out["webgl_churn"] = {"ok": not any("Too many active WebGL contexts" in m for m in logs)}
    pg.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="P4 acceptance checks -> outputs/acceptance.json")
    ap.add_argument("--local", default="http://127.0.0.1:8791")
    ap.add_argument("--tunnel")
    a = ap.parse_args()
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "env": "headless Chromium (software WebGL) on the team server; not a real-device test",
           "http_loopback": http_bench(a.local)}
    if a.tunnel:
        out["http_cloudflare"] = http_bench(a.tunnel)
    out["browser_loopback"] = browser_checks(a.local)
    write_json(OUTPUTS / "acceptance.json", out)
    print(dumps(out)[:6000])


if __name__ == "__main__":
    main()
