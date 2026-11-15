"""The visual rules of UPGRADE_PLAN.md §9.4, measured on the rendered pages (desktop, Traditional Chinese):

  - small text is the exception: at most 25% of a page's visible characters are under 15 px
    (chart ticks and units, drawn in SVG, are the 13 px exception and are not counted);
  - the first screen is mostly picture: graphics (images, canvases, charts, video) cover at least half of the first
    screen of a tool page and a third of the home page;
  - one grid: blocks of text in the first screen start on at most 8 different left edges.
"""
import pytest

from .conftest import new_page

CENSUS = r"""() => {
  const vis = (e) => { const r = e.getBoundingClientRect(), c = getComputedStyle(e); return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && +c.opacity > 0.05 }
  const main = document.querySelector('main') || document.body
  // a row of repeated items (cards, chips, list items) is one edge: an item with a same-kind sibling to its left
  // continues the row, and so does everything inside it; different siblings side by side are columns and do count
  const rowItem = (e) => { const r = e.getBoundingClientRect(); for (let p = e.previousElementSibling; p; p = p.previousElementSibling) { const q = p.getBoundingClientRect(); if (q.width > 0 && q.bottom > r.top + 2 && q.top < r.bottom - 2 && q.left < r.left - 2 && (p.tagName === e.tagName && p.className === e.className || e.parentElement.children.length > 2 && getComputedStyle(e.parentElement).display.includes('flex'))) return true } return false }
  const firstInRow = (e) => { for (let a = e; a && a !== main; a = a.parentElement) if (rowItem(a)) return false; return true }
  let chars = 0, small = 0
  const edges = new Set()
  const tw = document.createTreeWalker(main, NodeFilter.SHOW_TEXT)
  while (tw.nextNode()) {
    const n = tw.currentNode, t = n.textContent.replace(/\s+/g, ''); if (!t) continue
    const e = n.parentElement
    if (!e || !vis(e) || e.closest('svg, .sx-aladin-map, .sr, .sr-only, script, style')) continue
    const c = getComputedStyle(e), r = e.getBoundingClientRect()
    chars += t.length; if (parseFloat(c.fontSize) < 15) small += t.length
    // a left edge counts once per row; labels printed on a picture and the parts of a small data graphic
    // (bar pairs, meters, colour keys) belong to that graphic, not to the page's grid
    if (r.top < innerHeight && r.bottom > 0 && /^(block|grid|flex|list-item)$/.test(c.display) && !e.closest('.lab-canvas, .pm-bars, .meter, .legend, .blink-frame') && firstInRow(e)) edges.add(Math.round(r.left / 8) * 8)
  }
  // share of the first screen that shows a graphic: what is actually on top at a grid of 48 x 30 points
  // (so a picture clipped by its frame, or covered by something else, counts only where it is seen)
  const SEL = 'canvas, img, video, .plot, svg.mv-vec, svg.var-dots, svg.gd-dia, svg.vglyph, svg.vpips, .stage, figure svg, .dx-funnel-plot'
  let hit = 0, tot = 0
  for (let i = 0; i < 48; i++) for (let k = 0; k < 30; k++) {
    const el = document.elementFromPoint(((i + 0.5) / 48) * innerWidth, ((k + 0.5) / 30) * innerHeight)
    tot++; if (el && main.contains(el) && el.closest(SEL)) hit++
  }
  return { chars, small: chars ? small / chars : 0, graphics: hit / tot, edges: edges.size }
}"""

PAGES = {
    "home": ("/", 0.33), "sky": ("/#/sky/162.294%20-53.317?fov=0.15", 0.5), "target": ("/#/target/wise0855", 0.5), "lab": ("/#/lab/cybele", 0.5),
    "object": ("/#/field/cybele/track/0", 0.5), "movers": ("/#/movers", None), "guide": ("/#/guide", None), "targets": ("/#/targets", None), "discovery": ("/#/discovery", None),
    "follow": ("/#/follow", None), "comet": ("/#/comet", None),
}


@pytest.mark.parametrize("page", list(PAGES))
def test_visual_rules(base, browser, page):
    route, min_graphics = PAGES[page]
    ctx, pg = new_page(browser, init="try { localStorage.setItem('sx:tour:quick', '1'); localStorage.setItem('sx:tour:lab', '1') } catch (e) {}")
    pg.goto(base + route, wait_until="load")
    pg.wait_for_timeout(7000)
    m = pg.evaluate(CENSUS)
    ctx.close()
    assert m["chars"] > 50, m
    assert m["small"] <= 0.25, f"{page}: {m['small']:.0%} of the text is under 15 px"
    if min_graphics is not None:
        assert m["graphics"] >= min_graphics, f"{page}: graphics cover {m['graphics']:.0%} of the first screen"
    assert m["edges"] <= 8, f"{page}: {m['edges']} different left edges in the first screen"
