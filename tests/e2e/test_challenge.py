"""Every requirement of the challenge page, checked in a real browser (English UI).

Mirrors the 22-sentence check of round 6 (UPGRADE_PLAN.md): enter a position, watch it play like a video, the five named
test targets, a new position (quick look of Luhman 16, kept on the server) with its lab, coordinates in the URL and the
embed, contamination flags, Aladin, and the review queue. Note texts are read with textContent: the notes under each
control are folded behind "?" outside research mode.
"""
from .conftest import new_page


def txt(pg, sel):
    return pg.evaluate(f"() => document.querySelector({sel!r})?.textContent || ''")


def test_enter_position_plays(base, browser):
    ctx, pg = new_page(browser, lang="en")
    pg.goto(base + "/")
    pg.wait_for_timeout(2500)
    inp = pg.locator("#main input").first
    inp.fill("08h55m10.831s -7d14m42.53s")
    inp.press("Enter")
    pg.wait_for_timeout(5000)
    assert "wise0855" in pg.evaluate("location.hash")
    seen = set()
    for _ in range(8):                      # one pass every 0.9 s: sample for 2.8 s rather than twice
        seen.add(txt(pg, ".lab-badge"))
        pg.wait_for_timeout(350)
    assert len(seen - {""}) >= 2, f"the passes blink by themselves: {seen}"
    ctx.close()


def test_five_targets_by_name(base, browser):
    ctx, pg = new_page(browser, lang="en")
    for name, tid in [("Barnard's Star", "barnard"), ("Epsilon Indi B", "epsindi"), ("WISE 0855", "wise0855"), ("RW Aurigae", "rwaur"), ("R Draconis", "rdra")]:
        pg.goto(base + "/")
        pg.wait_for_timeout(1500)
        inp = pg.locator("#main input").first
        inp.fill(name)
        inp.press("Enter")
        pg.wait_for_timeout(5000)
        assert tid in pg.evaluate("location.hash"), name
        assert pg.evaluate("document.querySelectorAll('.plot circle').length") > 50, f"{name}: charts plotted"
    ctx.close()


def test_new_position_and_lab(base, browser):
    ctx, pg = new_page(browser, lang="en")
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.goto(base + "/#/sky/162.294%20-53.317?fov=0.15&x=43.5&y=44.1")
    pg.wait_for_timeout(12000)
    k1 = txt(pg, ".playbar-count")
    pg.wait_for_timeout(1500)
    assert k1 != txt(pg, ".playbar-count"), "the new position plays like a video"
    diff = pg.locator(".qp .seg button", has_text="Difference")
    assert not diff.is_disabled(), "difference frames make movers easy to spot"
    lab = pg.locator(".quick-lab")
    assert lab.count() == 1
    btn = lambda t: lab.locator(".toolbar button", has_text=t).first  # noqa: E731
    note = "document.querySelector('.quick-lab .stage-note')?.textContent || ''"
    btn("One pass").click()
    lab.locator("select.tb-det").select_option("6")
    pg.wait_for_timeout(1500)
    assert "stacked from this detector" in pg.evaluate(note)
    lab.locator("select.tb-det").select_option("rgb")
    pg.wait_for_timeout(2500)
    assert "red = D6" in pg.evaluate(note)
    assert pg.evaluate("document.querySelectorAll('.quick-lab .lab-measure .plot circle').length") > 100, "spectrum on the fly"
    btn("Add all").click()
    pg.wait_for_timeout(1500)
    assert "combined" in txt(pg, ".quick-lab .lab-badge")
    btn("Difference").click()
    pg.wait_for_timeout(1500)
    assert "−" in txt(pg, ".quick-lab .lab-badge")
    fovs = pg.evaluate("[...document.querySelectorAll('.sky-fov button')].map(b => b.textContent)")
    assert fovs == ["0.15°", "0.3°", "0.6°"] and "fov=0.15" in pg.evaluate("location.hash")
    # catalogue overlays live in the Layers panel of the image toolbar
    lab.locator("details.pop > summary").click()
    lab.locator("input[name=wise]").check()
    assert lab.locator("input[name=gaia]").is_checked() and lab.locator("input[name=wise]").is_checked()
    # the charts: time x wavelength of every exposure, and the spectrum with its detector strip
    assert pg.evaluate("document.querySelectorAll('.qp .stage-side .plot circle').length") > 50, "time x wavelength chart"
    pg.wait_for_timeout(4000)
    assert pg.evaluate("!!document.querySelector('.sx-aladin-map canvas')"), "Aladin Lite"
    snippet = pg.evaluate("document.querySelector('.embed-code code:nth-of-type(1)') ? [...document.querySelectorAll('.embed-code code')].map(c => c.textContent).join(' ') : ''")
    assert "<iframe" in snippet and "ra=" in snippet
    assert not errors, errors
    ctx.close()


def test_url_embed_and_flags(base, browser):
    ctx, pg = new_page(browser, lang="en")
    pg.goto(base + "/?ra=133.795&dec=-7.245&embed=1")
    pg.wait_for_timeout(6000)
    assert pg.evaluate("document.documentElement.classList.contains('embed-mode') && !!document.querySelector('.qp canvas')")
    pg.goto(base + "/#/sky/162.294%20-53.317?fov=0.15&pf=1&fl=1")
    pg.wait_for_timeout(10000)
    assert txt(pg, ".qp-meta"), "per-frame SPHEREx flags"
    assert pg.evaluate("document.querySelectorAll('.quick-lab .lab-flags li').length") == 5
    ctx.close()


def test_review_queue(base, browser):
    ctx, pg = new_page(browser, lang="en")
    pg.goto(base + "/#/movers")
    pg.wait_for_timeout(5000)
    assert pg.evaluate("document.querySelectorAll('.mv-card button').length") > 10
    assert txt(pg, ".spots h2")
    ctx.close()
