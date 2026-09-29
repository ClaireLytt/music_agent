# -*- coding: utf-8 -*-
"""Verify: song list one-per-line; settings tab exists and saves."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"
USER_SETTINGS = Path("data/user_settings.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    # 1. song list: one per line (each radio strictly below the previous)
    songs = page.locator("#ll-songs input[type='radio']")
    n = songs.count()
    ys = []
    for i in range(n):
        box = songs.nth(i).bounding_box()
        ys.append(box["y"] if box else -1)
    print("song radio count:", n, "y coords:", [round(y) for y in ys])
    one_per_line = all(ys[i + 1] > ys[i] + 5 for i in range(len(ys) - 1))
    print("one song per line:", one_per_line)

    # 2. settings tab
    page.get_by_role("tab", name="⚙️ 设置").click()
    page.wait_for_timeout(1000)
    pw = page.locator("input[type='password']")
    print("password field present:", pw.count() > 0)
    key_val = pw.first.input_value() if pw.count() else ""
    print("key prefilled:", bool(key_val))

    # 3. save round-trip (re-saves current values — harmless)
    if key_val:
        page.get_by_role("button", name="💾 保存设置").click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        saved = "已保存并生效" in body
        print("save status shown:", saved)
        print("user_settings.json written:", USER_SETTINGS.exists())
        if USER_SETTINGS.exists():
            data = json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
            print("json keys:", sorted(data.keys()),
                  "key matches:", data.get("api_key") == key_val)
    else:
        # no key configured: empty save must warn, and must NOT write the file
        page.get_by_role("button", name="💾 保存设置").click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        print("empty-key warning shown:", "请填写 API Key" in body)
        print("user_settings.json NOT written:", not USER_SETTINGS.exists())
    browser.close()
