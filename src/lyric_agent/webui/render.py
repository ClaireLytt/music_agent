"""渲染层：ui_helpers 拆出的全部纯 HTML renderers 及其专属常量。
数据由 ..songdata 提供；本模块不 import webui.runtime 或任何 tab 模块，
无 gradio 依赖，每个函数可独立单测。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..debate import DebateSession
from ..songdata import _fav_id, load_translation

_CHAT_HINT = ""
_CHAT_TOPIC_DEFAULT = '<div class="chat-topic dim">尚未选择歌词行</div>'
_NO_AUDIO_HINT = (
    "🎧 未检测到音频 — 当前为纯阅读模式。在当前页面的设置中放入歌曲 mp3 "
    "文件即可启用播放同步。"
)


from ..evidence import esc_html as _esc  # noqa: E402 — 渲染共用转义


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


_INTRO_EMPTY = ""


def _render_intro(text: str) -> str:
    if not text:
        return _INTRO_EMPTY
    return f'<div class="song-intro">{_esc(text)}</div>'


# ── HTML renderers ────────────────────────────────────────

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
    from ..insights import word_frequencies
    from ..intertextuality.search import artist_matches
    from ..lrc_parser import load_lrc_file

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


def _render_video_html(song_info: dict, public: bool) -> str:
    """📺 B 站视频区：官方嵌入播放器 + 绑定/候选 UI（非公开）。"""
    from ..bilibili import embed_url
    bvid = song_info.get("bvid", "")
    unbind = ('<button class="ptool" data-bvid-unbind="1" '
              'title="删除绑定并重新选择视频">🗑 换一个视频</button>'
              if not public else "")
    parts = []
    if bvid:
        # video collapsed by default for every song (inline style — the 📺
        # toggle JS reads/writes style.display, so the default must live
        # inline)
        parts.append(
            '<button class="ptool" data-video-toggle="1">'
            '📺 收起/展开 MV</button>' + unbind +
            f'<div class="bv-frame" style="display:none" '
            f'data-embed="{_esc(embed_url(bvid))}">'
            f'<iframe allowfullscreen scrolling="no" frameborder="0" '
            f'src="{_esc(embed_url(bvid))}"></iframe></div>')
    elif not public:
        parts.append(
            '<div class="bv-bind"><button class="ptool" '
            'data-bvid-search="1">🔍 搜索 B 站 MV</button>'
            '<span class="bv-bind-hint">或在当前设置「📺 关联 B 站视频」'
            '里粘贴链接</span></div>')
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


def _render_audio_html(song_info: dict, public: bool = False) -> str:
    a_type, src = song_info["audio_type"], song_info["audio_src"]
    offset = song_info.get("audio_offset_ms", 0)
    hint = ""
    if a_type not in ("local", "url"):
        video = _render_video_html(song_info, public=public)
        # 无音频时提示常驻 —— 绑没绑 MV 都显示
        return f'<div class="no-audio-hint">{_NO_AUDIO_HINT}</div>' + video
    url = _file_url(src) if a_type == "local" else src
    return (
        f'<audio id="ll-audio" controls preload="metadata" '
        f'controlslist="nodownload noplaybackrate" '
        f'data-offset="{offset}" '
        f'src="{_esc(url)}" style="width:100%"></audio>'
        + hint
        + _render_video_html(song_info, public=public)
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
  <div class="song-cover" aria-hidden="true">♪</div>
  <div>
    <h2 class="song-title-display">{_esc(song_info["title"])}</h2>
    <p class="song-meta-display">{_esc(meta_text)}</p>
  </div>
</div>"""

    parts = []
    for ln in lines:
        zh = trans.get(ln.line_index, "")
        zh_html = (f'<div class="lyric-trans">{_esc(zh)}</div>' if zh else "")
        parts.append(
            f'<div class="lyric-line" data-index="{ln.line_index}" '
            f'data-ts="{ln.timestamp_ms}">'
            f'<span class="lyric-text">{_esc(ln.text)}</span>'
            f'{zh_html}</div>'
        )

    return (
        header_html
        + _render_audio_html(song_info, public=public)
        + f'<div id="lyrics-container"><div id="lyrics-scroll">{"".join(parts)}</div></div>'
    )


def render_wordbook(entries: list[dict],
                    song_title: str | None = None,
                    phrases: bool = False) -> str:
    """📒 单词本 panel. With song_title, only words collected from that
    song show — 单词本跟随当前打开的歌曲。phrases=True 只显示多词词组
    （含空格，与练习范围「🧩 词组」同口径），False 只显示单词。"""
    if song_title is not None:
        entries = [e for e in entries if e.get("song", "") == song_title]
    from ..dictionary import is_phrase
    entries = [e for e in entries
               if is_phrase(e.get("word", "")) == phrases]
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




def _heatmap_html(series: list[tuple[str, int]], title: str,
                  unit: str) -> str:
    """GitHub 风格年历热力图（仿 qwerty-learner 的 ActivityCalendar，
    纯 HTML/CSS），横向排布：列 = 周，行 = 星期（GitHub 原版方向）。
    series 来自 stats.year_series：周日对齐的逐日计数。"""
    mx = max((c for _, c in series), default=0)
    weeks: list[list[tuple[str, int]]] = [
        series[i:i + 7] for i in range(0, len(series), 7)]
    months = "一 二 三 四 五 六 七 八 九 十 十一 十二".split()
    cols = []
    last_m = ""
    for wk in weeks:
        m = months[int(wk[0][0][5:7]) - 1] + "月"
        label = m if m != last_m else ""
        last_m = m
        cells = "".join(
            f'<i class="hm-c l{0 if not c else min(4, 1 + c * 4 // (mx + 1))}"'
            f' title="{d} {unit} {c} 次"></i>' for d, c in wk)
        cols.append(f'<div class="hm-week" data-m="{label}">{cells}</div>')
    wd = "".join(f"<i>{w}</i>" for w in ("日", "一", "二", "三", "四", "五", "六"))
    return (
        '<div class="hm-chart">'
        f'<div class="hm-title">{_esc(title)}</div>'
        f'<div class="hm-grid"><div class="hm-wd">{wd}</div>{"".join(cols)}</div>'
        '</div>')


