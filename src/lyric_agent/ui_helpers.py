"""UI helpers: song discovery, per-song caches/persistence and all the
pure HTML renderers. Split out of ui.py — no gradio dependency here, so
every function stays unit-testable in isolation."""

from __future__ import annotations

import re
import json
import logging
from pathlib import Path
from typing import Any

from .annotator.models import Song
from .audio_provider import resolve as resolve_audio
from .debate import DebateSession
from .lrc_parser import load_lrc_file

logger = logging.getLogger(__name__)


_CHAT_HINT = ""
_CHAT_TOPIC_DEFAULT = '<div class="chat-topic dim">尚未选择歌词行</div>'
_NO_AUDIO_HINT = (
    "🎧 未检测到音频 — 当前为纯阅读模式。将 audio.mp3 放入歌曲目录即可启用播放同步。"
)


from .evidence import esc_html as _esc  # noqa: E402 — 渲染共用转义


# ── Song loading ──────────────────────────────────────────

_SONG_CJK_CACHE: dict[str, bool] = {}


def song_is_cjk(song_dir: str | Path) -> bool:
    """这首歌是不是中文歌：取歌词前 30 行，过半数行 CJK 占比 >30% 判中文。
    产品定位是英文歌学英语，中文歌默认隐藏（LL_SHOW_CJK=1 可恢复）。"""
    key = str(song_dir)
    if key in _SONG_CJK_CACHE:
        return _SONG_CJK_CACHE[key]
    from .intertextuality.search import is_cjk_text
    from .lrc_parser import parse_lrc
    try:
        _, timed = parse_lrc((Path(song_dir) / "lyrics.lrc")
                             .read_text(encoding="utf-8"))
        lines = [ln.text for ln in timed[:30] if ln.text.strip()]
        result = bool(lines) and (
            sum(is_cjk_text(ln) for ln in lines) / len(lines) > 0.5)
    except Exception:
        result = False
    _SONG_CJK_CACHE[key] = result
    return result


def _discover_songs(songs_dir: str,
                    exclude_sources: set[str] | None = None,
                    exclude_cjk: bool = False) -> list[dict[str, Any]]:
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
        if exclude_cjk and song_is_cjk(d):
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
            # bound bilibili video for the 📺 video playback mode
            "bvid": meta.get("bvid", ""),
            "bvid_no_auto": bool(meta.get("bvid_no_auto")),
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
    """内置曲库（英文歌定位：默认滤掉中文条目，LL_SHOW_CJK=1 恢复）。"""
    import os
    import re as _re
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                if os.getenv("LL_SHOW_CJK", "") != "1":
                    cjk = _re.compile(r"[一-鿿]")
                    data = [c for c in data
                            if not cjk.search(str(c.get("title", ""))
                                              + str(c.get("artist", "")))]
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
        return ""
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
_INTRO_EMPTY = ""


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

_FAVORITES_PATH = Path("data/favorites.json")


def _fav_id(line: str, title: str) -> str:
    """Stable identity for a favorite (favorites dedup on line+title), so
    delete/jump match by id and never drift with list position."""
    import hashlib
    return hashlib.md5(
        f"{line}\x00{title}".encode("utf-8")).hexdigest()[:12]


