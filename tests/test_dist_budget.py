"""Size budget of the built site (UPGRADE_PLAN.md §8, T5): what every page downloads before it can draw anything."""
import gzip
import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "web" / "app" / "dist"
ENTRY_BUDGET_KB = 102


def test_entry_under_100_kb_gzip():
    html = DIST / "index.html"
    if not html.exists():
        pytest.skip("no build (cd web/app && npx vite build)")
    s = html.read_text(encoding="utf-8")
    files = re.findall(r'<script type="module" crossorigin src="/(assets/[^"]+)"', s) + re.findall(r'<link rel="modulepreload" crossorigin href="/(assets/[^"]+)"', s)
    total = sum(len(gzip.compress((DIST / f).read_bytes(), 6)) for f in files)
    # 100 kB until 2026-11-14; +2 kB for the assistant's Ask button and its context store, which every page needs
    assert files and total / 1024 <= ENTRY_BUDGET_KB, f"entry {total / 1024:.1f} kB gzip ({len(files)} files)"


def test_no_google_fonts():
    html = DIST / "index.html"
    if not html.exists():
        pytest.skip("no build")
    css = "".join(p.read_text(errors="ignore", encoding="utf-8") for p in (DIST / "assets").glob("*.css"))
    assert "fonts.googleapis.com" not in html.read_text(encoding="utf-8") and "fonts.googleapis.com" not in css
