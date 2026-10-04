"""Gradio UI — 歌词透镜 Lyric Lens（简体中文，极简私人版）.

页签 1  🎧 播放解读 — 同步歌词、点一句歌词、右侧问 AI 助手
页签 2  🗺️ 艺术家图谱 — 艺术家演化地图
页签 3  🥚 彩蛋地图 — 同歌手全曲库歌词互文网络图（含意象追踪）
页签 4  📊 曲库洞察 — 每日一句 / 词云 / 情绪地图 / 歌单故事线
页签 5  🎮 互动   — 歌词竞猜 / 歌名拼图 / 单词练习
页签 6  ➕ 添加歌曲 — 用户自行添加歌曲（LRC + 元数据 + 可选音频）

All JavaScript lives in gr.Blocks(head=...) because Gradio 6 injects
gr.HTML content via innerHTML (embedded <script> tags do not execute).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
import time
from pathlib import Path
from typing import Any

import gradio as gr

from dataclasses import replace

from .audio_provider import resolve as resolve_audio
from .config import (
    HACKATHON_PLAYLIST_SOURCE,
    Settings,
    default_model_for,
    save_user_settings,
)
from .debate import DebateSession, speak as ai_speak
from .dictionary import (add_word, load_wordbook, lookup as dict_lookup,
                         remove_word)
from .archaeology import mine_motifs
from .evidence import QuoteIndex, parse_claims, render_evidence_card
from .ui_helpers import (_ANN_HINT, _file_url, render_annotation_card,
                         render_practice_card, render_wordbook)
from .lrc_parser import parse_lrc
from .search import LyricsSearcher

try:
    from .intertextuality.echo_map import ECHO_MAP_CSS
except ImportError:  # embeddings extra not installed — tab shows a hint instead
    ECHO_MAP_CSS = ""

logger = logging.getLogger(__name__)

from .mcp_channel import MCP_COMMAND_PATH
from .ui_helpers import (  # noqa: F401 — re-exported for cli.py & handlers
    _CATALOG_PATH,
    _CHAT_HINT,
    _load_favorites,
    _render_favorites,
    _save_favorites,
    _CHAT_TOPIC_DEFAULT,
    _ECHO_HINT,
    _ECHO_NO_INDEX,
    _ECHO_OVERVIEW_EMPTY,
    _ECHO_SCAN_CACHE_DIR,
    _INTRO_EMPTY,
    _INTRO_FILENAME,
    _PLACEHOLDER_LRC,
    _SONG_DATA_CACHE,
    _chat_topic_html,
    _discover_songs,
    _esc,
    _fetch_lrc_from_lrclib,
    _load_catalog,
    _load_chat_history,
    _load_intro,
    _load_notes,
    _load_song_data,
    _render_chat,
    _render_echo_html,
    _render_echo_overview,
    _render_intro,
    _render_lyrics_html,
    _render_notes,
    _render_search_results,
    _save_chat_history,
    _save_notes,
)
from .mv_eggs import MV_CSS, MV_EMPTY
from .ui_assets import _CSS, _HEAD_JS

# ── App factory ───────────────────────────────────────────

def launch_kwargs() -> dict:
    """Style/head kwargs for app.launch() (Gradio 6 moved them off Blocks)."""
    return {
        "css": (_CSS + ECHO_MAP_CSS + MV_CSS),
        "head": _HEAD_JS,
        "theme": gr.themes.Base(primary_hue="blue", neutral_hue="slate"),
    }


def create_app(settings: Settings) -> gr.Blocks:
    ctx: dict[str, Any] = {}
    public = settings.public_mode

    def refresh_library() -> None:
        ctx.pop("overview_html", None)  # library changed -> stale overviews
        # hackathon-playlist material is licensed for offline demo only —
        # never expose it on a public deployment
        songs = _discover_songs(
            settings.songs_dir,
            exclude_sources={HACKATHON_PLAYLIST_SOURCE} if public else None)
        ctx["songs"] = songs
        searcher = LyricsSearcher(songs, model_name=settings.embedding_model,
                                  corpus_dir=settings.corpus_dir)
        ctx["searcher"] = searcher
        if songs:
            # pre-load the embedding model so the first semantic search doesn't
            # block on a ~90MB download / cold model init
            threading.Thread(target=searcher.warm_up, daemon=True).start()
        # library changes invalidate the in-library highlights on echo
        # graphs and (when no corpus is built, so the word cloud falls back
        # to library lyrics) the insights caches
        ctx.pop("echo_graphs", None)
        ctx.pop("corpus_lines", None)
        ctx.pop("clouds", None)
        # new songs may need a bilibili MV auto-bound (thread set up below;
        # indirect via ctx so the startup call above this definition is safe)
        kick = ctx.get("kick_autobind")
        if kick:
            kick()

    refresh_library()

    # ── 📺 自动绑定 B 站 MV（后台，节流，可用 BILI_AUTO_BIND=0 关闭）──
    _autobind_enabled = (os.getenv("BILI_AUTO_BIND", "1") != "0"
                         and not settings.public_mode)

    def _kick_autobind() -> None:
        if not _autobind_enabled or ctx.get("autobind_running"):
            return
        if not any(not s.get("bvid") for s in ctx["songs"]):
            return
        ctx["autobind_running"] = True

        def _run() -> None:
            try:
                from .bilibili import auto_bind_missing
                n = auto_bind_missing(list(ctx["songs"]),
                                      lambda: _autobind_enabled)
                if n:
                    refresh_library()
                    logger.info("auto-bound %d bilibili MVs", n)
            except Exception:
                logger.exception("MV auto-bind thread failed")
            finally:
                ctx["autobind_running"] = False

        threading.Thread(target=_run, daemon=True,
                         name="ll-autobind").start()

    ctx["kick_autobind"] = _kick_autobind

    def song_choice_label(s: dict) -> str:
        # titles are the identity in every handler; when two library songs
        # share a title (cross-artist covers), disambiguate with the artist
        title = s["title"]
        dup = sum(1 for o in ctx.get("songs", []) if o["title"] == title)
        return f"{title} — {s['artist']}" if dup > 1 else title

    _SORT_KEYS = {
        "added": lambda s: s["added_ts"],
        "album": lambda s: (s["album"].lower(), s["title"].lower()),
        "artist": lambda s: (s["artist"].lower(), s["title"].lower()),
    }

    def song_choices(sort: str = "added_desc") -> list[str]:
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
                ctx["echo_index"] = load_embeddings(
                    settings.corpus_dir, settings.embedding_model)
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
        # cache key: anything that changes the scan result invalidates it —
        # the song's lyrics, the corpus embeddings, model and thresholds
        lrc = Path(song_dir) / "lyrics.lrc"
        emb_file = Path(settings.corpus_dir) / "embeddings.npy"
        cache_key = [
            lrc.stat().st_mtime if lrc.exists() else 0.0,
            emb_file.stat().st_mtime if emb_file.exists() else 0.0,
            settings.embedding_model,
            settings.echo_min_similarity,
            settings.echo_min_similarity_cjk,
            "tour-v3",  # + target/note; filler-only lines dropped
        ]
        cache = ctx.setdefault("echo_maps", {})
        cached = cache.get(song_dir)
        if cached and cached[0] == cache_key:
            return cached[1], cached[2]
        # disk cache: whole-song scans cost 1-2s of model encoding each —
        # persisting them makes every restart start warm
        disk_path = _ECHO_SCAN_CACHE_DIR / f"{Path(song_dir).name}.json"
        try:
            if disk_path.exists():
                blob = json.loads(disk_path.read_text(encoding="utf-8"))
                if blob.get("key") == cache_key:
                    cache[song_dir] = (cache_key, blob["payload"],
                                       blob["overview"])
                    return blob["payload"], blob["overview"]
        except Exception:
            logger.exception("Failed reading echo scan cache %s", disk_path)
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
        from .intertextuality.echo_map import is_filler_line
        hits = [
            (ln, e) for ln, e in zip(lines, echoes)
            if e is not None and not is_filler_line(ln.text)
        ]
        anns = data["annotations"]

        def _note(i: int) -> str:
            a = anns.get(i)
            s = (a.summary or "").strip() if a else ""
            return s[:90] + "…" if len(s) > 90 else s

        payload = json.dumps({
            "song": info.get("title", ""),
            "lines": [
                {"i": ln.line_index, "song": e.song, "sim": e.similarity,
                 "target": e.line[:80], "note": _note(ln.line_index)}
                for ln, e in hits
            ],
        }, ensure_ascii=False)
        overview = _render_echo_overview(hits, info.get("artist", ""))
        cache[song_dir] = (cache_key, payload, overview)
        try:
            _ECHO_SCAN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            disk_path.write_text(json.dumps(
                {"key": cache_key, "payload": payload, "overview": overview},
                ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed writing echo scan cache %s", disk_path)
        return payload, overview

    def _warm_up() -> None:
        # the first echo query otherwise blocks 10-20s on model load; warm
        # the embedding model + corpus index in the background at startup
        try:
            _echo_index()
            from .intertextuality.search import get_model
            get_model(settings.embedding_model)
            # pre-mine motifs for the library's artists so the first
            # line-pick doesn't stall 1-3s on corpus tokenization
            index = ctx.get("echo_index")
            if index:
                motif_cache = ctx.setdefault("motifs", {})
                for artist in {s.get("artist", "") for s in ctx["songs"]}:
                    if artist and artist not in motif_cache:
                        try:
                            motif_cache[artist] = {
                                m["word"]: m["n_songs"]
                                for m in mine_motifs(index[1], artist)}
                        except Exception:
                            motif_cache[artist] = {}
            logger.info("Warm-up done: model + index + motifs ready")
        except Exception:
            logger.exception("Warm-up failed (features degrade gracefully)")
        _kick_autobind()

    threading.Thread(target=_warm_up, daemon=True,
                     name="ll-warmup").start()

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
        # backend -> JS: the login role ("admin"/"viewer"); _HEAD_JS hides
        # the management tabs for non-admins (gradio 6 ignores Tab
        # visibility updates, so this goes through the JS channel instead)
        role_box = gr.Textbox(value="", visible=True, elem_id="ll-role",
                              elem_classes=["ll-hidden"], show_label=False,
                              container=False)

        with gr.Tabs() as tabs:
            # ══ 页签 1: 播放解读 ══
            with gr.Tab("🎧 播放解读", id="play"):
                with gr.Row():
                    # ── 左栏: 歌曲 + 搜索 ──
                    with gr.Column(scale=1, min_width=230):
                        choices = song_choices()
                        # 黄金路径：默认落在主打歌《晴天》（不在库时回退第一首）
                        default_choice = next(
                            (c for c in choices
                             if c == "晴天" or c.startswith("晴天 — ")),
                            choices[0] if choices else None,
                        )
                        with gr.Accordion(
                                "🎵 歌曲列表" if choices
                                else "🎵 歌曲列表（空 — 去「添加歌曲」页签）",
                                open=True, elem_id="ll-songs-acc"):
                            with gr.Row(elem_id="ll-filter-row"):
                                song_filter = gr.Textbox(
                                    placeholder="筛选歌名 / 歌手 …",
                                    show_label=False, container=False,
                                    elem_id="ll-song-filter", scale=5)
                                filter_clear_btn = gr.Button(
                                    "✕", size="sm", scale=1, min_width=36,
                                    elem_id="ll-filter-clear")
                            song_radio = gr.Radio(
                                choices=choices,
                                show_label=False,
                                value=default_choice,
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
                            trans_btn = gr.Button(
                                "🀄 中文翻译对照（英文歌·首次生成调用 LLM，"
                                "之后永久缓存，可再点关闭）", size="sm")
                            with gr.Accordion("🎚 歌词时间校准", open=False):
                                gr.Markdown(
                                    "歌词快/慢半拍时微调（正值 = 歌词提前）。"
                                    "拖动即实时预览，满意后保存。", elem_id=None)
                                offset_slider = gr.Slider(
                                    minimum=-5000, maximum=5000, step=50,
                                    value=0, label="偏移 (ms)")
                                offset_save_btn = gr.Button("保存偏移",
                                                            size="sm")
                                offset_status = gr.Markdown("")
                            # backend -> JS: 偏移实时预览值
                            offset_box = gr.Textbox(
                                value="", visible=True,
                                elem_id="ll-offset-set",
                                elem_classes=["ll-hidden"], show_label=False,
                                container=False)
                            with gr.Accordion("📺 关联 B 站视频（BV 号/链接）",
                                              open=False):
                                bvid_input = gr.Textbox(
                                    placeholder="粘贴 BV 号或视频链接；"
                                                "留空保存 = 解绑",
                                    show_label=False, container=False)
                                bvid_save_btn = gr.Button("保存", size="sm")
                                bvid_status = gr.Markdown("")
                            # JS -> backend: 视频搜索/候选绑定
                            # ("search\t<ts>" / "pick\t<bvid>\t<ts>")
                            bvid_box = gr.Textbox(
                                value="", visible=True,
                                elem_id="ll-bvid-act",
                                elem_classes=["ll-hidden"], show_label=False,
                                container=False)
                            # delete rides the per-song ⋯ menu (JS):
                            # the menu confirms, then writes the label here
                            del_box = gr.Textbox(
                                value="", visible=True,
                                elem_id="ll-del-song",
                                elem_classes=["ll-hidden"],
                                show_label=False, container=False)
                            manage_refresh_btn = gr.Button(
                                "🔄 刷新曲库（手动增删过歌曲目录后同步）",
                                size="sm", elem_id="ll-refresh-btn")
                        sort_mode = gr.Radio(
                            choices=[
                                ("添加顺序（最早在前）", "added_asc"),
                                ("添加顺序（最新在前）", "added_desc"),
                                ("专辑（按字母排序）", "album_asc"),
                                ("歌手（按字母排序）", "artist_asc"),
                            ],
                            value="added_desc", label="🎛️ 排序")
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
                        ann_html = gr.HTML(_ANN_HINT)
                        # JS -> backend: 确认后为本句生成批注 ("<idx>	<ts>")
                        gen_ann_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-gen-ann",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        chat_topic = gr.HTML(_CHAT_TOPIC_DEFAULT)
                        chat_html = gr.HTML(_CHAT_HINT)
                        with gr.Row():
                            chat_input = gr.Textbox(
                                placeholder="针对这句歌词提问 ...",
                                show_label=False, scale=4, container=False)
                            chat_send = gr.Button("提问", scale=1, variant="primary")
                        # side panel: one flat content per icon, the
                        # icon dock sits at the BOTTOM (CSS column-reverse
                        # on #ll-side-dock)
                        with gr.Tabs(elem_id="ll-side-dock",
                                     elem_classes=["ll-icon-dock"]):
                            with gr.Tab("🥚"):
                                with gr.Column(elem_id="ll-echo"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '🥚 彩蛋 · 互文追踪</div>')
                                    echo_state = gr.State(None)
                                    echo_html = gr.HTML(_ECHO_HINT)
                                    with gr.Row():
                                        echo_btn = gr.Button(
                                            "✨ 让 AI 解释这些呼应",
                                            size="sm", scale=1)
                                        echo_card_btn = gr.Button(
                                            "🖼️ 彩蛋对照卡", size="sm", scale=1)
                                    echo_out = gr.HTML(
                                        "", elem_classes=["echo-explain"])
                                    echo_card_status = gr.Markdown("")
                                    echo_card_img = gr.Image(
                                        label="长按/右键保存图片",
                                        type="filepath", visible=False)
                            with gr.Tab("🗺️"):
                                with gr.Column(elem_id="ll-echo-overview"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '🗺️ 本歌彩蛋总览</div>')
                                    echo_overview = gr.HTML(_ECHO_OVERVIEW_EMPTY)
                            with gr.Tab("📖"):
                                with gr.Column(elem_id="ll-intro"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '📖 歌曲导读</div>')
                                    intro_html = gr.HTML(_INTRO_EMPTY)
                                    if not public:
                                        intro_btn = gr.Button(
                                            "🪄 生成 30 秒导读", size="sm")
                            if not public:
                                with gr.Tab("⭐"):
                                    with gr.Column(elem_id="ll-favs"):
                                        gr.HTML('<div class="side-panel-title">'
                                                '⭐ 歌词收藏夹</div>')
                                        gr.Markdown(
                                            "点选左侧一句歌词 → 点下面的按钮收藏。"
                                            "收藏**只在这首歌**打开时显示。",
                                            elem_classes=["wb-hint"])
                                        fav_add_btn = gr.Button(
                                            "⭐ 收藏当前选中的歌词", size="sm")
                                        fav_status = gr.Markdown("")
                                        favs_html = gr.HTML(
                                            _render_favorites(_load_favorites()))
                                        gr.HTML('<div class="side-panel-title" '
                                                'style="margin-top:14px">'
                                                '📒 单词本</div>')
                                        gr.Markdown(
                                            "**双击**歌词里的英文单词即可查词，"
                                            "弹窗里点 ⭐ 收藏到这里；"
                                            "单词**只在收藏它的那首歌**里显示。",
                                            elem_classes=["wb-hint"])
                                        wordbook_html = gr.HTML(
                                            render_wordbook(load_wordbook()))
                            with gr.Tab("🖼️"):
                                with gr.Column(elem_id="ll-card"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '🖼️ 分享卡片</div>')
                                    card_btn = gr.Button("生成歌词金句卡",
                                                         size="sm")
                                    card_status = gr.Markdown("")
                                    card_img = gr.Image(
                                        label="长按/右键保存图片",
                                        type="filepath", visible=False)
                            with gr.Tab("📝"):
                                with gr.Column(elem_id="ll-notes"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '📝 听歌笔记</div>')
                                    notes_html = gr.HTML(_render_notes([]))
                                    with gr.Row():
                                        note_input = gr.Textbox(
                                            placeholder="在当前播放位置记一句感想…",
                                            show_label=False, scale=4,
                                            container=False)
                                        note_add_btn = gr.Button(
                                            "添加", scale=1, size="sm")
                            if not public:
                                with gr.Tab("📻"):
                                    with gr.Column(elem_id="ll-radio-acc"):
                                        gr.HTML('<div class="side-panel-title">'
                                                '📻 AI 电台</div>')
                                        gr.Markdown(
                                            "勾选播放器下方的「📻 电台模式」后，"
                                            "歌曲播完会自动切到下一首；为歌曲生成过"
                                            "**串场语音**（把「歌曲导读」朗读成"
                                            " DJ 播报）的话，进歌前会先播报再放歌。")
                                        radio_gen_btn = gr.Button(
                                            "🎙️ 为本歌生成串场语音（需先有导读）",
                                            size="sm")
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
                        # JS -> backend: favorite entry clicks
                        # ("jump:<i>" / "del:<i>")
                        fav_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-fav-act",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # JS -> backend: evidence-card citation jumps
                        # ("<label>\t<line_index>\t<ts>")
                        cite_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-cite-jump",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        if not public:
                            # backend -> JS: MCP play-command relay
                            # (`lyric-agent mcp` writes a command file; a
                            # timer polls it and JS starts playback)
                            mcp_play_box = gr.Textbox(
                                value="", visible=True, elem_id="ll-mcp-play",
                                elem_classes=["ll-hidden"], show_label=False,
                                container=False)
                        # JS -> backend: double-clicked word ("word\tline\tsong\tts")
                        dict_pick_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-dict-pick",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # backend -> JS: dictionary/AI result JSON for the popover
                        dict_out_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-dict-out",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        # JS -> backend: "✨ AI 语境解释" requests
                        dict_ai_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-dict-ai",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        if not public:
                            # JS -> backend: wordbook add/del
                            wb_act_box = gr.Textbox(
                                value="", visible=True, elem_id="ll-wb-act",
                                elem_classes=["ll-hidden"], show_label=False,
                                container=False)
                        # JS -> backend: delete-note clicks (note index)
                        note_del_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-note-del",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)

            if not public:
                with gr.Tab("🔤 歌曲寻词"):
                    gr.Markdown(
                        "打字练收藏的单词（qwerty-learner 式）：看释义"
                        "和出处歌词盲打单词，**打错一个键整词重来**，"
                        "练对的字母会亮起；错得多的词会更频繁出现。")
                    review_state = gr.State(
                        {"word": "", "words": 0, "perfect": 0,
                         "chars": 0, "ms": 0, "queue": []})
                    review_html = gr.HTML("")
                    review_stats_md = gr.Markdown("")
                    with gr.Row():
                        review_start_btn = gr.Button(
                            "⌨️ 开始 / 换一词", variant="primary",
                            scale=1)
                        review_export_btn = gr.Button(
                            "📤 导出 qwerty-learner 词典", scale=1)
                        anki_export_btn = gr.Button(
                            "🗂️ 导出 Anki 牌组", scale=1)
                    review_download = gr.DownloadButton(
                        "⬇️ 下载词典 JSON", visible=False)
                    anki_download = gr.DownloadButton(
                        "⬇️ 下载 Anki TSV", visible=False)
                    review_export_status = gr.Markdown("")
                    # JS -> backend: word done ("word\tmistakes\tms\tts")
                    review_done_box = gr.Textbox(
                        value="", visible=True,
                        elem_id="ll-review-done",
                        elem_classes=["ll-hidden"], show_label=False,
                        container=False)

            # ══ 页签 3: 彩蛋地图 ══
            with gr.Tab("🥚 彩蛋地图"):
                gr.Markdown(
                    "「彩蛋」= 歌手在不同歌曲里埋下的互相呼应的歌词——"
                    "同一句话、同一个意象在两首歌里遥相呼应。这个页签把所选歌手的"
                    "**全部曲库歌曲**两两比对，自动找出这些呼应。"
                    "默认「⭐ 单曲聚焦」：以一首歌为中心，下方卡片逐对列出呼应歌词；"
                    "「🕸️ 整体网络」看全貌。歌手选「🌐 跨歌手引用」则只看"
                    "**不同歌手之间**的呼应（引用/致敬）。"
                )
                with gr.Tabs():
                    with gr.Tab("🗺️ 呼应地图"):
                        with gr.Row():
                            map_artist = gr.Dropdown(
                                choices=[], value=None, label="选择歌手",
                                # choices arrive via app.load; custom values
                                # keep direct API calls (self_test) from
                                # tripping server-side checks
                                allow_custom_value=True, scale=2,
                                elem_id="ll-map-artist")
                            map_focus = gr.Dropdown(
                                choices=[], value=None,
                                label="聚焦歌曲（按呼应数排序）",
                                allow_custom_value=True, scale=3,
                                elem_id="ll-map-focus")
                        map_view = gr.Radio(
                            choices=[("⭐ 单曲聚焦（简明）", "focus"),
                                     ("🕸️ 整体网络", "net")],
                            value="focus", show_label=False)
                        echo_map_html = gr.HTML("")
                        # JS -> backend: clicked song on the map (refocus)
                        focus_pick_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-focus-pick",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                        map_explain_btn = gr.Button(
                            "✨ 让 AI 解读这张彩蛋网络", size="sm")
                        map_explain_out = gr.Markdown(
                            "", elem_classes=["echo-explain"])
                    with gr.Tab("🔍 意象追踪"):
                        gr.Markdown(
                            "输入一个意象或母题（如：雨、scarf、童年、月光），"
                            "看它在所选范围的曲库里如何反复出现与演变"
                            "（按专辑分组）。")
                        with gr.Row():
                            imagery_box = gr.Textbox(
                                show_label=False,
                                placeholder="输入意象，如：雨 / scarf / 童年",
                                scale=4, container=False)
                            imagery_btn = gr.Button("追踪", scale=1,
                                                    variant="primary")
                        imagery_html = gr.HTML("")
                    with gr.Tab("🎬 MV 彩蛋") as mv_tab:
                        gr.Markdown("选一首歌，AI 整理它官方 MV 的导演、"
                                    "隐藏细节与歌词呼应（结果按歌缓存）。")
                        mv_song_dd = gr.Dropdown(
                            choices=song_choices(), value=None,
                            label="选择歌曲", allow_custom_value=True,
                            elem_id="ll-mv-song")
                        with gr.Column(elem_id="ll-mv"):
                            mv_html = gr.HTML(MV_EMPTY)
                        if not public:
                            mv_btn = gr.Button("🎬 生成 MV 彩蛋", size="sm")
                        # library may grow while the app runs — refresh the
                        # song picker whenever this sub-tab is opened
                        mv_tab.select(
                            lambda: gr.Dropdown(choices=song_choices()),
                            None, [mv_song_dd])

                        def _on_mv_song(choice: str, user_cfg):
                            from .mv_eggs import (load_mv, parse_mv,
                                                  render_mv_html)
                            if not choice:
                                return MV_EMPTY
                            info = find_song(choice)
                            model = _request_settings(user_cfg).model_name
                            cached = load_mv(info["dir"], model)
                            if cached is None:
                                return (MV_EMPTY if not public else
                                        '<div class="chat-empty">该歌曲还没有'
                                        'MV 彩蛋（公开版不提供现场生成）。</div>')
                            return render_mv_html(
                                parse_mv(cached), info.get("title", ""),
                                info.get("artist", ""),
                                verifier=_quote_verifier(),
                                label_of=_label_of(),
                                video=((choice, info["bvid"])
                                       if info.get("bvid") else None))
                        mv_song_dd.change(_on_mv_song, [mv_song_dd, user_llm],
                                          [mv_html])
                        # JS -> backend: ⏱ 锚点点击 → 切歌进播放页，
                        # iframe 定位由 JS 侧完成 ("<label>\t<ts>")
                        mv_seek_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-mv-seek",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)

                        def on_mv_seek(payload: str):
                            label = (payload or "").split("\t")[0].strip()
                            if (not label
                                    or label not in _label_of().values()):
                                return gr.skip(), gr.skip()
                            return (gr.Radio(value=label),
                                    gr.Tabs(selected="play"))

                        mv_seek_box.change(on_mv_seek, [mv_seek_box],
                                           [song_radio, tabs])

            # ══ 页签 5: 互动（竞猜 / 拼图 / 单词练习） ══
            with gr.Tab("🎮 互动"):
                with gr.Tabs():
                    with gr.Tab("🎯 歌词竞猜"):
                        gr.Markdown("从你的歌曲列表随机抽一句歌词，"
                                    "猜猜它出自哪首歌。")
                        quiz_state = gr.State(
                            {"score": 0, "total": 0, "answer": ""})
                        quiz_html = gr.HTML(
                            '<div class="chat-empty">点「开始/下一题」'
                            '抽一句歌词。</div>')
                        quiz_options = gr.Radio(choices=[],
                                                label="它出自哪首歌？",
                                                visible=False)
                        with gr.Row():
                            quiz_new_btn = gr.Button("🎲 开始 / 下一题",
                                                     variant="primary", scale=1)
                            quiz_submit_btn = gr.Button("提交答案", scale=1)
                        quiz_result = gr.Markdown("")
                    with gr.Tab("🧩 歌名拼图"):
                        gr.Markdown("歌名被挖掉了一块——从选项里把它"
                                    "拼回完整。")
                        blank_state = gr.State(
                            {"score": 0, "total": 0, "answer": "", "reveal": ""})
                        blank_html = gr.HTML(
                            '<div class="chat-empty">点「来一题」抽一个'
                            '缺了一块的歌名。</div>')
                        blank_options = gr.Radio(choices=[],
                                                 label="被挖掉的是哪一块？",
                                                 visible=False)
                        with gr.Row():
                            blank_new_btn = gr.Button("🧩 来一题",
                                                      variant="primary", scale=1)
                            blank_submit_btn = gr.Button("🧩 拼好了", scale=1)
                        blank_result = gr.Markdown("")
            # ══ 页签 6: 添加歌曲（公开版为只读曲库，不提供） ══
            if not public:
                with gr.Tab("➕ 添加歌曲"):
                    catalog = _load_catalog()
                    cat_labels = [f"{c['title']} — {c['artist']}" for c in catalog]
                    gr.Markdown(
                        f"### 添加歌曲\n"
                        f"搜索会同时覆盖**内置曲库（{len(catalog)} 首）"
                        "**和**你已添加的歌**；已在列表里的会标注"
                        "「✓ 已在列表」且不可重复勾选。勾选一首或多首后"
                        "一键添加。"
                    )
                    cat_search = gr.Textbox(
                        label="搜索曲库（歌名 / 歌手 / 专辑）", elem_id="ll-cat-search")
                    with gr.Row():
                        cat_all_btn = gr.Button("☑️ 全选", size="sm", scale=1)
                        cat_none_btn = gr.Button("⬜ 取消全选", size="sm", scale=1)
                    cat_radio = gr.CheckboxGroup(
                        choices=cat_labels, value=[],
                        label=f"曲库歌曲（{len(cat_labels)} 首）",
                        elem_id="ll-catalog")
                    cat_add_btn = gr.Button("＋ 添加勾选的歌曲", variant="primary")
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
                            add_title = gr.Textbox(label="歌曲标题（必填）",
                                                   elem_id="ll-add-title")
                            add_artist = gr.Dropdown(
                                choices=[], value=None,
                                label="歌手（选填 — 可从已有歌手里选，也可直接输入）",
                                allow_custom_value=True,
                                elem_id="ll-add-artist")
                            add_album = gr.Textbox(label="专辑（选填）")
                        add_lrc = gr.Textbox(
                            label="LRC 歌词（选填 — 格式如 [00:12.34] 歌词内容，留空将自动从 LRCLIB 获取）",
                            lines=8, elem_id="ll-add-lrc")
                        with gr.Row():
                            add_lrc_file = gr.File(
                                label="或上传 .lrc 文件（可选，优先于文本框）",
                                file_types=[".lrc", ".txt"])
                            add_audio_file = gr.File(
                                label="音频文件（可选）",
                                file_types=[".mp3", ".wav", ".m4a", ".ogg", ".flac"])
                        add_btn = gr.Button("💾 保存歌曲", variant="primary")

            # ══ 页签 7: 设置（三块功能 = 三个底部图标） ══
            with gr.Tab("⚙️ 设置"):
                with gr.Tabs(elem_classes=["ll-icon-dock"]):
                    with gr.Tab("📊"):
                        gr.Markdown("### 📊 API 用量\n本机记录的 LLM 调用"
                                    "与 token 消耗（批注/翻译/问答等全部"
                                    "计入；按模型方计费口径为准）。")
                        usage_md = gr.Markdown("")
                        usage_refresh_btn = gr.Button("🔄 刷新", size="sm")

                        def on_usage_refresh():
                            from .llm import load_usage
                            u = load_usage()
                            tot = u.get("total", {})
                            if not tot.get("calls"):
                                return "还没有任何 LLM 调用记录。"
                            # 单价表（服务商/中转价格差异大，不内置猜测）：
                            # data/cache/llm_prices.json
                            # {"模型名": {"in": 元/百万输入, "out": 元/百万输出}}
                            try:
                                prices = json.loads(Path(
                                    "data/cache/llm_prices.json"
                                ).read_text(encoding="utf-8"))
                            except (OSError, ValueError):
                                prices = {}

                            def _cost(model, b):
                                p = prices.get(model)
                                if not p:
                                    return "—"
                                yuan = (b.get("input_tokens", 0)
                                        * p.get("in", 0)
                                        + b.get("output_tokens", 0)
                                        * p.get("out", 0)) / 1_000_000
                                return f"¥{yuan:.4f}"

                            day = time.strftime("%Y-%m-%d")
                            today = u.get("days", {}).get(day, {})
                            rows = ["| | 调用 | 输入 tokens | 输出 tokens | 费用 |",
                                    "|---|---|---|---|---|"]
                            for label, b in (("今天", today), ("累计", tot)):
                                rows.append(
                                    f"| {label} | {b.get('calls', 0)} | "
                                    f"{b.get('input_tokens', 0):,} | "
                                    f"{b.get('output_tokens', 0):,} | — |")
                            for model, b in sorted(
                                    u.get("models", {}).items()):
                                rows.append(
                                    f"| `{model}` | {b.get('calls', 0)} | "
                                    f"{b.get('input_tokens', 0):,} | "
                                    f"{b.get('output_tokens', 0):,} | "
                                    f"{_cost(model, b)} |")
                            if not prices:
                                rows.append(
                                    "\n💡 想看金额：把你服务商的单价填进 "
                                    "`data/cache/llm_prices.json`，格式 "
                                    '`{"模型名": {"in": 元/百万输入, '
                                    '"out": 元/百万输出}}`。')
                            return "\n".join(rows)

                        usage_refresh_btn.click(on_usage_refresh, None,
                                                [usage_md])
                        app.load(on_usage_refresh, None, [usage_md])
                    with gr.Tab("🔑"):
                        if public:
                            gr.Markdown(
                                "### 🔑 API 设置（公开体验版）\n"
                                "请填入**你自己的**大模型 API Key。"
                                "Key 只会保存在你当前浏览器的本地存储"
                                "（localStorage）中，**不会上传或写入服务器**，"
                                "其他访客也看不到。"
                            )
                        else:
                            gr.Markdown(
                                "### 🔑 API 设置\n"
                                "在这里填入你自己的大模型 API Key，点保存后"
                                "**立即生效**，无需改任何文件、无需重启。"
                            )
                        set_provider = gr.Radio(
                            choices=[
                                ("OpenAI 兼容接口（DeepSeek / 通义 / Kimi 等）",
                                 "openai"),
                                ("Anthropic（Claude）", "anthropic"),
                            ],
                            value="openai" if public else settings.llm_provider,
                            label="接口类型")
                        set_key = gr.Textbox(
                            label="API Key（必填）", type="password",
                            value="" if public else settings.api_key)
                        set_base = gr.Textbox(
                            label="接口地址（选填 — OpenAI 兼容接口才需要，"
                                  "例如 https://api.deepseek.com）",
                            value="" if public else settings.llm_base_url)
                        set_model = gr.Textbox(
                            label="模型名称（选填 — 留空自动使用默认模型）",
                            value="" if public else settings.model_name)
                        set_btn = gr.Button("💾 保存设置", variant="primary")
                        set_status = gr.Markdown("")

                    if not public:
                        with gr.Tab("🧠"):
                            gr.Markdown(
                                "### 🧠 语料库与 Embedding 模型\n"
                                "彩蛋/互文/语义搜索使用本地 embedding 模型。"
                                "默认英文模型对中文歌词区分度差；曲库以中文为主时，"
                                "建议切换到多语模型后**重建索引**"
                                "（首次会下载模型，重建需 1-3 分钟）。"
                            )
                            emb_model_dd = gr.Dropdown(
                                choices=[
                                    ("英文为主（默认）：all-MiniLM-L6-v2",
                                     "all-MiniLM-L6-v2"),
                                    ("多语（中英均可）："
                                     "paraphrase-multilingual-MiniLM-L12-v2",
                                     "paraphrase-multilingual-MiniLM-L12-v2"),
                                ],
                                value=settings.embedding_model
                                if settings.embedding_model in (
                                    "all-MiniLM-L6-v2",
                                    "paraphrase-multilingual-MiniLM-L12-v2")
                                else None,
                                allow_custom_value=True,
                                label="Embedding 模型"
                                      "（可输入任意 sentence-transformers 模型名）")
                            rebuild_btn = gr.Button(
                                "🔨 重建语料库索引（含新添加的歌曲）")
                            rebuild_status = gr.Markdown("")
                        with gr.Tab("🧪"):
                            gr.Markdown(
                                "### 🧪 UI 自检（开发者）\n"
                                "启动一个**独立的**巡检服务器实例，"
                                "用真实浏览器逐页签走查 22+ 项交互"
                                "（含 JS 报错与服务端异常收集），约 2-3 分钟。"
                                "发现问题后可在终端运行 "
                                "`python scripts/ui_agent.py` 进入自动修复闭环"
                                "（改代码需重启，故修复环节不在网页内进行）。"
                            )
                            probe_btn = gr.Button("🧪 运行 UI 巡检")
                            probe_out = gr.Markdown("")
                            probe_table = gr.HTML("")

        # ── Handlers ──

        def _collections_for(title: str) -> tuple:
            """收藏歌词 + 单词本, both scoped to the open song."""
            if public:
                return ()
            return (_render_favorites(_load_favorites(), song_title=title),
                    render_wordbook(load_wordbook(), song_title=title))

        def on_song_select(choice: str):
            if not ctx["songs"]:
                return ("", None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT,
                        None, _ECHO_HINT, "", "", gr.Image(visible=False),
                        _INTRO_EMPTY, "", gr.Image(visible=False),
                        _render_notes([]), _ANN_HINT) + _collections_for("")
            info = find_song(choice)
            audio = resolve_audio(info["dir"])
            info["audio_type"], info["audio_src"] = audio.type, audio.path_or_url or ""
            data = _load_song_data(info["dir"])
            lyrics = _render_lyrics_html(data, info, public=public)
            intro = _render_intro(_load_intro(info["dir"]))
            return (lyrics, None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT,
                    None, _ECHO_HINT, "", "", gr.Image(visible=False),
                    intro, "", gr.Image(visible=False), _notes_for(info),
                    _ANN_HINT) + _collections_for(info["title"])

        song_outputs = [lyrics_html, chat_state, chat_topic, chat_html,
                        echo_state, echo_html, echo_out, card_status, card_img,
                        intro_html, echo_card_status, echo_card_img, notes_html,
                        ann_html]
        if not public:
            # the two per-song collections re-render on every song switch
            song_outputs += [favs_html, wordbook_html]

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

        _GRAPH_CACHE_DIR = Path("data/cache/echo_graphs")

        def _graph_cache_key(choice: str) -> list:
            corpus_p = Path(settings.corpus_dir) / "discography.jsonl"
            emb_p = Path(settings.corpus_dir) / "embeddings.npy"
            return [
                corpus_p.stat().st_mtime if corpus_p.exists() else 0,
                emb_p.stat().st_mtime if emb_p.exists() else 0,
                settings.embedding_model,
                settings.echo_min_similarity,
                settings.echo_min_similarity_cjk,
                settings.echo_map_max_nodes,
                sorted(s["title"] for s in ctx["songs"]),
                choice,
            ]

        def _map_graph(choice: str):
            """Build (or fetch cached) EchoGraph + rendered HTML for a choice.

            Two cache layers: per-session memory, then disk — the
            cross-artist graph costs 10-20s to build, and the disk layer
            (echo-scan pattern: mtimes + model + thresholds in the key)
            survives server restarts."""
            index = _echo_index()
            if index is None:
                return None, _ECHO_NO_INDEX
            cache = ctx.setdefault("echo_graphs", {})
            if choice not in cache:
                from .intertextuality.echo_map import (
                    build_echo_graph, graph_from_dict, graph_to_dict,
                    render_echo_map_html)
                key = _graph_cache_key(choice)
                slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", choice)
                disk = _GRAPH_CACHE_DIR / f"{slug}.json"
                graph = None
                try:
                    saved = json.loads(disk.read_text(encoding="utf-8"))
                    if saved.get("key") == key:
                        graph = graph_from_dict(saved["graph"])
                except (OSError, ValueError, KeyError, TypeError):
                    graph = None
                if graph is None:
                    embeddings, corpus = index
                    artist = (None if choice == _CROSS_ARTIST_CHOICE
                              else choice)
                    graph = build_echo_graph(
                        embeddings, corpus, artist,
                        min_similarity=settings.echo_min_similarity,
                        min_similarity_cjk=settings.echo_min_similarity_cjk,
                        max_nodes=settings.echo_map_max_nodes,
                        library_titles={s["title"] for s in ctx["songs"]},
                    )
                    try:
                        _GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        disk.write_text(
                            json.dumps({"key": key,
                                        "graph": graph_to_dict(graph)},
                                       ensure_ascii=False),
                            encoding="utf-8")
                    except OSError:
                        logger.warning("echo graph cache write failed",
                                       exc_info=True)
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
            all_choices = artists + [_CROSS_ARTIST_CHOICE]
            return (gr.Dropdown(choices=all_choices, value=value),
                    dd, _render_map(value, "focus", focus))

        def on_focus_pick(payload: str, artist: str):
            """Map-node click: refocus on that song (and switch to focus view)."""
            song = (payload or "").split("\t")[0].strip()
            if not song or not artist:
                return gr.skip(), gr.skip(), gr.skip()
            graph, _net = _map_graph(artist)
            if graph is None:
                return gr.skip(), gr.skip(), gr.skip()
            from .intertextuality.echo_map import focus_choices
            songs = focus_choices(graph)
            if song not in songs:
                return gr.skip(), gr.skip(), gr.skip()
            # visible=True: the click may arrive from the network view,
            # where the focus dropdown is hidden
            return (gr.Dropdown(choices=songs, value=song, visible=True),
                    gr.Radio(value="focus"),
                    _render_map(artist, "focus", song))

        # .change (not .input): .input silently drops events for some
        # components in this gradio build. init_echo_map's programmatic
        # updates DO re-trigger these handlers now; on_map_artist recomputes
        # the same default focus it was given, so the net render is identical
        # shared concurrency_id: these four all repaint echo_map_html.
        # Without it gradio may run them in parallel, and a slow render
        # (first cross-artist build) can finish AFTER a fast one and paint
        # a stale graph over the fresh one.
        map_artist.change(on_map_artist, [map_artist, map_view],
                         [map_focus, echo_map_html, map_explain_out],
                         concurrency_id="echo-map")
        map_view.change(on_map_view, [map_view, map_artist, map_focus],
                       [map_focus, echo_map_html],
                       concurrency_id="echo-map")
        map_focus.change(on_map_focus, [map_focus, map_artist, map_view],
                        [echo_map_html],
                        concurrency_id="echo-map")
        focus_pick_box.change(on_focus_pick, [focus_pick_box, map_artist],
                              [map_focus, map_view, echo_map_html],
                              concurrency_id="echo-map")
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
            passage = _esc(q.line).replace("\n", "<br>")
            html_q = (f'<div class="quiz-line">“{passage}”</div>'
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

        # ── 歌名挖空 ──

        def on_blank_new(state: dict):
            from .quiz import make_title_puzzle
            pool = [(s["title"], s["artist"]) for s in ctx["songs"]]
            q = make_title_puzzle(pool)
            if q is None:
                return (dict(state or {}, answer="", reveal=""),
                        '<div class="chat-empty">曲库里可拼的歌名不足'
                        '（至少需要 2 首可挖的歌名）。</div>',
                        gr.Radio(choices=[], visible=False), "")
            state = dict(state or {}, answer=q.answer,
                         reveal=f"《{q.title}》 · {q.artist}")
            html_q = (f'<div class="quiz-line blank-line">'
                      f'《{_esc(q.masked)}》</div>'
                      f'<div class="quiz-meta">歌手：{_esc(q.artist)}</div>')
            return (state, html_q,
                    gr.Radio(choices=q.options, value=None, visible=True), "")

        def on_blank_submit(state: dict, choice: str):
            state = dict(state or {})
            answer = state.get("answer", "")
            if not answer:
                return state, "⚠️ 先点「来一题」抽题。"
            if not choice:
                return state, "⚠️ 请先选择一个选项。"
            state["total"] = state.get("total", 0) + 1
            if choice == answer:
                state["score"] = state.get("score", 0) + 1
                verdict = "✅ 拼对了！"
            else:
                verdict = f"❌ 不对，缺的是「{answer}」。"
            reveal = state.get("reveal", "")
            state["answer"] = ""  # one submission per question
            return (state, f"{verdict}　完整歌名：{reveal}　当前战绩 "
                    f"**{state.get('score', 0)} / {state['total']}**")

        blank_new_btn.click(on_blank_new, [blank_state],
                            [blank_state, blank_html, blank_options,
                             blank_result])
        blank_submit_btn.click(on_blank_submit, [blank_state, blank_options],
                               [blank_state, blank_result])

        # ── 彩蛋猜猜乐 ──

        # ── ⌨️ 单词练习 ──
        if not public:
            def _review_stats_line(state) -> str:
                from .review import book_stats
                s = book_stats(load_wordbook())
                parts = []
                if state["words"]:
                    pct = round(100 * state["perfect"] / state["words"])
                    wpm = (round((state["chars"] / 5)
                                 / (state["ms"] / 60000), 1)
                           if state["ms"] else 0)
                    parts.append(f"本轮 **{state['words']}** 词 · 一遍过 "
                                 f"{state['perfect']}（{pct}%） · WPM {wpm}")
                parts.append(f"单词本 {s['practiced']}/{s['total']} 已练 · "
                             f"{s['mastered']} 熟练")
                return " ｜ ".join(parts)

            def _review_next(state, exclude: str = ""):
                from .review import round_queue, synthesize_word
                book = load_wordbook()
                titles = {e.get("word", "").lower() for e in book}
                # 本轮队列：收藏的词各打一遍、按优先级排序；打完重排开下一轮
                queue = [w for w in state.get("queue", [])
                         if w.lower() in titles]
                if not queue:
                    queue = round_queue(book)
                    if exclude and len(queue) > 1 \
                            and queue[0].lower() == exclude.lower():
                        queue.append(queue.pop(0))  # 新轮首词避开刚打完的
                entry = None
                if queue:
                    word = queue.pop(0)
                    entry = next((e for e in book
                                  if e.get("word", "").lower()
                                  == word.lower()), None)
                state["queue"] = queue
                if entry is None:
                    state["word"] = ""
                    return (state,
                            '<div class="chat-empty">单词本是空的——先去'
                            '「🎧 播放解读」双击歌词里的英文单词收藏几个。'
                            '</div>', _review_stats_line(state))
                mp3 = synthesize_word(entry["word"])
                url = _file_url(mp3) if mp3 else ""
                state["word"] = entry["word"]
                return (state,
                        render_practice_card(entry, url, uuid.uuid4().hex),
                        _review_stats_line(state))

            def on_review_start(state):
                return _review_next(state, exclude=state.get("word", ""))

            def on_review_done(payload: str, state):
                parts = (payload or "").split("\t")
                if len(parts) < 3:
                    return gr.skip(), gr.skip(), gr.skip()
                word, mistakes, ms = parts[0], parts[1], parts[2]
                if not word or word != state.get("word", "").lower():
                    return gr.skip(), gr.skip(), gr.skip()  # stale payload
                from .review import record_result
                clean = mistakes == "0"
                record_result(word, clean)
                state["words"] += 1
                state["perfect"] += 1 if clean else 0
                state["chars"] += len(word)
                try:
                    state["ms"] += max(0, int(ms))
                except ValueError:
                    pass
                return _review_next(state, exclude=word)

            def on_review_export():
                from .review import export_qwerty
                book = load_wordbook()
                if not book:
                    return (gr.DownloadButton(visible=False),
                            "单词本是空的，没有可导出的词。")
                out = Path("data/cache/qwerty_export.json")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(export_qwerty(book),
                                          ensure_ascii=False, indent=2),
                               encoding="utf-8")
                return (gr.DownloadButton(value=str(out), visible=True),
                        f"已生成 {len(book)} 词。把 JSON 放进你本地部署的 "
                        "qwerty-learner 的 `public/dicts/` 并在 "
                        "`resources/dictionary.ts` 注册即可使用。")

            review_start_btn.click(on_review_start, [review_state],
                                   [review_state, review_html,
                                    review_stats_md])
            review_done_box.change(on_review_done,
                                   [review_done_box, review_state],
                                   [review_state, review_html,
                                    review_stats_md])
            review_export_btn.click(on_review_export, None,
                                    [review_download, review_export_status])

            def on_anki_export():
                from .review import export_anki
                book = load_wordbook()
                if not book:
                    return (gr.DownloadButton(visible=False),
                            "单词本是空的，没有可导出的词。")
                out = Path("data/cache/anki_export.txt")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(export_anki(book), encoding="utf-8")
                return (gr.DownloadButton(value=str(out), visible=True),
                        f"已生成 {len(book)} 词的 Anki TSV——Anki 里"
                        "「文件 → 导入」选择它即可。")

            anki_export_btn.click(on_anki_export, None,
                                  [anki_download, review_export_status])

        # ── 听歌识曲 ──


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
                    None, _render_lyrics_html(data, info, public=public))

        if not public:
            audio_file_up.upload(on_audio_upload, [audio_file_up, song_radio],
                                 [audio_up_status, audio_file_up, lyrics_html])

        # ── 📺 B 站视频绑定（官方嵌入播放器；搜索为便捷辅助）──
        if not public:
            def _save_bvid(info: dict, bvid: str) -> None:
                """Persist (or clear) the bound video — on_audio_upload's
                read-modify-write metadata pattern."""
                meta_path = Path(info["dir"]) / "metadata.json"
                meta = (json.loads(meta_path.read_text(encoding="utf-8"))
                        if meta_path.exists() else {})
                if bvid:
                    meta["bvid"] = bvid
                    meta.pop("bvid_no_auto", None)  # 用户重选=重新放行
                else:
                    meta.pop("bvid", None)
                    # 用户主动删除：自动绑定线程此后跳过这首
                    meta["bvid_no_auto"] = True
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                refresh_library()

            def _bvid_rerender(choice: str):
                info = find_song(choice)
                data = _load_song_data(info["dir"])
                return _render_lyrics_html(data, info, public=public)

            def on_bvid_act(payload: str, choice: str):
                parts = (payload or "").split("\t")
                act = parts[0].strip() if parts else ""
                info = find_song(choice)
                if not act or not info.get("dir"):
                    return gr.skip()
                if act == "unbind":
                    _save_bvid(info, "")
                    gr.Info(f"🗑 已删除《{info['title']}》的视频绑定，"
                            "可重新搜索或手填。")
                    return _bvid_rerender(choice)
                if act == "search":
                    from .bilibili import search_mv
                    cands = search_mv(info["title"], info.get("artist", ""))
                    if not cands:
                        gr.Warning("B 站搜索暂不可用——可在「📺 关联 B 站视频」"
                                   "手风琴里手动粘 BV 号或链接。")
                        return gr.skip()
                    data = _load_song_data(info["dir"])
                    return _render_lyrics_html(
                        data, dict(info, bvid_cands=cands), public=public)
                if act == "pick" and len(parts) >= 2:
                    from .bilibili import extract_bvid
                    bvid = extract_bvid(parts[1])
                    if not bvid:
                        return gr.skip()
                    _save_bvid(info, bvid)
                    gr.Info(f"📺 已为《{info['title']}》绑定 {bvid}")
                    return _bvid_rerender(choice)
                return gr.skip()

            def on_bvid_save(text: str, choice: str):
                from .bilibili import extract_bvid
                info = find_song(choice)
                if not info.get("dir"):
                    return "⚠️ 请先在列表中选择一首歌。", gr.skip(), gr.skip()
                bvid = extract_bvid(text)
                if (text or "").strip() and not bvid:
                    return ("⚠️ 没找到 BV 号——请粘贴形如 BV1xx411c7mD 的 ID "
                            "或完整视频链接。"), gr.skip(), gr.skip()
                _save_bvid(info, bvid)
                msg = f"✅ 已绑定 {bvid}，视频已在上方展开。" if bvid                     else "✅ 已解绑视频。"
                return msg, _bvid_rerender(choice), gr.Textbox(value=bvid)

            def on_bvid_load(choice: str):
                # keep the accordion input mirroring the saved binding, so a
                # page refresh never looks like the link was lost
                return gr.Textbox(value=find_song(choice).get("bvid", ""))

            bvid_box.change(on_bvid_act, [bvid_box, song_radio],
                            [lyrics_html])
            bvid_save_btn.click(on_bvid_save, [bvid_input, song_radio],
                                [bvid_status, lyrics_html, bvid_input])
            song_radio.change(on_bvid_load, [song_radio], [bvid_input])

            # ── 🀄 中文翻译对照（用户点按钮才生成/显示；译文永久缓存）──
            trans_state = gr.State("")   # 当前开着翻译的歌名，"" = 关

            def on_trans_toggle(cur: str, choice: str, user_cfg):
                info = find_song(choice)
                if not info.get("dir"):
                    return cur, gr.skip()
                data = _load_song_data(info["dir"])
                title = info.get("title", "")
                if cur == title:   # 已开 → 关
                    return "", _render_lyrics_html(data, info, public=public)
                from .ui_helpers import load_translation
                if not load_translation(info["dir"]):
                    req = _request_settings(user_cfg)
                    if not req.api_key:
                        gr.Warning("需要 API Key 才能生成翻译（⚙️ 设置）。")
                        return cur, gr.skip()
                    gr.Info("🀄 正在生成整首中文翻译……")
                    lines = data["timed_lines"]
                    out: dict[str, str] = {}
                    from .llm import LLMClient
                    client = LLMClient(req)
                    try:
                        for i in range(0, len(lines), 40):
                            chunk = lines[i:i + 40]
                            payload = client.generate_json(
                                "你是歌词翻译。把给定歌词逐行翻成信达雅的"
                                "简体中文，行数与输入一致，返回 JSON："
                                '{"translations": [逐行译文]}。'
                                "已是中文的行原样返回。",
                                "\n".join(ln.text for ln in chunk))
                            arr = (payload or {}).get("translations", [])
                            for ln, zh in zip(chunk, arr):
                                if isinstance(zh, str) and zh.strip() \
                                        and zh.strip() != ln.text.strip():
                                    out[str(ln.line_index)] = zh.strip()
                        Path(info["dir"], "translation.json").write_text(
                            json.dumps({"lines": out}, ensure_ascii=False,
                                       indent=1), encoding="utf-8")
                    except Exception as exc:
                        logger.exception("translation failed")
                        gr.Warning(f"翻译失败：{str(exc)[:120]}")
                        return cur, gr.skip()
                return title, _render_lyrics_html(data, info, public=public,
                                                  show_trans=True)

            trans_btn.click(on_trans_toggle,
                            [trans_state, song_radio, user_llm],
                            [trans_state, lyrics_html])

            # ── 🎚 歌词时间校准 ──
            def on_offset_preview(v):
                # JS applies it live to #ll-audio's data-offset
                return json.dumps({"offset": int(v), "ts": time.time()})

            def on_offset_load(choice: str):
                info = find_song(choice)
                return gr.Slider(value=int(info.get("audio_offset_ms", 0)
                                           or 0))

            def on_offset_save(v, choice: str):
                info = find_song(choice)
                if not info.get("dir"):
                    return "⚠️ 请先在列表中选择一首歌。", gr.skip()
                meta_path = Path(info["dir"]) / "metadata.json"
                meta = (json.loads(meta_path.read_text(encoding="utf-8"))
                        if meta_path.exists() else {})
                if int(v):
                    meta["audio_offset_ms"] = int(v)
                else:
                    meta.pop("audio_offset_ms", None)
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                refresh_library()
                return (f"✅ 已保存偏移 {int(v)} ms。",
                        _bvid_rerender(choice))

            offset_slider.change(on_offset_preview, [offset_slider],
                                 [offset_box])
            offset_save_btn.click(on_offset_save,
                                  [offset_slider, song_radio],
                                  [offset_status, lyrics_html])
            # 切歌时带出当前偏移（独立监听，不动 on_song_select 的输出位序）
            song_radio.change(on_offset_load, [song_radio], [offset_slider])

        def _filtered_labels(sort: str, q: str) -> list[str]:
            labels = song_choices(sort)
            q = (q or "").strip().casefold()
            if q:
                labels = [
                    l for l in labels
                    if q in l.casefold()
                    or q in find_song(l).get("artist", "").casefold()
                ]
            return labels

        def on_song_filter(q: str, sort: str):
            # choices-only update: the current selection (and playback)
            # stays untouched even while filtered out of view
            return gr.Radio(choices=_filtered_labels(sort, q))

        # .change, not .input: mirrors cat_search — .input never reached
        # the backend for this textbox (zero API calls observed)
        song_filter.change(on_song_filter, [song_filter, sort_mode],
                           [song_radio])
        # ✕ 取消筛选：清空输入 → 上面的 .change 自然恢复完整列表
        filter_clear_btn.click(lambda: "", None, [song_filter])

        def on_sort(sort: str, choice: str, q: str):
            labels = _filtered_labels(sort, q)
            value = choice if choice in labels else (labels[0] if labels else None)
            return gr.Radio(choices=labels, value=value)

        sort_mode.change(on_sort, [sort_mode, song_radio, song_filter],
                         [song_radio])

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

        def _artist_motifs(artist: str) -> dict[str, int]:
            """word -> n_songs for the artist's mined motifs (cached)."""
            cache = ctx.setdefault("motifs", {})
            if artist not in cache:
                index = _echo_index()
                if index is None:
                    cache[artist] = {}
                else:
                    cache[artist] = {m["word"]: m["n_songs"]
                                     for m in mine_motifs(index[1], artist)}
            return cache[artist]

        def _line_dossier(line_text: str, info: dict,
                          echoes: list[dict] | None) -> str:
            """机器检索到的行级互文档案 for the AI context."""
            parts = []
            for r in (echoes or [])[:3]:
                parts.append(f"- 《{r['song']}》：“{r['line']}”"
                             f"（相似度 {r['similarity']}）")
            motifs = _artist_motifs(info.get("artist", ""))
            words = [w for w in re.findall(r"[a-zA-Z']{3,}|[\u4e00-\u9fff]{2,}",
                                           line_text.casefold())
                     if w in motifs]
            for w in sorted(set(words), key=lambda x: -motifs[x]):
                parts.append(f"- 「{w}」是这位歌手的母题词，"
                             f"出现在 {motifs[w]} 首歌里")
            return "\n".join(parts)

        def on_line_pick(idx_str: str, choice: str, session):
            idx_str = (idx_str or "").strip()
            if not idx_str.isdigit() or not ctx["songs"]:
                return (session, _CHAT_TOPIC_DEFAULT, _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip(), gr.skip())
            idx = int(idx_str)
            info = find_song(choice)
            data = _load_song_data(info["dir"])
            line = next((ln for ln in data["timed_lines"] if ln.line_index == idx), None)
            if line is None:
                return (session, _CHAT_TOPIC_DEFAULT, _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip(), gr.skip())
            if session is not None and session.lyric_line == line.text \
                    and session.line_index == idx:
                return (session, _chat_topic_html(line.text), _render_chat(session),
                        gr.skip(), gr.skip(), gr.skip(), gr.skip())
            # annotations stay out of the UI but still feed the AI as context
            ann = data["annotations"].get(idx)
            # public mode: visitors must not see each other's saved Q&A
            saved = None if public else _load_chat_history(info["dir"]).get(str(idx))
            history = saved["turns"] if saved and isinstance(
                saved.get("turns"), list) else []
            ann_parts = []
            if ann:
                ann_parts.append(ann.summary)
                if getattr(ann, "metaphor_analysis", None):
                    ann_parts.append(f"修辞：{ann.metaphor_analysis}")
                if getattr(ann, "taylor_swift_context", None):
                    ann_parts.append(f"背景：{ann.taylor_swift_context}")
            echoes = find_echoes(line.text, info)
            session = DebateSession(
                lyric_line=line.text,
                song_title=info.get("title", ""),
                artist=info.get("artist", ""),
                annotation_context="　".join(ann_parts),
                echo_context=_line_dossier(line.text, info, echoes),
                line_index=idx,
                history=history,
            )
            if echoes is None:
                echo, echo_render = None, _ECHO_NO_INDEX
            else:
                echo = {"line": line.text, "song": info.get("title", ""),
                        "artist": info.get("artist", ""), "results": echoes}
                echo_render = _render_echo_html(echoes, info.get("artist", ""))
            return (session, _chat_topic_html(line.text), _render_chat(session),
                    echo, echo_render, "",
                    render_annotation_card(ann, idx, can_generate=not public))

        line_pick.change(on_line_pick, [line_pick, song_radio, chat_state],
                         [chat_state, chat_topic, chat_html,
                          echo_state, echo_html, echo_out, ann_html])

        def on_gen_ann(payload: str, choice: str, user_cfg):
            """「✨ 为本句生成」按钮：用户点击确认后才发生的唯一一次调用。"""
            idx_str = (payload or "").split("\t")[0].strip()
            if public or not idx_str.isdigit() or not ctx["songs"]:
                return gr.skip()
            idx = int(idx_str)
            info = find_song(choice)
            data = _load_song_data(info["dir"])
            line = next((ln for ln in data["timed_lines"]
                         if ln.line_index == idx), None)
            if line is None:
                return gr.skip()
            req_settings = _request_settings(user_cfg)
            if not req_settings.api_key:
                return ('<div class="ann-card ann-empty">⚠️ 未配置 API Key，'
                        '无法生成。请到「⚙️ 设置」页签填写。</div>')
            from .annotator.engine import regenerate_annotation
            from .annotator.models import Song, SongMetadata
            ann_path = Path(info["dir"]) / "annotations.json"
            try:
                song = (Song.load(ann_path) if ann_path.exists()
                        else Song(metadata=SongMetadata(
                            title=info.get("title", ""),
                            artist=info.get("artist", ""),
                            album=info.get("album", ""),
                            year=int(info.get("year") or 0),
                            era=info.get("era", ""))))
                ann = regenerate_annotation(req_settings, song.metadata,
                                            idx, line.text)
                song.annotations = [a for a in song.annotations
                                    if a.line_index != idx] + [ann]
                song.annotations.sort(key=lambda a: a.line_index)
                song.save(ann_path)
            except Exception as exc:
                logger.exception("single-line annotation failed")
                return (f'<div class="ann-card ann-empty">⚠️ 生成失败：'
                        f'{_esc(str(exc)[:150])}</div>')
            return render_annotation_card(ann, idx, can_generate=not public)

        gen_ann_box.change(on_gen_ann, [gen_ann_box, song_radio, user_llm],
                           [ann_html])

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

        def on_gen_mv(choice: str, user_cfg):
            from .mv_eggs import (
                load_mv, mv_messages, parse_mv, render_mv_html, save_mv)
            if not ctx["songs"]:
                yield MV_EMPTY
                return
            if not choice:
                yield '<div class="chat-empty">⚠️ 请先选择一首歌。</div>'
                return
            info = find_song(choice)
            title = info.get("title", "")
            artist = info.get("artist", "")
            req_settings = _request_settings(user_cfg)
            existing = load_mv(info["dir"], req_settings.model_name)
            if existing is not None:
                yield render_mv_html(
                    parse_mv(existing), title, artist,
                    verifier=_quote_verifier(), label_of=_label_of(),
                    video=(choice, info["bvid"]) if info.get("bvid") else None)
                return
            if not req_settings.api_key:
                yield ('<div class="chat-empty">⚠️ 未配置 API Key，无法生成。'
                       '请到「⚙️ 设置」页签填写。</div>')
                return
            yield ('<div class="chat-empty">🎬 AI 正在回忆这支 MV 的'
                   '导演、意象与彩蛋……</div>')
            system, user_msg = mv_messages(
                title, artist, info.get("album", ""), info.get("year"))
            from .llm import LLMClient
            try:
                data = LLMClient(req_settings).generate_json(system, user_msg)
            except Exception as exc:
                logger.exception("MV eggs generation failed")
                yield (f'<div class="chat-empty">⚠️ 生成失败：'
                       f'{_esc(str(exc)[:150])}</div>')
                return
            save_mv(info["dir"], data, req_settings.model_name)
            yield render_mv_html(
                parse_mv(data), title, artist,
                verifier=_quote_verifier(), label_of=_label_of(),
                video=(choice, info["bvid"]) if info.get("bvid") else None)

        # ── 歌词收藏夹 ──

        def on_fav_add(idx_str: str, choice: str):
            idx_str = (idx_str or "").strip().split("\t")[0]
            if not idx_str.isdigit() or not ctx["songs"]:
                return "⚠️ 先在歌词区点选一句歌词再收藏。", gr.skip()
            info = find_song(choice)
            data = _load_song_data(info["dir"])
            line = next((ln for ln in data["timed_lines"]
                         if ln.line_index == int(idx_str)), None)
            if line is None:
                return "⚠️ 未找到选中的歌词行。", gr.skip()
            from .ui_helpers import _fav_id
            favs = _load_favorites()
            title = info.get("title", "")
            if any(f.get("line") == line.text and f.get("title") == title
                   for f in favs):
                return "ℹ️ 这句已经在收藏夹里了。", gr.skip()
            favs.append({"id": _fav_id(line.text, title), "line": line.text,
                         "title": title, "artist": info.get("artist", ""),
                         "label": song_choice_label(info),
                         "line_index": line.line_index})
            _save_favorites(favs)
            return (f"✅ 已收藏（共 {len(favs)} 句）。",
                    _render_favorites(favs, song_title=title))

        def on_fav_act(payload: str, sort: str, choice: str):
            # payload is 'del:<id>' or 'jump:<id>' — id is stable, so neither
            # drifts with list position (multi-tab / stale render safe)
            act = (payload or "").split("\t")[0].strip()
            favs = _load_favorites()
            if act.startswith("del:"):
                fid = act[4:]
                kept = [f for f in favs if f.get("id") != fid]
                if len(kept) != len(favs):
                    _save_favorites(kept)
                cur = find_song(choice).get("title", "")
                return (_render_favorites(kept, song_title=cur),
                        gr.skip(), gr.skip())
            if act.startswith("jump:"):
                fid = act[5:]
                from .intertextuality.search import artist_matches
                fav = next((f for f in favs if f.get("id") == fid), None)
                if fav:
                    # re-resolve by title(+artist): the stored label can go
                    # stale (a same-title cover added later), so recompute
                    want_t, want_a = fav.get("title"), fav.get("artist", "")
                    song = next(
                        (s for s in ctx["songs"]
                         if s["title"] == want_t
                         and (not want_a
                              or artist_matches(want_a, s.get("artist", "")))),
                        None)
                    if song and song_choice_label(song) in song_choices(sort):
                        return (gr.skip(), gr.Radio(value=song_choice_label(song)),
                                "")
                    return (gr.skip(), gr.skip(),
                            "⚠️ 这首歌已不在列表中（可能已删除）。")
            return gr.skip(), gr.skip(), gr.skip()

        if not public:
            fav_add_btn.click(on_fav_add, [line_pick, song_radio],
                              [fav_status, favs_html])
            fav_box.change(on_fav_act, [fav_box, sort_mode, song_radio],
                           [favs_html, song_radio, fav_status])

        # ── mini 翻译器（双击取词）──

        def on_dict_pick(payload: str):
            parts = (payload or "").split("\t")
            word = parts[0].strip() if parts else ""
            if not word:
                return gr.skip()
            hit = dict_lookup(word)
            result = {
                "q": payload,
                "word": (hit or {}).get("word", word),
                "phonetic": (hit or {}).get("phonetic", ""),
                # normalize ECDICT's literal backslash-n to real newlines
                "translation": ((hit or {}).get("translation", "")
                                .replace("\\n", "\n")),
                "found": hit is not None,
                "canFav": not public,
            }
            return gr.Textbox(value=json.dumps(result, ensure_ascii=False))

        dict_pick_box.change(on_dict_pick, [dict_pick_box], [dict_out_box])

        _AI_CACHE_PATH = Path(settings.songs_dir).parent / "dict" / "ai_cache.json"

        def _cached_dict_ai(word: str, line: str) -> str:
            """The popup's AI explanation for word+line, if one was generated
            (same cache key derivation as on_dict_ai)."""
            import hashlib
            key = hashlib.md5(f"v2:{word}\x00{line}".encode()).hexdigest()
            try:
                cache = json.loads(_AI_CACHE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return ""
            return cache.get(key, "")

        def on_dict_ai(payload: str, user_cfg):
            parts = (payload or "").split("\t")
            if len(parts) < 3 or not parts[0].strip():
                return gr.skip()
            word, line, song = parts[0].strip(), parts[1], parts[2]
            req_settings = _request_settings(user_cfg)
            hit = dict_lookup(word) or {}
            base = {
                "q": payload, "word": hit.get("word", word),
                "phonetic": hit.get("phonetic", ""),
                "translation": (hit.get("translation", "")
                                .replace("\\n", "\n")),
                "found": bool(hit), "canFav": not public,
            }
            if not req_settings.api_key:
                base["ai"] = (_PUBLIC_KEY_HINT if public else
                              "⚠️ AI 语境解释需要配置 API Key（⚙️ 设置）。")
                return gr.Textbox(value=json.dumps(base, ensure_ascii=False))
            import hashlib
            # v2: the prompt now includes a usage/example section
            key = hashlib.md5(f"v2:{word}\x00{line}".encode()).hexdigest()
            try:
                cache = json.loads(_AI_CACHE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache = {}
            if key not in cache:
                from .llm import LLMClient
                try:
                    resp = LLMClient(req_settings).generate(
                        system_prompt=(
                            "你是英语歌词阅读助手。用户双击了歌词里的一个单词。"
                            "用简体中文回答，不超过 120 字，不要客套，按三行输出："
                            "①语境义：这个词在这句歌词里的含义；"
                            "②整句：这句歌词的通顺翻译；"
                            "③用法：这个词的常见用法/搭配，附一个简短英文例句"
                            "和中文翻译。"),
                        user_message=(f"单词：{word}\n"
                                      f"歌词句：{line}\n出自：《{song}》"),
                    )
                    cache[key] = resp.reply_text.strip()
                    _AI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _AI_CACHE_PATH.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                except Exception as exc:
                    logger.exception("dict AI explain failed")
                    base["ai"] = f"⚠️ LLM 调用失败：{str(exc)[:120]}"
                    return gr.Textbox(
                        value=json.dumps(base, ensure_ascii=False))
            base["ai"] = cache[key]
            return gr.Textbox(value=json.dumps(base, ensure_ascii=False))

        dict_ai_box.change(on_dict_ai, [dict_ai_box, user_llm],
                           [dict_out_box])

        if not public:
            def on_wb_act(payload: str, choice: str):
                act = (payload or "").split("\t")
                head = act[0].strip() if act else ""
                cur = find_song(choice).get("title", "")
                if head.startswith("add:"):
                    word = head[4:]
                    line = act[1] if len(act) > 1 else ""
                    song = act[2] if len(act) > 2 else ""
                    hit = _quote_verifier()(line, song) if line else None
                    book = add_word(
                        word, line=line, song=song,
                        label=(_label_of().get(hit["song_title"], "")
                               if hit else ""),
                        line_index=hit["line_index"] if hit else -1,
                        ai=_cached_dict_ai(word, line))
                    gr.Info(f"📒 已收藏单词 {word}。")
                    return render_wordbook(book, song_title=cur)
                if head.startswith("del:"):
                    book = remove_word(head[4:])
                    return render_wordbook(book, song_title=cur)
                return gr.skip()

            wb_act_box.change(on_wb_act, [wb_act_box, song_radio],
                              [wordbook_html])

        if not public:
            intro_btn.click(on_gen_intro, [song_radio, user_llm], [intro_html])
            mv_btn.click(on_gen_mv, [mv_song_dd, user_llm], [mv_html])

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
                    _render_lyrics_html(data, info, public=public))

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
                "请分析这句歌词与上面哪些歌构成了真正的呼应或互文，"
                "只讨论列表中出现的歌曲，并输出 JSON（不要多余文字）：\n"
                '{"conclusion": "2-3 句总结这组呼应讲了什么",\n'
                ' "quotes": [{"text": "逐字照抄的歌词原句", '
                '"song": "出处歌名"}, ...],\n'
                ' "facts": ["可查证的事实背景（专辑/年份），没有就留空列表"],\n'
                ' "speculation": ["明确属于推测/粉丝理论的内容"]}\n'
                "要求：quotes 里的 text 必须逐字照抄上面给出的歌词，"
                "不得改写、翻译或缩略；无实质关联的检索结果不要引用。"
            )
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt=("你是精通歌词文本分析的音乐评论人。"
                                   "严格按用户要求的 JSON 结构输出，"
                                   "用简体中文。"),
                    user_message=user_msg,
                )
                text = (resp.reply_text or "").strip()
                claims = parse_claims(text)
                if claims is None:
                    # structured check failed -> degrade to plain text
                    yield ("⚠️ 本次输出未通过结构化校验，以下为原始回答：\n\n"
                           + (text or "（空）"))
                    return
                idx = ctx.get("quote_index")
                if idx is None or idx._songs is not ctx["songs"]:
                    idx = QuoteIndex(ctx["songs"])
                    ctx["quote_index"] = idx
                yield render_evidence_card(claims, idx, _label_of())
            except Exception as exc:
                logger.exception("Echo explain failed")
                yield f"⚠️ LLM 调用失败：{str(exc)[:200]}"

        echo_btn.click(on_echo_explain, [echo_state, user_llm], [echo_out])

        # ── 证据卡引用跳转：切歌并高亮那一行（行号由 JS 记忆并滚动）──

        def _quote_verifier():
            idx = ctx.get("quote_index")
            if idx is None or idx._songs is not ctx["songs"]:
                idx = QuoteIndex(ctx["songs"])
                ctx["quote_index"] = idx
            return idx.verify

        def _label_of() -> dict[str, str]:
            return {s.get("title", ""): song_choice_label(s)
                    for s in ctx["songs"]}

        def on_cite_jump(payload: str, sort: str, q: str):
            parts = (payload or "").split("\t")
            label = parts[0].strip() if parts else ""
            if label and label in _filtered_labels(sort, q):
                return gr.Radio(value=label)
            if label:
                gr.Warning("该歌曲不在当前列表中（可能被筛选或已删除）。")
            return gr.skip()

        cite_box.change(
            on_cite_jump, [cite_box, sort_mode, song_filter], [song_radio],
        ).then(on_song_select, [song_radio], song_outputs
        ).then(on_echo_map, [song_radio], [echo_map_box, echo_overview])

        if not public:
            # ── MCP 播放命令通道（lyric-agent mcp 写命令文件，这里轮询）──
            mcp_seen = gr.State(0.0)
            mcp_timer = gr.Timer(1.0)

            def on_mcp_tick(seen: float):
                from .mcp_channel import read_mcp_command
                mtime, cmd = read_mcp_command(seen)
                if cmd is None:
                    return ((mtime if mtime != seen else gr.skip()),
                            gr.skip(), gr.skip())
                payload = json.dumps(
                    {"cmd": cmd.get("cmd"), "title": cmd.get("title", ""),
                     "line": cmd.get("line_index"), "ts": cmd.get("ts")},
                    ensure_ascii=False)
                label = _label_of().get(cmd.get("title", ""))
                if cmd.get("cmd") == "play" and label:
                    return mtime, gr.Radio(value=label), payload
                return mtime, gr.skip(), payload

            # programmatic Radio updates fire song_radio.change in this
            # build (the overview-chip jump relies on the same mechanism),
            # so no explicit re-render chain here — and none is wanted:
            # a .then would re-render on every tick, not just on commands
            mcp_timer.tick(on_mcp_tick, [mcp_seen],
                           [mcp_seen, song_radio, mcp_play_box])

            # a page opened later must not replay an old command
            app.load(
                lambda: (MCP_COMMAND_PATH.stat().st_mtime
                         if MCP_COMMAND_PATH.exists() else 0.0),
                None, [mcp_seen])

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
                return msg, gr.skip(), ""

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
            new_song = next((s for s in ctx["songs"] if s["name"] == slug), None)
            new_label = song_choice_label(new_song) if new_song else None
            status = (
                f"✅ 已添加《{title}》（{lrc_note}）到 `data/songs/{slug}/`。\n\n"
                "已切到「最新在前」排序，它就在左侧歌曲列表**最上方**并已打开。"
                "目前还没有 AI 批注 —— 点击下方按钮生成，"
                f"或在终端运行 `lyric-agent generate data/songs/{slug}`。"
            )
            return (status,
                    gr.Radio(choices=song_choices("added_desc"),
                             value=new_label), slug)

        if not public:
            add_btn.click(
                on_add_song,
                [add_title, add_artist, add_album,
                 add_lrc, add_lrc_file, add_audio_file, sort_mode],
                [add_status, song_radio, add_state],
            ).then(
                # choices come pre-sorted newest-first so the new song is at
                # the TOP; rebuilding choices doesn't fire song_radio.change,
                # so load it explicitly here. song_filter is intentionally
                # NOT an output: clearing it cascades through on_song_filter
                # and re-sorts the list, undoing the newest-first order
                on_song_select, [song_radio], song_outputs,
            ).then(on_echo_map, [song_radio], [echo_map_box, echo_overview]
            ).then(lambda: gr.Radio(value="added_desc"), None, [sort_mode])

        # ── 曲库 ──

        def _cat_matches(q: str) -> list[dict]:
            q = (q or "").strip().lower()
            return catalog if not q else [
                c for c in catalog
                if q in c["title"].lower() or q in c["album"].lower()
                or q in c["artist"].lower()
            ]

        def _have_labels() -> set[str]:
            # a catalog entry counts as "already in the list" when a library
            # song shares its title+artist (slug/casing-proof)
            return {(s["title"], s["artist"]) for s in ctx["songs"]}

        def _cat_choices(q: str) -> list[tuple[str, str]]:
            """(display, value) pairs covering BOTH the built-in catalog and
            the user's own songs. In-library rows (catalog or manually
            added) are badged 已在列表 with a value gradio can't re-add
            (prefixed). Addable catalog rows use the plain 'title — artist'
            value that on_cat_add resolves."""
            have = _have_labels()
            ql = (q or "").strip().lower()
            out = []
            cat_keys = set()
            for c in _cat_matches(q):
                val = f"{c['title']} — {c['artist']}"
                cat_keys.add((c["title"], c["artist"]))
                if (c["title"], c["artist"]) in have:
                    out.append((f"{val}　✓ 已在列表", "__have__" + val))
                else:
                    out.append((val, val))
            # library songs NOT in the catalog (e.g. manual adds) — so a
            # song you added by hand is findable here, not a dead end
            for s in ctx["songs"]:
                key = (s.get("title", ""), s.get("artist", ""))
                if key in cat_keys:
                    continue
                val = f"{key[0]} — {key[1]}"
                if ql and ql not in val.lower():
                    continue
                out.append((f"{val}　✓ 已在列表", "__have__" + val))
            return out

        def _cat_label(choices: list) -> str:
            n_add = sum(1 for _d, v in choices if not v.startswith("__have__"))
            return f"搜索结果（{len(choices)} 首，其中 {n_add} 首可添加）"

        def on_cat_search(q: str):
            ch = _cat_choices(q)
            return gr.CheckboxGroup(choices=ch, value=[],
                                    label=_cat_label(ch))

        def on_cat_all(q: str):
            # select-all = every ADDABLE row in the current search
            ch = _cat_choices(q)
            addable = [v for _d, v in ch if not v.startswith("__have__")]
            return gr.CheckboxGroup(choices=ch, value=addable,
                                    label=_cat_label(ch))

        def on_cat_none():
            return gr.CheckboxGroup(value=[])

        if not public:
            cat_search.change(on_cat_search, [cat_search], [cat_radio])
            cat_all_btn.click(on_cat_all, [cat_search], [cat_radio])
            cat_none_btn.click(on_cat_none, None, [cat_radio])

        def on_cat_add(labels, sort: str):
            if isinstance(labels, str):  # defensive: single-select payloads
                labels = [labels]
            # drop already-in-library rows (their values are prefixed)
            labels = [l for l in (labels or [])
                      if l and not l.startswith("__have__")]
            if not labels:
                return ("⚠️ 请先勾选至少一首可添加的歌"
                        "（标「✓ 已在列表」的无法重复添加）。",
                        gr.skip(), gr.skip())
            added: list[str] = []
            existed: list[str] = []
            missing: list[str] = []
            last_slug = ""
            for label in labels:
                entry = next(
                    (c for c in catalog
                     if f"{c['title']} — {c['artist']}" == label), None)
                if not entry:
                    missing.append(label)
                    continue
                slug = re.sub(r"[^\w]+", "_",
                              entry["title"].lower()).strip("_") \
                    or f"song_{int(time.time())}"
                d = Path(settings.songs_dir) / slug
                if d.exists():
                    # same dir ≠ same song: "ME!" and "Me" share a slug
                    try:
                        have = json.loads(
                            (d / "metadata.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        have = {}
                    if (have.get("title") == entry["title"]
                            and have.get("artist") == entry["artist"]):
                        existed.append(entry["title"])
                        continue
                    slug += "_" + (re.sub(r"[^\w]+", "_",
                                          entry["artist"].lower()).strip("_")
                                   or "x")
                    d = Path(settings.songs_dir) / slug
                    if d.exists():
                        existed.append(entry["title"])
                        continue
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
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                added.append(entry["title"])
                last_slug = slug
            parts = []
            if added:
                shown = "》《".join(added[:8])
                parts.append(f"✅ 新增 {len(added)} 首：《{shown}》"
                             + ("…" if len(added) > 8 else ""))
            if existed:
                parts.append(f"ℹ️ {len(existed)} 首已在列表中")
            if missing:
                parts.append(f"⚠️ {len(missing)} 首未找到")
            if not added:
                return ("　".join(parts), gr.skip(), gr.skip())
            refresh_library()
            new_song = next(
                (s for s in ctx["songs"] if s["name"] == last_slug), None)
            last_label = song_choice_label(new_song) if new_song else None
            parts.append("已切到「最新在前」排序，新增的歌就在列表"
                         "**最上方**。🪄 批注按钮作用于最后新增的一首。")
            return ("　".join(parts),
                    gr.Radio(choices=song_choices("added_desc"),
                             value=last_label),
                    last_slug)

        if not public:
            cat_add_btn.click(on_cat_add, [cat_radio, sort_mode],
                              [add_status, song_radio, add_state]).then(
                # newest-first choices + explicit load; song_filter left out
                # on purpose (see on_add_song wiring)
                on_song_select, [song_radio], song_outputs,
            ).then(on_echo_map, [song_radio], [echo_map_box, echo_overview]
            ).then(lambda: gr.Radio(value="added_desc"), None, [sort_mode])

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

        def _library_updates(keep_choice: str | None, sort: str, q: str):
            """Fresh Radio update after a library change, honoring the
            user's current sort mode and filter text."""
            labels = _filtered_labels(sort, q)
            value = keep_choice if keep_choice in labels else \
                (labels[0] if labels else None)
            return gr.Radio(choices=labels, value=value)

        def on_manage_refresh(choice: str, sort: str, q: str):
            refresh_library()
            _SONG_DATA_CACHE.clear()
            ctx.pop("echo_maps", None)
            gr.Info(f"🔄 已刷新，共 {len(ctx['songs'])} 首歌。")
            return _library_updates(choice, sort, q)

        def on_del_song(payload: str, sort: str, q: str):
            # payload: '<label>\t<ts>' from the ⋯ menu, already confirmed
            # by a native dialog in the browser
            label = (payload or "").split("\t")[0].strip()
            if not label:
                return gr.skip()
            info = next(
                (s for s in ctx["songs"] if song_choice_label(s) == label), None)
            if not info:
                gr.Warning("未找到该歌曲，点「刷新曲库」让列表同步。")
                return gr.skip()
            try:
                shutil.rmtree(info["dir"])
            except Exception as exc:
                logger.exception("Delete song failed")
                gr.Warning(f"删除失败（文件可能被占用）：{str(exc)[:120]}")
                return gr.skip()
            _SONG_DATA_CACHE.pop(info["dir"], None)
            ctx.setdefault("echo_maps", {}).pop(info["dir"], None)
            refresh_library()
            gr.Info(f"🗑️ 已删除《{label}》。")
            return _library_updates(None, sort, q)

        if not public:
            # rebuilding Radio choices never fires .change, so chain the
            # full select pipeline (incl. echo map) explicitly — otherwise
            # deleting the selected song leaves the previous song's 🥚
            # markers/overview on screen
            manage_refresh_btn.click(
                on_manage_refresh, [song_radio, sort_mode, song_filter],
                [song_radio],
            ).then(on_song_select, [song_radio], song_outputs
            ).then(on_echo_map, [song_radio], [echo_map_box, echo_overview])
            del_box.change(
                on_del_song, [del_box, sort_mode, song_filter],
                [song_radio],
            ).then(on_song_select, [song_radio], song_outputs
            ).then(on_echo_map, [song_radio], [echo_map_box, echo_overview])

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
            from .config import user_settings_path
            try:
                sp = user_settings_path()
                current = json.loads(
                    sp.read_text(encoding="utf-8")) if sp.exists() else {}
            except Exception:
                logger.exception("Failed reading user settings — overwriting")
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

        # ── UI 自检（开发者） ──

        def on_ui_probe():
            import subprocess
            import sys as _sys
            root = Path(__file__).resolve().parents[2]
            script = root / "scripts" / "ui_probe.py"
            if not script.exists():
                yield "⚠️ 未找到 scripts/ui_probe.py（需在源码仓库内运行）。", ""
                return
            import importlib.util
            if importlib.util.find_spec("playwright") is None:
                yield ("⚠️ 需要 playwright：`pip install playwright && "
                       "playwright install chromium`"), ""
                return
            yield "⏳ 正在启动独立巡检服务器并打开无头浏览器（约 2-3 分钟）……", ""
            proc = subprocess.Popen(
                [_sys.executable, str(script)], cwd=str(root),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            done = failed = 0
            for line in proc.stdout:
                line = line.strip()
                if line.startswith(("[PASS]", "[FAIL]")):
                    done += 1
                    failed += line.startswith("[FAIL]")
                    yield (f"⏳ 已完成 {done} 项（失败 {failed}）—— "
                           f"`{line[:90]}`"), gr.skip()
            proc.wait()
            report_path = root / "data" / "ui_probe" / "report.json"
            if not report_path.exists():
                yield "⚠️ 巡检未产出报告，请查看终端输出。", ""
                return
            report = json.loads(report_path.read_text(encoding="utf-8"))
            rows = []
            for c in report["checks"]:
                mark = "✅" if c["ok"] else "❌"
                detail = _esc(c["detail"][:160]) if not c["ok"] else ""
                rows.append(
                    f'<tr><td>{mark}</td><td>{_esc(c["id"])}</td>'
                    f'<td>{_esc(c["name"])}</td>'
                    f'<td class="probe-detail">{detail}</td></tr>')
            table = (
                '<table class="probe-table"><tr><th></th><th>ID</th>'
                '<th>检查项</th><th>失败详情</th></tr>'
                + "".join(rows) + "</table>")
            if report["failed"]:
                summary = (f"❌ 巡检完成：{report['passed']} 通过 / "
                           f"**{report['failed']} 失败**。失败截图在 "
                           "`data/ui_probe/`；在终端运行 "
                           "`python scripts/ui_agent.py` 可进入自动修复闭环。")
            else:
                summary = f"✅ 巡检完成：{report['passed']} 项全部通过。"
            yield summary, table

        if not public:
            probe_btn.click(on_ui_probe, None, [probe_out, probe_table])

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

        if not public:
            # suggest existing artists in the manual-add artist field
            app.load(lambda: gr.Dropdown(choices=_corpus_artists()),
                     None, [add_artist])

        # role gating (unconditional — the first version of this sat inside
        # the empty-library else-branch above and never ran with songs
        # present): viewers don't see management tabs. With login disabled
        # (no data/users.json) role_of() says admin for everyone. UI-level
        # only: the JS channel hides tab buttons — handlers are not
        # role-checked server-side (hackathon threat model).
        def _apply_role(request: gr.Request):
            from .auth import role_of
            return role_of(getattr(request, "username", None))

        app.load(_apply_role, None, [role_box])
        if not public:
            # favs_html was frozen at Blocks-construction time; refresh it
            # for each new session/reload from the current file
            def _reload_collections(choice: str):
                title = find_song(choice).get("title", "")
                return _collections_for(title)
            app.load(_reload_collections, [song_radio],
                     [favs_html, wordbook_html])

    return app
