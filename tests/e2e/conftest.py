"""Browser checks against a running site (default http://127.0.0.1:8791; SX_E2E_BASE=... for another address).

They take a few minutes, so they run only with SX_E2E=1 (`npm run check` in web/app sets it).
Chromium is launched with its DEFAULT flags on purpose (UPGRADE_PLAN.md §8.1):
  - with --use-angle=vulkan this server's headless Chromium leaves the home all-sky canvas blank at 1440 px and fakes a
    0.76 s long task, which is a measuring artefact, not a site bug;
  - default flags mean software WebGL here, i.e. the "device without GPU acceleration" case the site must handle.
"""
import os
import urllib.request

import pytest

BASE = os.environ.get("SX_E2E_BASE", "http://127.0.0.1:8791").rstrip("/")
ON = os.environ.get("SX_E2E") == "1"


def pytest_collection_modifyitems(config, items):
    if ON:
        return
    skip = pytest.mark.skip(reason="browser checks: set SX_E2E=1 (npm run check does)")
    for it in items:
        if f"{os.sep}e2e{os.sep}" in str(it.fspath):
            it.add_marker(skip)


@pytest.fixture(scope="session")
def base():
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=5)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"site not reachable at {BASE}: {e}")
    return BASE


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def new_page(browser, lang="zh-Hant", mobile=False, init=""):
    vp = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}
    ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, device_scale_factor=2 if mobile else 1)
    ctx.add_init_script(f"try {{ localStorage.setItem('sx:language:v1', '{lang}') }} catch (e) {{}}\n{init}")
    return ctx, ctx.new_page()
