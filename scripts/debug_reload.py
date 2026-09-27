# -*- coding: utf-8 -*-
"""Verify the stale-page guard: open page, keep it open while the server is
restarted externally, confirm the page reloads itself and stays functional."""
import time

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.evaluate("window.__stale_marker = 1")
    print("page open, marker set — restart the server now", flush=True)

    deadline = time.time() + 60
    reloaded = False
    while time.time() < deadline:
        time.sleep(2)
        try:
            marker = page.evaluate("window.__stale_marker || 0")
        except Exception:
            continue
        if marker != 1:
            reloaded = True
            break
    print("page auto-reloaded:", reloaded, flush=True)

    if reloaded:
        page.wait_for_selector("input[type='radio']", timeout=20000)
        page.wait_for_timeout(2000)
        radios = page.locator("input[type='radio']")
        radios.nth(3).click()
        page.wait_for_timeout(2000)
        title = page.locator(".song-title-display").inner_text()
        print("after reload, click song[3] -> header:", repr(title), flush=True)
    browser.close()
