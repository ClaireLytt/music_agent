# -*- coding: utf-8 -*-
"""End-to-end UI check: radio clicks must drive real UI updates."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    radios = page.locator("input[type='radio']")

    # 1. click song 4 (exile) -> lyrics header should switch to exile
    radios.nth(3).click()
    page.wait_for_timeout(2000)
    title = page.locator(".song-title-display").inner_text()
    print("after click song[3]: header title =", repr(title))

    # 2. click song 5 (Anti-Hero)
    radios.nth(4).click()
    page.wait_for_timeout(2000)
    title = page.locator(".song-title-display").inner_text()
    print("after click song[4]: header title =", repr(title))

    # 3. click sort album_asc -> first song radio label should change
    first_label_before = radios.nth(0).get_attribute("value")
    radios.nth(7).click()  # album_asc
    page.wait_for_timeout(2000)
    first_label_after = page.locator("input[type='radio']").nth(0).get_attribute("value")
    print(f"sort album_asc: first label {first_label_before!r} -> {first_label_after!r}")

    # 4. search mode radio toggle
    page.locator("input[type='radio']").last.click()
    page.wait_for_timeout(300)
    print("search-mode 'sem' checked =", page.locator("input[type='radio']").last.is_checked())

    page.screenshot(path="scripts/debug_screen.png", full_page=False)
    print("screenshot saved")
    browser.close()
