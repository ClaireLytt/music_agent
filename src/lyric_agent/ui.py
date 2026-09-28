"""Gradio UI — 歌词透镜 Lyric Lens（简体中文，极简私人版）.

页签 1  🎧 播放解读 — 同步歌词、点一句歌词、右侧问 AI 助手
页签 2  🗺️ 艺术家图谱 — 艺术家演化地图
页签 3  🥚 彩蛋地图 — 同歌手全曲库歌词互文网络图（含意象追踪）
页签 4  📊 曲库洞察 — 每日一句 / 词云 / 情绪地图 / 歌单故事线
页签 5  🎮 互动   — 歌词竞猜 / 曲库内听歌识曲
页签 6  ➕ 添加歌曲 — 用户自行添加歌曲（LRC + 元数据 + 可选音频）

All JavaScript lives in gr.Blocks(head=...) because Gradio 6 injects
gr.HTML content via innerHTML (embedded <script> tags do not execute).
"""

from __future__ import annotations

import html
import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import gradio as gr

from dataclasses import replace

from .annotator.models import Song
from .audio_provider import resolve as resolve_audio
from .config import (
    HACKATHON_PLAYLIST_SOURCE,
    Settings,
    default_model_for,
    save_user_settings,
)
from .debate import PERSONAS, DebateSession, speak as ai_speak
from .evolution.engine import load_or_build
from .evolution.ui import EVOLUTION_CSS, render_evolution_html
from .lrc_parser import load_lrc_file, parse_lrc
from .search import LyricsSearcher

try:
    from .intertextuality.echo_map import ECHO_MAP_CSS
except ImportError:  # embeddings extra not installed — tab shows a hint instead
    ECHO_MAP_CSS = ""

logger = logging.getLogger(__name__)

_CHAT_HINT = (
    '<div class="chat-empty">点击左侧任意一句歌词，然后在这里向 AI 助手提问，'
    '比如：这句用了什么修辞？背后有什么故事？</div>'
)
_CHAT_TOPIC_DEFAULT = '<div class="chat-topic dim">尚未选择歌词行</div>'
_NO_AUDIO_HINT = (
    "🎧 未检测到音频 — 当前为纯阅读模式。将 audio.mp3 放入歌曲目录即可启用播放同步。"
)


def _esc(text: str) -> str:
    return html.escape(str(text))


# ── Song loading ──────────────────────────────────────────

def _discover_songs(songs_dir: str,
                    exclude_sources: set[str] | None = None) -> list[dict[str, Any]]:
    base = Path(songs_dir)
    if not base.exists():
        return []
    songs = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not (d / "lyrics.lrc").exists():
            continue
        meta = {}
        if (d / "metadata.json").exists():
            meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        if exclude_sources and meta.get("source") in exclude_sources:
            continue
        audio = resolve_audio(d)
        era = meta.get("era", "").lower()
        songs.append({
            "dir": str(d), "name": d.name,
            "title": meta.get("title", d.name.replace("_", " ").title()),
            "artist": meta.get("artist", "未知歌手"),
            "album": meta.get("album", ""), "year": meta.get("year", 0),
            "era": era,
            "audio_type": audio.type, "audio_src": audio.path_or_url or "",
            # preview clips start mid-song; shift lyric sync by this many ms
            "audio_offset_ms": int(meta.get("audio_offset_ms", 0) or 0),
            # Windows: st_ctime is directory creation time = when the song was added
            "added_ts": d.stat().st_ctime,
        })
    return songs


