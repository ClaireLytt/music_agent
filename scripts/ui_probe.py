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
    "ERR_CERT_COMMON_NAME_INVALID",  # external resource via local proxy —
                                     # TLS noise, never our code
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
        # 预置"新手指引已看过"，避免自动弹出的指引遮挡其余检查
        page.add_init_script(
            "try{localStorage.setItem('ll_onboard','1')}catch(e){}")
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
                # 多卡并存后弹卡不再因外部点击关闭——用 ✕ 收掉
                pg.locator(".ll-dict-pop .dict-close").first.click()
                probe.wait_until(lambda: count(".ll-dict-pop") == 0,
                                 msg="dict popover did not close via ✕")
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
            # 歌词片段也能搜到歌（合并后的全库歌词搜索）
            box.fill("vintage tee")
            probe.wait_until(
                lambda: 0 < count("#ll-songs input[type=radio]") < n_all,
                msg="lyric-fragment search did not match a song")
            must(any("cardigan" in (v or "") for v in pg.evaluate(
                "() => [...document.querySelectorAll("
                "'#ll-songs input[type=radio]')].map(i => i.value)")),
                 "lyric search did not surface cardigan")
            box.fill("")
            probe.wait_until(
                lambda: count("#ll-songs input[type=radio]") == n_all,
                msg="clearing the filter did not restore the full list")
        probe.check("song_filter", "song list filter narrows + restores",
                    c_song_filter)



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



        def c_intro_panel():
            probe.tab("📖")
            html = pg.locator("#ll-intro").inner_html()
            must("song-intro" in html or "尚未生成" in html,
                 "intro panel neither text nor empty-state")
        probe.check("intro_panel", "song intro panel content or hint",
                    c_intro_panel)

        def c_onboarding():
            # ❓ reopens the guided tour; 跳过 closes it (reopenable = spec)
            probe.tab("🎧 播放解读")
            probe.wait_until(lambda: count("#ll-onboard-btn") == 1,
                             msg="onboarding ❓ button missing")
            pg.locator("#ll-onboard-btn").click()
            probe.wait_until(lambda: count(".ll-onboard-box") == 1,
                             msg="tour box did not open")
            pg.locator('[data-ob="next"]').click()
            probe.wait_until(
                lambda: "歌词区" in pg.locator(".ll-onboard-box").inner_text(),
                msg="step 2 text missing")
            pg.locator('[data-ob="skip"]').click()
            probe.wait_until(lambda: count(".ll-onboard-box") == 0,
                             msg="tour box did not close")
            pg.locator("#ll-onboard-btn").click()   # 可反复打开
            probe.wait_until(lambda: count(".ll-onboard-box") == 1,
                             msg="tour not reopenable")
            pg.locator('[data-ob="skip"]').click()
            probe.wait_until(lambda: count(".ll-onboard-box") == 0,
                             msg="tour box did not close again")
        probe.check("onboarding", "guided tour opens/advances/reopens",
                    c_onboarding)

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

        # ── 歌迷考据 tab ──
        def c_fanlore():
            probe.tab("🕵️ 歌迷考据")
            pg.wait_for_timeout(1000)
            must(pg.locator("#ll-lore-song").count() == 1,
                 "fanlore song picker missing")
            # LLM-priced button asserted present but NOT clicked
            must(pg.get_by_role(
                "button",
                name="🕵️ 生成考据故事（调用 1 次 LLM，之后永久缓存）"
            ).count() == 1, "fanlore generate button missing")
            body = pg.locator("body").inner_text()
            must("考据" in body, "fanlore intro text missing")
            # 右侧 AI 助手（提问按钮存在即可，不真的花 LLM）
            must(pg.locator("#ll-lore-chat").count() == 1
                 and "AI 助手" in pg.locator("#ll-lore-chat").inner_text(),
                 "lore chat panel missing")
        probe.check("fanlore", "fanlore tab picker + guarded button",
                    c_fanlore)



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
            probe.tab("🔤 歌曲寻词")
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
            # keystrokes occasionally get lost before the JS loop arms —
            # a wrong key resets the whole word, so blind retyping is safe
            for _ in range(3):
                pg.locator(".ll-type-input").press_sequentially(word,
                                                                delay=40)
                pg.wait_for_timeout(700)
                if "本轮 1 词" in pg.locator("body").inner_text():
                    break
            probe.wait_until(
                lambda: "本轮 1 词" in pg.locator("body").inner_text(),
                msg="completed word did not update the session stats")
        probe.check("word_practice", "typing drill grades a typed word",
                    c_word_practice)


        def c_word_import():
            # CSV 导入 -> 新分组 + 立刻出卡（净零：随后删除导入的词）
            probe.tab("🔤 歌曲寻词")
            import tempfile
            csv_path = Path(tempfile.gettempdir()) / "ll_probe_words.csv"
            csv_path.write_text(
                "word,translation\nzzprobeword,探针词\n",
                encoding="utf-8")
            pg.get_by_text("📥 导入单词表", exact=False).first.click()
            pg.wait_for_timeout(600)
            pg.locator('input[type="file"]').last.set_input_files(
                str(csv_path))
            pg.wait_for_timeout(1200)
            pg.get_by_role("button", name="📥 导入到单词本").click()
            probe.wait_until(
                lambda: "已导入" in pg.locator("body").inner_text(),
                msg="import did not report success")
            probe.wait_until(
                lambda: count(".ll-type-card") >= 1
                and (pg.locator(".ll-type-card").first
                     .get_attribute("data-word")) == "zzprobeword",
                msg="imported word did not become the practice card")
            # cleanup: remove the probe word from the wordbook
            pg.evaluate(
                "() => {const b=document.querySelector('#ll-wb-act textarea,"
                "#ll-wb-act input'); if(b){b.value='del:zzprobeword\\t'"
                "+Date.now(); b.dispatchEvent(new Event('input',"
                "{bubbles:true}));}}")
            pg.wait_for_timeout(1500)
            csv_path.unlink(missing_ok=True)
        probe.check("word_import", "CSV import -> group + practice card",
                    c_word_import)

        def c_word_export():
            probe.tab("🔤 歌曲寻词")
            pg.get_by_role("button",
                           name="📤 导出 qwerty-learner 词典").click()
            probe.wait_until(
                lambda: ("已生成" in pg.locator("body").inner_text()
                         or "没有可导出" in pg.locator("body").inner_text()),
                msg="export produced neither a file notice nor the empty hint")
        probe.check("word_export", "qwerty dictionary export responds",
                    c_word_export)

        def c_annotation_card():
            # clicking an annotated line surfaces the annotation card;
            # an unannotated line offers the consent button (NOT clicked —
            # it would spend an LLM call)
            probe.tab("🎧 播放解读")
            pg.get_by_role("radio", name=PLAIN_SONG).check()
            probe.wait_until(lambda: count(".lyric-line") > 12,
                             msg="cardigan lyrics did not render")
            pg.locator('.lyric-line[data-index="12"]').click()
            probe.tab("🖊")   # 批注卡移进了右栏图标 dock
            probe.wait_until(
                lambda: count(".ann-card .ann-summary") >= 1,
                msg="annotated line showed no annotation card")
        probe.check("annotation_card", "line click surfaces its annotation",
                    c_annotation_card)

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
            probe.tab("⚙️ 设置")
            must(pg.get_by_text("📺 关联 B 站视频").count() >= 1,
                 "manual bvid accordion missing (moved to settings 🎛)")
            probe.tab("🎧 播放解读")
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





        # ── add-song tab ──
        def c_catalog():
            probe.tab("➕ 添加歌曲")
            # 内置曲库折叠在手风琴里，先展开
            pg.get_by_text("📚 从内置曲库挑选", exact=False).first.click()
            pg.wait_for_timeout(600)
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
            probe.tab("⚙️ 设置")   # 刷新按钮移进了设置 🎛
            pg.locator("#ll-refresh-btn").click()
            probe.wait_until(
                lambda: "已刷新" in pg.locator("body").inner_text(),
                msg="refresh library toast missing")
            probe.tab("🎧 播放解读")
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
            probe.tab("⚙️ 设置")   # 刷新按钮移进了设置 🎛
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
            probe.tab("🔑")  # 📊 用量页现在是默认首页
            probe.wait_until(
                lambda: count("input[type=password]") >= 1,
                msg="api key field missing")
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
               "BILI_AUTO_BIND": "0",
               "LL_CORPUS_REBUILD": "0",
               "LL_WORD_EXAMPLES": "0"}
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
