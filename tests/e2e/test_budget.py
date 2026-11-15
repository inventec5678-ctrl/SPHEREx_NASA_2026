"""Performance budget (UPGRADE_PLAN.md §8, T1/T2/T9): no web-font download from Google, the Chinese home page under
400 kB, and no page that jumps (CLS < 0.1) on a desktop or a phone."""
import pytest

from .conftest import new_page

ROUTES = {
    "home": "/", "sky": "/#/sky/162.294%20-53.317?fov=0.15", "target": "/#/target/barnard", "viewer": "/#/field/cybele",
    "lab": "/#/lab/cybele", "movers": "/#/movers", "guide": "/#/guide", "targets": "/#/targets", "features": "/#/features",
    "discovery": "/#/discovery", "universe": "/#/universe/cybele", "embed": "/?target=barnard&embed=1", "story": "/#/story",
    "follow": "/#/follow", "comet": "/#/comet", "credits": "/#/credits",
}
METRICS = """
window.__m = { cls: 0 };
new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) __m.cls += e.value }).observe({ type: 'layout-shift', buffered: true });
"""


@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "phone"])
@pytest.mark.parametrize("route", list(ROUTES))
def test_no_layout_jumps(base, browser, route, mobile):
    ctx, pg = new_page(browser, mobile=mobile, init=METRICS)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.goto(base + ROUTES[route], wait_until="load")
    pg.wait_for_timeout(6000)
    cls = pg.evaluate("__m.cls")
    ctx.close()
    assert not errors, errors
    assert cls < 0.1, f"{route}: CLS {cls:.3f}"


def test_home_weight_and_fonts(base, browser):
    ctx, pg = new_page(browser)
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Network.enable")
    total, hosts = [0], set()
    urls = {}
    cdp.on("Network.responseReceived", lambda e: urls.__setitem__(e["requestId"], e["response"]["url"]))
    def fin(e):
        total[0] += e["encodedDataLength"]
        hosts.add(urls.get(e["requestId"], "").split("/")[2] if "://" in urls.get(e["requestId"], "") else "")
    cdp.on("Network.loadingFinished", fin)
    pg.goto(base + "/", wait_until="load")
    pg.wait_for_timeout(5000)
    ctx.close()
    assert not any("fonts.g" in h for h in hosts), hosts
    assert total[0] / 1024 < 400, f"home {total[0] / 1024:.0f} kB"
