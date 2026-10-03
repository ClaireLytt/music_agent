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
- Destructive actions (rebuild index) are NOT clicked; the delete flow
  is exercised only against a throwaway song the probe adds itself.
- Known-benign console noise (CDN offline for the optional waveform, favicon)
  is whitelisted; everything else that hits the JS console as an error, any
  pageerror, and any server-side traceback fails the corresponding check.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
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
    "player.bilibili.com",       # bound-MV iframe noise is not an app bug
    "bilibili.com",              # ditto (embed player's own asset chatter)
    "bili-user-fingerprint",     # embed player's internal reporter errors
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
        # exact: role-name matching is substring-based, and sub-tab labels
        # can be prefixes of one another ("🥚 彩蛋" vs "🥚 彩蛋猜猜乐")
        self.page.get_by_role("tab", name=name, exact=True).click()
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
            probe.tab("🖼️")
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
            # scrub probe notes a previous aborted run left on disk —
            # a stale same-text note breaks the delete-to-zero assertion
            nf = ROOT / "data" / "songs" / AUDIO_SONG / "notes.json"
            if nf.exists():
                stale = json.loads(nf.read_text(encoding="utf-8"))
                keep = [n for n in stale
                        if "ui-probe" not in n.get("text", "")]
                if len(keep) != len(stale):
                    nf.write_text(json.dumps(keep, ensure_ascii=False),
                                  encoding="utf-8")
            probe.tab("📝")
            box = pg.get_by_placeholder("在当前播放位置记一句感想…")
            box.fill("ui-probe 自检笔记")
            pg.get_by_role("button", name="添加").click()
            probe.wait_until(
                lambda: count(".note-item >> text=ui-probe 自检笔记") >= 1,
                msg="note not added")
            # delete exactly the probe note
            item = pg.locator(".note-item",
                              has_text="ui-probe 自检笔记").first
            item.locator(".note-del").click()
            probe.wait_until(
                lambda: count(".note-item >> text=ui-probe 自检笔记") == 0,
                msg="probe note not deleted")
        probe.check("notes", "listening note add + delete roundtrip", c_notes)

        def c_favorites():
            # NON-DESTRUCTIVE: favorites.json is the real user file, so this
            # records the starting count, adds one, then deletes the one it
            # added (the LAST item — favorites append), returning to the
            # starting state. It never touches pre-existing favorites.
            probe.tab("🎧 播放解读")
            pg.locator(".lyric-line").nth(2).click()
            pg.wait_for_timeout(1500)
            probe.tab("⭐")
            n0 = count(".fav-item")
            pg.get_by_role("button", name="⭐ 收藏当前选中的歌词").click()
            # either it was added (n0+1) or the line was already a favorite
            probe.wait_until(
                lambda: count(".fav-item") in (n0, n0 + 1),
                msg="favorite add produced no stable state")
            if count(".fav-item") == n0 + 1:
                pg.locator(".fav-item .fav-del").last.click()  # the one we added
                probe.wait_until(lambda: count(".fav-item") == n0,
                                 msg="favorite not deleted back to start")
        probe.check("favorites", "favorite a lyric line: add + delete",
                    c_favorites)

        def c_dict_popover():
            # mini translator: select an English word in the lyrics, dispatch
            # dblclick, expect the offline-dictionary popover; then ⭐ it into
            # the wordbook and delete it again (net-zero on wordbook.json)
            probe.tab("🎧 播放解读")
            word = pg.evaluate("""() => {
              const lines = document.querySelectorAll('#lyrics-scroll .lyric-line');
              for (const line of lines) {
                const el = line.querySelector('.lyric-text');
                if (!el || !el.firstChild) continue;
                const m = el.textContent.match(/[A-Za-z]{5,}/);
                if (!m) continue;
                const node = el.firstChild;
                const i = node.textContent.indexOf(m[0]);
                if (i < 0) continue;
                const range = document.createRange();
                range.setStart(node, i); range.setEnd(node, i + m[0].length);
                const sel = window.getSelection();
                sel.removeAllRanges(); sel.addRange(range);
                line.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                return m[0];
              }
              return null;
            }""")
            must(word, "no english word found in current lyrics")
            probe.wait_until(
                lambda: count(".ll-dict-pop") == 1
                and ("收藏单词" in pg.locator(".ll-dict-pop").inner_text()
                     or "本地词典" in pg.locator(".ll-dict-pop").inner_text()),
                msg="translator popover did not render a result")
            if count("[data-dict-fav]"):
                pg.locator("[data-dict-fav]").click()
                probe.tab("⭐")
                probe.wait_until(lambda: count(".wb-item") >= 1,
                                 msg="word not added to wordbook")
                item = pg.locator(".wb-item", has_text=word).first
                item.locator(".wb-del").click()
                probe.wait_until(
                    lambda: count(f".wb-item >> text={word}") == 0,
                    msg="word not removed from wordbook")
        probe.check("dict_popover",
                    "dblclick word -> dict popover -> wordbook roundtrip",
                    c_dict_popover)

        def c_cite_jump():
            # evidence-card citation jump: a [data-cite-label] click must
            # switch to that song and flash the cited line (zero-LLM: the
            # card is injected, exercising the delegate + channel + watcher)
            probe.tab("🎧 播放解读")
            target = pg.evaluate("""() => {
              const radios = document.querySelectorAll('#ll-songs input[type=radio]');
              const cur = document.querySelector('#ll-songs input[type=radio]:checked');
              for (const r of radios) {
                if (r !== cur) {
                  const el = document.createElement('div');
                  el.id = 'probe-cite';
                  el.dataset.citeLabel = r.value;
                  el.dataset.citeLine = '2';
                  el.textContent = 'probe cite';
                  document.body.appendChild(el);
                  return r.value;
                }
              }
              return null;
            }""")
            must(target, "library too small for a cite jump")
            pg.locator("#probe-cite").click()
            probe.wait_until(
                lambda: pg.evaluate(
                    """() => { const c = document.querySelector(
                        '#ll-songs input[type=radio]:checked');
                      return c ? c.value : ''; }""") == target,
                msg="cite jump did not switch the song")
            probe.wait_until(
                lambda: count(".lyric-line.cite-flash") >= 1,
                msg="cited line did not flash after the jump")
            pg.evaluate("() => document.getElementById('probe-cite').remove()")
        probe.check("cite_jump",
                    "evidence citation click -> song switch + line flash",
                    c_cite_jump)

        def c_archaeology_guard():
            # 考古报告 guard path (free): the cross-artist pseudo-entry is
            # not a single artist, so generation must refuse politely
            probe.tab("🕵️ 歌词宇宙")
            pg.get_by_role("tab", name="🏺 考古报告").click()
            pg.wait_for_timeout(400)
            prev = pg.evaluate(
                """() => { const b = document.querySelector('#ll-uni-artist input');
                   return b ? b.value : ''; }""")
            pg.locator("#ll-uni-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option",
                           name="🌐 跨歌手引用（全部歌手）").click()
            pg.get_by_role("button",
                           name="🏺 生成考古报告（已有缓存则秒开）").click()
            probe.wait_until(
                lambda: "请先在上方选择一位具体的歌手"
                in pg.locator("body").inner_text(),
                msg="archaeology artist guard missing")
            if prev:
                pg.locator("#ll-uni-artist input").click()
                pg.wait_for_timeout(400)
                pg.get_by_role("option", name=prev, exact=True).click()
        probe.check("archaeology_guard",
                    "archaeology report refuses the cross-artist entry",
                    c_archaeology_guard)

        def c_tour_toggle():
            # 🎧 导览 toggle ships with the player tools — audio songs only
            # (reading-mode songs have no player toolbar at all)
            probe.tab("🎧 播放解读")
            pg.get_by_role("radio", name=AUDIO_SONG, exact=True).check()
            probe.wait_until(lambda: count("#ll-tour-toggle") == 1,
                             msg="tour toggle missing on an audio song")
            pg.locator("#ll-tour-toggle").check()
            pg.wait_for_timeout(300)
            must(pg.locator("#ll-tour-toggle").is_checked(),
                 "tour toggle did not check")
            pg.locator("#ll-tour-toggle").uncheck()
        probe.check("tour_toggle", "🎧 tour toggle present + togglable",
                    c_tour_toggle)

        def c_song_filter():
            # the filter narrows the radio by title/artist and restores on
            # clear — this path previously broke (dead .input event)
            probe.tab("🎧 播放解读")
            box = pg.locator("#ll-song-filter input, #ll-song-filter textarea")
            n_all = count("#ll-songs input[type=radio]")
            must(n_all >= 2, f"song list too small to filter: {n_all}")
            # derive a query from an actual choice value (library-
            # independent; label TEXT would include the ⋯ menu glyph)
            first_label = (pg.locator("#ll-songs input[type=radio]").first
                           .get_attribute("value") or "").strip()
            needle = first_label[:3] or first_label
            box.fill(needle)
            probe.wait_until(
                lambda: 0 < count("#ll-songs input[type=radio]") <= n_all,
                msg="song filter did not narrow the list")
            box.fill("")
            probe.wait_until(
                lambda: count("#ll-songs input[type=radio]") == n_all,
                msg="clearing the filter did not restore the full list")
        probe.check("song_filter", "song list filter narrows + restores",
                    c_song_filter)


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
            probe.wait_until(   # first semantic query may load the model;
                # the multilingual L12 model embeds the library ~5x slower
                # than the old L6 (measured 55s cold on this machine)
                lambda: count(".search-mode-tag") >= 1, timeout_s=150,
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
            probe.tab("🥚")
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
            probe.tab("🗺️")
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
            probe.tab("📖")
            html = pg.locator("#ll-intro").inner_html()
            must("song-intro" in html or "尚未生成" in html,
                 "intro panel neither text nor empty-state")
        probe.check("intro_panel", "song intro panel content or hint",
                    c_intro_panel)

        def c_radio_gen_guard():
            # exile has no intro.txt -> the TTS button must guard, not spend
            pg.get_by_role("radio", name="exile").check()
            pg.wait_for_timeout(2500)
            probe.tab("📻")
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

        def c_mcp_channel():
            # `lyric-agent mcp` play_song writes a command file; the UI's
            # 1s timer must pick it up and switch the song. (Playback itself
            # is not asserted — headless Chromium blocks autoplay.)
            from lyric_agent.mcp_channel import write_mcp_command
            pg.get_by_role("radio", name=PLAIN_SONG).check()
            probe.wait_until(
                lambda: pg.locator(".song-title-display").inner_text().strip()
                == PLAIN_SONG, msg="could not open the starting song")
            write_mcp_command("play", title=AUDIO_SONG,
                              path=ROOT / "data" / "cache" / "mcp_command.json")
            probe.wait_until(
                lambda: pg.locator(".song-title-display").inner_text().strip()
                == AUDIO_SONG,
                timeout_s=15, msg="MCP play command did not switch the song")
            must(pg.evaluate(
                "(document.querySelector('#ll-mcp-play textarea, "
                "#ll-mcp-play input') || {value: ''}).value") != "",
                "ll-mcp-play relay box stayed empty")
        probe.check("mcp_channel", "MCP command file switches the song",
                    c_mcp_channel)

        # ── evolution tab ──
        def c_evolution():
            probe.tab("🗺️ 艺术家图谱")
            # artist profile page: overview + motif sections open by default
            probe.wait_until(lambda: count(".ov-album") >= 1,
                             msg="artist overview rendered no album cards")
            must(pg.locator("#ll-overview-artist").count() == 1,
                 "artist picker missing")
            # motif section renders content or its explicit empty state
            # (the alphabetically-first artist may have too few songs)
            probe.wait_until(
                lambda: count(".apm-motif") >= 1 or count(".chat-empty") >= 1,
                msg="motif section rendered neither motifs nor empty state")
            # a song chip jumps to the play tab with that song opened
            chip = pg.locator(".ov-song").first
            title = chip.inner_text().strip()
            chip.click()
            probe.wait_until(
                lambda: pg.get_by_role("tab", name="🎧 播放解读", exact=True)
                .get_attribute("aria-selected") == "true"
                and pg.locator(".song-title-display").inner_text().strip()
                == title,
                msg="overview chip did not open the song on the play tab")
        probe.check("evolution", "artist overview renders + chip jumps",
                    c_evolution)

        def c_profile_cite():
            # motif hit on a library song switches the selected song
            # (the cite-jump channel changes the radio without leaving
            # the current tab — same contract as archaeology citations)
            probe.tab("🗺️ 艺术家图谱")
            pg.locator("#ll-overview-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option", name="Taylor Swift", exact=True).click()
            probe.wait_until(
                lambda: count(".apm-hit[data-cite-label]") >= 1,
                msg="no clickable motif hits for Taylor Swift")
            hit = pg.locator(".apm-hit[data-cite-label]").first
            label = hit.get_attribute("data-cite-label")
            hit.click()
            probe.wait_until(
                lambda: pg.locator(
                    "#ll-songs input[type=radio]:checked"
                ).get_attribute("value") == label,
                msg="motif hit did not switch the selected song")
        probe.check("profile_cite", "motif hit switches the selected song",
                    c_profile_cite)

        def c_profile_echo():
            # lazy echo-heat accordion builds on expand (cold graph ok)
            probe.tab("🗺️ 艺术家图谱")
            pg.get_by_text("🥚 专辑互文热度").click()
            probe.wait_until(lambda: count(".aph-row") >= 1, timeout_s=40,
                             msg="echo heat rendered no album rows")
        probe.check("profile_echo", "echo heat builds on accordion expand",
                    c_profile_echo)

        def c_profile_timeline():
            probe.tab("🗺️ 艺术家图谱")
            pg.get_by_text("📅 专辑时间轴").click()
            probe.wait_until(
                lambda: pg.locator(".ovt-album").first.is_visible()
                and pg.locator(".ovt-year").first.inner_text().strip() != "",
                msg="album timeline missing or yearless after expand")
        probe.check("profile_timeline", "album timeline renders on expand",
                    c_profile_timeline)

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
            probe.tab("🔍 意象追踪")
            pg.get_by_placeholder("输入意象，如：雨 / scarf / 童年").fill("time")
            pg.get_by_role("button", name="追踪").click()
            pg.wait_for_timeout(6000)
            must(count(".img-timeline") == 1, "imagery timeline missing")
        probe.check("imagery", "imagery trace search", c_imagery)


        def c_map_cross():
            probe.tab("🗺️ 呼应地图")
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
            for attempt in (1, 2, 3):
                artist_val = pg.locator("#ll-map-artist input").input_value()
                if attempt > 1 and " · " in (
                        pg.locator("g.egg-clickable").first
                        .get_attribute("data-focus-pick") or ""):
                    # cross-artist DOM although the input displays a single
                    # artist: the option click likely never fired .input —
                    # re-select the artist to resync, keep the evidence
                    pg.locator("#ll-map-artist input").click()
                    pg.wait_for_timeout(400)
                    pg.get_by_role("option", name=artist_val,
                                   exact=True).click()
                    probe.wait_until(
                        lambda: " · " not in (
                            pg.locator("g.egg-clickable").first
                            .get_attribute("data-focus-pick") or " · "),
                        msg="re-select did not restore the artist map")
                target = pg.locator("g.egg-clickable").first \
                    .get_attribute("data-focus-pick")
                last = target or ""
                pg.locator("g.egg-clickable").first.click()
                try:
                    probe.wait_until(
                        lambda: ("《" + target + "》的彩蛋网络")
                        in pg.locator(".egg-headline").inner_text(),
                        timeout_s=12.0, msg="no refocus")
                    if attempt > 1:
                        print(f"  [focus_pick] self-healed on attempt "
                              f"{attempt} (artist input was "
                              f"{artist_val!r}, DOM was stale)")
                    return
                except AssertionError:
                    if attempt == 3:
                        raise AssertionError(
                            "no refocus to " + repr(last)
                            + f" | artist input={artist_val!r} | headline="
                            + pg.locator(".egg-headline").inner_text()[:80])
        probe.check("focus_pick", "map node click refocuses the star view",
                    c_focus_pick)

        # ── insights tab ──
        def c_insights():
            probe.tab("📊 曲库洞察")
            pg.wait_for_timeout(1000)
            # sub-tab panels render lazily — visit each before counting
            must(count(".daily-card") == 1, "daily quote missing")
            probe.tab("☁️ 意象词云")
            probe.wait_until(lambda: count(".cloud-word") >= 10,
                             msg="word cloud too small")
            probe.tab("🎭 情绪地图")
            probe.wait_until(lambda: count(".emo-node") >= 1,
                             msg="emotion map empty")
        probe.check("insights", "insights tab (daily/cloud/emotion)",
                    c_insights)

        def c_word_click():
            probe.tab("☁️ 意象词云")
            pg.locator(".cloud-word").first.click()
            pg.wait_for_timeout(6000)
            must(count(".img-timeline") >= 1, "word click opened no timeline")
        probe.check("word_click", "word cloud click -> imagery timeline",
                    c_word_click)

        def c_emo_click():
            probe.tab("🎭 情绪地图")
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
            probe.tab("☁️ 意象词云")
            pg.locator("#ll-cloud-artist input").click()
            pg.wait_for_timeout(400)
            pg.get_by_role("option", name="🌍 全部歌手").click()
            probe.wait_until(lambda: count(".cloud-word") >= 10,
                             msg="word cloud empty after artist switch")
        probe.check("cloud_switch", "word cloud artist switch re-renders",
                    c_cloud_switch)

        def c_story_guard():
            probe.tab("📖 歌单故事线")
            pg.get_by_role("button", name="✨ 生成故事线").click()
            probe.wait_until(
                lambda: "至少勾选 2 首歌" in pg.locator("body").inner_text(),
                msg="storyline <2 songs guard missing")
        probe.check("story_guard", "storyline with <2 songs -> guard",
                    c_story_guard)

        # ── interactive tab ──
        def c_quiz():
            probe.tab("🎮 互动")
            probe.tab("🎯 歌词竞猜")
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

        def c_title_puzzle():
            probe.tab("🧩 歌名拼图")
            pg.get_by_role("button", name="🧩 来一题").click()
            pg.wait_for_timeout(2500)
            body = pg.locator("body").inner_text()
            must(count(".blank-line") == 1 or "可拼的歌名不足" in body,
                 "title puzzle: neither question nor guard rendered")
            if count(".blank-line") == 1:
                must("____" in pg.locator(".blank-line").inner_text(),
                     "puzzle title is not masked")
                pg.locator("input[type=radio]:visible").last.check()
                pg.get_by_role("button", name="🧩 拼好了").click()
                probe.wait_until(
                    lambda: "拼对" in pg.locator("body").inner_text()
                    or "不对" in pg.locator("body").inner_text(),
                    msg="title puzzle verdict missing")
        probe.check("title_puzzle", "title puzzle question + submit",
                    c_title_puzzle)

        def c_word_practice():
            # typing drill renders a card (or the empty-book hint — the
            # wordbook is gitignored and may be empty on a fresh machine)
            probe.tab("⌨️ 单词练习")
            pg.get_by_role("button", name="⌨️ 开始 / 换一词").click()
            probe.wait_until(
                lambda: count(".ll-type-card") >= 1
                or "单词本是空的" in pg.locator("body").inner_text(),
                msg="practice rendered neither a card nor the empty hint")
            if count(".ll-type-card") == 0:
                return  # empty book: guard path verified
            card = pg.locator(".ll-type-card").first
            word = card.get_attribute("data-word")
            # press_sequentially focuses the element itself — immune to the
            # click→focus race that made this check flaky
            pg.locator(".ll-type-input").press_sequentially(word, delay=40)
            probe.wait_until(
                lambda: "本轮 1 词" in pg.locator("body").inner_text(),
                msg="completed word did not update the session stats")
        probe.check("word_practice", "typing drill grades a typed word",
                    c_word_practice)

        def c_word_export():
            probe.tab("⌨️ 单词练习")
            pg.get_by_role("button",
                           name="📤 导出 qwerty-learner 词典").click()
            probe.wait_until(
                lambda: ("已生成" in pg.locator("body").inner_text()
                         or "没有可导出" in pg.locator("body").inner_text()),
                msg="export produced neither a file notice nor the empty hint")
        probe.check("word_export", "qwerty dictionary export responds",
                    c_word_export)

        def c_video_bind_ui():
            # auto-bind is disabled for probe runs (BILI_AUTO_BIND=0); pick
            # a still-unbound song from disk and assert the bind entry
            # points render without any iframe. If the whole library is
            # bound, fall back to asserting the manual accordion exists.
            probe.tab("🎧 播放解读")
            import json as _json
            target = None
            for d in sorted((ROOT / "data" / "songs").iterdir()):
                mp = d / "metadata.json"
                if not mp.exists():
                    continue
                try:
                    meta = _json.loads(mp.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if not meta.get("bvid"):
                    target = meta.get("title", d.name)
                    break
            must(pg.get_by_text("📺 关联 B 站视频").count() >= 1,
                 "manual bvid accordion missing")
            if target is None:
                return  # every song bound — nothing unbound to assert on
            pg.get_by_role("radio", name=target, exact=True).first.check()
            probe.wait_until(
                lambda: count("[data-bvid-search]") >= 1,
                msg=f"B站 MV search button missing on unbound song {target}")
            must(count(".bv-frame") == 0,
                 "iframe rendered without a bound bvid")
        probe.check("video_bind_ui", "bilibili bind entry points render",
                    c_video_bind_ui)

        def c_universe_present():
            # universe/letter are LLM-priced AND the pair dropdown is
            # pre-filled on load (clicking 写信 would actually spend), so
            # assert the controls are present WITHOUT clicking them
            probe.tab("🕵️ 歌词宇宙")
            probe.tab("🕵️ 开始破案")
            must(pg.get_by_role(
                "button",
                name="🕵️ 开始破案（AI 推理，约 10-30 秒）").count() == 1,
                "detective button missing")
            probe.tab("💌 隔空回信")
            must(pg.locator("#ll-letter-pair").count() == 1,
                 "letter pair picker missing")
            must(pg.get_by_role("button", name="💌 写信",
                                exact=True).count() == 1,
                 "letter button missing")
        probe.check("universe_present",
                    "universe/letter controls present (LLM, not clicked)",
                    c_universe_present)

        def c_mv_eggs_present():
            probe.tab("🥚 彩蛋地图")
            probe.tab("🎬 MV 彩蛋")
            pg.wait_for_timeout(600)
            must(pg.locator("#ll-mv-song").count() == 1,
                 "MV song picker missing")
            must("MV 彩蛋" in pg.locator("#ll-mv").inner_text()
                 or "生成 MV 彩蛋" in pg.locator("body").inner_text(),
                 "MV eggs panel missing")
            # LLM-priced button is asserted present but NOT clicked
            must(pg.get_by_role("button", name="🎬 生成 MV 彩蛋").count() == 1,
                 "MV eggs generate button missing")
            probe.tab("🎮 互动")  # hand the tab back to the checks after us
        probe.check("mv_eggs_present", "MV eggs accordion present",
                    c_mv_eggs_present)


        # ── add-song tab ──
        def c_catalog():
            probe.tab("➕ 添加歌曲")
            n_before = count("#ll-catalog input[type=checkbox]")
            must(n_before >= 50, f"catalog too small: {n_before}")
            pg.locator("#ll-cat-search input, #ll-cat-search textarea") \
                .fill("周杰伦")
            pg.wait_for_timeout(1500)
            n_after = count("#ll-catalog input[type=checkbox]")
            must(0 < n_after < n_before, "catalog search did not filter")
            # unified search lists library songs too, badged "✓ 已在列表";
            # select-all checks exactly the ADDABLE rows (those without the
            # badge). Count addable from the labels so the assertion holds
            # whether or not the library already contains the matches.
            addable = pg.evaluate(
                """() => [...document.querySelectorAll('#ll-catalog label')]
                    .filter(l => !l.textContent.includes('已在列表')).length""")
            pg.get_by_role("button", name="☑️ 全选").click()
            pg.wait_for_timeout(800)
            must(count("#ll-catalog input[type=checkbox]:checked") == addable,
                 f"select-all checked != addable rows ({addable})")
            pg.get_by_role("button", name="⬜ 取消全选").click()
            pg.wait_for_timeout(800)
            must(count("#ll-catalog input[type=checkbox]:checked") == 0,
                 "deselect-all left songs checked")
        probe.check("catalog", "catalog renders + search filters", c_catalog)


        def c_manage_guards():
            # the selected row carries a ⋯ menu; refresh sits under the list
            probe.tab("🎧 播放解读")
            probe.wait_until(lambda: count(".ll-dots") == 1,
                             msg="⋯ menu missing on the selected song")
            # opening it must land the menu in-viewport next to the ⋯
            # button (regression: a transformed ancestor hijacked the
            # fixed positioning and the list overflow clipped the menu)
            pg.locator(".ll-dots").click()
            geo = pg.evaluate(
                """() => {
                    const m = document.querySelector('.ll-dots-menu');
                    const b = document.querySelector('.ll-dots');
                    if (!m || !b) return null;
                    const mr = m.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return {inView: mr.top >= 0 && mr.left >= 0
                                && mr.bottom <= window.innerHeight
                                && mr.right <= window.innerWidth,
                            gap: Math.abs(mr.top - br.bottom)};
                }""")
            must(geo is not None, "⋯ menu did not open on click")
            must(geo["inView"] and geo["gap"] < 40,
                 f"⋯ menu misplaced/off-screen: {geo}")
            pg.locator("#ll-refresh-btn").click()
            probe.wait_until(
                lambda: "已刷新" in pg.locator("body").inner_text(),
                msg="refresh library toast missing")
        probe.check("manage_guards", "⋯ on selected row + refresh works",
                    c_manage_guards)

        def c_add_delete_roundtrip():
            # REAL add -> lands at the TOP of the song list -> delete via
            # manage (confirm-guard first, then confirmed) -> gone again and
            # the confirm checkbox resets. Net-zero: only ever touches the
            # throwaway song it creates itself.
            shutil.rmtree(ROOT / "data" / "songs" / "zzz_probe_roundtrip",
                          ignore_errors=True)
            probe.tab("➕ 添加歌曲")
            # the manual-add form lives in a collapsed accordion
            pg.get_by_text("✍️ 手动添加曲库以外的歌曲").click()
            pg.wait_for_timeout(500)
            pg.locator("#ll-add-title input, #ll-add-title textarea") \
                .fill("Zzz Probe Roundtrip")
            pg.locator("#ll-add-artist input").fill("UI Probe")
            pg.locator("#ll-add-lrc textarea") \
                .fill("[00:01.00] probe alpha\n[00:05.00] probe beta")
            pg.get_by_role("button", name="💾 保存歌曲").click()
            probe.wait_until(
                lambda: "已添加《Zzz Probe Roundtrip》"
                in pg.locator("body").inner_text(),
                msg="add-song success status missing")
            first = pg.locator("#ll-songs label").first.inner_text()
            must("Zzz Probe Roundtrip" in first,
                 f"new song not at top of list: {first[:60]!r}")
            # delete via the ⋯ menu on the selected (new) row: cancel the
            # native confirm first (song must survive), then accept it
            probe.tab("🎧 播放解读")
            probe.wait_until(lambda: count(".ll-dots") == 1,
                             msg="⋯ menu missing on the new song")

            def _menu_delete():
                pg.locator(".ll-dots").click()
                pg.get_by_role("button", name="🗑️ 删除这首歌").click()

            pg.once("dialog", lambda d: d.dismiss())
            _menu_delete()
            pg.wait_for_timeout(1200)
            must("Zzz Probe Roundtrip" in pg.locator("#ll-songs").inner_text(),
                 "cancelled confirm still deleted the song")
            pg.once("dialog", lambda d: d.accept())
            _menu_delete()
            probe.wait_until(
                lambda: "Zzz Probe Roundtrip"
                not in pg.locator("#ll-songs").inner_text(),
                msg="deleted song still in the list")
            must(not (ROOT / "data" / "songs"
                      / "zzz_probe_roundtrip").exists(),
                 "song directory still on disk after delete")
        probe.check("add_delete_roundtrip",
                    "add a song -> top of list -> ⋯ delete -> gone",
                    c_add_delete_roundtrip)

        def c_refresh_keeps_filter():
            # refreshing the library must not blow away the active filter
            probe.tab("🎧 播放解读")
            n_all = count("#ll-songs input[type=radio]")
            must(n_all >= 2, f"library too small: {n_all}")
            needle = (pg.locator("#ll-songs input[type=radio]").first
                      .get_attribute("value") or "").strip()
            box = pg.locator("#ll-song-filter input, #ll-song-filter textarea")
            box.fill(needle)
            probe.wait_until(
                lambda: 0 < count("#ll-songs input[type=radio]") < n_all,
                msg="filter did not narrow the list")
            n1 = count("#ll-songs input[type=radio]")
            pg.locator("#ll-refresh-btn").click()
            probe.wait_until(
                lambda: "已刷新" in pg.locator("body").inner_text(),
                msg="refresh status missing")
            pg.wait_for_timeout(800)
            must(count("#ll-songs input[type=radio]") == n1,
                 "refresh reverted the active filter")
            probe.tab("🎧 播放解读")
            box.fill("")
            probe.wait_until(
                lambda: count("#ll-songs input[type=radio]") == n_all,
                msg="clearing the filter did not restore the full list")
        probe.check("refresh_keeps_filter",
                    "refresh honors the active song filter",
                    c_refresh_keeps_filter)

        # ── settings tab ──
        def c_settings():
            probe.tab("⚙️ 设置")
            must(count("input[type=password]") >= 1, "api key field missing")
            probe.tab("🧠")  # sections live behind bottom icons now
            probe.wait_until(
                lambda: "重建语料库索引" in pg.locator("body").inner_text(),
                msg="rebuild section missing")
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
        # BILI_AUTO_BIND=0: no grey-API搜索 traffic from probe runs
        env = {**__import__("os").environ, "UI_PORT": str(port),
               "BILI_AUTO_BIND": "0"}
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
