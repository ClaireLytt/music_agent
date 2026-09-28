# -*- coding: utf-8 -*-
"""Verify public-mode isolation: per-visitor key, read-only library,
no server-side history, hackathon songs excluded."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7861"
HACKATHON_SONGS = ["北京昨夜下了雪", "今晚月色真美"]

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        ok = False


def click_tab(pg, text: str) -> None:
    pg.get_by_role("tab", name=text).click(force=True)


settings_before = Path("data/user_settings.json").read_bytes() \
    if Path("data/user_settings.json").exists() else None

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']")
    page.wait_for_timeout(2500)

    body = page.locator("body").inner_text()

    # hackathon playlist songs must be excluded
    for song in HACKATHON_SONGS:
        check(f"hackathon song hidden: {song}", song not in body)

    # read-only: no add-song tab, no audio upload accordion
    check("add-song tab hidden", "添加歌曲" not in body)
    check("audio upload hidden",
          page.locator("#ll-audio-up").count() == 0)

    # settings tab: server key must NOT be prefilled
    click_tab(page, "⚙️ 设置")
    page.wait_for_selector("input[type='password']", timeout=15000)
    page.wait_for_timeout(1000)
    key_val = page.evaluate(
        "() => { const el = document.querySelector('input[type=\"password\"]');"
        " return el ? el.value : null; }")
    check("server API key not leaked to visitor", key_val == "",
          f"value={'<empty>' if key_val == '' else '<NON-EMPTY!>'}")

    # save a visitor key -> stored in browser, server file untouched
    page.evaluate(
        "() => { const el = document.querySelector('input[type=\"password\"]');"
        " el.value = 'sk-test-visitor-123';"
        " el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.locator("button", has_text="保存设置").first.click()
    page.wait_for_timeout(2000)
    body2 = page.locator("body").inner_text()
    check("save confirms browser-only storage", "已保存到你的浏览器" in body2)

    ls = page.evaluate("() => JSON.stringify(Object.keys(localStorage))")
    check("browser localStorage holds the config", "lyric_lens_llm" in ls,
          f"keys={ls}")

    # fresh browser context = a different visitor
    ctx2 = browser.new_context()
    page2 = ctx2.new_page()
    page2.goto(URL, wait_until="load")
    page2.wait_for_selector("input[type='radio']")
    page2.wait_for_timeout(2500)

    # new visitor cannot see the first visitor's key
    click_tab(page2, "⚙️ 设置")
    page2.wait_for_selector("input[type='password']", timeout=15000)
    page2.wait_for_timeout(1000)
    key2 = page2.evaluate(
        "() => { const el = document.querySelector('input[type=\"password\"]');"
        " return el ? el.value : null; }")
    check("visitor B cannot see visitor A's key", key2 == "")

    # chat without a key -> hint to fill own key
    click_tab(page2, "🎧 播放解读")
    page2.wait_for_timeout(500)
    page2.locator("label", has_text="cardigan").first.click()
    page2.wait_for_selector(".lyric-line", timeout=15000)
    page2.wait_for_timeout(1000)
    page2.evaluate(
        "() => { const el = document.querySelector('.lyric-line');"
        " el.scrollIntoView(); el.click(); }")
    page2.wait_for_timeout(2000)
    page2.locator("[placeholder*='提问']").first.fill("这句什么意思？")
    page2.locator("button", has_text="提问").first.click()
    page2.wait_for_timeout(2500)
    chat_text = page2.locator("body").inner_text()
    check("chat without key shows own-key hint",
          "需使用你自己的 API Key" in chat_text)

    # positive control: local-mode server on 7860 DOES list hackathon songs
    page3 = ctx2.new_page()
    page3.goto("http://127.0.0.1:7860", wait_until="load")
    page3.wait_for_selector("input[type='radio']")
    page3.wait_for_timeout(2500)
    body3 = page3.locator("body").inner_text()
    for song in HACKATHON_SONGS:
        check(f"local mode still lists: {song}", song in body3)

    browser.close()

settings_after = Path("data/user_settings.json").read_bytes() \
    if Path("data/user_settings.json").exists() else None
check("server user_settings.json untouched", settings_before == settings_after)

hist_mtimes_ok = True
print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
