# -*- coding: utf-8 -*-
"""Verify preview-segment lyric sync for imported hackathon-playlist songs."""
import sys

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"
SONG = "北京昨夜下了雪"

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

    # select the imported song
    radio = page.locator("label", has_text=SONG).first
    check("song appears in list", radio.count() > 0)
    radio.click()
    page.wait_for_timeout(2000)

    audio = page.locator("#ll-audio")
    check("audio element present", audio.count() > 0)
    offset = page.evaluate(
        "() => { const a = document.getElementById('ll-audio');"
        " return a ? a.dataset.offset : null; }")
    check("data-offset set", offset == "58502", f"offset={offset}")

    hint = page.locator(".preview-hint")
    check("preview hint shown", hint.count() > 0 and "试听片段" in hint.inner_text())

    # audio should actually load (preview mp3 served by gradio)
    dur = page.evaluate(
        "() => new Promise(res => { const a = document.getElementById('ll-audio');"
        " if (!a) return res(-1);"
        " if (a.readyState >= 1) return res(a.duration);"
        " a.addEventListener('loadedmetadata', () => res(a.duration));"
        " setTimeout(() => res(-2), 8000); })")
    check("audio metadata loaded", isinstance(dur, (int, float)) and 15 < dur < 90,
          f"duration={dur}")

    # play muted for 2s -> active lyric line should be inside [58502, 78495]
    page.evaluate(
        "() => { const a = document.getElementById('ll-audio');"
        " a.muted = true; a.currentTime = 1; return a.play(); }")
    page.wait_for_timeout(2000)
    active_ts = page.evaluate(
        "() => { const el = document.querySelector('.lyric-line.active');"
        " return el ? parseFloat(el.dataset.ts) : null; }")
    check("active line inside preview window",
          active_ts is not None and 58502 <= active_ts <= 78495,
          f"active ts={active_ts}")
    page.evaluate("() => document.getElementById('ll-audio').pause()")

    # click a lyric line inside the segment -> currentTime = (ts-offset)/1000
    target_ts = page.evaluate(
        "() => { const lines = [...document.querySelectorAll('.lyric-line')];"
        " const el = lines.find(l => parseFloat(l.dataset.ts) > 65000"
        "   && parseFloat(l.dataset.ts) < 78000);"
        " if (!el) return null; el.scrollIntoView(); el.click();"
        " return parseFloat(el.dataset.ts); }")
    page.wait_for_timeout(800)
    cur = page.evaluate(
        "() => document.getElementById('ll-audio').currentTime")
    expected = (target_ts - 58502) / 1000 if target_ts else -1
    check("line click seeks with offset",
          target_ts is not None and abs(cur - expected) < 1.5,
          f"ts={target_ts} cur={cur:.2f} expected={expected:.2f}")

    browser.close()

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
