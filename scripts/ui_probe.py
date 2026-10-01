#!/usr/bin/env python3
"""UI probe: drive the real browser through every tab and interaction,
collect failures into a machine-readable report (the "detect" half of the
UI test-and-fix loop — scripts/ui_agent.py and the /ui-fixloop skill are
the "fix" half).

Usage:
    python scripts/ui_probe.py                # spawn a fresh server, probe it
    python scripts/ui_probe.py --port 7860    # attach to a running server
    python scripts/ui_probe.py --json         # print the report JSON to stdout

Outputs:
    data/ui_probe/report.json   structured findings (id, name, ok, detail)
    data/ui_probe/<check>.png   screenshot of every failed check
Exit code: number of failed checks (0 = all green).

Design notes:
- Checks never abort the run; every failure is recorded and probing continues.
- LLM-priced actions are exercised only through their free guard paths.
- Destructive actions (delete song, rebuild index) are NOT clicked.
- Known-benign console noise (CDN offline for the optional waveform, favicon)
  is whitelisted; everything else that hits the JS console as an error, any
  pageerror, and any server-side traceback fails the corresponding check.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "ui_probe"

# console errors that do not indicate app bugs
_BENIGN_CONSOLE = (
    "cdnjs.cloudflare.com",      # optional waveform CDN may be unreachable
    "favicon",
    "manifest.json",
    "the server responded with a status of 404",  # gradio asset probes
)

AUDIO_SONG = "北京昨夜下了雪"   # library song that ships with audio
PLAIN_SONG = "cardigan"        # library song without audio


class Probe:
    def __init__(self, page, server_log: Path | None):
        self.page = page
        self.server_log = server_log
        self.results: list[dict] = []
        self.console_errors: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror",
                lambda e: self.console_errors.append(f"pageerror: {e}"))

    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text
        if any(b in text for b in _BENIGN_CONSOLE):
            return
        self.console_errors.append(text)

    def check(self, check_id: str, name: str, fn) -> None:
        """Run one check; record ok/fail + detail, screenshot on failure."""
        try:
            detail = fn() or ""
            ok = True
        except Exception as exc:  # noqa: BLE001 — a failed check is data
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
            try:
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(OUT_DIR / f"{check_id}.png"))
            except Exception:
                pass
        self.results.append(
            {"id": check_id, "name": name, "ok": ok, "detail": str(detail)})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {check_id}: {name}"
              + (f"  -- {detail}" if not ok else ""))

    # ── helpers ───────────────────────────────────────────

    def tab(self, name: str) -> None:
        self.page.get_by_role("tab", name=name).click()
        self.page.wait_for_timeout(700)

    def must(self, cond: bool, msg: str) -> None:
        if not cond:
            raise AssertionError(msg)

    def count(self, selector: str) -> int:
        return self.page.locator(selector).count()

    def wait_until(self, fn, timeout_s: float = 25.0, msg: str = "") -> None:
        """Poll a condition — first-time actions may block on cold model
        loads (embedding warm-up), which is expected, not a bug."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if fn():
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        raise AssertionError(msg or f"condition not met in {timeout_s}s")


