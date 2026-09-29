# -*- coding: utf-8 -*-
"""Verify multi-artist catalog: search by artist, add Chinese song, duplicate warn."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(URL, wait_until="load")
    page.wait_for_selector("input[type='radio']", timeout=20000)
    page.wait_for_timeout(2500)

    page.get_by_role("tab", name="➕ 添加歌曲").click()
    page.wait_for_timeout(1500)

    cat = page.locator("#ll-catalog input[type='radio']")
    total = cat.count()
    print("catalog entries shown:", total)

    # search by Chinese artist
    box = page.locator("#ll-cat-search textarea, #ll-cat-search input").first
    box.fill("周杰伦")
    page.wait_for_timeout(2000)
    cat = page.locator("#ll-catalog input[type='radio']")
    n = cat.count()
    vals = [cat.nth(i).get_attribute("value") for i in range(n)]
    print(f"after search '周杰伦': {n} entries")
    print("all are 周杰伦:", all("周杰伦" in v for v in vals))

    # narrow to one song and add it
    box.fill("晴天")
    page.wait_for_timeout(2000)
    cat = page.locator("#ll-catalog input[type='radio']")
    vals = [cat.nth(i).get_attribute("value") for i in range(cat.count())]
    print("after search '晴天':", vals)
    cat.first.click()
    page.wait_for_timeout(500)
    page.get_by_role("button", name="＋ 添加到我的列表").click()
    page.wait_for_timeout(3000)
    body = page.inner_text("body")
    print("add status ok:", "已添加《晴天》" in body)

    # player tab: 晴天 should be in list and selected
    page.get_by_role("tab", name="🎧 播放解读").click()
    page.wait_for_timeout(1500)
    songs = page.locator("#ll-songs input[type='radio']")
    labels = [songs.nth(i).get_attribute("value") for i in range(songs.count())]
    print("song list now:", labels)
    checked = [songs.nth(i).is_checked() for i in range(songs.count())]
    sel = labels[checked.index(True)] if True in checked else None
    print("selected song:", sel)
    title = page.locator(".song-title-display").inner_text()
    print("lyrics header:", repr(title))

    # duplicate add should warn
    page.get_by_role("tab", name="➕ 添加歌曲").click()
    page.wait_for_timeout(1000)
    page.locator("#ll-catalog input[type='radio']").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="＋ 添加到我的列表").click()
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    print("duplicate warns:", "已在你的列表中" in body)

    # search by western artist still works
    page.locator("#ll-cat-search textarea, #ll-cat-search input").first.fill("adele")
    page.wait_for_timeout(2000)
    cat = page.locator("#ll-catalog input[type='radio']")
    vals = [cat.nth(i).get_attribute("value") for i in range(cat.count())]
    print("after search 'adele':", vals)
    browser.close()
