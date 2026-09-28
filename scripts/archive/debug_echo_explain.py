# -*- coding: utf-8 -*-
"""One real LLM call through the echo-explain button."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    page.locator(".lyric-line", has_text="Dancin' in your Levi's").first.click()
    page.wait_for_timeout(6000)
    print("cards:", page.locator(".echo-card").count())

    page.get_by_text("✨ 让 AI 解释这些呼应").click()
    # wait for thinking indicator then final answer
    page.wait_for_timeout(3000)
    panel = page.locator("#ll-echo").inner_text()
    print("thinking shown:", "正在分析" in panel)

    for _ in range(60):
        page.wait_for_timeout(3000)
        panel = page.locator("#ll-echo").inner_text()
        if "正在分析" not in panel:
            break
    tail = panel.split("让 AI 解释这些呼应")[-1].strip()
    print("explanation length:", len(tail))
    print("explanation:", tail[:500])
    print("no error:", "⚠️" not in tail)
    browser.close()
