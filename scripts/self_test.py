#!/usr/bin/env python3
"""Self-test against a running lyric-agent server (http://127.0.0.1:7860).

Uses the raw Gradio HTTP API (POST /gradio_api/call/<name> + SSE result)
so Radio client-side validation doesn't get in the way.

Usage: python scripts/self_test.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:7860"
ROOT = Path(__file__).resolve().parent.parent
SONGS_DIR = ROOT / "data" / "songs"
EVOLUTION_JSON = ROOT / "data" / "evolution" / "evolution.json"
# unique per run: gr.State inputs use server-side session state keyed by
# session_hash, so reusing a hash would leak state between runs
SESSION = f"selftest-{uuid.uuid4().hex[:8]}"

PASS, FAIL = [], []


def unlink_with_retry(path: Path, attempts: int = 10, delay: float = 0.5) -> None:
    """Windows: the server may still hold the file handle right after serving it."""
    for n in range(attempts):
        try:
            path.unlink()
            return
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(delay)


def rmtree_with_retry(path: Path, attempts: int = 10, delay: float = 0.5) -> None:
    for n in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(delay)


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def call(api_name: str, data: list, session: str | None = None) -> list:
    """Invoke a named endpoint via the raw HTTP API, return output data list."""
    r = httpx.post(f"{BASE}/gradio_api/call/{api_name}",
                   json={"data": data, "session_hash": session or SESSION},
                   timeout=30)
    r.raise_for_status()
    event_id = r.json()["event_id"]
    out = None
    with httpx.stream("GET", f"{BASE}/gradio_api/call/{api_name}/{event_id}",
                      timeout=120) as resp:
        event = ""
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                if event == "complete":
                    out = json.loads(payload)
                elif event == "error":
                    raise RuntimeError(f"endpoint error: {payload}")
    if out is None:
        raise RuntimeError("no complete event received")
    return out


def get_radio_choices() -> list[str]:
    cfg = httpx.get(f"{BASE}/config", timeout=15).json()
    for comp in cfg["components"]:
        if comp.get("type") == "radio":
            return [c[0] if isinstance(c, list) else c
                    for c in comp["props"].get("choices", [])]
    raise RuntimeError("song radio not found in config")


def main() -> None:
    songs = get_radio_choices()
    print(f"Discovered {len(songs)} songs:")
    for s in songs:
        print(f"  - {s}")
    cardigan = next(s for s in songs if "cardigan" in s)

    # ── 1. song select: all songs ──
    for label in songs:
        try:
            out = call("on_song_select", [label])
            lyrics, _state, topic, _chat, evo = out
            ok = ("lyrics-scroll" in lyrics and bool(str(evo).strip())
                  and "尚未选择" in str(topic))
            check(f"song_select: {label}", ok)
        except Exception as e:
            check(f"song_select: {label}", False, repr(e))

    # ── 2. simplified UI: removed panels stay removed ──
    try:
        cfg = httpx.get(f"{BASE}/config", timeout=15).json()
        blob = json.dumps(cfg, ensure_ascii=False)
        ok = ("下一首推荐" not in blob and "主题雷达" not in blob
              and "情绪曲线" not in blob)
        check("no rec/radar/arc panels in config", ok)
    except Exception as e:
        check("no rec/radar/arc panels in config", False, repr(e))

    # ── 2b. song list labels carry no era emoji ──
    emojis = ("🦋", "💛", "💜", "🧣", "🌊", "🐍", "🍂", "🍃", "🌙", "🪶", "🎵")
    check("song labels have no emoji",
          not any(e in label for label in songs for e in emojis),
          f"labels={songs}")

    # ── 2c. sorting ──
    # each call in its own session: on_sort rewrites the radio's choices in the
    # server-side session state, which affects later calls' input validation
    def sort_labels(sort: str, tag: str) -> list[str]:
        out = call("on_sort", [sort, cardigan], session=f"{SESSION}-{tag}")
        upd = out[0]
        return [c[0] if isinstance(c, list) else c
                for c in upd.get("choices", [])] if isinstance(upd, dict) else []

    try:
        labels = sort_labels("album_asc", "s1")
        # evermore < folklore < midnights < red... (case-insensitive)
        ok = len(labels) == len(songs) and "champagne" in labels[0].lower()
        check("sort by album asc", bool(ok), f"labels={labels}")
    except Exception as e:
        check("sort by album asc", False, repr(e))
    try:
        asc = sort_labels("added_asc", "s2")
        desc = sort_labels("added_desc", "s3")
        ok = len(asc) == len(songs) and desc == list(reversed(asc))
        check("sort by added asc/desc are mirrored", bool(ok),
              f"asc={asc} desc={desc}")
    except Exception as e:
        check("sort by added asc/desc are mirrored", False, repr(e))
    try:
        labels = sort_labels("artist_asc", "s4")
        # "Taylor Swift ft. Bon Iver" (exile) sorts after "Taylor Swift" -> last on asc
        ok = len(labels) == len(songs) and "exile" in labels[-1].lower()
        check("sort by artist asc", bool(ok), f"labels={labels}")
    except Exception as e:
        check("sort by artist asc", False, repr(e))

    # ── 3. search ──
    try:
        out = call("on_search", ["scarf", "kw", songs[0]])
        check("search kw 'scarf' (hits)", "data-seek" in out[0] or "scarf" in out[0].lower())
    except Exception as e:
        check("search kw 'scarf' (hits)", False, repr(e))
    try:
        out = call("on_search", ["zzzznothing", "kw", songs[0]])
        check("search kw no-hit message", bool(str(out[0]).strip()))
    except Exception as e:
        check("search kw no-hit message", False, repr(e))
    try:
        out = call("on_search", ["scarf", "sem", songs[0]])
        check("search semantic (or fallback)", bool(str(out[0]).strip()))
    except Exception as e:
        check("search semantic (or fallback)", False, repr(e))
    try:
        out = call("on_search", ["", "kw", songs[0]])
        check("search empty query", out[0] == "")
    except Exception as e:
        check("search empty query", False, repr(e))

    # ── 4. AI assistant: line pick + chat ──
    try:
        out = call("on_line_pick", ["0", cardigan, None])
        _st, topic, _chat = out
        check("line_pick idx 0 -> topic", "正在讨论" in str(topic))
    except Exception as e:
        check("line_pick idx 0 -> topic", False, repr(e))
    try:
        out = call("on_line_pick", ["not-a-number", cardigan, None])
        check("line_pick invalid idx -> default", "尚未选择" in str(out[1]))
    except Exception as e:
        check("line_pick invalid idx -> default", False, repr(e))
    try:
        # session state persists per session_hash: the line picked above feeds this
        out = call("on_chat_send", [None, "这句歌词用了什么修辞？", cardigan])
        chat, cleared = out[1], out[2]
        check("chat send (reply or key warning)",
              "chat-bubble" in str(chat) and cleared == "")
    except Exception as e:
        check("chat send (reply or key warning)", False, repr(e))
    try:
        out = call("on_chat_send", [None, "  ", cardigan])
        check("chat send empty input (no-op)", True)
    except Exception as e:
        check("chat send empty input (no-op)", False, repr(e))
    try:
        # fresh session: no line picked yet -> hint to pick a line first
        out = call("on_chat_send", [None, "问题", cardigan],
                   session=f"{SESSION}-noline")
        check("chat send without line pick -> hint", "请先点击" in str(out[1]))
    except Exception as e:
        check("chat send without line pick -> hint", False, repr(e))

    # ── 5. add song ──
    try:
        out = call("on_add_song",
                   ["", "Taylor Swift", "", "[00:01.00] hi",
                    None, None, "added_asc"])
        check("add_song empty title -> warning", "⚠" in str(out[0]))
    except Exception as e:
        check("add_song empty title -> warning", False, repr(e))
    try:
        out = call("on_add_song",
                   ["Bad LRC Song", "Taylor Swift", "",
                    "no timestamps here", None, None, "added_asc"])
        check("add_song bad lrc -> warning", "⚠" in str(out[0]))
    except Exception as e:
        check("add_song bad lrc -> warning", False, repr(e))

    test_title = "Selftest Temp Song"
    test_slug = re.sub(r"[^\w]+", "_", test_title.lower()).strip("_")
    test_dir = SONGS_DIR / test_slug
    lrc = "[00:01.00] first test line\n[00:05.50] second test line\n"
    try:
        if test_dir.exists():
            rmtree_with_retry(test_dir)
        out = call("on_add_song",
                   [test_title, "Taylor Swift", "Test Album",
                    lrc, None, None, "added_asc"])
        status, radio_update = out[0], out[1]
        new_choices = []
        if isinstance(radio_update, dict):
            new_choices = [c[0] if isinstance(c, list) else c
                           for c in radio_update.get("choices", [])]
        check("add_song success",
              "✅" in str(status) and test_dir.exists()
              and any(test_title in c for c in new_choices),
              f"status={status!r} choices={len(new_choices)}")

        new_label = next((c for c in new_choices if test_title in c), None)
        if new_label:
            out = call("on_song_select", [new_label])
            check("added song renders", "first test line" in out[0])
        else:
            check("added song renders", False, "label not found")

        out = call("on_add_song",
                   [test_title, "Taylor Swift", "", lrc,
                    None, None, "added_asc"])
        check("add_song duplicate -> warning", "已存在" in str(out[0]))
    except Exception as e:
        check("add_song success", False, repr(e))
    finally:
        if test_dir.exists():
            rmtree_with_retry(test_dir)

    # only title filled — everything else blank (LRCLIB lookup fails for this
    # made-up title, so a placeholder lyrics.lrc is created)
    nolrc_title = "Selftest NoLrc Zzqx Song"
    nolrc_dir = SONGS_DIR / re.sub(r"[^\w]+", "_", nolrc_title.lower()).strip("_")
    try:
        if nolrc_dir.exists():
            rmtree_with_retry(nolrc_dir)
        out = call("on_add_song",
                   [nolrc_title, "", "", "", None, None, "added_asc"])
        status = str(out[0])
        check("add_song title-only (no lrc)",
              "✅" in status and nolrc_dir.exists()
              and (nolrc_dir / "lyrics.lrc").exists(),
              f"status={status!r}")
    except Exception as e:
        check("add_song title-only (no lrc)", False, repr(e))
    finally:
        if nolrc_dir.exists():
            rmtree_with_retry(nolrc_dir)
        # deleting a song LOWERS max mtime, so the evolution staleness check
        # can't see it — force a rebuild next launch
        if EVOLUTION_JSON.exists():
            unlink_with_retry(EVOLUTION_JSON)

    # ── 6. generate annotations guard (fresh session: no slug saved) ──
    try:
        out = call("on_generate_ann", [None], session=f"{SESSION}-gen")
        check("generate_ann without slug -> warning", "⚠" in str(out[0]))
    except Exception as e:
        check("generate_ann without slug -> warning", False, repr(e))

    # ── 7. dynamic audio: dummy WAV, re-select, served, removed ──
    wav_path = SONGS_DIR / "cardigan" / "audio.wav"
    created = False
    try:
        if wav_path.exists():
            # leftover from a previous crashed run — clean it up first
            unlink_with_retry(wav_path)
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 800)
        created = True
        out = call("on_song_select", [cardigan])
        lyrics = out[0]
        check("dynamic audio pickup (no restart)",
              "ll-audio" in lyrics and "/gradio_api/file=" in lyrics)
        m = re.search(r'src="([^"]+)"', lyrics)
        if m:
            url = m.group(1)
            if url.startswith("/"):
                url = BASE + url
            resp = httpx.get(url, timeout=10)
            check("audio file served via /gradio_api/file=",
                  resp.status_code == 200, f"status={resp.status_code} url={url}")
        else:
            check("audio file served via /gradio_api/file=", False, "no src attr found")
        if created:
            unlink_with_retry(wav_path)
            created = False
        out = call("on_song_select", [cardigan])
        check("audio removal fallback", "/gradio_api/file=" not in out[0])
    except Exception as e:
        check("audio dynamic tests", False, repr(e))
    finally:
        if created and wav_path.exists():
            unlink_with_retry(wav_path)

    print(f"\n{'=' * 40}\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failed:", *FAIL, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    main()