def _fetch_lrc_from_lrclib(title: str, artist: str) -> str | None:
    """Best-effort synced-lyrics lookup on LRCLIB; None when nothing found."""
    import urllib.parse
    import urllib.request
    try:
        query = urllib.parse.quote(f"{artist} {title}".strip())
        req = urllib.request.Request(
            f"https://lrclib.net/api/search?q={query}",
            headers={"User-Agent": "lyric-agent/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read().decode("utf-8"))
        return next(
            (e["syncedLyrics"] for e in results if e.get("syncedLyrics")), None)
    except Exception:
        return None


_PLACEHOLDER_LRC = "[00:00.00] （暂无歌词 — 可编辑本目录下的 lyrics.lrc 补充）\n"

_CATALOG_PATH = Path("data/catalog/catalog.json")


def _load_catalog() -> list[dict]:
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _load_chat_history(song_dir: str | Path) -> dict:
    """Per-line saved chats: {"<line_index>": {"line": str, "turns": [...]}}"""
    path = Path(song_dir) / "chat_history.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_chat_history(song_dir: str | Path, line_index: int,
                       lyric_line: str, turns: list[dict]) -> None:
    data = _load_chat_history(song_dir)
    data[str(line_index)] = {"line": lyric_line, "turns": turns}
    path = Path(song_dir) / "chat_history.json"
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        logger.exception("Failed to save chat history")


# per-song listening notes: [{"ts_ms": int, "text": str}]
_NOTES_FILENAME = "notes.json"


def _load_notes(song_dir: str | Path) -> list[dict]:
    path = Path(song_dir) / _NOTES_FILENAME
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        logger.exception("Failed reading notes for %s", song_dir)
    return []


def _save_notes(song_dir: str | Path, notes: list[dict]) -> None:
    (Path(song_dir) / _NOTES_FILENAME).write_text(
        json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")


def _render_notes(notes: list[dict]) -> str:
    if not notes:
        return ('<div class="chat-empty">播放到喜欢的位置，写句感想点「添加」——'
                '笔记会带上时间戳，点笔记即可跳回该位置。</div>')
    items = []
    for i, n in enumerate(notes):
        ts = int(n.get("ts_ms", 0))
        mm, ss = divmod(ts // 1000, 60)
        items.append(
            f'<div class="note-item" data-seek="{ts}">'
            f'<span class="note-ts">▶ {mm:02d}:{ss:02d}</span>'
            f'<span class="note-text">{_esc(n.get("text", ""))}</span>'
            f'<span class="note-del" data-del-note="{i}" data-del-ts="{ts}" '
            'title="删除">✕</span>'
            '</div>'
        )
    return '<div class="note-list">' + "".join(items) + "</div>"


# distinct colors for end-rhyme groups (cycled when a song has more groups)
_RHYME_COLORS = [
    "#0969da", "#bf3989", "#1a7f37", "#bc4c00", "#8250df",
    "#cf222e", "#0550ae", "#9a6700", "#6639ba", "#2da44e",
]

# whole-song AI intro, generated once and cached in the song directory
_INTRO_FILENAME = "intro.txt"
_INTRO_EMPTY = ('<div class="chat-empty">尚未生成本歌导读 — '
                '点击下方按钮由 AI 生成（需 API Key，几秒钟）。</div>')


def _load_intro(song_dir: str | Path) -> str:
    path = Path(song_dir) / _INTRO_FILENAME
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        logger.exception("Failed reading intro for %s", song_dir)
    return ""


def _render_intro(text: str) -> str:
    if not text:
        return _INTRO_EMPTY
    return f'<div class="song-intro">{_esc(text)}</div>'


# mtime-keyed cache: repeated song selections skip re-parsing lrc/annotations
_SONG_DATA_CACHE: dict[str, tuple[tuple[float, float], dict]] = {}


def _load_song_data(song_dir: str) -> dict[str, Any]:
    d = Path(song_dir)
    lrc_path = d / "lyrics.lrc"
    ann_path = d / "annotations.json"
    stamp = (
        lrc_path.stat().st_mtime if lrc_path.exists() else 0.0,
        ann_path.stat().st_mtime if ann_path.exists() else 0.0,
    )
    cached = _SONG_DATA_CACHE.get(song_dir)
    if cached and cached[0] == stamp:
        return cached[1]

    _meta, timed_lines = load_lrc_file(str(lrc_path))
    annotations = {}
    if ann_path.exists():
        song = Song.load(ann_path)
        for ann in song.annotations:
            annotations[ann.line_index] = ann
    try:
        from .rhyme import line_rhyme_groups
        rhymes = line_rhyme_groups([ln.text for ln in timed_lines])
    except Exception:
        logger.exception("Rhyme grouping failed for %s", song_dir)
        rhymes = [None] * len(timed_lines)
    from .insights import find_chorus_ts
    data = {
        "timed_lines": timed_lines,
        "annotations": annotations,
        "rhymes": rhymes,
        "chorus_ts": find_chorus_ts(timed_lines),
    }
    _SONG_DATA_CACHE[song_dir] = (stamp, data)
    return data


# ── HTML renderers ────────────────────────────────────────

def _file_url(path: str | Path) -> str:
    return "/gradio_api/file=" + str(Path(path).resolve()).replace("\\", "/")


def _player_tools(song_info: dict, chorus_ts: int | None) -> str:
    """Chorus jump, A-B loop, rhyme + radio toggles (wired up in _HEAD_JS)."""
    chorus = (f'<button class="ptool" data-seek="{chorus_ts}" '
              'title="跳到检测出的副歌位置">⏩ 副歌</button>'
              if chorus_ts is not None else "")
    return (
        '<div class="player-tools">'
        + chorus +
        '<button class="ptool" id="ll-ab-a" title="以当前位置为循环起点">🅰 起点</button>'
        '<button class="ptool" id="ll-ab-b" title="以当前位置为循环终点并开始循环">🅱 循环</button>'
        '<button class="ptool" id="ll-ab-clear" style="display:none">✕ 停止循环</button>'
        '<label class="ptool-toggle" title="同韵脚的歌词行标同色圆点">'
        '<input type="checkbox" id="ll-rhyme-toggle"> 🎯 韵脚</label>'
        '<label class="ptool-toggle" '
        'title="播完自动切下一首；有串场语音时先播报再进歌">'
        '<input type="checkbox" id="ll-radio-toggle"> 📻 电台模式</label>'
        '</div>'
    )


def _render_audio_html(song_info: dict, chorus_ts: int | None = None) -> str:
    a_type, src = song_info["audio_type"], song_info["audio_src"]
    offset = song_info.get("audio_offset_ms", 0)
    hint = ('<div class="preview-hint">🎧 官方试听片段 · 歌词已自动对齐</div>'
            if offset else "")
    if a_type not in ("local", "url"):
        return f'<div class="no-audio-hint">{_NO_AUDIO_HINT}</div>'
    url = _file_url(src) if a_type == "local" else src
    # cached radio intro (电台串场语音), if generated for this song
    from .radio import intro_audio_path
    intro = ""
    if song_info.get("dir"):
        p = intro_audio_path(song_info["dir"])
        if p.exists():
            intro = f' data-intro="{_esc(_file_url(p))}"'
    return (
        '<div id="ll-wave" title="波形加载中（需联网加载 wavesurfer）"></div>'
        f'<audio id="ll-audio" controls preload="metadata" '
        f'data-offset="{offset}"{intro} '
        f'src="{_esc(url)}" style="width:100%"></audio>'
        + _player_tools(song_info, chorus_ts) + hint
    )


def _render_search_results(hits: list, current_song: str, mode_used: str) -> str:
    if not hits:
        return '<div class="search-none">没有找到匹配的歌词。</div>'
    items = []
    for h in hits:
        same = h.song_name == current_song
        seek = f' data-seek="{h.timestamp_ms}"' if same else ""
        cls = "search-hit seekable" if same else "search-hit"
        mm, ss = divmod(h.timestamp_ms // 1000, 60)
        score = f' · {h.score:.2f}' if mode_used == "semantic" else ""
        items.append(
            f'<div class="{cls}"{seek}>'
            f'<div class="search-line">"{_esc(h.text)}"</div>'
            f'<div class="search-meta">{_esc(h.song_title)} · '
            f'{mm:02d}:{ss:02d}{score}{" · ▶" if same else ""}</div></div>'
        )
    tag = "🧠 语义匹配" if mode_used == "semantic" else "🔤 关键词匹配"
    return f'<div class="search-mode-tag">{tag}</div>' + "".join(items)


_SPEAKER_CLASSES = {"🎭 文学评论家": "critic", "🎵 粉丝考据家": "fan"}


def _render_chat(
    session: DebateSession | None,
    live: str | None = None,
    live_speaker: str = "🤖 AI 助手",
) -> str:
    """Render assistant chat; `live` = partial streaming text."""
    if session is None or (not session.history and live is None):
        return _CHAT_HINT

    def bubble(speaker: str, text: str, streaming: bool = False) -> str:
        cls = "chat-bubble ai " + _SPEAKER_CLASSES.get(speaker, "")
        cls += " streaming" if streaming else ""
        cursor = "▌" if streaming else ""
        return (f'<div class="{cls.strip()}"><b>{_esc(speaker)}</b>'
                f'<p>{_esc(text)}{cursor}</p></div>')

    bubbles = []
    for turn in session.history:
        if turn["speaker"] == "user":
            bubbles.append(
                f'<div class="chat-bubble user"><p>{_esc(turn["text"])}</p></div>')
        else:
            bubbles.append(bubble(turn["speaker"], turn["text"]))
    if live is not None:
        bubbles.append(bubble(live_speaker, live, streaming=True))
    return f'<div id="chat-scroll">{"".join(bubbles)}</div>'


def _chat_topic_html(line_text: str) -> str:
    return f'<div class="chat-topic">💬 正在讨论：「{_esc(line_text)}」</div>'


_ECHO_HINT = ('<div class="chat-empty">点击一句歌词，自动在同一歌手的其他作品里'
              '检索相似的意象与措辞，发现歌与歌之间的"彩蛋"呼应。</div>')

_ECHO_NO_INDEX = ('<div class="chat-empty">⚠️ 歌词语料库尚未构建，'
                  '请先运行 <code>python scripts/build_corpus.py</code> '
                  '并生成 embeddings。</div>')


_ECHO_OVERVIEW_EMPTY = ('<div class="chat-empty">本歌暂未发现与同歌手其他作品的'
                        '强呼应彩蛋。</div>')


def _render_echo_overview(hits: list[tuple[Any, Any]], artist: str) -> str:
    """Whole-song echo overview: every 🥚 line and its strongest target.

    hits: (TimedLine, EchoLine) pairs; each entry is clickable and jumps to
    the lyric line (data-goto-line is handled in _HEAD_JS).
    """
    if not hits:
        return _ECHO_OVERVIEW_EMPTY
    items = []
    for ln, e in hits:
        album = f" · {_esc(e.album)}" if e.album else ""
        items.append(
            f'<div class="echo-ov-item" data-goto-line="{ln.line_index}" '
            f'title="点击跳转到这句歌词">'
            f'<div class="echo-ov-src">“{_esc(ln.text)}”</div>'
            f'<div class="echo-ov-dst">↔ 《{_esc(e.song)}》{album}：'
            f'“{_esc(e.line)}”<span class="echo-ov-sim">{e.similarity}</span>'
            '</div></div>'
        )
    head = (f'<div class="echo-ov-head">共 {len(hits)} 处与'
            f'{_esc(artist or "同歌手")}其他作品的呼应 · 点击条目跳转</div>')
    return f'<div class="echo-ov-list">{head}{"".join(items)}</div>'


def _render_echo_html(results: list[dict], artist: str) -> str:
    if not results:
        return (f'<div class="chat-empty">未在 {_esc(artist or "该歌手")} '
                '的其他作品中找到明显呼应（相似度不足）。</div>')
    cards = []
    for r in results:
        album = f' · {_esc(r["album"])}' if r["album"] else ""
        cards.append(
            '<div class="echo-card">'
            f'<div class="echo-line">“{_esc(r["line"])}”</div>'
            f'<div class="echo-meta">《{_esc(r["song"])}》{album}</div></div>'
        )
    return '<div class="echo-list">' + "".join(cards) + "</div>"


def _render_lyrics_html(song_data: dict, song_info: dict) -> str:
    lines = song_data["timed_lines"]

    artist = song_info["artist"]
    album = song_info["album"]
    meta_text = " · ".join(x for x in (artist, album) if x)
    header_html = f"""\
<div class="song-header">
  <div>
    <h2 class="song-title-display">{_esc(song_info["title"])}</h2>
    <p class="song-meta-display">{_esc(meta_text)}</p>
  </div>
</div>"""

    rhymes = song_data.get("rhymes") or [None] * len(lines)
    parts = []
    for ln, group in zip(lines, rhymes):
        mark = ""
        if group is not None:
            color = _RHYME_COLORS[group % len(_RHYME_COLORS)]
            mark = (f'<span class="rhyme-mark" style="background:{color}" '
                    f'title="韵脚组 {group + 1}"></span>')
        parts.append(
            f'<div class="lyric-line" data-index="{ln.line_index}" '
            f'data-ts="{ln.timestamp_ms}">'
            f'<span class="lyric-text">{_esc(ln.text)}</span>{mark}</div>'
        )

    return (
        header_html
        + _render_audio_html(song_info, song_data.get("chorus_ts"))
        + '<div class="lyrics-hint">点击一句歌词，在右侧向 AI 助手提问 · '
          '⌨️ 空格 播放/暂停 · ←/→ 快退/快进 5 秒</div>'
        + f'<div id="lyrics-container"><div id="lyrics-scroll">{"".join(parts)}</div></div>'
    )


# ── Insights renderers (曲库洞察) ─────────────────────────

def _render_daily_quote(q: dict | None) -> str:
    if not q:
        return ('<div class="chat-empty">曲库中还没有带 AI 批注的歌曲，'
                '生成批注后这里每天会推一句值得品的歌词。</div>')
    return (
        '<div class="daily-card">'
        '<div class="daily-label">📅 每日一句</div>'
        f'<div class="daily-line">“{_esc(q["line"])}”</div>'
        f'<div class="daily-meta">——《{_esc(q["song"])}》· {_esc(q["artist"])}</div>'
        f'<div class="daily-insight">{_esc(q["insight"])}</div>'
        '</div>'
    )


def _render_word_cloud(freqs: list[tuple[str, int]], scope: str) -> str:
    if not freqs:
        return (f'<div class="chat-empty">{_esc(scope)} 的语料不足，'
                '暂无法生成高频意象。</div>')
    top = freqs[0][1]
    spans = []
    for word, n in freqs:
        # font size 13-34px by relative frequency
        size = 13 + 21 * (n / top) ** 0.6
        spans.append(
            f'<span class="cloud-word" data-word="{_esc(word)}" '
            f'style="font-size:{size:.0f}px" '
            f'title="出现 {n} 次，点击查看具体歌词">{_esc(word)}</span>'
        )
    return ('<div class="cloud-hint">词越大出现越多 · 点任意词看它出现在哪些歌词里</div>'
            f'<div class="word-cloud">{"".join(spans)}</div>')


_EMO_W, _EMO_H, _EMO_PAD = 860, 460, 60

_TONE_COLORS = {
    "nostalgia": "#bc4c00", "love": "#bf3989", "joy": "#1a7f37",
    "regret": "#57606a", "anger": "#cf222e", "sadness": "#0969da",
    "self-doubt": "#8250df", "hope": "#2da44e", "defiance": "#9a6700",
}


def _render_emotion_map(emotions: list) -> str:
    """Valence (x) × arousal (y) scatter; click a song dot to play it."""
    if not emotions:
        return ('<div class="chat-empty">曲库中还没有带 AI 批注的歌曲 —— '
                '情绪坐标来自批注里的逐行 valence/arousal。</div>')
    plot_w = _EMO_W - 2 * _EMO_PAD
    plot_h = _EMO_H - 2 * _EMO_PAD
    parts = [
        # quadrant guides
        f'<line x1="{_EMO_W / 2:.0f}" y1="{_EMO_PAD}" x2="{_EMO_W / 2:.0f}" '
        f'y2="{_EMO_H - _EMO_PAD}" class="emo-axis"/>',
        f'<line x1="{_EMO_PAD}" y1="{_EMO_H / 2:.0f}" x2="{_EMO_W - _EMO_PAD}" '
        f'y2="{_EMO_H / 2:.0f}" class="emo-axis"/>',
        f'<text x="{_EMO_W - _EMO_PAD}" y="{_EMO_H / 2 - 8:.0f}" '
        f'text-anchor="end" class="emo-axis-label">正向 →</text>',
        f'<text x="{_EMO_PAD}" y="{_EMO_H / 2 - 8:.0f}" '
        f'class="emo-axis-label">← 低落</text>',
        f'<text x="{_EMO_W / 2 + 6:.0f}" y="{_EMO_PAD + 12}" '
        f'class="emo-axis-label">激昂 ↑</text>',
        f'<text x="{_EMO_W / 2 + 6:.0f}" y="{_EMO_H - _EMO_PAD - 4}" '
        f'class="emo-axis-label">平静 ↓</text>',
    ]
    for e in emotions:
        x = _EMO_PAD + plot_w * max(0.0, min(1.0, e.valence))
        y = _EMO_H - _EMO_PAD - plot_h * max(0.0, min(1.0, e.arousal))
        color = _TONE_COLORS.get(e.tone, "#0969da")
        tip = (f'《{e.title}》· {e.artist}\n情绪基调：{e.tone or "未知"} · '
               f'正负向 {e.valence:.2f} · 能量 {e.arousal:.2f}\n点击播放这首歌')
        parts.append(
            f'<g class="emo-node" data-emo-pick="{_esc(e.title)}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{color}">'
            f'<title>{_esc(tip)}</title></circle>'
            f'<text x="{x:.1f}" y="{y - 14:.1f}" text-anchor="middle" '
            f'class="emo-label">{_esc(e.title[:12])}</text></g>'
        )
    legend = "".join(
        f'<span class="evo-legend-item"><span class="evo-legend-swatch" '
        f'style="background:{c}"></span>{_esc(t)}</span>'
        for t, c in _TONE_COLORS.items()
        if any(e.tone == t for e in emotions)
    )
    return (
        '<div class="cloud-hint">每个点是一首歌（基于 AI 批注的逐行情绪均值）'
        '· 点击任意歌曲直接播放</div>'
        f'<div class="evo-legend">{legend}</div>'
        f'<svg viewBox="0 0 {_EMO_W} {_EMO_H}" class="egg-svg" role="img">'
        + "".join(parts) + '</svg>'
    )


# ── Global JS (Blocks head) ──────────────────────────────

_HEAD_JS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/wavesurfer.js/7.8.6/wavesurfer.min.js" defer></script>
<script>
// force Gradio's light theme so the UI is always white regardless of the
// OS dark-mode setting (Gradio otherwise follows prefers-color-scheme)
(function() {
  try {
    const u = new URL(window.location);
    if (u.searchParams.get('__theme') !== 'light') {
      u.searchParams.set('__theme', 'light');
      window.location.replace(u);
    }
  } catch (e) {}
})();
// stale-page guard: after a server restart, an already-open page keeps a dead
// session and every click silently does nothing — detect the restart via the
// per-launch app_id and reload automatically
(function() {
  let appId = null;
  setInterval(async () => {
    try {
      const r = await fetch('config', { cache: 'no-store' });
      if (!r.ok) return;
      const c = await r.json();
      const id = String(c.app_id || '');
      if (!id) return;
      if (appId === null) appId = id;
      else if (id !== appId) window.location.reload();
    } catch (e) {}
  }, 4000);
})();
(function() {
  let userScrolling = false, scrollTimeout = null, lastActive = -2;
  // player tools state (survives per-song re-renders of the audio block)
  let abStart = null, abEnd = null;
  let radioOn = false, rhymeOn = false, radioPending = false;
  let lastAudioEl = null;

  function getAudio() { return document.getElementById('ll-audio'); }
  // preview clips start mid-song: lyric-time = audio-time + offset
  function getOffset(audio) { return parseFloat(audio.dataset.offset || '0'); }

  function fmt(t) {
    const s = Math.max(0, Math.floor(t));
    return String(Math.floor(s / 60)).padStart(2, '0') + ':' +
           String(s % 60).padStart(2, '0');
  }

  // write into a hidden gradio textbox channel and notify the backend
  function writeChannel(id, value) {
    const box = document.querySelector('#' + id + ' textarea, #' + id + ' input');
    if (!box) return;
    box.value = value;
    box.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function applyRhyme() {
    const c = document.getElementById('lyrics-container');
    if (c) c.classList.toggle('rhyme-on', rhymeOn);
  }

  // waveform: wavesurfer (CDN) drawing on top of the native audio element;
  // silently absent when the CDN is unreachable
  function initWave(a) {
    const holder = document.getElementById('ll-wave');
    if (!holder) return;
    if (!window.WaveSurfer) {
      // the deferred CDN script may not have loaded yet on first render —
      // retry for a while (still this song's audio element) before giving up
      holder.style.display = 'none';
      a._llWaveTries = (a._llWaveTries || 0) + 1;
      if (a._llWaveTries <= 20)
        setTimeout(() => { if (getAudio() === a) initWave(a); }, 500);
      return;
    }
    try {
      if (window._llWave) { window._llWave.destroy(); window._llWave = null; }
      holder.style.display = 'block';
      window._llWave = WaveSurfer.create({
        container: holder, media: a, height: 54,
        waveColor: '#c9d4df', progressColor: '#0969da',
        cursorColor: '#0969da', barWidth: 2, barGap: 1, barRadius: 1,
      });
    } catch (err) { holder.style.display = 'none'; }
  }

  function sync() {
    const audio = getAudio();
    const lines = document.querySelectorAll('#lyrics-scroll .lyric-line');
    if (audio && lines.length) {
      const ms = audio.currentTime * 1000 + getOffset(audio);
      let idx = -1;
      for (let i = lines.length - 1; i >= 0; i--) {
        if (ms >= parseFloat(lines[i].dataset.ts || '0')) { idx = i; break; }
      }
      if (idx !== lastActive) {
        lines.forEach((el, i) => {
          el.classList.toggle('played', i < idx);
          el.classList.toggle('active', i === idx);
          if (i !== idx) {
            const s = el.querySelector('.lyric-text');
            if (s && s.style.backgroundImage) s.style.backgroundImage = '';
          }
        });
        if (idx >= 0 && !userScrolling) {
          // scroll ONLY the lyrics container — scrollIntoView also scrolls the
          // page itself, hijacking clicks on other controls (e.g. search box)
          const c = document.getElementById('lyrics-container');
          const el = lines[idx];
          if (c && el) {
            c.scrollTo({
              top: el.offsetTop - c.clientHeight / 2 + el.offsetHeight / 2,
              behavior: 'smooth',
            });
          }
        }
        lastActive = idx;
      }
      // A-B loop: jump back to A whenever playback passes B
      if (abStart !== null && abEnd !== null && !audio.paused
          && audio.currentTime >= abEnd) {
        audio.currentTime = abStart;
      }
      // karaoke sweep on the active line: estimated per-line progress
      // (linear between this line's timestamp and the next one's)
      if (idx >= 0 && !audio.paused) {
        const el = lines[idx];
        const t0 = parseFloat(el.dataset.ts || '0');
        const next = lines[idx + 1];
        const t1 = next ? parseFloat(next.dataset.ts || '0')
                        : (audio.duration || 0) * 1000 + getOffset(audio);
        const p = Math.min(100, Math.max(0, 100 * (ms - t0) / Math.max(t1 - t0, 1)));
        const s = el.querySelector('.lyric-text');
        if (s) {
          s.style.backgroundImage =
            'linear-gradient(90deg, var(--accent) ' + p.toFixed(1) +
            '%, var(--karaoke-rest) ' + p.toFixed(1) + '%)';
        }
      }
    }
    requestAnimationFrame(sync);
  }
  requestAnimationFrame(sync);

  // whole-song echo map: backend writes JSON into #ll-echo-map, we decorate
  // matching lyric lines with a 🥚 marker (idempotent; re-applies after any
  // lyrics re-render, skips maps that belong to a different song)
  setInterval(() => {
    const box = document.querySelector('#ll-echo-map textarea, #ll-echo-map input');
    if (!box || !box.value) return;
    let data;
    try { data = JSON.parse(box.value); } catch (e) { return; }
    const lines = document.querySelectorAll('#lyrics-scroll .lyric-line');
    if (!lines.length) return;
    const title = document.querySelector('.song-title-display');
    if (!title || title.textContent.trim() !== data.song) return;
    const want = new Map((data.lines || []).map(o => [o.i, o]));
    lines.forEach(el => {
      const has = el.querySelector('.echo-mark');
      const o = want.get(parseInt(el.dataset.index));
      if (o && !has) {
        const m = document.createElement('span');
        m.className = 'echo-mark';
        m.title = '彩蛋：与《' + o.song + '》有呼应（相似度 ' + o.sim +
                  '），点击这行查看详情';
        m.textContent = '🥚';
        el.appendChild(m);
      } else if (!o && has) has.remove();
    });
  }, 600);

  // new-song watcher: the audio block is re-rendered per song, so restore
  // toggle states, rebuild the waveform, reset the A-B loop, and (in radio
  // mode) play the spoken intro before the song itself
  setInterval(() => {
    const a = getAudio();
    if (!a || a === lastAudioEl) return;
    lastAudioEl = a;
    abStart = abEnd = null;
    const r = document.getElementById('ll-radio-toggle');
    if (r) r.checked = radioOn;
    const y = document.getElementById('ll-rhyme-toggle');
    if (y) y.checked = rhymeOn;
    applyRhyme();
    initWave(a);
    if (radioPending) {
      radioPending = false;
      const intro = a.dataset.intro;
      if (radioOn && intro) {
        const voice = new Audio(intro);
        voice.addEventListener('ended', () => a.play().catch(() => {}));
        // a broken intro file fires 'error', never 'ended' — don't stall
        voice.addEventListener('error', () => a.play().catch(() => {}));
        voice.play().catch(() => { a.play().catch(() => {}); });
      } else if (radioOn) {
        a.play().catch(() => {});
      }
    }
  }, 500);

  // radio mode: when the song ends, advance to the next one in the list
  document.addEventListener('ended', function(e) {
    if (!e.target || e.target.id !== 'll-audio' || !radioOn) return;
    const inputs = Array.from(
      document.querySelectorAll('#ll-songs input[type=radio]'));
    if (!inputs.length) return;
    const i = inputs.findIndex(x => x.checked);
    radioPending = true;
    inputs[(i + 1) % inputs.length].click();
  }, true);  // 'ended' does not bubble — capture it

  // toggle listeners (delegated: the checkboxes are re-rendered per song)
  document.addEventListener('change', function(e) {
    if (!e.target) return;
    if (e.target.id === 'll-radio-toggle') radioOn = e.target.checked;
    if (e.target.id === 'll-rhyme-toggle') {
      rhymeOn = e.target.checked;
      applyRhyme();
    }
  }, true);

  // player-tool buttons + click-to-backend channels (capture phase so a
  // delete click doesn't also trigger the note's data-seek)
  document.addEventListener('click', function(e) {
    if (!e.target.closest) return;
    const audio = getAudio();
    if (e.target.closest('#ll-ab-a') && audio) {
      abStart = audio.currentTime; abEnd = null;
      e.target.closest('#ll-ab-a').textContent = '🅰 ' + fmt(abStart);
      const b = document.getElementById('ll-ab-b');
      if (b) b.textContent = '🅱 循环';
      const c = document.getElementById('ll-ab-clear');
      if (c) c.style.display = 'none';
      return;
    }
    if (e.target.closest('#ll-ab-b') && audio) {
      if (abStart === null || audio.currentTime <= abStart + 0.3) return;
      abEnd = audio.currentTime;
      e.target.closest('#ll-ab-b').textContent = '🅱 ' + fmt(abEnd);
      const c = document.getElementById('ll-ab-clear');
      if (c) c.style.display = '';
      return;
    }
    if (e.target.closest('#ll-ab-clear')) {
      abStart = abEnd = null;
      const a2 = document.getElementById('ll-ab-a');
      if (a2) a2.textContent = '🅰 起点';
      const b2 = document.getElementById('ll-ab-b');
      if (b2) b2.textContent = '🅱 循环';
      e.target.closest('#ll-ab-clear').style.display = 'none';
      return;
    }
    const del = e.target.closest('[data-del-note]');
    if (del) {
      e.stopPropagation();
      writeChannel('ll-note-del', del.dataset.delNote + ':' +
                   (del.dataset.delTs || '') + '\\t' + Date.now());
      return;
    }
    const word = e.target.closest('.cloud-word');
    if (word) {
      writeChannel('ll-word-pick', word.dataset.word + '\\t' + Date.now());
      return;
    }
    const emo = e.target.closest('[data-emo-pick]');
    if (emo) {
      writeChannel('ll-emo-pick', emo.dataset.emoPick + '\\t' + Date.now());
    }
  }, true);

  // current playback position → hidden channel (used by 听歌笔记)
  setInterval(() => {
    const a = getAudio();
    const box = document.querySelector('#ll-cur-time textarea, #ll-cur-time input');
    if (!box) return;
    // no audio on this song: reset instead of keeping the previous song's
    // position (a note added here would inherit that stale timestamp)
    const v = a ? a.currentTime.toFixed(2) : '0';
    if (box.value !== v) {
      box.value = v;
      box.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, 700);

  // keep the AI chat scrolled to the bottom while streaming (only when near bottom)
  setInterval(() => {
    const c = document.getElementById('chat-scroll');
    if (!c) return;
    if (c.scrollHeight - c.scrollTop - c.clientHeight < 140) c.scrollTop = c.scrollHeight;
  }, 400);

  document.addEventListener('wheel', function(e) {
    if (e.target.closest && e.target.closest('#lyrics-container')) {
      userScrolling = true;
      clearTimeout(scrollTimeout);
      scrollTimeout = setTimeout(() => { userScrolling = false; }, 5000);
    }
  }, { passive: true });

  // focus assist on pointerdown (fires before click; more reliable when
  // some other handler swallows the click): pressing anywhere on the
  // search field focuses its input
  document.addEventListener('pointerdown', function(e) {
    if (!e.target.closest) return;
    const sw = e.target.closest('#ll-search');
    if (sw) {
      const inp = sw.querySelector('textarea, input');
      if (inp) setTimeout(() => inp.focus(), 0);
    }
  }, true);

  document.addEventListener('click', function(e) {
    if (!e.target.closest) return;
    if (e.target.closest('#ll-search')) return;

    const audio = getAudio();

    // 彩蛋总览 entry: jump to (and select) the referenced lyric line
    const ov = e.target.closest('[data-goto-line]');
    if (ov) {
      const line = document.querySelector(
        '#lyrics-scroll .lyric-line[data-index="' + ov.dataset.gotoLine + '"]');
      if (line) {
        const c = document.getElementById('lyrics-container');
        if (c) {
          c.scrollTo({
            top: line.offsetTop - c.clientHeight / 2 + line.offsetHeight / 2,
            behavior: 'smooth',
          });
        }
        line.click();
      }
      return;
    }

    const seekEl = e.target.closest('[data-seek]');
    if (seekEl && audio) {
      audio.currentTime = Math.max(0,
        (parseFloat(seekEl.dataset.seek) - getOffset(audio)) / 1000);
      audio.play().catch(() => {});
      return;
    }

    const line = e.target.closest('#lyrics-scroll .lyric-line');
    if (line) {
      document.querySelectorAll('.lyric-line.picked').forEach(el => el.classList.remove('picked'));
      line.classList.add('picked');
      // tell the backend which line is selected (feeds the AI assistant panel)
      const pick = document.querySelector('#ll-line-pick textarea, #ll-line-pick input');
      if (pick) {
        pick.value = line.dataset.index;
        pick.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (audio && line.dataset.ts) {
        audio.currentTime = Math.max(0,
          (parseFloat(line.dataset.ts) - getOffset(audio)) / 1000);
        audio.play().catch(() => {});
      }
    }
  });

  document.addEventListener('keydown', function(e) {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
    const audio = getAudio();
    if (!audio) return;
    if (e.code === 'Space') {
      e.preventDefault();
      audio.paused ? audio.play().catch(() => {}) : audio.pause();
    } else if (e.key === 'ArrowLeft') {
      audio.currentTime = Math.max(0, audio.currentTime - 5);
    } else if (e.key === 'ArrowRight') {
      audio.currentTime = Math.min(audio.duration || 1e9, audio.currentTime + 5);
    }
  });
})();
</script>
"""

# ── CSS ───────────────────────────────────────────────────

_CSS = """\
:root {
  --bg-primary: #ffffff;
  --bg-secondary: #f6f8fa;
  --bg-card: #f6f8fa;
  --bg-card-hover: #eaeef2;
  --text-primary: #1f2328;
  --text-secondary: #656d76;
  --text-played: #a9b1ba;
  --accent: #0969da;
  --accent-soft: rgba(9, 105, 218, 0.08);
  --accent-glow: rgba(9, 105, 218, 0.15);
  --border: #d0d7de;
  --karaoke-rest: #57606a; /* un-sung part of the active karaoke line */
}

body, .gradio-container { background: var(--bg-primary) !important; }

/* hide gradio footer (Runs / API / Gradio links) */
footer, .gradio-container footer { display: none !important; }

/* song list & catalog: one song per line, never side by side */
#ll-songs .wrap, #ll-songs [data-testid="radio"], #ll-songs fieldset,
#ll-catalog .wrap, #ll-catalog [data-testid="radio"], #ll-catalog fieldset {
  display: flex !important;
  flex-direction: column !important;
  align-items: stretch !important;
  gap: 4px !important;
}
#ll-songs label, #ll-catalog label { width: 100%; }
#ll-catalog { max-height: 46vh; overflow-y: auto; }

/* white theme: every field on white with clearly visible text + caret */
.gradio-container input:not([type="checkbox"]):not([type="radio"]),
.gradio-container textarea,
.gradio-container select {
  background: #ffffff !important;
  color: var(--text-primary) !important;
  caret-color: var(--accent) !important;
  border: 1px solid var(--border) !important;
}
.gradio-container input:focus, .gradio-container textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-soft) !important;
}
.gradio-container input::placeholder, .gradio-container textarea::placeholder {
  color: var(--text-secondary) !important; opacity: 0.6;
}

.app-header { text-align: center; padding: 16px 0 4px; }
.app-header h1 { color: var(--accent); font-size: 26px; margin: 0; font-weight: 700; }
.app-header p { color: var(--text-secondary); margin: 4px 0 0; font-size: 14px; }

/* ── Prominent tab navigation ── */
.gradio-container .tab-nav, .gradio-container div[role="tablist"] {
  justify-content: center; gap: 10px; border-bottom: 1px solid var(--border);
  padding-bottom: 0; margin-bottom: 10px;
}
.gradio-container .tab-nav button, .gradio-container button[role="tab"] {
  font-size: 17px !important; font-weight: 700 !important;
  padding: 12px 30px !important; border-radius: 12px 12px 0 0 !important;
  color: var(--text-secondary) !important; background: transparent !important;
  border: none !important; border-bottom: 3px solid transparent !important;
  transition: all 0.2s ease;
}
.gradio-container .tab-nav button:hover, .gradio-container button[role="tab"]:hover {
  color: var(--text-primary) !important; background: var(--bg-card-hover) !important;
}
.gradio-container .tab-nav button.selected,
.gradio-container button[role="tab"][aria-selected="true"] {
  color: var(--accent) !important; background: var(--accent-soft) !important;
  border-bottom: 3px solid var(--accent) !important;
}

.ll-hidden { display: none !important; }

.side-panel-title {
  font-size: 15px; font-weight: 700; color: var(--text-primary);
  padding: 4px 2px 6px; border-bottom: 2px solid var(--accent-soft); margin-bottom: 8px;
}

/* Song header */
.song-header {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 20px; border-bottom: 1px solid var(--border); margin-bottom: 8px;
}
.song-title-display { margin: 0; font-size: 22px; font-weight: 700; color: var(--text-primary); }
.song-meta-display { margin: 2px 0 0; font-size: 13px; color: var(--text-secondary); }

.no-audio-hint {
  padding: 10px 16px; margin: 8px 0; border-radius: 8px; font-size: 13px;
  background: var(--bg-card); border: 1px dashed var(--border);
  color: var(--text-secondary);
}
.preview-hint {
  margin-top: 4px; font-size: 11px; color: var(--text-secondary);
}
.echo-mark {
  margin-left: 6px; font-size: 12px; opacity: 0.7; user-select: none;
}
.lyric-line:hover .echo-mark { opacity: 1; }

.lyrics-hint { text-align: center; color: var(--text-secondary); font-size: 12px; padding: 6px 0; opacity: 0.7; }

/* Lyrics */
#lyrics-container {
  position: relative; /* anchors .lyric-line offsetTop for container-scoped scroll */
  max-height: 66vh; overflow-y: auto; padding: 8px 12px;
  scroll-behavior: smooth; scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
#lyrics-container::-webkit-scrollbar { width: 6px; }
#lyrics-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
#lyrics-scroll { display: flex; flex-direction: column; gap: 2px; }

.lyric-line {
  padding: 8px 16px; border-radius: 8px; cursor: pointer;
  transition: all 0.25s ease; border-left: 3px solid transparent;
}
.lyric-line:hover { background: var(--bg-card-hover); }
.lyric-line.picked { background: var(--accent-soft); border-left-color: var(--accent); }
.lyric-line.played .lyric-text { color: var(--text-played); }
.lyric-line.active { background: var(--accent-glow); border-left-color: var(--accent); transform: scale(1.01); }
.lyric-line.active .lyric-text { color: var(--accent); font-weight: 600; font-size: 17px; }
/* karaoke sweep: JS drives a gradient over the active line's text; the
   estimated progress paints sung characters accent-blue */
@supports (-webkit-background-clip: text) or (background-clip: text) {
  .lyric-line.active .lyric-text[style*="background-image"] {
    -webkit-background-clip: text; background-clip: text;
    color: transparent; -webkit-text-fill-color: transparent;
  }
}
.lyric-text { font-size: 15px; color: var(--text-primary); transition: all 0.25s ease; line-height: 1.65; }

/* Search */
#ll-search { position: relative; z-index: 5; }
#ll-search textarea, #ll-search input {
  pointer-events: auto !important; cursor: text;
}
.search-mode-tag { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.search-hit {
  padding: 8px 12px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 6px;
}
.search-hit.seekable { cursor: pointer; }
.search-hit.seekable:hover { border-color: var(--accent); }
.search-line { font-size: 13px; color: var(--text-primary); font-style: italic; }
.search-meta { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.search-none { color: var(--text-secondary); font-size: 13px; padding: 8px; }

/* AI assistant chat */
.chat-topic {
  font-size: 13px; color: var(--accent); padding: 8px 12px;
  background: var(--accent-soft); border-radius: 8px; margin-bottom: 8px;
}
.chat-topic.dim { color: var(--text-secondary); background: var(--bg-card); }
.chat-empty { color: var(--text-secondary); font-size: 13px; padding: 10px; line-height: 1.7; }
#chat-scroll {
  max-height: 56vh; overflow-y: auto; display: flex; flex-direction: column;
  gap: 8px; padding: 4px 2px; scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.chat-bubble {
  padding: 10px 14px; border-radius: 12px; font-size: 13px;
  line-height: 1.7; max-width: 94%;
}
.chat-bubble b { display: block; font-size: 12px; margin-bottom: 4px; color: var(--accent); }
.chat-bubble p { margin: 0; color: var(--text-primary); white-space: pre-wrap; }
.chat-bubble.ai { background: rgba(9,105,218,0.06); border: 1px solid rgba(9,105,218,0.22); align-self: flex-start; }
.chat-bubble.user { background: var(--bg-card); border: 1px solid var(--border); align-self: flex-end; }
.chat-bubble.streaming { border-style: dashed; opacity: 0.92; }
/* debate personas get their own tints */
.chat-bubble.critic { background: rgba(130,80,223,0.07); border-color: rgba(130,80,223,0.30); }
.chat-bubble.critic b { color: #8250df; }
.chat-bubble.fan { background: rgba(191,57,137,0.07); border-color: rgba(191,57,137,0.30); }
.chat-bubble.fan b { color: #bf3989; }

/* whole-song AI intro */
.song-intro {
  font-size: 13px; line-height: 1.8; color: var(--text-primary);
  padding: 10px 12px; background: var(--bg-card); border-radius: 10px;
  white-space: pre-wrap;
}

.add-status { font-size: 14px; line-height: 1.8; }

/* Easter-egg intertextuality tracker */
.echo-list { display: flex; flex-direction: column; gap: 6px; }
.echo-card {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card);
}
.echo-line { font-size: 13px; font-style: italic; color: var(--text-primary); }
.echo-meta { font-size: 11px; color: var(--text-secondary); margin-top: 3px; }
.echo-explain { font-size: 13px; line-height: 1.7; }

/* player tools (chorus / A-B loop / toggles) */
#ll-wave { width: 100%; min-height: 0; }
.player-tools {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  padding: 6px 2px 0;
}
.ptool {
  font-size: 12px; padding: 3px 10px; border-radius: 14px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-primary);
}
.ptool:hover { border-color: var(--accent); color: var(--accent); }
.ptool-toggle {
  font-size: 12px; color: var(--text-secondary); cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
}

/* end-rhyme dots: hidden until the 🎯 韵脚 toggle adds .rhyme-on */
.rhyme-mark {
  display: none; width: 9px; height: 9px; border-radius: 50%;
  margin-left: 8px; vertical-align: middle;
}
#lyrics-container.rhyme-on .rhyme-mark { display: inline-block; }

/* listening notes */
.note-list { display: flex; flex-direction: column; gap: 5px; max-height: 32vh; overflow-y: auto; }
.note-item {
  display: flex; gap: 8px; align-items: baseline; cursor: pointer;
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); font-size: 13px;
}
.note-item:hover { border-color: var(--accent); }
.note-ts { color: var(--accent); font-size: 12px; white-space: nowrap; }
.note-text { flex: 1; color: var(--text-primary); }
.note-del { color: var(--text-secondary); padding: 0 4px; }
.note-del:hover { color: #cf222e; }

/* daily quote card */
.daily-card {
  background: linear-gradient(135deg, rgba(9,105,218,0.07), rgba(130,80,223,0.07));
  border: 1px solid var(--border); border-radius: 14px; padding: 16px 20px;
}
.daily-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.daily-line { font-size: 19px; font-weight: 700; color: var(--text-primary); font-style: italic; }
.daily-meta { font-size: 13px; color: var(--accent); margin: 6px 0 8px; }
.daily-insight { font-size: 13px; color: var(--text-secondary); line-height: 1.7; }

/* word cloud */
.cloud-hint { font-size: 12px; color: var(--text-secondary); margin: 4px 0 8px; }
.word-cloud {
  display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: baseline;
  padding: 10px 4px;
}
.cloud-word { color: var(--accent); cursor: pointer; line-height: 1.1; }
.cloud-word:hover { text-decoration: underline; }

/* emotion map */
.emo-axis { stroke: var(--border); stroke-dasharray: 4 4; }
.emo-axis-label { font-size: 12px; fill: var(--text-secondary); }
.emo-node { cursor: pointer; }
.emo-node circle { stroke: #ffffff; stroke-width: 1.5; }
.emo-node:hover circle { stroke: var(--accent); stroke-width: 2.5; }
.emo-label { font-size: 11px; fill: var(--text-secondary); }

/* quiz */
.quiz-line {
  font-size: 18px; font-weight: 700; font-style: italic;
  color: var(--text-primary); padding: 14px 18px;
  background: var(--bg-card); border-radius: 12px;
}
.quiz-meta { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }

/* whole-song easter-egg overview (🗺️ 本歌彩蛋总览) */
.echo-ov-head { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.echo-ov-list { max-height: 40vh; overflow-y: auto; scrollbar-width: thin; }
.echo-ov-item {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); margin-bottom: 6px; cursor: pointer;
  transition: border-color 0.15s ease;
}
.echo-ov-item:hover { border-color: var(--accent); }
.echo-ov-src { font-size: 13px; font-style: italic; color: var(--text-primary); }
.echo-ov-dst { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
.echo-ov-sim { margin-left: 6px; font-size: 11px; color: var(--accent); }
"""


# ── App factory ───────────────────────────────────────────

def launch_kwargs() -> dict:
    """Style/head kwargs for app.launch() (Gradio 6 moved them off Blocks)."""
    return {
        "css": _CSS + EVOLUTION_CSS + ECHO_MAP_CSS,
        "head": _HEAD_JS,
        "theme": gr.themes.Base(primary_hue="blue", neutral_hue="slate"),
    }


def create_app(settings: Settings) -> gr.Blocks:
    ctx: dict[str, Any] = {}
    public = settings.public_mode

    def refresh_library() -> None:
        # hackathon-playlist material is licensed for offline demo only —
        # never expose it on a public deployment
        songs = _discover_songs(
            settings.songs_dir,
            exclude_sources={HACKATHON_PLAYLIST_SOURCE} if public else None)
        ctx["songs"] = songs
        searcher = LyricsSearcher(songs, model_name=settings.embedding_model)
        ctx["searcher"] = searcher
        if songs:
            # pre-load the embedding model so the first semantic search doesn't
            # block on a ~90MB download / cold model init
            threading.Thread(target=searcher.warm_up, daemon=True).start()
        ctx["evolution"] = load_or_build(
            settings.songs_dir, Path(settings.evolution_path))
        # library changes invalidate the in-library highlights on echo graphs,
        # the audio fingerprint index, and (when no corpus is built, so the
        # word cloud falls back to library lyrics) the insights caches
        ctx.pop("echo_graphs", None)
        ctx.pop("fp_index", None)
        ctx.pop("corpus_lines", None)
        ctx.pop("clouds", None)

    refresh_library()

    def song_choice_label(s: dict) -> str:
        return s["title"]

    _SORT_KEYS = {
        "added": lambda s: s["added_ts"],
        "album": lambda s: (s["album"].lower(), s["title"].lower()),
        "artist": lambda s: (s["artist"].lower(), s["title"].lower()),
    }

    def song_choices(sort: str = "added_asc") -> list[str]:
        field, _, direction = sort.rpartition("_")
        key = _SORT_KEYS.get(field, _SORT_KEYS["added"])
        ordered = sorted(ctx["songs"], key=key, reverse=direction == "desc")
        return [song_choice_label(s) for s in ordered]

    def find_song(choice: str) -> dict:
        songs = ctx["songs"]
        return next(
            (s for s in songs if choice and song_choice_label(s) == choice),
            songs[0] if songs else {},
        )

    _PUBLIC_KEY_HINT = ("⚠️ 公开体验版需使用你自己的 API Key：请到「⚙️ 设置」页签填写"
                        "（Key 只保存在你的浏览器里，服务器不落盘）。")

    def _request_settings(cfg) -> Settings:
        """Per-visitor settings: in public mode the LLM config comes from the
        visitor's browser (gr.BrowserState), never from the server .env."""
        if not public:
            return settings
        cfg = cfg if isinstance(cfg, dict) else {}
        provider = (cfg.get("llm_provider") or "openai").strip()
        model = (cfg.get("model_name") or "").strip() or default_model_for(provider)
        return replace(
            settings,
            api_key=(cfg.get("api_key") or "").strip(),
            llm_provider=provider,
            llm_base_url=(cfg.get("llm_base_url") or "").strip(),
            model_name=model,
        )

    def _echo_index():
        if "echo_index" not in ctx:
            try:
                from .intertextuality.embeddings import load_embeddings
                ctx["echo_index"] = load_embeddings(settings.corpus_dir)
            except Exception:
                logger.exception("Intertextuality index unavailable")
                ctx["echo_index"] = None
        return ctx["echo_index"]

    def find_echoes(line_text: str, info: dict) -> list[dict] | None:
        """Top-K similar lines from the same artist's other songs.

        Returns None when the corpus/embeddings are not built.
        """
        index = _echo_index()
        if index is None:
            return None
        embeddings, corpus = index
        from .intertextuality.search import search_similar
        hits = search_similar(
            line_text, embeddings, corpus,
            model_name=settings.embedding_model,
            top_k=settings.echo_top_k,
            min_similarity=settings.echo_search_min_similarity,
            min_similarity_cjk=settings.echo_search_min_similarity_cjk,
            exclude_song=info.get("title", ""),
            artist=info.get("artist") or None,
        )
        return [{"song": h.song, "album": h.album, "line": h.line,
                 "similarity": h.similarity} for h in hits]

    def build_echo_map(info: dict) -> tuple[str, str]:
        """Whole-song 🥚 scan → (JS payload JSON, overview panel HTML).

        The payload decorates echoing lyric lines with 🥚 markers; the
        overview panel lists every echoing line with its strongest target.
        """
        song_dir = info.get("dir")
        if not song_dir:
            return "", _ECHO_OVERVIEW_EMPTY
        index = _echo_index()
        if index is None:
            return "", _ECHO_NO_INDEX
        lrc = Path(song_dir) / "lyrics.lrc"
        mtime = lrc.stat().st_mtime if lrc.exists() else 0.0
        cache = ctx.setdefault("echo_maps", {})
        cached = cache.get(song_dir)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        embeddings, corpus = index
        data = _load_song_data(song_dir)
        lines = data["timed_lines"]
        from .intertextuality.search import find_song_echoes
        try:
            echoes = find_song_echoes(
                [ln.text for ln in lines], embeddings, corpus,
                model_name=settings.embedding_model,
                exclude_song=info.get("title", ""),
                min_similarity=settings.echo_min_similarity,
                min_similarity_cjk=settings.echo_min_similarity_cjk,
                artist=info.get("artist") or None,
            )
        except Exception:
            logger.exception("Echo map failed for %s", song_dir)
            return "", _ECHO_OVERVIEW_EMPTY
        hits = [
            (ln, e) for ln, e in zip(lines, echoes) if e is not None
        ]
        payload = json.dumps({
            "song": info.get("title", ""),
            "lines": [
                {"i": ln.line_index, "song": e.song, "sim": e.similarity}
                for ln, e in hits
            ],
        }, ensure_ascii=False)
        overview = _render_echo_overview(hits, info.get("artist", ""))
        cache[song_dir] = (mtime, payload, overview)
        return payload, overview

    with gr.Blocks(title="歌词透镜 — AI 歌词批注播放器") as app:
        # per-visitor LLM config, persisted in the visitor's own browser
        user_llm = gr.BrowserState(
            {"api_key": "", "llm_provider": "openai",
             "llm_base_url": "", "model_name": ""},
            storage_key="lyric_lens_llm")
        gr.HTML(
            '<div class="app-header"><h1>🔍 歌词透镜</h1>'
            '<p>点一句歌词，问懂一句歌词</p></div>'
        )

        with gr.Tabs() as tabs:
            # ══ 页签 1: 播放解读 ══
            with gr.Tab("🎧 播放解读", id="play"):
                with gr.Row():
                    # ── 左栏: 歌曲 + 搜索 ──
                    with gr.Column(scale=1, min_width=230):
                        choices = song_choices()
                        song_radio = gr.Radio(
                            choices=choices,
                            label="🎵 歌曲列表" if choices else "未找到歌曲，请到「添加歌曲」页签添加",
                            value=choices[0] if choices else None,
                            elem_id="ll-songs",
                        )
                        if not public:
                            with gr.Accordion("🎵 为当前歌曲上传音频", open=False,
                                              elem_id="ll-audio-up"):
                                audio_file_up = gr.File(
                                    label="拖拽 mp3 / wav / flac 文件到这里",
                                    file_types=[".mp3", ".wav", ".flac",
                                                ".ogg", ".m4a"])
                                audio_up_status = gr.Markdown("")
                        sort_mode = gr.Radio(
                            choices=[
                                ("添加顺序（最早在前）", "added_asc"),
                                ("添加顺序（最新在前）", "added_desc"),
                                ("专辑（按字母排序）", "album_asc"),
                                ("歌手（按字母排序）", "artist_asc"),
                            ],
                            value="added_asc", label="🎛️ 排序")
                        search_box = gr.Textbox(
                            label="🔍 全库歌词搜索", elem_id="ll-search")
                        search_mode = gr.Radio(
                            choices=[("关键词", "kw"), ("语义", "sem")],
                            value="kw", show_label=False,
                        )
                        with gr.Row():
                            search_btn = gr.Button("搜索", size="sm", scale=1)
                            search_clear = gr.Button("✕ 清除", size="sm", scale=1)
                        search_results = gr.HTML("")

                    # ── 中栏: 歌词 ──
                    with gr.Column(scale=3):
                        lyrics_html = gr.HTML("")

                    # ── 右栏: AI 助手 ──
                    with gr.Column(scale=2, min_width=320):
                        gr.HTML('<div class="side-panel-title">💬 AI 助手</div>')
                        chat_state = gr.State(None)
                        chat_topic = gr.HTML(_CHAT_TOPIC_DEFAULT)
                        chat_html = gr.HTML(_CHAT_HINT)
                        with gr.Row():
                            chat_input = gr.Textbox(
                                placeholder="针对这句歌词提问 ...",
                                show_label=False, scale=4, container=False)
                            chat_send = gr.Button("提问", scale=1, variant="primary")
                        debate_btn = gr.Button(
                            "🎭 乐评人 vs 粉丝 · 双视角辩论这句歌词", size="sm")
                        with gr.Accordion("📖 歌曲导读", open=False,
                                          elem_id="ll-intro"):
                            intro_html = gr.HTML(_INTRO_EMPTY)
                            if not public:
                                intro_btn = gr.Button("🪄 生成 30 秒导读", size="sm")
                        with gr.Accordion("🖼️ 分享卡片", open=False,
                                          elem_id="ll-card"):
                            card_btn = gr.Button("生成歌词金句卡", size="sm")
                            card_status = gr.Markdown("")
                            card_img = gr.Image(
                                label="长按/右键保存图片", type="filepath",
                                visible=False)
                        with gr.Accordion("🥚 彩蛋 · 互文追踪", open=True,
                                          elem_id="ll-echo"):
                            echo_state = gr.State(None)
                            echo_html = gr.HTML(_ECHO_HINT)
                            with gr.Row():
                                echo_btn = gr.Button("✨ 让 AI 解释这些呼应",
                                                     size="sm", scale=1)
                                echo_card_btn = gr.Button("🖼️ 彩蛋对照卡",
                                                          size="sm", scale=1)
                            echo_out = gr.Markdown("", elem_classes=["echo-explain"])
                            echo_card_status = gr.Markdown("")
                            echo_card_img = gr.Image(
                                label="长按/右键保存图片", type="filepath",
                                visible=False)
                        with gr.Accordion("🗺️ 本歌彩蛋总览", open=False,
                                          elem_id="ll-echo-overview"):
                            echo_overview = gr.HTML(_ECHO_OVERVIEW_EMPTY)
                        with gr.Accordion("📝 听歌笔记", open=False,
                                          elem_id="ll-notes"):
                            notes_html = gr.HTML(_render_notes([]))
                            with gr.Row():
                                note_input = gr.Textbox(
                                    placeholder="在当前播放位置记一句感想…",
                                    show_label=False, scale=4, container=False)
                                note_add_btn = gr.Button("添加", scale=1, size="sm")
                        if not public:
                            with gr.Accordion("📻 AI 电台", open=False,
                                              elem_id="ll-radio-acc"):
                                gr.Markdown(
                                    "勾选播放器下方的「📻 电台模式」后，"
                                    "歌曲播完会自动切到下一首；为歌曲生成过"
                                    "**串场语音**（把「歌曲导读」朗读成 DJ 播报）"
                                    "的话，进歌前会先播报再放歌。")
                                radio_gen_btn = gr.Button(
                                    "🎙️ 为本歌生成串场语音（需先有导读）", size="sm")
                                radio_status = gr.Markdown("")
                        line_pick = gr.Textbox(
                            value="", visible=True, elem_id="ll-line-pick",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # backend -> JS channel: whole-song echo map (🥚 markers)
                        echo_map_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-echo-map",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # JS -> backend: current audio position (for notes)
                        cur_time_box = gr.Textbox(
                            value="0", visible=True, elem_id="ll-cur-time",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # JS -> backend: delete-note clicks (note index)
                        note_del_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-note-del",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)

            # ══ 页签 2: 艺术家图谱 ══
            with gr.Tab("🗺️ 艺术家图谱"):
                evolution_html = gr.HTML("")

            # ══ 页签 3: 彩蛋地图 ══
            with gr.Tab("🥚 彩蛋地图"):
                gr.Markdown(
                    "在同一歌手的**全部曲库歌曲**之间批量检索歌词呼应。"
                    "默认「⭐ 单曲聚焦」：选一首歌，直接看它和哪些歌互文、"
                    "两句歌词怎么呼应；想看全貌再切「🕸️ 整体网络」。"
                    "歌手选「🌐 跨歌手引用」则只看**不同歌手之间**的呼应（引用/致敬）。"
                )
                with gr.Row():
                    map_artist = gr.Dropdown(
                        choices=[], value=None, label="选择歌手",
                        # choices arrive via app.load; custom values keep direct
                        # API calls (self_test) from tripping server-side checks
                        allow_custom_value=True, scale=2,
                        elem_id="ll-map-artist")
                    map_focus = gr.Dropdown(
                        choices=[], value=None, label="聚焦歌曲（按呼应数排序）",
                        allow_custom_value=True, scale=3,
                        elem_id="ll-map-focus")
                map_view = gr.Radio(
                    choices=[("⭐ 单曲聚焦（简明）", "focus"),
                             ("🕸️ 整体网络", "net")],
                    value="focus", show_label=False)
                echo_map_html = gr.HTML("")
                map_explain_btn = gr.Button("✨ 让 AI 解读这张彩蛋网络", size="sm")
                map_explain_out = gr.Markdown("", elem_classes=["echo-explain"])
                gr.Markdown("---\n### 🔍 意象追踪\n"
                            "输入一个意象或母题（如：雨、scarf、童年、月光），"
                            "看它在上面所选范围的曲库里如何反复出现与演变（按专辑分组）。")
                with gr.Row():
                    imagery_box = gr.Textbox(
                        show_label=False, placeholder="输入意象，如：雨 / scarf / 童年",
                        scale=4, container=False)
                    imagery_btn = gr.Button("追踪", scale=1, variant="primary")
                imagery_html = gr.HTML("")

            # ══ 页签 4: 曲库洞察 ══
            with gr.Tab("📊 曲库洞察"):
                daily_html = gr.HTML("")
                gr.Markdown("### ☁️ 高频意象词云")
                cloud_artist = gr.Dropdown(
                    choices=[], value=None, label="选择歌手（含全部）",
                    allow_custom_value=True, elem_id="ll-cloud-artist")
                cloud_html = gr.HTML("")
                word_trace_html = gr.HTML("")
                # JS -> backend: clicked word in the cloud
                word_pick_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-word-pick",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                gr.Markdown("### 🎭 曲库情绪地图")
                emotion_html = gr.HTML("")
                # JS -> backend: clicked song on the emotion map
                emo_pick_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-emo-pick",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                gr.Markdown("### 📖 歌单故事线\n"
                            "勾选几首歌，AI 按情绪弧线给出播放顺序，"
                            "并讲出这个歌单串成的故事。")
                story_songs = gr.CheckboxGroup(choices=[], label="选择歌曲")
                story_btn = gr.Button("✨ 生成故事线", size="sm")
                story_out = gr.Markdown("", elem_classes=["echo-explain"])

            # ══ 页签 5: 互动（竞猜 + 听歌识曲） ══
            with gr.Tab("🎮 互动"):
                gr.Markdown("### 🎯 歌词竞猜\n"
                            "从你的歌曲列表随机抽一句歌词，猜猜它出自哪首歌。")
                quiz_state = gr.State({"score": 0, "total": 0, "answer": ""})
                quiz_html = gr.HTML(
                    '<div class="chat-empty">点「开始/下一题」抽一句歌词。</div>')
                quiz_options = gr.Radio(choices=[], label="它出自哪首歌？",
                                        visible=False)
                with gr.Row():
                    quiz_new_btn = gr.Button("🎲 开始 / 下一题", variant="primary",
                                             scale=1)
                    quiz_submit_btn = gr.Button("提交答案", scale=1)
                quiz_result = gr.Markdown("")

                gr.Markdown("---\n### 🎙️ 听歌识曲（曲库内）\n"
                            "用麦克风录一段（或上传一段音频片段），"
                            "在你的本地曲库中识别是哪首歌、唱到了哪里。")
                fp_audio = gr.Audio(sources=["microphone", "upload"],
                                    type="numpy", label="录一段或上传片段")
                fp_btn = gr.Button("🔍 识别", variant="primary")
                fp_result = gr.Markdown("")

            # ══ 页签 6: 添加歌曲（公开版为只读曲库，不提供） ══
            if not public:
                with gr.Tab("➕ 添加歌曲"):
                    catalog = _load_catalog()
                    cat_labels = [f"{c['title']} — {c['artist']}" for c in catalog]
                    gr.Markdown(
                        f"### 从曲库添加（推荐）\n"
                        f"内置 {len(catalog)} 首中外热门歌曲（带时间戳歌词），"
                        "搜索后点选一首，一键添加到你的列表。"
                    )
                    cat_search = gr.Textbox(
                        label="搜索曲库（歌名 / 歌手 / 专辑）", elem_id="ll-cat-search")
                    cat_radio = gr.Radio(
                        choices=cat_labels, value=None,
                        label=f"曲库歌曲（{len(cat_labels)} 首）",
                        elem_id="ll-catalog")
                    cat_add_btn = gr.Button("＋ 添加到我的列表", variant="primary")
                    add_status = gr.Markdown("", elem_classes=["add-status"])
                    add_state = gr.State("")  # last added song dir name
                    gen_btn = gr.Button("🪄 为刚添加的歌曲生成 AI 批注（需 API Key，耗时约 1-3 分钟）")

                    with gr.Accordion("✍️ 手动添加曲库以外的歌曲", open=False):
                        gr.Markdown(
                            "**只有「歌曲标题」是必填项**，其余全部可以留空。\n"
                            "不填歌词时，会根据歌名和歌手自动尝试从 LRCLIB 获取带时间戳的歌词；"
                            "获取失败则先创建占位歌词，之后可随时编辑歌曲目录下的 `lyrics.lrc`。"
                        )
                        with gr.Row():
                            add_title = gr.Textbox(label="歌曲标题（必填）")
                            add_artist = gr.Textbox(label="歌手（选填）")
                            add_album = gr.Textbox(label="专辑（选填）")
                        add_lrc = gr.Textbox(
                            label="LRC 歌词（选填 — 格式如 [00:12.34] 歌词内容，留空将自动从 LRCLIB 获取）",
                            lines=8)
                        with gr.Row():
                            add_lrc_file = gr.File(
                                label="或上传 .lrc 文件（可选，优先于文本框）",
                                file_types=[".lrc", ".txt"])
                            add_audio_file = gr.File(
                                label="音频文件（可选）",
                                file_types=[".mp3", ".wav", ".m4a", ".ogg", ".flac"])
                        add_btn = gr.Button("💾 保存歌曲", variant="primary")

                    with gr.Accordion("🗂️ 管理歌曲列表", open=False):
                        gr.Markdown(
                            "从列表中**永久删除**一首歌（连同其歌词/批注/音频目录）。"
                            "如果你在磁盘上手动增删过歌曲目录，点「刷新曲库」让列表同步。"
                        )
                        manage_song = gr.Dropdown(
                            choices=choices, value=None, label="选择要删除的歌曲",
                            # newly added songs land via the add handlers'
                            # updates; custom values keep raw API calls working
                            allow_custom_value=True)
                        manage_confirm = gr.Checkbox(
                            label="我确认要删除这首歌（不可恢复）", value=False)
                        with gr.Row():
                            manage_del_btn = gr.Button("🗑️ 删除所选歌曲", scale=1)
                            manage_refresh_btn = gr.Button("🔄 刷新曲库", scale=1)
                        manage_status = gr.Markdown("")

            # ══ 页签 7: 设置 ══
            with gr.Tab("⚙️ 设置"):
                if public:
                    gr.Markdown(
                        "### API 设置（公开体验版）\n"
                        "请填入**你自己的**大模型 API Key。"
                        "Key 只会保存在你当前浏览器的本地存储（localStorage）中，"
                        "**不会上传或写入服务器**，其他访客也看不到。"
                    )
                else:
                    gr.Markdown(
                        "### API 设置\n"
                        "在这里填入你自己的大模型 API Key，点保存后**立即生效**，"
                        "无需改任何文件、无需重启。"
                    )
                set_provider = gr.Radio(
                    choices=[
                        ("OpenAI 兼容接口（DeepSeek / 通义 / Kimi 等）", "openai"),
                        ("Anthropic（Claude）", "anthropic"),
                    ],
                    value="openai" if public else settings.llm_provider,
                    label="接口类型")
                set_key = gr.Textbox(
                    label="API Key（必填）", type="password",
                    value="" if public else settings.api_key)
                set_base = gr.Textbox(
                    label="接口地址（选填 — OpenAI 兼容接口才需要，例如 https://api.deepseek.com）",
                    value="" if public else settings.llm_base_url)
                set_model = gr.Textbox(
                    label="模型名称（选填 — 留空自动使用默认模型）",
                    value="" if public else settings.model_name)
                set_btn = gr.Button("💾 保存设置", variant="primary")
                set_status = gr.Markdown("")

                if not public:
                    gr.Markdown(
                        "---\n### 语料库与 Embedding 模型\n"
                        "彩蛋/互文/语义搜索使用本地 embedding 模型。默认英文模型对"
                        "中文歌词区分度差；曲库以中文为主时，建议切换到多语模型后"
                        "**重建索引**（首次会下载模型，重建需 1-3 分钟）。"
                    )
                    emb_model_dd = gr.Dropdown(
                        choices=[
                            ("英文为主（默认）：all-MiniLM-L6-v2",
                             "all-MiniLM-L6-v2"),
                            ("多语（中英均可）：paraphrase-multilingual-MiniLM-L12-v2",
                             "paraphrase-multilingual-MiniLM-L12-v2"),
                        ],
                        value=settings.embedding_model
                        if settings.embedding_model in (
                            "all-MiniLM-L6-v2",
                            "paraphrase-multilingual-MiniLM-L12-v2")
                        else None,
                        allow_custom_value=True,
                        label="Embedding 模型（可输入任意 sentence-transformers 模型名）")
                    rebuild_btn = gr.Button("🔨 重建语料库索引（含新添加的歌曲）")
                    rebuild_status = gr.Markdown("")

        # ── Handlers ──

        def on_song_select(choice: str):
            if not ctx["songs"]:
                return ("", None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT,
                        render_evolution_html(ctx["evolution"], lang="zh"),
                        None, _ECHO_HINT, "", "", gr.Image(visible=False),
                        _INTRO_EMPTY, "", gr.Image(visible=False),
                        _render_notes([]))
            info = find_song(choice)
            audio = resolve_audio(info["dir"])
            info["audio_type"], info["audio_src"] = audio.type, audio.path_or_url or ""
            data = _load_song_data(info["dir"])
            lyrics = _render_lyrics_html(data, info)
            evo = render_evolution_html(
                ctx["evolution"], current_song_title=info["title"],
                current_era=info["era"], lang="zh")
            intro = _render_intro(_load_intro(info["dir"]))
            return (lyrics, None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT, evo,
                    None, _ECHO_HINT, "", "", gr.Image(visible=False),
                    intro, "", gr.Image(visible=False), _notes_for(info))

        song_outputs = [lyrics_html, chat_state, chat_topic, chat_html, evolution_html,
                        echo_state, echo_html, echo_out, card_status, card_img,
                        intro_html, echo_card_status, echo_card_img, notes_html]

        def on_echo_map(choice: str) -> tuple[str, str]:
            if not ctx["songs"]:
                return "", _ECHO_OVERVIEW_EMPTY
            return build_echo_map(find_song(choice))

        song_radio.change(on_song_select, [song_radio], song_outputs).then(
            on_echo_map, [song_radio], [echo_map_box, echo_overview])

        # ── 彩蛋地图（歌手级互文网络）──

        def _corpus_artists() -> list[str]:
            """Distinct primary artists in the corpus (display-name order)."""
            index = _echo_index()
            if index is None:
                return []
            from .intertextuality.search import primary_artist
            names: dict[str, str] = {}
            for line in index[1]:
                key = primary_artist(line.artist)
                if key:
                    names.setdefault(key, line.artist)
            return sorted(names.values(), key=str.lower)

        # dropdown sentinel for the cross-artist (references between artists) mode
        _CROSS_ARTIST_CHOICE = "🌐 跨歌手引用（全部歌手）"

        def _map_graph(choice: str):
            """Build (or fetch cached) EchoGraph + rendered HTML for a choice."""
            index = _echo_index()
            if index is None:
                return None, _ECHO_NO_INDEX
            cache = ctx.setdefault("echo_graphs", {})
            if choice not in cache:
                from .intertextuality.echo_map import (
                    build_echo_graph, render_echo_map_html)
                embeddings, corpus = index
                artist = None if choice == _CROSS_ARTIST_CHOICE else choice
                graph = build_echo_graph(
                    embeddings, corpus, artist,
                    min_similarity=settings.echo_min_similarity,
                    min_similarity_cjk=settings.echo_min_similarity_cjk,
                    max_nodes=settings.echo_map_max_nodes,
                    library_titles={s["title"] for s in ctx["songs"]},
                )
                cache[choice] = (graph, render_echo_map_html(graph))
            return cache[choice]

        def _render_map(artist: str, view: str, focus: str) -> str:
            graph, net_html = _map_graph(artist)
            if graph is None or view == "net":
                return net_html
            from .intertextuality.echo_map import render_focus_html
            return render_focus_html(graph, focus or "")

        def _focus_dd(graph, preferred: str | None = None):
            """Focus dropdown update + effective focus value for a graph."""
            if graph is None:
                return gr.Dropdown(choices=[], value=None), ""
            from .intertextuality.echo_map import focus_choices
            songs = focus_choices(graph)
            value = preferred if preferred in songs else \
                (songs[0] if songs else None)
            return gr.Dropdown(choices=songs, value=value), value or ""

        def on_map_artist(artist: str, view: str):
            if not artist:
                return gr.skip(), "", ""
            graph, _net = _map_graph(artist)
            dd, focus = _focus_dd(graph)
            # switching scope also resets the AI interpretation
            return dd, _render_map(artist, view, focus), ""

        def on_map_view(view: str, artist: str, focus: str):
            return (gr.Dropdown(visible=view == "focus"),
                    _render_map(artist, view, focus))

        def on_map_focus(focus: str, artist: str, view: str) -> str:
            return _render_map(artist, view, focus)

        def init_echo_map(choice: str):
            """Populate the dropdowns; default to the current song's artist
            and, when possible, focus on the current song itself."""
            artists = _corpus_artists()
            if not artists:
                return (gr.Dropdown(choices=[], value=None),
                        gr.Dropdown(choices=[], value=None), _ECHO_NO_INDEX)
            from .intertextuality.search import artist_matches
            info = find_song(choice) if ctx["songs"] else {}
            current = info.get("artist", "")
            value = next(
                (a for a in artists if current and artist_matches(a, current)),
                artists[0])
            graph, _net = _map_graph(value)
            dd, focus = _focus_dd(graph, preferred=info.get("title"))
            return (gr.Dropdown(choices=artists + [_CROSS_ARTIST_CHOICE],
                                value=value),
                    dd, _render_map(value, "focus", focus))

        # .input (not .change): programmatic updates from init_echo_map must
        # not re-trigger these handlers, or the default focus gets overwritten
        map_artist.input(on_map_artist, [map_artist, map_view],
                         [map_focus, echo_map_html, map_explain_out])
        map_view.input(on_map_view, [map_view, map_artist, map_focus],
                       [map_focus, echo_map_html])
        map_focus.input(on_map_focus, [map_focus, map_artist, map_view],
                        [echo_map_html])
        app.load(init_echo_map, [song_radio],
                 [map_artist, map_focus, echo_map_html])

        def on_map_explain(artist: str, user_cfg):
            """LLM interpretation of the strongest pairs on the current map."""
            if not artist:
                yield "⚠️ 请先选择歌手。"
                return
            graph, _html = _map_graph(artist)
            if graph is None or not graph.edges:
                yield "⚠️ 当前范围没有可解读的彩蛋呼应。"
                return
            req_settings = _request_settings(user_cfg)
            if public and not req_settings.api_key:
                yield _PUBLIC_KEY_HINT
                return
            yield "🤔 AI 正在解读这张彩蛋网络……"
            pair_lines = "\n".join(
                f"- 《{e.song_a}》↔《{e.song_b}》（{e.count} 处呼应）："
                f"“{e.example.line_a}” ↔ “{e.example.line_b}”"
                f"（相似度 {e.example.similarity}）"
                for e in graph.edges[:8]
            )
            scope = graph.artist or "多位歌手之间（跨歌手引用）"
            user_msg = (
                f"检索范围：{scope}\n"
                f"以下是曲库中呼应最强的歌曲对及代表歌词：\n{pair_lines}\n\n"
                "请从歌词创作的角度解读这张互文网络：哪些是真正有意味的呼应"
                "（重复意象、母题、自我引用或跨歌手致敬），哪些只是字面撞车？"
                "指出 2-3 条最值得听众注意的线索，用简体中文，200 字以内。"
            )
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt=("你是精通歌词文本分析的音乐评论人，"
                                   "用简体中文回答，简洁自然。"),
                    user_message=user_msg,
                )
                yield (resp.reply_text or "").strip() or "⚠️ AI 未返回内容，请重试。"
            except Exception as exc:
                logger.exception("Map explain failed")
                yield f"⚠️ LLM 调用失败：{str(exc)[:200]}"

        map_explain_btn.click(on_map_explain, [map_artist, user_llm],
                              [map_explain_out])

        # ── 意象追踪 ──

        def on_imagery(query: str, artist: str) -> str:
            index = _echo_index()
            if index is None:
                return _ECHO_NO_INDEX
            query = (query or "").strip()
            from .intertextuality.echo_map import render_imagery_timeline
            if not query:
                return render_imagery_timeline("", [], artist="")
            from .intertextuality.search import trace_imagery
            embeddings, corpus = index
            scope = None if (not artist or artist == _CROSS_ARTIST_CHOICE) \
                else artist
            hits = trace_imagery(
                query, embeddings, corpus,
                model_name=settings.embedding_model,
                artist=scope,
                min_similarity=settings.echo_search_min_similarity,
                min_similarity_cjk=settings.echo_search_min_similarity_cjk,
            )
            # album chronology where known (era registry), alphabetical otherwise
            from .evolution.engine import ERA_REGISTRY
            album_order = {
                album.lower(): idx
                for idx, era in enumerate(ERA_REGISTRY)
                for album in era.get("albums", [])
            }
            return render_imagery_timeline(
                query, hits, album_order=album_order, artist=scope or "")

        imagery_btn.click(on_imagery, [imagery_box, map_artist], [imagery_html])
        imagery_box.submit(on_imagery, [imagery_box, map_artist], [imagery_html])

        # ── 曲库洞察 ──

        _ALL_ARTISTS_CHOICE = "🌍 全部歌手"

        def _corpus_text_lines() -> list[tuple[str, str]]:
            """(text, artist) pairs — corpus when built, else library lyrics."""
            if "corpus_lines" not in ctx:
                from .intertextuality.corpus import load_corpus
                corpus = load_corpus(settings.corpus_dir)
                if corpus:
                    ctx["corpus_lines"] = [(l.text, l.artist) for l in corpus]
                else:
                    ctx["corpus_lines"] = [
                        (ln.text, s["artist"])
                        for s in ctx["songs"]
                        if (Path(s["dir"]) / "lyrics.lrc").exists()
                        for ln in _load_song_data(s["dir"])["timed_lines"]
                    ]
            return ctx["corpus_lines"]

        def on_cloud_artist(artist: str) -> str:
            from .insights import word_frequencies
            scope = None if (not artist or artist == _ALL_ARTISTS_CHOICE) \
                else artist
            cache = ctx.setdefault("clouds", {})
            if artist not in cache:
                freqs = word_frequencies(_corpus_text_lines(), scope)
                cache[artist] = _render_word_cloud(
                    freqs, scope or "全部歌手")
            return cache[artist]

        def on_word_pick(word: str, artist: str) -> str:
            word = (word or "").split("	")[0].strip()
            if not word:
                return ""
            return on_imagery(word, "" if artist == _ALL_ARTISTS_CHOICE
                              else artist)

        def on_emo_pick(title: str):
            """Emotion-map click: jump to that song on the play tab."""
            title = (title or "").split("	")[0].strip()
            label = next((song_choice_label(s) for s in ctx["songs"]
                          if s["title"] == title), None)
            if label is None:
                return gr.skip(), gr.skip()
            return gr.Radio(value=label), gr.Tabs(selected="play")

        def init_insights(choice: str):
            from .insights import daily_quote, library_emotions
            daily = _render_daily_quote(daily_quote(ctx["songs"]))
            artists = _corpus_artists()
            cloud_choices = [_ALL_ARTISTS_CHOICE] + artists
            current = find_song(choice).get("artist", "") if ctx["songs"] else ""
            from .intertextuality.search import artist_matches
            value = next(
                (a for a in artists if current and artist_matches(a, current)),
                _ALL_ARTISTS_CHOICE)
            emotions = _render_emotion_map(library_emotions(ctx["songs"]))
            titles = [s["title"] for s in ctx["songs"]]
            return (daily,
                    gr.Dropdown(choices=cloud_choices, value=value),
                    on_cloud_artist(value), emotions,
                    gr.CheckboxGroup(choices=titles))

        cloud_artist.input(on_cloud_artist, [cloud_artist], [cloud_html])
        word_pick_box.change(on_word_pick, [word_pick_box, cloud_artist],
                             [word_trace_html])
        emo_pick_box.change(on_emo_pick, [emo_pick_box],
                            [song_radio, tabs])
        app.load(init_insights, [song_radio],
                 [daily_html, cloud_artist, cloud_html, emotion_html,
                  story_songs])

        def on_storyline(selected: list[str], user_cfg):
            if not selected or len(selected) < 2:
                yield "⚠️ 请至少勾选 2 首歌。"
                return
            req_settings = _request_settings(user_cfg)
            if not req_settings.api_key:
                yield ("⚠️ 未配置 API Key。请到「⚙️ 设置」页签填写。"
                       if not public else _PUBLIC_KEY_HINT)
                return
            yield "🤔 AI 正在为这组歌编排情绪弧线……"
            from .insights import library_emotions
            emos = {e.title: e for e in library_emotions(ctx["songs"])}
            desc = []
            for t in selected:
                info = next((s for s in ctx["songs"] if s["title"] == t), {})
                e = emos.get(t)
                emo_part = (f"情绪 valence={e.valence:.2f} arousal={e.arousal:.2f}"
                            f" 基调={e.tone}" if e else "无情绪数据")
                intro = _load_intro(info.get("dir", "")) if info else ""
                desc.append(f"- 《{t}》（{info.get('artist', '')} · "
                            f"{info.get('album', '') or '未知专辑'}）：{emo_part}"
                            + (f"；导读：{intro[:80]}" if intro else ""))
            user_msg = (
                "以下是一组歌曲及其情绪数据：\n" + "\n".join(desc) +
                "\n\n请把它们编排成一个有情绪弧线的歌单：\n"
                "1. 给出推荐播放顺序（编号列表）；\n"
                "2. 用 100-150 字讲这个歌单串成了一个什么故事"
                "（开头什么心境、中段如何转折、结尾落在哪里）。\n"
                "用简体中文，直接输出。"
            )
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt="你是擅长编排歌单情绪弧线的音乐编辑，简体中文回答。",
                    user_message=user_msg,
                )
                yield (resp.reply_text or "").strip() or "⚠️ AI 未返回内容，请重试。"
            except Exception as exc:
                logger.exception("Storyline failed")
                yield f"⚠️ LLM 调用失败：{str(exc)[:200]}"

        story_btn.click(on_storyline, [story_songs, user_llm], [story_out])

        # ── 歌词竞猜 ──

        def _quiz_pool() -> dict:
            # skip songs whose directory vanished since library discovery
            # (e.g. deleted on disk without a 刷新曲库)
            return {
                s["title"]: (s["artist"],
                             [ln.text for ln in
                              _load_song_data(s["dir"])["timed_lines"]])
                for s in ctx["songs"]
                if (Path(s["dir"]) / "lyrics.lrc").exists()
            }

        def on_quiz_new(state: dict):
            from .quiz import make_question
            q = make_question(_quiz_pool())
            if q is None:
                # drop any previous question so 提交 can't grade a stale one
                return (dict(state or {}, answer=""),
                        '<div class="chat-empty">歌曲列表至少需要 2 首歌'
                        '才能出题。</div>',
                        gr.Radio(choices=[], visible=False), "")
            state = dict(state or {}, answer=q.answer)
            html_q = (f'<div class="quiz-line">“{_esc(q.line)}”</div>'
                      f'<div class="quiz-meta">歌手：{_esc(q.artist)}</div>')
            return (state, html_q,
                    gr.Radio(choices=q.options, value=None, visible=True), "")

        def on_quiz_submit(state: dict, choice: str):
            state = dict(state or {})
            answer = state.get("answer", "")
            if not answer:
                return state, "⚠️ 先点「开始 / 下一题」抽题。"
            if not choice:
                return state, "⚠️ 请先选择一个选项。"
            state["total"] = state.get("total", 0) + 1
            if choice == answer:
                state["score"] = state.get("score", 0) + 1
                verdict = f"✅ 答对了！正是《{answer}》。"
            else:
                verdict = f"❌ 不对，这句出自《{answer}》。"
            state["answer"] = ""  # one submission per question
            return (state, f"{verdict}　当前战绩 "
                    f"**{state.get('score', 0)} / {state['total']}**")

        quiz_new_btn.click(on_quiz_new, [quiz_state],
                           [quiz_state, quiz_html, quiz_options, quiz_result])
        quiz_submit_btn.click(on_quiz_submit, [quiz_state, quiz_options],
                              [quiz_state, quiz_result])

        # ── 听歌识曲 ──

        def on_identify(sample):
            if sample is None:
                yield "⚠️ 请先录一段或上传一段音频。"
                return
            from .fingerprint import build_index, match_sample
            if "fp_index" not in ctx:
                yield "⏳ 首次识别：正在为曲库音频建立声纹索引……"
                ctx["fp_index"] = build_index(ctx["songs"])
            index = ctx["fp_index"]
            skipped = ""
            if index.skipped:
                skipped = ("\n\n⚠️ 以下歌曲的音频无法解码、未入索引："
                           + "、".join(f"《{t}》" for t in index.skipped)
                           + "（mp3 解码需要安装 ffmpeg 并加入 PATH）")
            n_url = sum(1 for s in ctx["songs"]
                        if s.get("audio_type") == "url")
            if n_url:
                skipped += (f"\n\nℹ️ 另有 {n_url} 首歌只有在线试听片段，"
                            "不参与声纹索引。")
            if not index.indexed:
                yield ("⚠️ 曲库中没有可解码的音频，无法识别。" + skipped)
                return
            yield "🔎 正在比对声纹……"
            sr, data = sample
            result = match_sample(index, sr, data)
            if result is None:
                yield ("🤷 没有找到匹配（片段太短、噪声太大，或不在曲库中）。"
                       f"当前已索引 {len(index.indexed)} 首。" + skipped)
                return
            title, offset_s, conf = result
            mm, ss = divmod(int(offset_s), 60)
            yield (f"🎯 识别结果：**《{title}》**，片段大约在 "
                   f"**{mm:02d}:{ss:02d}** 处（置信度 {conf:.0%}）。" + skipped)

        fp_btn.click(on_identify, [fp_audio], [fp_result])

        def on_audio_upload(fpath, choice: str):
            if not fpath:
                return gr.skip(), gr.skip(), gr.skip()
            info = find_song(choice)
            if not info.get("dir"):
                return "⚠️ 请先在列表中选择一首歌。", None, gr.skip()
            ext = Path(fpath).suffix.lower()
            if ext not in {".mp3", ".wav", ".flac", ".ogg", ".m4a"}:
                return "⚠️ 仅支持 mp3 / wav / flac / ogg / m4a 格式。", None, gr.skip()
            d = Path(info["dir"])
            for old in d.glob("audio.*"):
                old.unlink()
            shutil.copy(fpath, d / f"audio{ext}")
            # a manually uploaded file is the full song — drop any preview offset
            meta_path = d / "metadata.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta.pop("audio_offset_ms", None):
                        meta_path.write_text(
                            json.dumps(meta, ensure_ascii=False, indent=2),
                            encoding="utf-8")
                except Exception:
                    logger.exception("Failed to clear audio_offset_ms")
            refresh_library()
            info = find_song(choice)
            data = _load_song_data(info["dir"])
            return (f"✅ 已为《{info['title']}》添加音频，现在可以播放了。",
                    None, _render_lyrics_html(data, info))

        if not public:
            audio_file_up.upload(on_audio_upload, [audio_file_up, song_radio],
                                 [audio_up_status, audio_file_up, lyrics_html])

        def on_sort(sort: str, choice: str):
            labels = song_choices(sort)
            value = choice if choice in labels else (labels[0] if labels else None)
            return gr.Radio(choices=labels, value=value)

        sort_mode.change(on_sort, [sort_mode, song_radio], [song_radio])

        def on_search_clear():
            return "", ""

        search_clear.click(on_search_clear, None, [search_box, search_results])

        def on_search(query: str, mode: str, choice: str):
            if not query.strip():
                return ""
            current = find_song(choice).get("name", "")
            if mode == "sem":
                hits, used = ctx["searcher"].semantic(query)
            else:
                hits, used = ctx["searcher"].keyword(query), "keyword"
            return _render_search_results(hits, current, used)

        search_btn.click(on_search, [search_box, search_mode, song_radio], [search_results])
        search_box.submit(on_search, [search_box, search_mode, song_radio], [search_results])

        # ── AI 助手（行级问答）──

        def on_line_pick(idx_str: str, choice: str, session):
            idx_str = (idx_str or "").strip()
            if not idx_str.isdigit() or not ctx["songs"]:
                return (session, _CHAT_TOPIC_DEFAULT, _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip())
            idx = int(idx_str)
            info = find_song(choice)
            data = _load_song_data(info["dir"])
            line = next((ln for ln in data["timed_lines"] if ln.line_index == idx), None)
            if line is None:
                return (session, _CHAT_TOPIC_DEFAULT, _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip())
            if session is not None and session.lyric_line == line.text \
                    and session.line_index == idx:
                return (session, _chat_topic_html(line.text), _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip())
            # annotations stay out of the UI but still feed the AI as context
            ann = data["annotations"].get(idx)
            # public mode: visitors must not see each other's saved Q&A
            saved = None if public else _load_chat_history(info["dir"]).get(str(idx))
            history = saved["turns"] if saved and isinstance(
                saved.get("turns"), list) else []
            session = DebateSession(
                lyric_line=line.text,
                song_title=info.get("title", ""),
                annotation_context=ann.summary if ann else "",
                line_index=idx,
                history=history,
            )
            echoes = find_echoes(line.text, info)
            if echoes is None:
                echo, echo_render = None, _ECHO_NO_INDEX
            else:
                echo = {"line": line.text, "song": info.get("title", ""),
                        "artist": info.get("artist", ""), "results": echoes}
                echo_render = _render_echo_html(echoes, info.get("artist", ""))
            return (session, _chat_topic_html(line.text), _render_chat(session),
                    echo, echo_render, "")

        line_pick.change(on_line_pick, [line_pick, song_radio, chat_state],
                         [chat_state, chat_topic, chat_html,
                          echo_state, echo_html, echo_out])

        def on_chat_send(session, user_text: str, choice: str, user_cfg):
            text = (user_text or "").strip()
            if not text:
                yield session, _render_chat(session), user_text
                return
            if session is None:
                yield (session,
                       '<div class="chat-empty">请先点击左侧一句歌词，再提问。</div>',
                       user_text)
                return
            req_settings = _request_settings(user_cfg)
            if public and not req_settings.api_key:
                yield session, _render_chat(session, live=_PUBLIC_KEY_HINT), user_text
                return
            session.history.append({"speaker": "user", "text": text})
            partial = ""
            for delta in ai_speak(req_settings, session, "assistant", user_prompt=text):
                partial += delta
                yield session, _render_chat(session, live=partial), ""
            # speak() skips history append on warning/error paths — keep the
            # rendered transcript consistent by appending whatever streamed
            if partial and session.history and session.history[-1]["speaker"] == "user":
                session.history.append({"speaker": "🤖 AI 助手", "text": partial})
            if not public and session.line_index >= 0 and partial \
                    and not partial.startswith("⚠️"):
                info = find_song(choice)
                if info.get("dir"):
                    _save_chat_history(info["dir"], session.line_index,
                                       session.lyric_line, session.history)
            yield session, _render_chat(session), ""

        chat_send.click(on_chat_send,
                        [chat_state, chat_input, song_radio, user_llm],
                        [chat_state, chat_html, chat_input])
        chat_input.submit(on_chat_send,
                          [chat_state, chat_input, song_radio, user_llm],
                          [chat_state, chat_html, chat_input])

        # ── 双视角辩论（乐评人 vs 粉丝考据家）──

        def on_debate(session, choice: str, user_cfg):
            if session is None:
                yield session, ('<div class="chat-empty">请先点击左侧一句歌词，'
                                '再发起双视角辩论。</div>')
                return
            req_settings = _request_settings(user_cfg)
            if public and not req_settings.api_key:
                yield session, _render_chat(session, live=_PUBLIC_KEY_HINT)
                return
            for persona in ("critic", "fan"):
                name = PERSONAS[persona]["name_zh"]
                partial = ""
                for delta in ai_speak(req_settings, session, persona):
                    partial += delta
                    yield session, _render_chat(
                        session, live=partial, live_speaker=name)
                # error/warning turns are yielded by speak() without being
                # appended to history — mirror them so the transcript reads on
                if partial and (not session.history
                                or session.history[-1]["text"] != partial):
                    session.history.append({"speaker": name, "text": partial})
            if not public and session.line_index >= 0:
                info = find_song(choice)
                if info.get("dir"):
                    _save_chat_history(info["dir"], session.line_index,
                                       session.lyric_line, session.history)
            yield session, _render_chat(session)

        debate_btn.click(on_debate, [chat_state, song_radio, user_llm],
                         [chat_state, chat_html])

        # ── 歌曲导读 ──

        def on_gen_intro(choice: str, user_cfg):
            if not ctx["songs"]:
                yield _INTRO_EMPTY
                return
            info = find_song(choice)
            req_settings = _request_settings(user_cfg)
            if not req_settings.api_key:
                yield ('<div class="chat-empty">⚠️ 未配置 API Key，无法生成导读。'
                       '请到「⚙️ 设置」页签填写。</div>')
                return
            existing = _load_intro(info["dir"])
            if existing:
                yield _render_intro(existing)
                return
            yield '<div class="chat-empty">🪄 AI 正在通读整首歌词，生成导读……</div>'
            data = _load_song_data(info["dir"])
            lyrics_text = "\n".join(ln.text for ln in data["timed_lines"])
            user_msg = (
                f"歌名：《{info.get('title', '')}》\n"
                f"歌手：{info.get('artist', '')}\n"
                f"专辑：{info.get('album', '') or '未知'}\n\n"
                f"完整歌词：\n{lyrics_text}\n\n"
                "请写一段 120-180 字的「歌曲导读」：这首歌讲了什么故事/情绪，"
                "创作背景（确定的才写），以及听的时候值得注意的 1-2 个歌词细节。"
                "语气亲切自然，直接输出正文。"
            )
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt=("你是精通流行音乐与歌词分析的电台 DJ，"
                                   "用简体中文写作，克制而准确。"),
                    user_message=user_msg,
                )
                text = (resp.reply_text or "").strip()
            except Exception as exc:
                logger.exception("Intro generation failed")
                yield f'<div class="chat-empty">⚠️ 生成失败：{_esc(str(exc)[:150])}</div>'
                return
            if not text:
                yield '<div class="chat-empty">⚠️ AI 未返回内容，请重试。</div>'
                return
            try:
                (Path(info["dir"]) / _INTRO_FILENAME).write_text(
                    text, encoding="utf-8")
            except Exception:
                logger.exception("Failed saving intro")
            yield _render_intro(text)

        if not public:
            intro_btn.click(on_gen_intro, [song_radio, user_llm], [intro_html])

        # ── 彩蛋对照卡 ──

        def on_echo_card(echo, choice: str):
            if not echo or not echo.get("results"):
                return ("⚠️ 请先点击一句有彩蛋呼应的歌词，再生成对照卡。",
                        gr.Image(visible=False))
            top = echo["results"][0]
            try:
                from .share_card import render_echo_card
                path = render_echo_card(
                    artist=echo.get("artist", ""),
                    song_a=echo.get("song", ""), line_a=echo.get("line", ""),
                    song_b=top["song"], line_b=top["line"],
                    similarity=top.get("similarity", 0.0),
                )
            except Exception as exc:
                logger.exception("Echo card failed")
                return f"⚠️ 卡片生成失败：{str(exc)[:120]}", gr.Image(visible=False)
            return "", gr.Image(value=path, visible=True)

        echo_card_btn.click(on_echo_card, [echo_state, song_radio],
                            [echo_card_status, echo_card_img])

        # ── 听歌笔记 ──

        _NOTES_PUBLIC_HINT = ('<div class="chat-empty">公开体验版不提供听歌笔记'
                              '（不写服务器磁盘）。</div>')

        def _notes_for(info: dict) -> str:
            if public:
                return _NOTES_PUBLIC_HINT
            return _render_notes(_load_notes(info["dir"])) if info.get("dir") \
                else _render_notes([])

        def on_add_note(choice: str, text: str, cur_time: str):
            text = (text or "").strip()
            info = find_song(choice)
            if public:
                return _NOTES_PUBLIC_HINT, gr.skip()
            if not text or not info.get("dir"):
                return gr.skip(), gr.skip()
            try:
                ts_ms = int(float(cur_time or "0") * 1000)
            except ValueError:
                ts_ms = 0
            # preview clips: note timestamps live on the lyric timeline
            ts_ms += int(info.get("audio_offset_ms", 0) or 0)
            notes = _load_notes(info["dir"])
            notes.append({"ts_ms": ts_ms, "text": text})
            notes.sort(key=lambda n: n.get("ts_ms", 0))
            _save_notes(info["dir"], notes)
            return _render_notes(notes), ""

        def on_del_note(idx_str: str, choice: str):
            payload = (idx_str or "").split("	")[0].strip()
            idx_part, _, ts_part = payload.partition(":")
            if public or not idx_part.isdigit():
                return gr.skip()
            info = find_song(choice)
            if not info.get("dir"):
                return gr.skip()
            notes = _load_notes(info["dir"])
            idx = int(idx_part)
            # the timestamp guards against deleting the wrong note off a
            # stale list (e.g. another tab changed notes.json since render);
            # on mismatch just re-render the fresh list
            if 0 <= idx < len(notes) and (
                    not ts_part.isdigit()
                    or int(notes[idx].get("ts_ms", 0)) == int(ts_part)):
                notes.pop(idx)
                _save_notes(info["dir"], notes)
            return _render_notes(notes)

        note_add_btn.click(on_add_note, [song_radio, note_input, cur_time_box],
                           [notes_html, note_input])
        note_input.submit(on_add_note, [song_radio, note_input, cur_time_box],
                          [notes_html, note_input])
        note_del_box.change(on_del_note, [note_del_box, song_radio],
                            [notes_html])

        # ── AI 电台串场语音 ──

        def on_gen_radio_intro(choice: str):
            info = find_song(choice)
            if not info.get("dir"):
                return "⚠️ 请先选择一首歌。", gr.skip()
            intro_text = _load_intro(info["dir"])
            if not intro_text:
                return ("⚠️ 本歌还没有导读文本 —— 先在「📖 歌曲导读」里点"
                        "「生成 30 秒导读」，再来生成串场语音。"), gr.skip()
            from .radio import synthesize_intro
            try:
                speech = (f"接下来这首，是{info.get('artist', '')}的"
                          f"《{info.get('title', '')}》。{intro_text}")
                synthesize_intro(info["dir"], speech)
            except Exception as exc:
                logger.exception("TTS failed")
                return f"⚠️ 串场语音生成失败：{str(exc)[:150]}", gr.skip()
            data = _load_song_data(info["dir"])
            audio = resolve_audio(info["dir"])
            info["audio_type"], info["audio_src"] = \
                audio.type, audio.path_or_url or ""
            return ("✅ 串场语音已生成。勾选播放器下方「📻 电台模式」，"
                    "自动切到这首歌时会先播报再进歌。",
                    _render_lyrics_html(data, info))

        if not public:
            radio_gen_btn.click(on_gen_radio_intro, [song_radio],
                                [radio_status, lyrics_html])

        def on_echo_explain(echo, user_cfg):
            if not echo or not echo.get("results"):
                yield "⚠️ 请先点击一句歌词，检索到呼应结果后再让 AI 解释。"
                return
            req_settings = _request_settings(user_cfg)
            if public and not req_settings.api_key:
                yield _PUBLIC_KEY_HINT
                return
            yield "🤔 AI 正在分析这些呼应关系……"
            hits = "\n".join(
                f"- 《{r['song']}》(专辑：{r['album'] or '未知'})："
                f"“{r['line']}”（相似度 {r['similarity']}）"
                for r in echo["results"]
            )
            user_msg = (
                f"歌手：{echo['artist']}\n"
                f"当前歌曲：《{echo['song']}》\n"
                f"当前歌词行：“{echo['line']}”\n\n"
                f"在这位歌手的其他作品中检索到以下相似歌词：\n{hits}\n\n"
                "请分析这句歌词与上面哪些歌构成了真正的呼应或互文"
                "（重复的意象、措辞、主题），用 2-4 句人话解释；"
                "如果某条结果只是字面相似、并无实质关联，请直接指出。"
                "只讨论列表中出现的歌曲。"
            )
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt=("你是精通歌词文本分析的音乐评论人，"
                                   "用简体中文回答，简洁自然。"),
                    user_message=user_msg,
                )
                text = (resp.reply_text or "").strip()
                yield text or "⚠️ AI 未返回内容，请重试。"
            except Exception as exc:
                logger.exception("Echo explain failed")
                yield f"⚠️ LLM 调用失败：{str(exc)[:200]}"

        echo_btn.click(on_echo_explain, [echo_state, user_llm], [echo_out])

        def on_share_card(session, choice: str):
            if session is None or not getattr(session, "lyric_line", ""):
                return ("⚠️ 请先点击一句歌词再生成卡片。",
                        gr.Image(visible=False))
            info = find_song(choice)
            insight = next(
                (t["text"] for t in reversed(session.history)
                 if t["speaker"] != "user"), "")
            if not insight:
                data = _load_song_data(info["dir"]) if info.get("dir") else {}
                ann = data.get("annotations", {}).get(session.line_index)
                if ann:
                    insight = " ".join(
                        x for x in (ann.summary, ann.metaphor_analysis) if x)
            if not insight:
                insight = "一句值得反复品味的歌词。"
            try:
                from .share_card import render_share_card
                path = render_share_card(
                    song_title=info.get("title", session.song_title),
                    artist=info.get("artist", ""),
                    lyric_line=session.lyric_line,
                    insight=insight,
                )
            except Exception as exc:
                logger.exception("Share card failed")
                return f"⚠️ 卡片生成失败：{str(exc)[:120]}", gr.Image(visible=False)
            return "", gr.Image(value=path, visible=True)

        card_btn.click(on_share_card, [chat_state, song_radio],
                       [card_status, card_img])

        # ── 添加歌曲 ──

        def on_add_song(title, artist, album, lrc_text, lrc_file, audio_file, sort):
            def fail(msg):
                return msg, gr.skip(), "", gr.skip()

            title = (title or "").strip()
            if not title:
                return fail("⚠️ 请填写歌曲标题（唯一必填项，其余均可留空）。")

            slug = re.sub(r"[^\w]+", "_", title.lower()).strip("_") \
                or f"song_{int(time.time())}"
            d = Path(settings.songs_dir) / slug
            if d.exists():
                return fail(f"⚠️ 歌曲目录已存在：`{slug}`，请换一个标题。")

            lrc_content = ""
            if lrc_file:
                try:
                    lrc_content = Path(lrc_file).read_text(
                        encoding="utf-8", errors="replace")
                except Exception as exc:
                    return fail(f"⚠️ 读取 LRC 文件失败：{exc}")
            elif lrc_text and lrc_text.strip():
                lrc_content = lrc_text

            if lrc_content.strip():
                _, timed = parse_lrc(lrc_content)
                if not timed:
                    return fail(
                        "⚠️ 未能解析出带时间戳的歌词行，"
                        "请检查格式（如 `[00:12.34] 歌词内容`）。"
                        "如果暂时没有歌词，也可以直接留空。")
                lrc_note = f"{len(timed)} 行歌词"
            else:
                fetched = _fetch_lrc_from_lrclib(title, (artist or "").strip())
                if fetched:
                    lrc_content = fetched
                    _, timed = parse_lrc(lrc_content)
                    lrc_note = f"已自动从 LRCLIB 获取 {len(timed)} 行歌词"
                else:
                    lrc_content = _PLACEHOLDER_LRC
                    lrc_note = "LRCLIB 未找到歌词，已创建占位歌词"

            d.mkdir(parents=True)
            (d / "lyrics.lrc").write_text(lrc_content, encoding="utf-8")
            meta = {
                "title": title,
                "artist": (artist or "").strip() or "未知歌手",
                "album": (album or "").strip(),
                "year": 0,
                "era": "",
                "themes": [],
            }
            (d / "metadata.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            if audio_file:
                ext = Path(audio_file).suffix.lower() or ".mp3"
                shutil.copy(audio_file, d / f"audio{ext}")

            refresh_library()
            new_choices = song_choices(sort)
            new_song = next((s for s in ctx["songs"] if s["name"] == slug), None)
            new_label = song_choice_label(new_song) if new_song else None
            status = (
                f"✅ 已添加《{title}》（{lrc_note}）到 `data/songs/{slug}/`。\n\n"
                "已切换到该歌曲。目前还没有 AI 批注 —— 点击下方按钮生成，"
                f"或在终端运行 `lyric-agent generate data/songs/{slug}`。"
            )
            return (status, gr.Radio(choices=new_choices, value=new_label), slug,
                    gr.Dropdown(choices=song_choices(), value=None))

        if not public:
            add_btn.click(
                on_add_song,
                [add_title, add_artist, add_album,
                 add_lrc, add_lrc_file, add_audio_file, sort_mode],
                [add_status, song_radio, add_state, manage_song],
            )

        # ── 曲库 ──

        def on_cat_search(q: str):
            q = (q or "").strip().lower()
            items = catalog if not q else [
                c for c in catalog
                if q in c["title"].lower() or q in c["album"].lower()
                or q in c["artist"].lower()
            ]
            labels = [f"{c['title']} — {c['artist']}" for c in items]
            return gr.Radio(choices=labels, value=None,
                            label=f"曲库歌曲（{len(labels)} 首）")

        if not public:
            cat_search.change(on_cat_search, [cat_search], [cat_radio])

        def on_cat_add(label: str, sort: str):
            if not label:
                return "⚠️ 请先在曲库中点选一首歌。", gr.skip(), gr.skip(), gr.skip()
            entry = next(
                (c for c in catalog if f"{c['title']} — {c['artist']}" == label),
                None)
            if not entry:
                return "⚠️ 未找到该曲目。", gr.skip(), gr.skip(), gr.skip()
            slug = re.sub(r"[^\w]+", "_", entry["title"].lower()).strip("_") \
                or f"song_{int(time.time())}"
            d = Path(settings.songs_dir) / slug
            if d.exists():
                return (f"ℹ️ 《{entry['title']}》已在你的列表中。",
                        gr.skip(), gr.skip(), gr.skip())
            d.mkdir(parents=True)
            (d / "lyrics.lrc").write_text(entry["lrc"], encoding="utf-8")
            meta = {
                "title": entry["title"],
                "artist": entry["artist"],
                "album": entry["album"],
                "year": 0,
                "era": entry.get("era", ""),
                "themes": [],
            }
            (d / "metadata.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            refresh_library()
            new_choices = song_choices(sort)
            new_song = next((s for s in ctx["songs"] if s["name"] == slug), None)
            new_label = song_choice_label(new_song) if new_song else None
            return (f"✅ 已添加《{entry['title']}》到你的列表，并已切换到该歌曲。",
                    gr.Radio(choices=new_choices, value=new_label), slug,
                    gr.Dropdown(choices=song_choices(), value=None))

        if not public:
            cat_add_btn.click(on_cat_add, [cat_radio, sort_mode],
                              [add_status, song_radio, add_state, manage_song])

        def on_generate_ann(slug: str):
            if not slug:
                return "⚠️ 请先在上方保存一首歌曲。", gr.skip()
            if not settings.api_key:
                return ("⚠️ 未配置 API Key，无法生成批注。"
                        "请到「⚙️ 设置」页签填写 API Key 并保存。"), gr.skip()
            d = Path(settings.songs_dir) / slug
            if not d.exists():
                return f"⚠️ 找不到歌曲目录 `{slug}`。", gr.skip()
            from .annotator.engine import generate_annotations
            try:
                song = generate_annotations(settings, d)
            except Exception as exc:
                return f"⚠️ 生成失败：{exc}", gr.skip()
            refresh_library()
            new_choices = song_choices()
            new_song = next((s for s in ctx["songs"] if s["name"] == slug), None)
            new_label = song_choice_label(new_song) if new_song else None
            return (f"✅ 已为《{song.metadata.title}》生成 {len(song.annotations)} 条批注。",
                    gr.Radio(choices=new_choices, value=new_label))

        if not public:
            gen_btn.click(on_generate_ann, [add_state], [add_status, song_radio])

        # ── 管理歌曲列表 ──

        def _library_updates(keep_choice: str | None = None):
            """Fresh Radio + manage-Dropdown updates after a library change."""
            labels = song_choices()
            value = keep_choice if keep_choice in labels else \
                (labels[0] if labels else None)
            return (gr.Radio(choices=labels, value=value),
                    gr.Dropdown(choices=labels, value=None))

        def on_manage_refresh(choice: str):
            refresh_library()
            _SONG_DATA_CACHE.clear()
            ctx.pop("echo_maps", None)
            radio, dd = _library_updates(choice)
            return f"🔄 已刷新，共 {len(ctx['songs'])} 首歌。", radio, dd

        def on_manage_delete(label: str, confirm: bool, choice: str):
            if not label:
                return "⚠️ 请先选择要删除的歌曲。", gr.skip(), gr.skip()
            if not confirm:
                return "⚠️ 请勾选确认框后再删除。", gr.skip(), gr.skip()
            info = next(
                (s for s in ctx["songs"] if song_choice_label(s) == label), None)
            if not info:
                return "⚠️ 未找到该歌曲，请先刷新曲库。", gr.skip(), gr.skip()
            try:
                shutil.rmtree(info["dir"])
            except Exception as exc:
                logger.exception("Delete song failed")
                return (f"⚠️ 删除失败（文件可能被占用）：{str(exc)[:120]}",
                        gr.skip(), gr.skip())
            _SONG_DATA_CACHE.pop(info["dir"], None)
            ctx.setdefault("echo_maps", {}).pop(info["dir"], None)
            refresh_library()
            radio, dd = _library_updates(
                choice if choice != label else None)
            return f"🗑️ 已删除《{label}》。", radio, dd

        if not public:
            manage_refresh_btn.click(
                on_manage_refresh, [song_radio],
                [manage_status, song_radio, manage_song])
            manage_del_btn.click(
                on_manage_delete, [manage_song, manage_confirm, song_radio],
                [manage_status, song_radio, manage_song])

        # ── 语料库索引重建 ──

        def on_rebuild(model_name: str):
            nonlocal settings
            model_name = (model_name or "").strip() or settings.embedding_model
            try:
                yield "⏳ 1/2 正在重建语料库（曲库歌曲 + 内置曲库）……"
                from .intertextuality.corpus import build_corpus
                n_songs, n_lines = build_corpus(
                    settings.songs_dir, settings.corpus_dir,
                    catalog_path=_CATALOG_PATH if _CATALOG_PATH.exists() else None,
                )
                yield (f"⏳ 2/2 语料库完成（{n_songs} 首 / {n_lines} 行），"
                       f"正在用 {model_name} 生成 embeddings"
                       "（首次使用该模型会先下载，需 1-3 分钟）……")
                from .intertextuality.embeddings import generate_embeddings
                embeddings, _corpus = generate_embeddings(
                    settings.corpus_dir, model_name=model_name)
            except Exception as exc:
                logger.exception("Rebuild index failed")
                yield f"⚠️ 重建失败：{str(exc)[:200]}"
                return
            settings = replace(settings, embedding_model=model_name)
            # persist so a restart keeps using this model (merge, don't clobber)
            from .config import USER_SETTINGS_PATH
            try:
                current = json.loads(USER_SETTINGS_PATH.read_text(
                    encoding="utf-8")) if USER_SETTINGS_PATH.exists() else {}
            except Exception:
                current = {}
            current["embedding_model"] = model_name
            save_user_settings(current)
            # all cached echo results were computed with the old index,
            # and the corpus text itself may have changed
            ctx.pop("echo_index", None)
            ctx.pop("echo_maps", None)
            ctx.pop("corpus_lines", None)
            ctx.pop("clouds", None)
            refresh_library()  # rebuilds the searcher on the new model
            yield (f"✅ 索引已重建：{embeddings.shape[0]} 行 × "
                   f"{embeddings.shape[1]} 维（模型：{model_name}）。"
                   "彩蛋/互文/语义搜索已切换到新索引。")

        if not public:
            rebuild_btn.click(on_rebuild, [emb_model_dd], [rebuild_status])

        # ── 设置 ──

        def on_save_settings(provider: str, key: str, base: str, model: str):
            nonlocal settings
            key = (key or "").strip()
            if not key:
                return "⚠️ 请填写 API Key。", gr.skip()
            base = (base or "").strip()
            model = (model or "").strip() or default_model_for(provider)
            if public:
                # per-visitor: browser localStorage only, never server disk
                cfg = {"api_key": key, "llm_provider": provider,
                       "llm_base_url": base, "model_name": model}
                return f"✅ 已保存到你的浏览器（模型：{model}）。", cfg
            settings = replace(
                settings, api_key=key, llm_provider=provider,
                llm_base_url=base, model_name=model)
            save_user_settings({
                "api_key": key, "llm_provider": provider,
                "llm_base_url": base, "model_name": model,
            })
            return f"✅ 已保存并生效（模型：{model}）。", gr.skip()

        set_btn.click(on_save_settings,
                      [set_provider, set_key, set_base, set_model],
                      [set_status, user_llm])

        if public:
            def load_user_cfg(cfg):
                cfg = cfg if isinstance(cfg, dict) else {}
                return (cfg.get("llm_provider") or "openai",
                        cfg.get("api_key") or "",
                        cfg.get("llm_base_url") or "",
                        cfg.get("model_name") or "")

            app.load(load_user_cfg, [user_llm],
                     [set_provider, set_key, set_base, set_model])

        if ctx["songs"]:
            app.load(on_song_select, [song_radio], song_outputs).then(
                on_echo_map, [song_radio], [echo_map_box, echo_overview])
        else:
            app.load(lambda: render_evolution_html(ctx["evolution"], lang="zh"),
                     None, [evolution_html])

    return app
