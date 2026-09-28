# -*- coding: utf-8 -*-
"""Verify: title-only song labels, header shows artist+album (no year), footer hidden."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    radios = page.locator("input[type='radio']")
    labels = [radios.nth(i).get_attribute("value") for i in range(5)]
    print("song labels:", labels)
    print("title-only labels:", all("—" not in (l or "") for l in labels))

    radios.nth(3).click()
    page.wait_for_timeout(2000)
    title = page.locator(".song-title-display").inner_text()
    meta = page.locator(".song-meta-display").inner_text()
    print("header title:", repr(title))
    print("header meta:", repr(meta))
    print("meta has artist:", "Bon Iver" in meta or "Taylor" in meta)
    print("meta has no year:", "2020" not in meta and "(" not in meta)

    footer_visible = page.evaluate(
        """() => { const f = document.querySelector('footer');
                   return f ? getComputedStyle(f).display !== 'none' : false; }"""
    )
    print("footer visible:", footer_visible)
    browser.close()
