# -*- coding: utf-8 -*-
"""Verify whole-song echo map (🥚 markers) and share-card generation."""
import sys

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"
TS_SONG = "cardigan"

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        ok = False


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']")
    page.wait_for_timeout(2500)

    # --- echo map on a Taylor Swift song (corpus has same-artist coverage) ---
    radio = page.locator("label", has_text=TS_SONG).first
    check("TS song appears in list", radio.count() > 0)
    radio.click()
    page.wait_for_timeout(2000)

    # hidden channel textbox exists but is not visible
    box = page.locator("#ll-echo-map")
    check("echo-map channel present", box.count() > 0)
    visible = page.evaluate(
        "() => { const el = document.querySelector('#ll-echo-map');"
        " return el ? el.offsetParent !== null : null; }")
    check("echo-map channel hidden", visible is False, f"visible={visible}")

    # wait for markers (cold index can take ~6-10s + 600ms poller)
    marks = 0
    for _ in range(30):
        marks = page.locator(".echo-mark").count()
        if marks > 0:
            break
        page.wait_for_timeout(1000)
    check("echo marks rendered on lyrics", marks > 0, f"marks={marks}")

    tooltip = page.evaluate(
        "() => { const el = document.querySelector('.echo-mark');"
        " return el ? el.getAttribute('title') : null; }")
    check("echo mark has tooltip", bool(tooltip and "彩蛋" in tooltip))

    total_lines = page.locator(".lyric-line").count()
    check("marks are a subset of lines", 0 < marks < total_lines,
          f"{marks}/{total_lines}")

    # --- share card: guard message when no line picked ---
    page.locator("#ll-card").scroll_into_view_if_needed()
    page.locator("#ll-card button", has_text="分享卡片").first.click()
    page.wait_for_timeout(600)
    page.locator("button", has_text="生成歌词金句卡").first.click()
    page.wait_for_timeout(1500)
    status = page.locator("#ll-card").inner_text()
    check("guard message without picked line", "请先点击一句歌词" in status,
          f"status={status[:60]!r}")

    # --- pick a lyric line, then generate the card ---
    page.evaluate(
        "() => { const el = document.querySelector('.lyric-line');"
        " el.scrollIntoView(); el.click(); }")
    page.wait_for_timeout(2500)
    page.locator("button", has_text="生成歌词金句卡").first.click()

    img_visible = False
    for _ in range(20):
        img_visible = page.evaluate(
            "() => { const img = document.querySelector('#ll-card img');"
            " return !!(img && img.offsetParent !== null && img.src); }")
        if img_visible:
            break
        page.wait_for_timeout(1000)
    check("card image rendered after generate", img_visible)

    status2 = page.locator("#ll-card").inner_text()
    check("no error status after generate", "失败" not in status2 and "⚠" not in status2,
          f"status={status2[:60]!r}")

    browser.close()

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
