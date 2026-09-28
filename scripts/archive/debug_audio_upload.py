# -*- coding: utf-8 -*-
"""Verify drag-drop audio upload for the current song."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    print("audio player before:", page.locator("#ll-audio").count())

    # open accordion and upload
    page.get_by_text("🎵 为当前歌曲上传音频").click()
    page.wait_for_timeout(800)
    page.locator("#ll-audio-up input[type='file']").set_input_files(
        "test_audio.wav")
    page.wait_for_timeout(3500)

    body = page.inner_text("body")
    print("status ok:", "✅ 已为《cardigan》添加音频" in body)
    print("audio player after:", page.locator("#ll-audio").count())
    src = page.locator("#ll-audio").get_attribute("src")
    print("audio src:", src)
    browser.close()