def wait_server(base: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base, timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"server at {base} not ready in {timeout_s}s")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_probe(base: str, server_log: Path | None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        probe = Probe(page, server_log)
        pg, must, count = page, probe.must, probe.count

        # ── boot ──
        def c_boot():
            pg.goto(base + "/?__theme=light", wait_until="load")
            pg.wait_for_selector(".lyric-line", timeout=40000)
            pg.wait_for_timeout(4000)
            must(count("#ll-songs input[type=radio]") >= 2, "song list empty")
        probe.check("boot", "page loads, songs & lyrics render", c_boot)

        # ── play tab ──
        def c_line_click():
            pg.locator(".lyric-line").nth(2).click()
            must(count(".lyric-line.picked") == 1, "no picked line")
            # first pick blocks on the embedding model warm-up; the
            # multilingual L12 model loads ~5x slower than the old L6,
            # so this one check gets a much larger window (everything
            # after it runs against a warm model)
            probe.wait_until(
                lambda: "正在讨论" in pg.locator(".chat-topic").inner_text(),
                timeout_s=120.0,
                msg="chat topic not updated after lyric click")
        probe.check("line_click", "lyric click selects line + chat topic",
                    c_line_click)

        def c_echo_panel():
            probe.wait_until(
                lambda: any(k in pg.locator("#ll-echo").inner_html()
                            for k in ("echo-card", "未在", "语料库")),
                msg="echo panel neither results nor hint")
        probe.check("echo_panel", "echo panel populated after line click",
                    c_echo_panel)

        def c_share_guard():
            # switch to a different song: resets the chat session so the
            # guard path (no picked line) is what gets exercised
            pg.get_by_role("radio", name="exile").check()
            pg.wait_for_timeout(2500)
            pg.get_by_text("🖼️ 分享卡片").click()
            pg.wait_for_timeout(300)
            pg.get_by_role("button", name="生成歌词金句卡").click()
            pg.wait_for_timeout(1500)
            must("请先点击" in pg.locator("#ll-card").inner_text(),
                 "share-card guard hint missing")
        probe.check("share_guard", "share card without picked line -> guard",
                    c_share_guard)

        def c_audio_tools():
            pg.get_by_role("radio", name=AUDIO_SONG).check()
            pg.wait_for_timeout(3500)
            must(count("#ll-audio") == 1, "audio element missing")
            must(count(".ptool") >= 3, "player tools missing")
            must(count("#ll-rhyme-toggle") == 1, "rhyme toggle missing")
        probe.check("audio_tools", "audio song renders player tools",
                    c_audio_tools)

        def c_rhyme_toggle():
            pg.locator("#ll-rhyme-toggle").check()
            pg.wait_for_timeout(500)
            visible = pg.evaluate(
                "Array.from(document.querySelectorAll('.rhyme-mark'))"
                ".filter(m => m.offsetParent !== null).length")
            must(visible > 0, "no rhyme dots after toggle")
            pg.locator("#ll-rhyme-toggle").uncheck()
        probe.check("rhyme_toggle", "rhyme toggle shows colored dots",
                    c_rhyme_toggle)

        def c_karaoke():
            pg.evaluate("document.getElementById('ll-audio').play()")
            pg.wait_for_timeout(2500)
            grad = pg.evaluate(
                "(document.querySelector('.lyric-line.active .lyric-text')"
                " || {style:{}}).style.backgroundImage || ''")
            pg.evaluate("document.getElementById('ll-audio').pause()")
            must("linear-gradient" in grad, f"no karaoke gradient: {grad!r}")
        probe.check("karaoke", "karaoke sweep during playback", c_karaoke)

        def c_ab_loop():
            pg.evaluate("document.getElementById('ll-audio').play()")
            pg.wait_for_timeout(800)
            pg.locator("#ll-ab-a").click()
            pg.wait_for_timeout(1200)
            pg.locator("#ll-ab-b").click()
            pg.wait_for_timeout(300)
            pg.evaluate("document.getElementById('ll-audio').pause()")
            must(pg.locator("#ll-ab-clear").is_visible(),
                 "A-B clear button not shown after setting loop")
            pg.locator("#ll-ab-clear").click()
        probe.check("ab_loop", "A-B loop set + clear", c_ab_loop)

        def c_notes():
            pg.get_by_text("📝 听歌笔记").click()
            pg.wait_for_timeout(400)
            box = pg.get_by_placeholder("在当前播放位置记一句感想…")
            box.fill("ui-probe 自检笔记")
            pg.get_by_role("button", name="添加").click()
            pg.wait_for_timeout(1500)
            must(count(".note-item") >= 1, "note not added")
            # delete exactly the probe note
            item = pg.locator(".note-item",
                              has_text="ui-probe 自检笔记").first
            item.locator(".note-del").click()
            pg.wait_for_timeout(1500)
            must(count(".note-item >> text=ui-probe 自检笔记") == 0,
                 "probe note not deleted")
        probe.check("notes", "listening note add + delete roundtrip", c_notes)


        def c_search_kw():
            probe.tab("🎧 播放解读")
            pg.locator("#ll-search input, #ll-search textarea").fill("scarf")
            pg.get_by_role("button", name="搜索", exact=True).click()
            probe.wait_until(
                lambda: count(".search-hit") >= 1
                or "没有找到" in pg.locator("body").inner_text(),
                msg="keyword search produced neither hits nor empty-state")
            must(count(".search-hit") >= 1, "no hits for 'scarf'")
            pg.get_by_role("button", name="✕ 清除").click()
            probe.wait_until(lambda: count(".search-hit") == 0,
                             msg="clear button did not empty results")
        probe.check("search_kw", "keyword search + clear button", c_search_kw)

        def c_search_semantic():
            pg.locator("#ll-search input, #ll-search textarea").fill(
                "losing someone you love")
            pg.get_by_role("radio", name="语义").check()
            pg.get_by_role("button", name="搜索", exact=True).click()
            probe.wait_until(   # first semantic query may load the model
                lambda: count(".search-mode-tag") >= 1, timeout_s=60,
                msg="semantic search returned nothing (no mode tag)")
            pg.get_by_role("button", name="✕ 清除").click()
            pg.get_by_role("radio", name="关键词").check()
        probe.check("search_semantic", "semantic search (or fallback) works",
                    c_search_semantic)

        def c_sort_modes():
            n = count("#ll-songs input[type=radio]")
            pg.get_by_role("radio", name="专辑（按字母排序）").check()
            pg.wait_for_timeout(1500)
            must(count("#ll-songs input[type=radio]") == n,
                 "song count changed after re-sort")
            must(count("#ll-songs input[type=radio]:checked") == 1,
                 "selection lost after re-sort")
            pg.get_by_role("radio", name="添加顺序（最早在前）").check()
            pg.wait_for_timeout(1500)
        probe.check("sort_modes", "re-sorting keeps songs + selection",
                    c_sort_modes)

        def c_chat_guard():
            # fresh song switch resets the chat session -> guard, no LLM cost
            pg.get_by_role("radio", name=PLAIN_SONG).check()
            pg.wait_for_timeout(2500)
            pg.get_by_placeholder("针对这句歌词提问 ...").fill("这句什么意思")
            pg.get_by_role("button", name="提问").click()
            probe.wait_until(
                lambda: "请先点击左侧" in pg.locator("body").inner_text(),
                msg="chat without picked line: guard hint missing")
        probe.check("chat_guard", "chat without picked line -> guard",
                    c_chat_guard)

        def c_debate_guard():
            pg.get_by_role(
                "button",
                name="🎭 乐评人 vs 粉丝 · 双视角辩论这句歌词").click()
            probe.wait_until(
                lambda: "再发起双视角辩论" in pg.locator("body").inner_text(),
                msg="debate without picked line: guard hint missing")
        probe.check("debate_guard", "debate without picked line -> guard",
                    c_debate_guard)

        def c_echo_explain_guard():
            pg.get_by_role("button", name="✨ 让 AI 解释这些呼应").click()
            probe.wait_until(
                lambda: "请先点击一句歌词" in pg.locator("body").inner_text(),
                msg="echo explain guard missing")
        probe.check("echo_explain_guard",
                    "echo explain without line -> guard (no LLM cost)",
                    c_echo_explain_guard)

        def c_echo_card_guard():
            pg.get_by_role("button", name="🖼️ 彩蛋对照卡").click()
            probe.wait_until(
                lambda: "有彩蛋呼应的歌词" in pg.locator("body").inner_text(),
                msg="echo card guard missing")
        probe.check("echo_card_guard", "echo card without echo -> guard",
                    c_echo_card_guard)

        def c_echo_overview():
            pg.get_by_text("🗺️ 本歌彩蛋总览").click()
            probe.wait_until(
                lambda: count(".echo-ov-item") >= 1
                or "未发现" in pg.locator("#ll-echo-overview").inner_text(),
                msg="echo overview neither items nor empty-state")
            if count(".echo-ov-item"):
                goto = pg.locator(".echo-ov-item").first \
                    .get_attribute("data-goto-line")
                pg.locator(".echo-ov-item").first.click()
                probe.wait_until(
                    lambda: count(".lyric-line.picked") == 1
                    and pg.locator(".lyric-line.picked")
                        .get_attribute("data-index") == goto,
                    msg="overview click did not select the right line")
        probe.check("echo_overview", "echo overview list + click-to-jump",
                    c_echo_overview)

        def c_intro_panel():
            pg.get_by_text("📖 歌曲导读").click()
            pg.wait_for_timeout(500)
            html = pg.locator("#ll-intro").inner_html()
            must("song-intro" in html or "尚未生成" in html,
                 "intro panel neither text nor empty-state")
        probe.check("intro_panel", "song intro panel content or hint",
                    c_intro_panel)

        def c_radio_gen_guard():
            # exile has no intro.txt -> the TTS button must guard, not spend
            pg.get_by_role("radio", name="exile").check()
            pg.wait_for_timeout(2500)
            pg.get_by_text("📻 AI 电台").click()
            pg.wait_for_timeout(400)
            pg.get_by_role(
                "button",
                name="🎙️ 为本歌生成串场语音（需先有导读）").click()
            probe.wait_until(
                lambda: "导读" in pg.locator("#ll-radio-acc").inner_text()
                and "先" in pg.locator("#ll-radio-acc").inner_text(),
                msg="radio TTS guard missing for song without intro")
        probe.check("radio_gen_guard", "radio TTS without intro -> guard",
                    c_radio_gen_guard)

        def c_space_shortcut():
            pg.get_by_role("radio", name=AUDIO_SONG).check()
            pg.wait_for_timeout(3000)
            pg.locator("body").press("Space")
            probe.wait_until(
                lambda: pg.evaluate(
                    "!document.getElementById('ll-audio').paused"),
                timeout_s=8, msg="space did not start playback")
            pg.locator("body").press("Space")
            probe.wait_until(
                lambda: pg.evaluate(
                    "document.getElementById('ll-audio').paused"),
                timeout_s=8, msg="space did not pause playback")
        probe.check("space_shortcut", "space toggles play/pause",
                    c_space_shortcut)

        def c_seek_click():
            before = pg.evaluate(
                "document.getElementById('ll-audio').currentTime")
            pg.locator(".lyric-line").nth(6).click()
            probe.wait_until(
                lambda: abs(pg.evaluate(
                    "document.getElementById('ll-audio').currentTime")
                    - before) > 0.5,
                timeout_s=8, msg="lyric click did not seek the audio")
            pg.evaluate("document.getElementById('ll-audio').pause()")
        probe.check("seek_click", "lyric click seeks audio position",
                    c_seek_click)

        # ── evolution tab ──
        def c_evolution():
            probe.tab("🗺️ 艺术家图谱")
            must(count(".evo-timeline") >= 1 or count(".evo-svg") >= 1,
                 "evolution map empty")
        probe.check("evolution", "artist evolution tab renders", c_evolution)

        # ── echo map tab ──
        def c_map_focus():
            probe.tab("🥚 彩蛋地图")
            pg.wait_for_timeout(1500)
            must(count(".egg-focus") == 1, "focus star not rendered")
            must(count(".egg-pair") >= 1, "no quote cards under focus view")
        probe.check("map_focus", "echo map default focus view", c_map_focus)

        def c_map_network():
            pg.get_by_role("radio", name="🕸️ 整体网络").check()
            pg.wait_for_timeout(2500)
            must(count(".egg-edge") >= 1, "network view has no edges")
            pg.get_by_role("radio", name="⭐ 单曲聚焦（简明）").check()
            pg.wait_for_timeout(1500)
        probe.check("map_network", "echo map network view toggle",
                    c_map_network)

        def c_imagery():
            pg.get_by_placeholder("输入意象，如：雨 / scarf / 童年").fill("time")
            pg.get_by_role("button", name="追踪").click()
            pg.wait_for_timeout(6000)
            must(count(".img-timeline") == 1, "imagery timeline missing")
        probe.check("imagery", "imagery trace search", c_imagery)


        def c_map_cross():
            pg.locator("#ll-map-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option", name="🌐 跨歌手引用（全部歌手）").click()
            probe.wait_until(
                lambda: "跨歌手" in pg.locator("body").inner_text()
                and count(".egg-svg") >= 1,
                msg="cross-artist mode did not render")
            # back to the default artist for the following checks
            pg.locator("#ll-map-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option", name="Taylor Swift", exact=True).click()
            # wait until the single-artist graph actually replaced the
            # cross-artist one (cross-mode node keys carry a " · artist"
            # suffix) — a fixed sleep raced the re-render under load and
            # left focus_pick clicking the stale cross-artist SVG
            probe.wait_until(
                lambda: count("g.egg-clickable") >= 1
                and " · " not in (pg.locator("g.egg-clickable").first
                                  .get_attribute("data-focus-pick") or " · "),
                msg="single-artist map did not come back after cross mode")
        probe.check("map_cross", "cross-artist reference mode", c_map_cross)

        def c_focus_pick():
            probe.wait_until(lambda: count(".egg-focus") == 1,
                             msg="focus view not rendered before pick")
            # a queued re-render can occasionally swallow the first click
            # (artist switch and node click landing in the same tick); one
            # bounded retry absorbs that — a real regression fails twice
            last = ""
            for attempt in (1, 2):
                target = pg.locator("g.egg-clickable").first \
                    .get_attribute("data-focus-pick")
                last = target or ""
                pg.locator("g.egg-clickable").first.click()
                try:
                    probe.wait_until(
                        lambda: ("《" + target + "》的彩蛋网络")
                        in pg.locator(".egg-headline").inner_text(),
                        timeout_s=12.0, msg="no refocus")
                    return
                except AssertionError:
                    if attempt == 2:
                        raise AssertionError(
                            "clicking node did not refocus to " + repr(last))
        probe.check("focus_pick", "map node click refocuses the star view",
                    c_focus_pick)

        # ── insights tab ──
        def c_insights():
            probe.tab("📊 曲库洞察")
            pg.wait_for_timeout(1000)
            must(count(".daily-card") == 1, "daily quote missing")
            must(count(".cloud-word") >= 10, "word cloud too small")
            must(count(".emo-node") >= 1, "emotion map empty")
        probe.check("insights", "insights tab (daily/cloud/emotion)",
                    c_insights)

        def c_word_click():
            pg.locator(".cloud-word").first.click()
            pg.wait_for_timeout(6000)
            must(count(".img-timeline") >= 1, "word click opened no timeline")
        probe.check("word_click", "word cloud click -> imagery timeline",
                    c_word_click)

        def c_emo_click():
            pg.locator(".emo-node").first.click()
            pg.wait_for_timeout(2500)
            sel = pg.get_by_role("tab", name="🎧 播放解读") \
                .get_attribute("aria-selected")
            must(sel == "true", "emotion click did not jump to play tab")
        probe.check("emo_click", "emotion map click jumps to play tab",
                    c_emo_click)


        def c_cloud_switch():
            # the emo_click check intentionally navigated to the play tab;
            # come back before touching insights controls
            probe.tab("📊 曲库洞察")
            pg.locator("#ll-cloud-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option", name="🌍 全部歌手").click()
            probe.wait_until(lambda: count(".cloud-word") >= 10,
                             msg="word cloud empty after artist switch")
        probe.check("cloud_switch", "word cloud artist switch re-renders",
                    c_cloud_switch)

        def c_story_guard():
            pg.get_by_role("button", name="✨ 生成故事线").click()
            probe.wait_until(
                lambda: "至少勾选 2 首歌" in pg.locator("body").inner_text(),
                msg="storyline <2 songs guard missing")
        probe.check("story_guard", "storyline with <2 songs -> guard",
                    c_story_guard)

        # ── interactive tab ──
        def c_quiz():
            probe.tab("🎮 互动")
            pg.get_by_role("button", name="🎲 开始 / 下一题").click()
            pg.wait_for_timeout(2500)
            must(count(".quiz-line") == 1, "quiz question missing")
            pg.get_by_role("button", name="提交答案").click()
            pg.wait_for_timeout(1200)
            body = pg.locator("body").inner_text()
            must("请先选择" in body, "no-choice submit guard missing")
        probe.check("quiz", "quiz question + no-choice guard", c_quiz)


        def c_quiz_answer():
            pg.get_by_role("button", name="🎲 开始 / 下一题").click()
            probe.wait_until(lambda: count(".quiz-line") == 1,
                             msg="no quiz question")
            # pick an option and submit
            pg.locator("input[type=radio]:visible").last.check()
            pg.get_by_role("button", name="提交答案").click()
            probe.wait_until(
                lambda: "/ " in pg.locator("body").inner_text()
                and ("答对" in pg.locator("body").inner_text()
                     or "不对" in pg.locator("body").inner_text()),
                msg="quiz verdict/score missing after submit")
        probe.check("quiz_answer", "quiz answer submit -> verdict + score",
                    c_quiz_answer)

        def c_blank_quiz():
            pg.get_by_role("button", name="🕳️ 来一题").click()
            pg.wait_for_timeout(2500)
            body = pg.locator("body").inner_text()
            must(count(".blank-line") == 1 or "至少需要 2 首歌" in body
                 or "歌词唱到歌名" in body,
                 "blank quiz: neither question nor guard rendered")
            if count(".blank-line") == 1:
                must("＿" in pg.locator(".blank-line").inner_text(),
                     "blank quiz line is not blanked")
                pg.locator("input[type=radio]:visible").last.check()
                pg.get_by_role("button", name="🕳️ 选好了").click()
                probe.wait_until(
                    lambda: "答对" in pg.locator("body").inner_text()
                    or "不对" in pg.locator("body").inner_text(),
                    msg="blank quiz verdict missing")
        probe.check("blank_quiz", "title-blank quiz question + submit",
                    c_blank_quiz)

        def c_mv_eggs_present():
            probe.tab("🎧 播放解读")
            pg.locator("#ll-mv").click()  # open the accordion
            pg.wait_for_timeout(600)
            must("MV 彩蛋" in pg.locator("#ll-mv").inner_text(),
                 "MV eggs accordion missing")
            # LLM-priced button is asserted present but NOT clicked
            must(pg.get_by_role("button", name="🎬 生成 MV 彩蛋").count() == 1,
                 "MV eggs generate button missing")
            probe.tab("🎮 互动")  # hand the tab back to the checks after us
        probe.check("mv_eggs_present", "MV eggs accordion present",
                    c_mv_eggs_present)

        def c_identify_guard():
            pg.get_by_role("button", name="🔍 识别").click()
            pg.wait_for_timeout(2500)
            body = pg.locator("body").inner_text()
            must("请先录" in body or "无法识别" in body or "声纹" in body,
                 "identify guard/result missing")
        probe.check("identify_guard", "identify without recording -> guard",
                    c_identify_guard)

        # ── add-song tab ──
        def c_catalog():
            probe.tab("➕ 添加歌曲")
            n_before = count("#ll-catalog input[type=radio]")
            must(n_before >= 50, f"catalog too small: {n_before}")
            pg.locator("#ll-cat-search input, #ll-cat-search textarea") \
                .fill("周杰伦")
            pg.wait_for_timeout(1500)
            n_after = count("#ll-catalog input[type=radio]")
            must(0 < n_after < n_before, "catalog search did not filter")
        probe.check("catalog", "catalog renders + search filters", c_catalog)


        def c_manage_guards():
            pg.get_by_text("🗂️ 管理歌曲列表").click()
            pg.wait_for_timeout(500)
            pg.get_by_role("button", name="🗑️ 删除所选歌曲").click()
            probe.wait_until(
                lambda: "请先选择要删除的歌曲"
                in pg.locator("body").inner_text(),
                msg="delete without selection guard missing")
            pg.get_by_role("button", name="🔄 刷新曲库").click()
            probe.wait_until(
                lambda: "已刷新" in pg.locator("body").inner_text(),
                msg="refresh library status missing")
        probe.check("manage_guards", "manage: delete guard + refresh works",
                    c_manage_guards)

        # ── settings tab ──
        def c_settings():
            probe.tab("⚙️ 设置")
            must(count("input[type=password]") >= 1, "api key field missing")
            must("重建语料库索引" in pg.locator("body").inner_text(),
                 "rebuild section missing")
        probe.check("settings", "settings tab fields present", c_settings)

        # ── global sweeps ──
        def c_console():
            must(not probe.console_errors,
                 "; ".join(probe.console_errors[:5]))
        probe.check("js_console", "no JS console errors / pageerrors",
                    c_console)

        def c_server_log():
            if server_log is None or not server_log.exists():
                return "no server log to scan (attached mode)"
            text = server_log.read_text(encoding="utf-8", errors="replace")
            tracebacks = re.findall(
                r"Traceback \(most recent call last\).*?(?:\w+Error[^\n]*)",
                text, re.DOTALL)
            # Windows asyncio noise when the browser drops a connection
            # mid-reload (e.g. the __theme redirect): not an app bug
            tracebacks = [t for t in tracebacks
                          if "ConnectionResetError" not in t
                          and "_call_connection_lost" not in t]
            must(not tracebacks,
                 f"{len(tracebacks)} traceback(s), first: "
                 + tracebacks[0][-200:].replace("\n", " | ") if tracebacks
                 else "")
        probe.check("server_log", "no server-side tracebacks", c_server_log)

        browser.close()
        return probe.results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=None,
                    help="attach to a running server instead of spawning one")
    ap.add_argument("--json", action="store_true",
                    help="print the report JSON to stdout")
    args = ap.parse_args()

    proc, server_log = None, None
    if args.port:
        base = f"http://127.0.0.1:{args.port}"
    else:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        server_log = OUT_DIR / "server.log"
        env = {**__import__("os").environ, "UI_PORT": str(port)}
        with open(server_log, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                [sys.executable, "-m", "lyric_agent.cli", "serve", "--no-browser"],
                cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT, env=env)
        print(f"spawned server on {base} (pid {proc.pid})")

    try:
        wait_server(base)
        results = run_probe(base, server_log)
    finally:
        if proc is not None:
            proc.kill()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "base": base,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "checks": results,
    }
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 46)
    print(f"UI probe: {report['passed']} passed, {report['failed']} failed"
          f"  ->  {OUT_DIR / 'report.json'}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report["failed"]


if __name__ == "__main__":
    raise SystemExit(main())
