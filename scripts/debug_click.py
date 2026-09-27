# -*- coding: utf-8 -*-
"""Playwright diagnostic: are the radio dots actually clickable in a real browser?"""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"


def probe(page, label, loc):
    n = loc.count()
    print(f"\n== {label}: {n} radio inputs ==")
    for i in range(n):
        inp = loc.nth(i)
        box = inp.bounding_box()
        if not box:
            print(f"  [{i}] NO bounding box (hidden?)")
            continue
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        top = page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                if (!el) return 'NONE';
                const cs = getComputedStyle(el);
                return el.tagName + '#' + (el.id || '-') + '.' +
                       (typeof el.className === 'string' ? el.className.slice(0, 60) : '-') +
                       ' | pe=' + cs.pointerEvents + ' z=' + cs.zIndex;
            }""",
            [cx, cy],
        )
        covered = page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                return el ? (el.tagName === 'INPUT' || !!el.closest('label')) : false;
            }""",
            [cx, cy],
        )
        val = inp.get_attribute("value") or ""
        print(f"  [{i}] value={val[:36]!r} at ({cx:.0f},{cy:.0f}) topEl={top} reachable={covered}")


def try_click(page, label, loc, idx):
    inp = loc.nth(idx)
    before = inp.is_checked()
    try:
        inp.click(timeout=3000)
        page.wait_for_timeout(600)
        after = inp.is_checked()
        print(f"CLICK {label}[{idx}]: checked {before} -> {after}")
    except Exception as e:
        print(f"CLICK {label}[{idx}] FAILED: {type(e).__name__}: {str(e).splitlines()[0]}")


import sys

W = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
H = int(sys.argv[2]) if len(sys.argv) > 2 else 900

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": W, "height": H})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)
    print("URL after load:", page.url)

    # song list radio = first fieldset/group with 5 inputs; identify groups by label text
    groups = page.locator(".gradio-container fieldset, .gradio-container div[data-testid='radio']")
    radios = page.locator("input[type='radio']")
    print("total radio inputs on page:", radios.count())

    song_radios = page.locator("div:has(> span:has-text('歌曲列表')) input[type='radio']")
    if song_radios.count() == 0:
        song_radios = page.locator("input[name][type='radio']")
    # simpler: group by name attribute
    names = page.evaluate(
        "() => [...document.querySelectorAll('input[type=radio]')].map(i => i.name)")
    print("radio name attrs:", names)

    # probe every radio on the page
    probe(page, "ALL radios", radios)

    # click tests: song 4, song 5 (indices 3,4 of first 5), then later groups
    total = radios.count()
    for idx in [3, 4]:
        if idx < total:
            try_click(page, "radio", radios, idx)
    # sort group: next 4 after the songs (5..8), search mode: (9..10)
    for idx in [5, 6, 9, 10]:
        if idx < total:
            try_click(page, "radio", radios, idx)

    if errors:
        print("\nJS pageerrors:")
        for e in errors[:10]:
            print("  ", e)
    else:
        print("\nno JS pageerrors")
    browser.close()