def _stat_details(label: str, words: list[dict]) -> str:
    """概览数字做成可展开的 <details>：点击弹出具体词汇列表。"""
    chips = "".join(
        f'<span class="hm-chip" title="{_esc(e.get("translation", ""))}">'
        f'{_esc(e.get("word", ""))}</span>' for e in words) or \
        '<span class="hm-chip-none">（暂无）</span>'
    return (f'<details class="hm-stat"><summary><b>{len(words)}</b>'
            f' {label}</summary><div class="hm-words">{chips}</div></details>')


def render_analysis(book: list[dict]) -> str:
    """「📊 数据分析」全屏页：只有概览数字 + 两张竖向年度热力图
    （对应 qwerty-learner Analysis 页的两张 HeatmapCharts），✕ 关闭。"""
    from ..review import is_mastered, weak_words
    from ..stats import backfill_from_wordbook, year_series

    stats = backfill_from_wordbook(book)
    practice = year_series(stats, "practice")
    collect = year_series(stats, "collect")
    # 与 review.book_stats 同一口径，但这里要具体词条列表而非计数
    practiced = [e for e in book
                 if (e.get("review") or {}).get("correct", 0)
                 + (e.get("review") or {}).get("wrong", 0) > 0]
    mastered = [e for e in book if is_mastered(e)]
    weak = weak_words(book)
    close = ('<span class="hm-close" title="关闭" '
             'onclick="this.closest(\'.hm-overlay\').remove()">✕</span>')
    help_btn = (
        '<details class="hm-help"><summary title="口径说明">❓</summary>'
        '<div class="hm-help-pop">'
        '<b>一次练习</b><br>从单词卡出现到把词完整打完算 1 次；'
        '中途打错任何键被要求重来，这 1 次就记为「错误的一次」。<br><br>'
        '<b>已掌握</b><br>盲打（遮住字母）、全程不按 Tab 提示、'
        '零击键错误一次打完，算 1 次干净通过；累计 ≥ 3 次即已掌握。<br><br>'
        '<b>弱点词</b><br>只统计盲打：错误的练习 ≥ 3 次才入表。'
        'Tab 列 = 提示次数；错误率 = 错误次数 ÷ 练习次数。<br><br>'
        '<b>收藏 / 已练习</b><br>收藏 = 单词本全部词条；'
        '已练习 = 至少完整打完过一次（盲打与否都算）。'
        '</div></details>')
    if not any(c for _, c in practice) and not any(c for _, c in collect):
        body = '<div class="hm-empty">还没有练习数据——去打几个词再来看看 📊</div>'
    else:
        wk_rows = "".join(
            f'<tr><td class="hm-wk-w">{_esc(w["word"])}</td>'
            f'<td>{w["attempts"]}</td><td>{w["wrong"]}</td>'
            f'<td>{w["peek"]}</td><td>{round(w["rate"] * 100)}%</td></tr>'
            for w in weak)
        # 「错误」列可点排序（降/升切换）；表格在 gr.HTML 里，用内联
        # handler 原地重排行（行数据都在 DOM 里，无需回后端）
        sort_js = (
            "(function(t){const tb=t.closest('table');"
            "const rows=[].slice.call(tb.querySelectorAll('tr'),1);"
            "const asc=tb.dataset.asc==='1';tb.dataset.asc=asc?'0':'1';"
            "rows.sort(function(a,b){return (+a.cells[2].textContent"
            "-+b.cells[2].textContent)*(asc?1:-1);});"
            "rows.forEach(function(r){tb.appendChild(r);});"
            "t.querySelector('.hm-sort').textContent=asc?'↑':'↓';})(this)")
        wk_table = (
            '<table class="hm-wk"><tr><th>单词</th><th>练习</th>'
            f'<th class="hm-th-sort" onclick="{sort_js}" '
            'title="按错误次数排序">错误 <span class="hm-sort">⇅</span></th>'
            '<th>Tab</th><th>错误率</th></tr>'
            + wk_rows + '</table>') if weak else \
            '<div class="hm-chip-none">还没有错 3 次以上的盲打词 🎉</div>'
        weak_entry = (f'<details class="hm-stat"><summary><b>{len(weak)}</b>'
                      f' 弱点词</summary><div class="hm-words hm-wk-box">'
                      f'{wk_table}</div></details>')
        nums = ('<div class="hm-nums">'
                + _stat_details("收藏", book)
                + _stat_details("已练习", practiced)
                + _stat_details("已掌握", mastered)
                + weak_entry
                + '</div>')
        body = (nums + '<div class="hm-charts">'
                + _heatmap_html(practice, "过去一年练习次数热力图", "练习")
                + _heatmap_html(collect, "过去一年收藏单词热力图", "收藏")
                + '</div>')
    return ('<div class="hm-overlay"><div class="hm-sheet">'
            f'<div class="hm-page-title">📊 数据分析{close}{help_btn}</div>'
            + body + '</div></div>')