def _load_favorites() -> list[dict]:
    try:
        if _FAVORITES_PATH.exists():
            data = json.loads(_FAVORITES_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            # backfill ids for entries written before ids existed
            for f in data:
                if isinstance(f, dict) and not f.get("id"):
                    f["id"] = _fav_id(f.get("line", ""), f.get("title", ""))
            return data
    except (OSError, ValueError):
        logger.exception("Failed reading favorites")
    return []


def _save_favorites(favs: list[dict]) -> None:
    try:
        _FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FAVORITES_PATH.write_text(
            json.dumps(favs, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.exception("Failed saving favorites")


_OVERVIEW_CSS = """
.ov-head { font-size: 20px; font-weight: 800; color: var(--text-primary);
  margin: 2px 0 2px; }
.ov-sub { font-size: 13px; color: var(--text-secondary); margin-bottom: 14px; }
.ov-tiles { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
.ov-tile { flex: 1 1 110px; padding: 12px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); text-align: center; }
.ov-tile-num { font-size: 24px; font-weight: 800; color: var(--accent);
  line-height: 1.1; }
.ov-tile-label { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.ov-section-title { font-size: 13px; font-weight: 700; color: var(--text-primary);
  margin: 6px 0 8px; }
.ov-imagery { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: baseline;
  margin-bottom: 16px; }
.ov-word { color: var(--accent); line-height: 1.1; }
.ov-word .ov-word-n { font-size: 11px; color: var(--text-secondary);
  margin-left: 2px; }
.ov-albums { display: flex; flex-direction: column; gap: 10px; }
.ov-album { padding: 12px 16px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); }
.ov-album-name { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.ov-album-meta { font-size: 12px; color: var(--text-secondary);
  margin: 2px 0 8px; }
.ov-songs { display: flex; flex-wrap: wrap; gap: 6px; }
.ov-song { font-size: 12px; padding: 3px 10px; border-radius: 100px;
  background: var(--bg-primary); border: 1px solid var(--border);
  color: var(--text-primary); cursor: pointer; }
.ov-song:hover { border-color: var(--accent); color: var(--accent); }
.ov-themes { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.ov-theme { font-size: 11px; padding: 2px 8px; border-radius: 100px;
  background: var(--accent-soft); color: var(--accent); }
"""


def render_artist_overview(songs: list, artist: str) -> str:
    """Artist-agnostic overview: stat tiles + top imagery words (from the
    artist's lyrics) + albums with per-album line counts. Works for every
    artist — unlike the Taylor-only era timeline — with no LLM cost, and
    enriches itself from lyrics that already exist on disk."""
    from .insights import word_frequencies
    from .intertextuality.search import artist_matches
    from .lrc_parser import load_lrc_file

    mine = ([s for s in songs
             if artist and artist_matches(artist, s.get("artist", ""))]
            if artist else [])
    if not mine:
        return ('<div class="chat-empty">这位歌手暂无歌曲。</div>')

    albums: dict[str, list] = {}
    album_lines: dict[str, int] = {}
    total_lines = 0
    freq_input: list = []
    for s in mine:
        album = s.get("album") or "未知专辑"
        albums.setdefault(album, []).append(s)
        try:
            _m, timed = load_lrc_file(str(Path(s["dir"]) / "lyrics.lrc"))
        except Exception:
            timed = []
        album_lines[album] = album_lines.get(album, 0) + len(timed)
        total_lines += len(timed)
        freq_input.extend((ln.text, artist) for ln in timed)

    top_words = word_frequencies(freq_input, artist, top_n=14)
    imagery = ""
    if top_words:
        chips = "".join(
            f'<span class="ov-word">{_esc(w)}'
            f'<span class="ov-word-n">·{n}</span></span>'
            for w, n in top_words)
        imagery = (
            '<div class="ov-section-title">🔑 高频意象（来自歌词）</div>'
            f'<div class="ov-imagery">{chips}</div>')

    tiles = (
        '<div class="ov-tiles">'
        f'<div class="ov-tile"><div class="ov-tile-num">{len(mine)}</div>'
        '<div class="ov-tile-label">歌曲</div></div>'
        f'<div class="ov-tile"><div class="ov-tile-num">{len(albums)}</div>'
        '<div class="ov-tile-label">专辑</div></div>'
        f'<div class="ov-tile"><div class="ov-tile-num">{total_lines}</div>'
        '<div class="ov-tile-label">歌词行</div></div>'
        '</div>')

    cards = []
    for album, items in sorted(albums.items(),
                               key=lambda kv: (-len(kv[1]), kv[0])):
        # data-ov-pick jumps to the song on the play tab (on_overview_pick)
        song_html = "".join(
            f'<span class="ov-song" data-ov-pick="{_esc(s.get("title", ""))}"'
            f' title="在播放解读里打开">{_esc(s.get("title", ""))}</span>'
            for s in items)
        lines = album_lines.get(album, 0)
        meta = f"{len(items)} 首" + (f" · {lines} 行歌词" if lines else "")
        cards.append(
            f'<div class="ov-album"><div class="ov-album-name">'
            f'💿 {_esc(album)}</div>'
            f'<div class="ov-album-meta">{meta}</div>'
            f'<div class="ov-songs">{song_html}</div></div>')
    return (
        f'<div class="ov-head">🎤 {_esc(artist)}</div>'
        f'<div class="ov-sub">点任意歌曲在「🎧 播放解读」里打开。</div>'
        + tiles + imagery
        + '<div class="ov-section-title">💿 专辑</div>'
        + f'<div class="ov-albums">{"".join(cards)}</div>')


def _render_favorites(favs: list[dict], song_title: str | None = None) -> str:
    """Favorites panel. With song_title, only that song's entries show —
    收藏跟随当前打开的歌曲。"""
    if song_title is not None:
        favs = [f for f in favs if f.get("title", "") == song_title]
    if not favs:
        return ""
    def _jump_attr(f: dict, fid: str) -> str:
        # exact-line jump (cite pipeline) when the entry knows its line;
        # legacy entries fall back to the song-level jump
        if f.get("line_index", -1) >= 0 and f.get("title"):
            return (f'data-cite-label="{_esc(f["title"])}" '
                    f'data-cite-line="{f["line_index"]}"')
        return f'data-fav="jump:{_esc(fid)}"'

    items = "".join(
        f'<div class="fav-item" {_jump_attr(f, fid)} '
        f'title="点击打开《{_esc(f.get("title", ""))}》并定位到这句">'
        f'<div class="fav-line">“{_esc(f.get("line", ""))}”</div>'
        f'<div class="fav-song">——《{_esc(f.get("title", ""))}》'
        f'<span class="fav-del" data-fav="del:{_esc(fid)}" '
        f'title="移除">✖</span>'
        f'</div></div>'
        for f in favs
        for fid in [f.get("id") or _fav_id(f.get("line", ""),
                                           f.get("title", ""))])
    return f'<div class="fav-list">{items}</div>'


def _file_url(path: str | Path) -> str:
    return "/gradio_api/file=" + str(Path(path).resolve()).replace("\\", "/")


def _player_tools(song_info: dict, chorus_ts: int | None) -> str:
    """Chorus jump, A-B loop, rhyme/echo toggles (wired up in _HEAD_JS)."""
    chorus = (f'<button class="ptool" data-seek="{chorus_ts}" '
              'title="跳到检测出的副歌位置">⏩ 副歌</button>'
              if chorus_ts is not None else "")
    return (
        '<div class="player-tools">'
        + chorus +
        '<label class="ptool-toggle" title="同韵脚的歌词行标同色圆点">'
        '<input type="checkbox" id="ll-rhyme-toggle"> 🎯 韵脚</label>'
        '</div>'
    )


_BV_NOTE = ''


def _render_video_html(song_info: dict, has_audio: bool,
                       public: bool) -> str:
    """📺 B 站视频区：官方嵌入播放器 + 绑定/候选 UI（非公开）。"""
    from .bilibili import embed_url
    bvid = song_info.get("bvid", "")
    unbind = ('<button class="ptool" data-bvid-unbind="1" '
              'title="删除绑定并重新选择视频">🗑 换一个视频</button>'
              if not public else "")
    parts = []
    if bvid:
        if has_audio:
            # video always shown alongside the audio player (user choice);
            # the 📺 button only collapses/expands it
            parts.append(
                '<button class="ptool" data-video-toggle="1">'
                '📺 收起/展开 MV</button>' + unbind +
                f'<div class="bv-frame" '
                f'data-embed="{_esc(embed_url(bvid))}">'
                f'<iframe allowfullscreen scrolling="no" frameborder="0" '
                f'src="{_esc(embed_url(bvid))}"></iframe></div>')
        else:
            parts.append(
                f'<div class="bv-frame" data-embed="{_esc(embed_url(bvid))}">'
                f'<iframe allowfullscreen scrolling="no" frameborder="0" '
                f'src="{_esc(embed_url(bvid))}"></iframe></div>'
                + _BV_NOTE + unbind)
    elif not public:
        parts.append(
            '<div class="bv-bind"><button class="ptool" '
            'data-bvid-search="1">🔍 搜索 B 站 MV</button>'
            '<span class="bv-bind-hint">或在下方「📺 关联 B 站视频」'
            '手风琴里粘 BV 号</span></div>')
        cands = sorted(song_info.get("bvid_cands", []),
                       key=lambda c: c.get("play", 0), reverse=True)
        for c in cands:
            play = c.get("play", 0)
            play_s = (f"{play / 10000:.1f}万" if play >= 10000
                      else str(play)) + "播放"
            parts.append(
                f'<div class="bv-cand" data-bvid-pick="{_esc(c["bvid"])}">'
                f'<b>{_esc(c["title"])}</b>'
                f'<span class="bv-cand-meta">▶ {play_s} · '
                f'UP主 {_esc(c["author"])} · '
                f'{_esc(c["duration"])} · {_esc(c["bvid"])}'
                '（点击绑定）</span></div>')
    return "".join(parts)


def _render_audio_html(song_info: dict, chorus_ts: int | None = None,
                       public: bool = False) -> str:
    a_type, src = song_info["audio_type"], song_info["audio_src"]
    offset = song_info.get("audio_offset_ms", 0)
    hint = ""
    if a_type not in ("local", "url"):
        video = _render_video_html(song_info, has_audio=False,
                                   public=public)
        if song_info.get("bvid"):
            return video  # bound video replaces the no-audio banner
        return f'<div class="no-audio-hint">{_NO_AUDIO_HINT}</div>' + video
    url = _file_url(src) if a_type == "local" else src
    return (
        '<div id="ll-wave" title="波形加载中（需联网加载 wavesurfer）"></div>'
        f'<audio id="ll-audio" controls preload="metadata" '
        f'data-offset="{offset}" '
        f'src="{_esc(url)}" style="width:100%"></audio>'
        + _player_tools(song_info, chorus_ts) + hint
        + _render_video_html(song_info, has_audio=True, public=public)
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
    """Whole-song echo overview: a hero "你可能没注意到" pick on top, the
    full list folded below.

    hits: (TimedLine, EchoLine) pairs; each entry is clickable and jumps to
    the lyric line (data-goto-line is handled in _HEAD_JS).
    """
    if not hits:
        return _ECHO_OVERVIEW_EMPTY

    def _item(ln, e, extra_cls="", label=""):
        album = f" · {_esc(e.album)}" if e.album else ""
        return (
            f'<div class="echo-ov-item{extra_cls}" '
            f'data-goto-line="{ln.line_index}" title="点击跳转到这句歌词">'
            f'{label}'
            f'<div class="echo-ov-src">“{_esc(ln.text)}”</div>'
            f'<div class="echo-ov-dst">↔ 《{_esc(e.song)}》{album}：'
            f'“{_esc(e.line)}”<span class="echo-ov-sim">{e.similarity}</span>'
            '</div></div>')

    # 最强的一处呼应置顶（"哇"时刻），其余折叠备查
    best = max(hits, key=lambda p: p[1].similarity)
    hero = _item(best[0], best[1], " echo-hero",
                 '<div class="echo-hero-head">👀 你可能没注意到</div>')
    rest = [_item(ln, e) for ln, e in hits if (ln, e) != best]
    folded = ""
    if rest:
        folded = (f'<details class="echo-ov-more"><summary>展开全部 '
                  f'{len(hits)} 处与{_esc(artist or "同歌手")}'
                  '其他作品的呼应</summary>'
                  + "".join(rest) + "</details>")
    return f'<div class="echo-ov-list">{hero}{folded}</div>'


def load_translation(song_dir: str) -> dict[int, str]:
    """data/songs/<歌>/translation.json → {line_index: 中文}；无则 {}。"""
    p = Path(song_dir) / "translation.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.get("lines", {}).items() if v}
    except (OSError, ValueError):
        return {}


def _render_lyrics_html(song_data: dict, song_info: dict,
                        public: bool = False,
                        show_trans: bool = False) -> str:
    lines = song_data["timed_lines"]
    trans = (load_translation(song_info["dir"])
             if show_trans and song_info.get("dir") else {})

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
        zh = trans.get(ln.line_index, "")
        zh_html = (f'<div class="lyric-trans">{_esc(zh)}</div>' if zh else "")
        parts.append(
            f'<div class="lyric-line" data-index="{ln.line_index}" '
            f'data-ts="{ln.timestamp_ms}">'
            f'<span class="lyric-text">{_esc(ln.text)}</span>{mark}'
            f'{zh_html}</div>'
        )

    return (
        header_html
        + _render_audio_html(song_info, song_data.get("chorus_ts"),
                             public=public)
        + f'<div id="lyrics-container"><div id="lyrics-scroll">{"".join(parts)}</div></div>'
    )


def render_wordbook(entries: list[dict],
                    song_title: str | None = None) -> str:
    """📒 单词本 panel. With song_title, only words collected from that
    song show — 单词本跟随当前打开的歌曲。"""
    if song_title is not None:
        entries = [e for e in entries if e.get("song", "") == song_title]
    if not entries:
        return ""
    items = []
    for e in entries:
        word = e.get("word", "")
        phon = e.get("phonetic", "")
        # ECDICT translations use a literal backslash-n separator
        meaning = (e.get("translation", "") or "").replace("\\n", "；")
        if len(meaning) > 90:
            meaning = meaning[:90] + "…"
        src = e.get("line", "")
        phon_html = (f'<span class="wb-phon">/{_esc(phon)}/</span>'
                     if phon else "")
        if src and e.get("line_index", -1) >= 0 and e.get("label"):
            src_html = (f'<div class="wb-src wb-jump" '
                        f'data-cite-label="{_esc(e.get("song", ""))}" '
                        f'data-cite-line="{e["line_index"]}" '
                        f'title="点击跳到这句歌词">「{_esc(src)}」</div>')
        elif src:
            src_html = f'<div class="wb-src">「{_esc(src)}」</div>'
        else:
            src_html = ""
        ai = (e.get("ai", "") or "").strip()
        ai_html = (f'<div class="wb-ai">✨ {_esc(ai)}</div>'.replace(
            "\n", "<br>") if ai else "")
        note = (e.get("note", "") or "").strip()
        note_html = (f'<div class="wb-note">📝 {_esc(note)}</div>'
                     if note else "")
        items.append(
            f'<div class="wb-item">'
            f'<span class="wb-del" data-wb="del:{_esc(word)}" '
            f'title="移出单词本">✕</span>'
            f'<span class="wb-note-btn" data-wb-note="{_esc(word)}" '
            f'data-note="{_esc(note)}" title="写/改我的笔记">📝</span>'
            f'<div class="wb-word">{_esc(word)} {phon_html}</div>'
            f'<div class="wb-meaning">{_esc(meaning)}</div>'
            f'{src_html}{note_html}{ai_html}</div>'
        )
    return f'<div class="wb-list">{"".join(items)}</div>'


_ANN_HINT = ('<div class="chat-empty">点一句歌词，这里展示它的'
             ' AI 批注。</div>')

_ANN_ROWS = [  # (attr, emoji, label)
    ("metaphor_analysis", "🎭", "修辞"),
    ("allusions", "📜", "用典"),
    ("wordplay", "🃏", "文字游戏"),
    ("cultural_context", "🌍", "文化背景"),
    ("taylor_swift_context", "📀", "创作背景"),
]


def render_annotation_card(ann, line_index: int,
                           can_generate: bool) -> str:
    """点句后的批注卡。ann 为 None 时给空态——非公开模式附一个需要用户
    点击确认的「生成本句批注」按钮（按钮即授权，不点永不调 LLM）。"""
    if ann is None or not getattr(ann, "summary", ""):
        btn = (f'<button class="dict-btn" data-gen-ann="{line_index}">'
               '✨ 为本句生成 AI 批注（调用 1 次 LLM）</button>'
               if can_generate else "")
        return (f'<div class="ann-card ann-empty">这句还没有 AI 批注。'
                f'{btn}</div>')
    parts = [f'<div class="ann-card">'
             f'<div class="ann-summary">📖 {_esc(ann.summary)}</div>']
    for attr, emoji, label in _ANN_ROWS:
        v = getattr(ann, attr, None)
        if v:
            parts.append(f'<div class="ann-row">{emoji} '
                         f'<b>{label}</b> {_esc(v)}</div>')
    tone = getattr(ann, "emotional_tone", "") or ""
    if tone and tone != "unknown":
        parts.append(f'<div class="ann-row">💗 <b>情绪</b> {_esc(tone)}</div>')
    related = getattr(ann, "related_lines", None) or []
    for r in related[:2]:
        song = getattr(r, "song", "") or ""
        line = getattr(r, "line", "") or ""
        if song and line:
            parts.append(f'<div class="ann-row ann-rel">🔗 '
                         f'《{_esc(song)}》“{_esc(line)}”</div>')
    parts.append('</div>')
    return "".join(parts)


def _mask_word(text: str, word: str) -> str:
    """Escape text and wrap each occurrence of word in the blind-mode mask
    span (tp-wline-word) so blind practice never leaks the answer."""
    return re.sub(re.escape(_esc(word)),
                  lambda m: f'<span class="tp-wline-word">{m.group(0)}'
                            '</span>',
                  _esc(text), flags=re.IGNORECASE)


def render_practice_card(entry: dict, mp3_url: str, nonce: str,
                         examples: list[str] | None = None) -> str:
    """⌨️ 单词练习 card. The JS keystroke loop (ui_assets) reads data-word /
    data-mp3 / data-nonce and colors the .tp-ch spans; the hidden input
    receives focus so the player's space/arrow shortcuts stay exempt.

    examples: 零 LLM 真例句（词典 API/曲库，review.word_examples）。"""
    word = entry.get("word", "")
    chars = "".join(
        ('<span class="tp-ch tp-space" data-ch=" ">&nbsp;</span>'
         if c == " " else
         f'<span class="tp-ch" data-ch="{_esc(c.lower())}">{_esc(c)}</span>')
        for c in word)
    phon = entry.get("phonetic", "")
    phon_html = f'<span class="wb-phon">/{_esc(phon)}/</span>' if phon else ""
    say = ('<button class="ptool" data-ll-say="1" title="重播发音">🔊</button>'
           if mp3_url else "")
    eye = ('<button class="ptool" data-tp-eye="1" '
           'title="切换 显示单词 / 盲打模式">👁</button>')
    meaning = (entry.get("translation", "") or "").replace("\\n", "；")
    rows = []
    if meaning:
        rows.append(f'<div class="wb-meaning">{_esc(meaning)}</div>')
    if entry.get("line"):
        # 目标单词嵌在原句里高亮；盲打模式下由 CSS 遮住
        src = _mask_word(entry["line"], word)
        # 条目带定位信息时整行可点：跳到那首歌的那一句（JS 委托）
        song = entry.get("song", "")
        line_idx = entry.get("line_index", -1)
        jump = (f' data-tp-jump="{_esc(song)}" data-tp-line="{line_idx}" '
                'title="点击去歌里听这句"'
                if song and line_idx >= 0 else "")
        rows.append(f'<div class="wb-src"{jump}>「{src}」'
                    f'·《{_esc(entry.get("song", ""))}》</div>')
    ai = (entry.get("ai", "") or "").strip()
    if ai:
        rows.append(f'<div class="wb-ai">✨ {_esc(ai)}</div>'.replace(
            "\n", "<br>"))
    return (  # 默认盲打（tp-blind 烘焙进首帧，杜绝"闪现全词"）；
        # 用户点 👁 或 localStorage 记忆为显示时由 JS 摘除
        f'<div class="ll-type-card tp-blind" '
        f'data-word="{_esc(word.lower())}" '
        f'data-mp3="{_esc(mp3_url)}" data-nonce="{_esc(nonce)}">'
        f'<div class="tp-word">{chars} {phon_html} {say} {eye}</div>'
        f'<input class="ll-type-input" autocomplete="off" '
        f'autocapitalize="off" spellcheck="false">'
        f'<div class="tp-ime-hint">请切换到英文输入法</div>'
        f'<div class="tp-donehint">🎉 完成！按 Enter 下一个词</div>'
        f'{"".join(rows)}'
        f'</div>'
        + ((
            '<div class="ll-example-card">'
            + "".join(f'<div class="wb-example">📚 {_mask_word(ex, word)}'
                      '</div>' for ex in examples[:3])
            + '</div>') if examples else ''))


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
        f'<div class="cloud-hint">每个点是一首歌（基于 AI 批注的逐行'
        f'情绪均值）· 点击任意歌曲直接播放 · 拥挤处的歌名悬停圆点可见。'
        f'<br>当前仅 {len(emotions)} 首已有 AI 批注才会在此出现；'
        f'到「⚙️ 设置 → 🧠」重建或用 <code>lyric-agent generate-all</code> '
        f'批注更多歌后，这里会更丰富。</div>'
        f'<div class="evo-legend">{legend}</div>'
        f'<svg viewBox="0 0 {_EMO_W} {_EMO_H}" class="egg-svg" role="img">'
        + "".join(parts) + '</svg>'
    )




# 跨模块共享 API（ui.py / mcp_server.py / cli.py 共用）——公开名
discover_songs = _discover_songs
load_song_data = _load_song_data
