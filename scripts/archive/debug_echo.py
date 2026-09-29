# -*- coding: utf-8 -*-
"""Verify the intertextuality (echo) tracker panel."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    body = page.inner_text("body")
    print("panel title shown:", "彩蛋 · 互文追踪" in body)
    print("default hint shown:", "发现歌与歌之间" in body)

    # guard: explain before picking a line
    page.get_by_text("✨ 让 AI 解释这些呼应").click()
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    print("guard message:", "请先点击一句歌词" in body)

    # click a cardigan line with strong known echoes
    line = page.locator(".lyric-line", has_text="Dancin' in your Levi's").first
    print("line found:", line.count() > 0)
    line.click()
    page.wait_for_timeout(6000)

    body = page.inner_text("body")
    print("topic updated:", "正在讨论" in body and "Levi's" in body)
    print("echo panel text:", page.locator("#ll-echo").inner_text()[:300])

    cards = page.locator(".echo-card")
    n = cards.count()
    print("echo cards:", n)
    for i in range(n):
        print("  -", cards.nth(i).inner_text().replace("\n", " | "))

    body = page.inner_text("body")
    print("no self-echo (cardigan excluded):", "《cardigan》" not in body)

    # switching song resets the panel
    page.locator("#ll-songs input[type='radio']").nth(1).click()
    page.wait_for_timeout(2500)
    print("panel reset after song switch:",
          page.locator(".echo-card").count() == 0)

    browser.close()
