"""axe-core on the main pages, desktop and phone: no serious or critical violation."""
from pathlib import Path

import pytest

from .conftest import new_page

AXE = Path(__file__).resolve().parents[2] / "web" / "app" / "node_modules" / "axe-core" / "axe.min.js"
ROUTES = ["/", "/#/sky/77.96%20-45.02?fov=0.15&pf=1&fl=1&x=33.4&y=20.7", "/#/target/barnard", "/#/field/cybele", "/#/movers",
          "/#/guide", "/#/targets", "/#/features", "/#/story",
          "/#/follow", "/#/comet", "/#/credits"]


@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "phone"])
@pytest.mark.parametrize("route", ROUTES)
def test_axe(base, browser, route, mobile):
    if not AXE.exists():
        pytest.skip("axe-core not installed (npm install in web/app)")
    ctx, pg = new_page(browser, lang="en", mobile=mobile)
    pg.goto(base + route)
    pg.wait_for_timeout(6000)
    pg.evaluate(AXE.read_text(encoding="utf-8"))
    bad = pg.evaluate("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
                      ".filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ': ' + v.nodes.slice(0, 2).map(n => n.target.join(' ')).join(' | ')))")
    ctx.close()
    assert not bad, bad
