"""UI helpers: song discovery, per-song caches/persistence and all the
pure HTML renderers. Split out of ui.py — no gradio dependency here, so
every function stays unit-testable in isolation."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

from .annotator.models import Song
from .audio_provider import resolve as resolve_audio
from .debate import DebateSession
from .lrc_parser import load_lrc_file

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
    from .lrc_sources import fetch_synced_lyrics
    return fetch_synced_lyrics(title, artist)


_PLACEHOLDER_LRC = "[00:00.00] （暂无歌词 — 可编辑本目录下的 lyrics.lrc 补充）\n"

_CATALOG_PATH = Path("data/catalog/catalog.json")


def _load_catalog() -> list[dict]:
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        logger.exception("Failed reading catalog %s", _CATALOG_PATH)
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
        logger.exception("Failed reading chat history %s", path)
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

# disk cache for whole-song echo scans (survives restarts; key-invalidated)
_ECHO_SCAN_CACHE_DIR = Path("data/cache/echo_scans")

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
    # greedy label placement: try above/below/right/left of the dot and
    # keep the first spot that fits inside the canvas without touching an
    # already-placed label; when nothing fits the label is hidden until
    # the dot is hovered (the <title> tooltip always works)
    def _label_w(text: str) -> float:
        return sum(11.0 if ord(c) > 0x2E80 else 6.5 for c in text)

    placed: list[tuple[float, float, float, float]] = []

    def _fits(x0: float, y0: float, x1: float, y1: float) -> bool:
        if x0 < 2 or y0 < 2 or x1 > _EMO_W - 2 or y1 > _EMO_H - 2:
            return False
        return not any(x0 < px1 and x1 > px0 and y0 < py1 and y1 > py0
                       for px0, py0, px1, py1 in placed)

    seen: dict[tuple[int, int], int] = {}
    for e in emotions:
        x = _EMO_PAD + plot_w * max(0.0, min(1.0, e.valence))
        y = _EMO_H - _EMO_PAD - plot_h * max(0.0, min(1.0, e.arousal))
        bucket = (round(x / 8), round(y / 8))
        bump = seen.get(bucket, 0)
        seen[bucket] = bump + 1
        if bump:  # same spot as an earlier song: nudge the dot aside
            x = min(x + 10 * bump, _EMO_W - _EMO_PAD)
        color = _TONE_COLORS.get(e.tone, "#0969da")
        tip = (f'《{e.title}》· {e.artist}\n情绪基调：{e.tone or "未知"} · '
               f'正负向 {e.valence:.2f} · 能量 {e.arousal:.2f}\n点击播放这首歌')
        label = e.title[:12]
        w = _label_w(label)
        candidates = (
            (x, y - 14, "middle", x - w / 2, y - 24, x + w / 2, y - 12),
            (x, y + 24, "middle", x - w / 2, y + 14, x + w / 2, y + 26),
            (x + 13, y + 4, "start", x + 13, y - 6, x + 13 + w, y + 6),
            (x - 13, y + 4, "end", x - 13 - w, y - 6, x - 13, y + 6),
        )
        lx, ly, anchor, hidden = x, y - 14.0, "middle", " emo-hidden"
        for cx, cy, ca, bx0, by0, bx1, by1 in candidates:
            if _fits(bx0, by0, bx1, by1):
                lx, ly, anchor, hidden = cx, cy, ca, ""
                placed.append((bx0, by0, bx1, by1))
                break
        parts.append(
            f'<g class="emo-node" data-emo-pick="{_esc(e.title)}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{color}">'
            f'<title>{_esc(tip)}</title></circle>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'class="emo-label{hidden}">{_esc(label)}</text></g>'
        )
    legend = "".join(
        f'<span class="evo-legend-item"><span class="evo-legend-swatch" '
        f'style="background:{c}"></span>{_esc(t)}</span>'
        for t, c in _TONE_COLORS.items()
        if any(e.tone == t for e in emotions)
    )
    return (
        '<div class="cloud-hint">每个点是一首歌（基于 AI 批注的逐行情绪均值）'
        '· 点击任意歌曲直接播放 · 拥挤处的歌名悬停圆点可见</div>'
        f'<div class="evo-legend">{legend}</div>'
        f'<svg viewBox="0 0 {_EMO_W} {_EMO_H}" class="egg-svg" role="img">'
        + "".join(parts) + '</svg>'
    )


