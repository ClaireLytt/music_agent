# -*- coding: utf-8 -*-
"""Verify per-line chat history loads when a lyric line is re-opened."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    # ensure cardigan selected (first song)
    songs = page.locator("#ll-songs input[type='radio']")
    print("selected:", songs.first.is_checked())

    # click first lyric line (line_index 0, has seeded history)
    line = page.locator(".lyric-line[data-index='0']")
    print("line text:", line.inner_text())
    line.click()
    page.wait_for_timeout(2500)

    body = page.inner_text("body")
    print("topic shows line:", "正在讨论" in body and "Vintage tee" in body)
    print("history user q shown:", "vintage tee有什么含义" in body)
    print("history ai a shown:", "这是测试历史记录" in body)

    # click another line -> chat should reset to hint (no history there)
    page.locator(".lyric-line[data-index='1']").click()
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    print("other line has no stale history:", "这是测试历史记录" not in body)

    # back to line 0 -> history reappears
    page.locator(".lyric-line[data-index='0']").click()
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    print("history reappears:", "这是测试历史记录" in body)
    browser.close()
