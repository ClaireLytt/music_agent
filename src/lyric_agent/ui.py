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
from .lrc_parser import parse_lrc
from .search import LyricsSearcher

try:
    from .intertextuality.echo_map import ECHO_MAP_CSS
except ImportError:  # embeddings extra not installed — tab shows a hint instead
    ECHO_MAP_CSS = ""

from .universe import UNIVERSE_CSS, UNIVERSE_EMPTY

logger = logging.getLogger(__name__)

from .mv_eggs import MV_CSS, MV_EMPTY
from .ui_assets import _CSS, _HEAD_JS
from .ui_helpers import (  # noqa: F401 — re-exported for cli.py & handlers
    _CATALOG_PATH,
    _CHAT_HINT,
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
    _render_daily_quote,
    _render_echo_html,
    _render_echo_overview,
    _render_emotion_map,
    _render_intro,
    _render_lyrics_html,
    _render_notes,
    _render_search_results,
    _render_word_cloud,
    _save_chat_history,
    _save_notes,
)

# ── App factory ───────────────────────────────────────────

def launch_kwargs() -> dict:
    """Style/head kwargs for app.launch() (Gradio 6 moved them off Blocks)."""
    return {
        "css": _CSS + EVOLUTION_CSS + ECHO_MAP_CSS + UNIVERSE_CSS + MV_CSS,
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
        cache[song_dir] = (cache_key, payload, overview)
        try:
            _ECHO_SCAN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            disk_path.write_text(json.dumps(
                {"key": cache_key, "payload": payload, "overview": overview},
                ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed writing echo scan cache %s", disk_path)
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
                        # side panel: one flat content per icon, the
                        # icon dock sits at the BOTTOM (CSS column-reverse
                        # on #ll-side-dock)
                        with gr.Tabs(elem_id="ll-side-dock"):
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
                                    echo_out = gr.Markdown(
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
                            with gr.Tab("🎬"):
                                with gr.Column(elem_id="ll-mv"):
                                    gr.HTML('<div class="side-panel-title">'
                                            '🎬 MV 彩蛋</div>')
                                    mv_html = gr.HTML(MV_EMPTY)
                                    if not public:
                                        mv_btn = gr.Button(
                                            "🎬 生成 MV 彩蛋", size="sm")
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

            # ══ 页签 3.5: 歌词宇宙侦探 ══
            with gr.Tab("🕵️ 歌词宇宙"):
                gr.Markdown(
                    "彩蛋地图告诉你**哪两首歌呼应**，这里回答**为什么**："
                    "AI 侦探把呼应歌词当证据链，推理这些歌背后是否藏着同一个"
                    "故事宇宙（人物、关系、时间线），每条推断都附歌词证据。"
                    "经典案例：Taylor Swift 的 folklore 三角恋"
                    "（betty / cardigan / august 是同一故事的三个视角）。"
                )
                uni_artist = gr.Dropdown(
                    choices=[], value=None, label="选择歌手",
                    allow_custom_value=True, elem_id="ll-uni-artist")
                with gr.Tabs():
                    with gr.Tab("🕵️ 开始破案"):
                        uni_btn = gr.Button(
                            "🕵️ 开始破案（AI 推理，约 10-30 秒）",
                            variant="primary")
                        uni_html = gr.HTML(UNIVERSE_EMPTY)
                    with gr.Tab("💌 隔空回信"):
                        gr.Markdown("选一对呼应的歌，让前一首的叙事者给"
                                    "后一首写信——信里会原样嵌入两首歌"
                                    "互相呼应的歌词（高亮显示）。")
                        with gr.Row():
                            letter_pair = gr.Dropdown(
                                choices=[], value=None,
                                label="选择歌曲对（按呼应强度排序）",
                                allow_custom_value=True, scale=3,
                                elem_id="ll-letter-pair")
                            letter_btn = gr.Button("💌 写信",
                                                   variant="primary", scale=1)
                        letter_html = gr.HTML("")
                        # last generated letter, kept for the PNG card
                        letter_state = gr.State({})
                        with gr.Row():
                            letter_card_btn = gr.Button("🖼️ 生成信纸卡片",
                                                        size="sm")
                        letter_card_status = gr.Markdown("")
                        letter_card_img = gr.Image(visible=False,
                                                   label="信纸卡片",
                                                   interactive=False)

            # ══ 页签 4: 曲库洞察 ══
            with gr.Tab("📊 曲库洞察"):
                with gr.Tabs():
                    with gr.Tab("📅 每日一句"):
                        daily_html = gr.HTML("")
                    with gr.Tab("☁️ 意象词云"):
                        cloud_artist = gr.Dropdown(
                            choices=[], value=None, label="选择歌手（含全部）",
                            allow_custom_value=True,
                            elem_id="ll-cloud-artist")
                        cloud_html = gr.HTML("")
                        word_trace_html = gr.HTML("")
                        # JS -> backend: clicked word in the cloud
                        word_pick_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-word-pick",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                    with gr.Tab("🎭 情绪地图"):
                        emotion_html = gr.HTML("")
                        # JS -> backend: clicked song on the emotion map
                        emo_pick_box = gr.Textbox(
                            value="", visible=True, elem_id="ll-emo-pick",
                            elem_classes=["ll-hidden"], show_label=False,
                            container=False)
                    with gr.Tab("📖 歌单故事线"):
                        gr.Markdown("勾选几首歌，AI 按情绪弧线给出播放顺序，"
                                    "并讲出这个歌单串成的故事。")
                        story_songs = gr.CheckboxGroup(choices=[],
                                                       label="选择歌曲")
                        story_btn = gr.Button("✨ 生成故事线", size="sm")
                        story_out = gr.Markdown(
                            "", elem_classes=["echo-explain"])

            # ══ 页签 5: 互动（竞猜 + 听歌识曲） ══
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
                    with gr.Tab("🕳️ 歌名挖空"):
                        gr.Markdown("这句歌词唱到了歌名本身——歌名被挖掉了，"
                                    "猜猜被挖掉的是哪首歌的名字。")
                        blank_state = gr.State(
                            {"score": 0, "total": 0, "answer": "", "reveal": ""})
                        blank_html = gr.HTML(
                            '<div class="chat-empty">点「来一题」抽一句'
                            '挖掉歌名的歌词。</div>')
                        blank_options = gr.Radio(choices=[],
                                                 label="被挖掉的歌名是？",
                                                 visible=False)
                        with gr.Row():
                            blank_new_btn = gr.Button("🕳️ 来一题",
                                                      variant="primary", scale=1)
                            blank_submit_btn = gr.Button("🕳️ 选好了", scale=1)
                        blank_result = gr.Markdown("")
                    with gr.Tab("🥚 彩蛋猜猜乐"):
                        gr.Markdown("抽一句有回声的歌词，猜它在同一歌手的"
                                    "哪首歌里被呼应——答完揭晓两句歌词如何"
                                    "互相呼应。")
                        egg_quiz_artist = gr.Dropdown(
                            choices=[], value=None, label="选择歌手",
                            allow_custom_value=True, elem_id="ll-eggq-artist")
                        egg_quiz_state = gr.State(
                            {"score": 0, "total": 0, "answer": "", "reveal": ""})
                        egg_quiz_html = gr.HTML(
                            '<div class="chat-empty">点「抽一题」抽一句'
                            '有回声的歌词。</div>')
                        egg_quiz_options = gr.Radio(
                            choices=[], label="它的回声在哪首歌里？",
                            visible=False)
                        with gr.Row():
                            egg_quiz_new_btn = gr.Button(
                                "🥚 抽一题", variant="primary", scale=1)
                            egg_quiz_submit_btn = gr.Button("🥚 交卷", scale=1)
                        egg_quiz_result = gr.Markdown("")
                    with gr.Tab("🎙️ 听歌识曲"):
                        gr.Markdown("用麦克风录一段（或上传一段音频片段），"
                                    "在你的本地曲库中识别是哪首歌、"
                                    "唱到了哪里。")
                        fp_audio = gr.Audio(sources=["microphone", "upload"],
                                            type="numpy",
                                            label="录一段或上传片段")
                        fp_btn = gr.Button("🔍 识别", variant="primary")
                        fp_result = gr.Markdown("")

            # ══ 页签 6: 添加歌曲（公开版为只读曲库，不提供） ══
            tab_add = None
            if not public:
                with gr.Tab("➕ 添加歌曲") as tab_add:
                    catalog = _load_catalog()
                    cat_labels = [f"{c['title']} — {c['artist']}" for c in catalog]
                    gr.Markdown(
                        f"### 从曲库添加（推荐）\n"
                        f"内置 {len(catalog)} 首中外热门歌曲（带时间戳歌词），"
                        "搜索后勾选一首或多首，一键添加到你的列表。"
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
            with gr.Tab("⚙️ 设置") as tab_settings:
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

                    gr.Markdown(
                        "---\n### 🧪 UI 自检（开发者）\n"
                        "启动一个**独立的**巡检服务器实例，用真实浏览器逐页签走查 "
                        "22+ 项交互（含 JS 报错与服务端异常收集），约 2-3 分钟。"
                        "发现问题后可在终端运行 `python scripts/ui_agent.py` "
                        "进入自动修复闭环（改代码需重启，故修复环节不在网页内进行）。"
                    )
                    probe_btn = gr.Button("🧪 运行 UI 巡检")
                    probe_out = gr.Markdown("")
                    probe_table = gr.HTML("")

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
                        gr.Dropdown(choices=[], value=None), _ECHO_NO_INDEX,
                        gr.Dropdown(choices=[], value=None),
                        gr.Dropdown(choices=[], value=None),
                        gr.Dropdown(choices=[], value=None))
            from .intertextuality.search import artist_matches
            info = find_song(choice) if ctx["songs"] else {}
            current = info.get("artist", "")
            value = next(
                (a for a in artists if current and artist_matches(a, current)),
                artists[0])
            graph, _net = _map_graph(value)
            dd, focus = _focus_dd(graph, preferred=info.get("title"))
            all_choices = artists + [_CROSS_ARTIST_CHOICE]
            pairs = _pair_choices(value)
            return (gr.Dropdown(choices=all_choices, value=value),
                    dd, _render_map(value, "focus", focus),
                    gr.Dropdown(choices=all_choices, value=value),
                    gr.Dropdown(choices=pairs,
                                value=pairs[0] if pairs else None),
                    gr.Dropdown(choices=all_choices, value=value))

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

        # .input (not .change): programmatic updates from init_echo_map must
        # not re-trigger these handlers, or the default focus gets overwritten
        # shared concurrency_id: these four all repaint echo_map_html.
        # Without it gradio may run them in parallel, and a slow render
        # (first cross-artist build) can finish AFTER a fast one and paint
        # a stale graph over the fresh one.
        map_artist.input(on_map_artist, [map_artist, map_view],
                         [map_focus, echo_map_html, map_explain_out],
                         concurrency_id="echo-map")
        map_view.input(on_map_view, [map_view, map_artist, map_focus],
                       [map_focus, echo_map_html],
                       concurrency_id="echo-map")
        map_focus.input(on_map_focus, [map_focus, map_artist, map_view],
                        [echo_map_html],
                        concurrency_id="echo-map")
        focus_pick_box.change(on_focus_pick, [focus_pick_box, map_artist],
                              [map_focus, map_view, echo_map_html],
                              concurrency_id="echo-map")
        app.load(init_echo_map, [song_radio],
                 [map_artist, map_focus, echo_map_html,
                  uni_artist, letter_pair, egg_quiz_artist])

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

        # ── 歌词宇宙侦探 & 隔空回信 ──

        def _uni_msg(text: str) -> str:
            return f'<div class="chat-empty">{text}</div>'

        def _pair_choices(artist: str) -> list[str]:
            """Labels for the letter dropdown; index-aligned with edges."""
            graph, _net = _map_graph(artist)
            if graph is None:
                return []
            return [f"《{e.song_a}》 ↔ 《{e.song_b}》（{e.count} 处呼应）"
                    for e in graph.edges[:20]]

        def on_uni_artist(artist: str):
            choices = _pair_choices(artist) if artist else []
            return gr.Dropdown(choices=choices,
                               value=choices[0] if choices else None)

        def on_universe(artist: str, user_cfg):
            """LLM detective: echo edges as an evidence dossier → story."""
            if not artist:
                yield _uni_msg("⚠️ 请先选择歌手。")
                return
            graph, _net = _map_graph(artist)
            if graph is None:
                yield _ECHO_NO_INDEX
                return
            if not graph.edges:
                yield _uni_msg("⚠️ 当前范围没有可推理的彩蛋呼应。")
                return
            req_settings = _request_settings(user_cfg)
            from .intertextuality.search import artist_matches
            from .universe import (
                detective_messages, extract_name_lines, parse_universe,
                render_universe_html)
            index = _echo_index()
            cross = artist == _CROSS_ARTIST_CHOICE
            name_lines = extract_name_lines(
                (line.song, line.text) for line in index[1]
                if cross or artist_matches(artist, line.artist))
            songs = [(nd.song, nd.album) for nd in graph.nodes]
            edges = [(e.song_a, e.song_b, e.count,
                      [(p.line_a, p.line_b)
                       for p in (e.examples or [e.example])])
                     for e in graph.edges]
            scope = "多位歌手之间（跨歌手引用）" if cross else artist
            system, user_msg = detective_messages(scope, songs, edges,
                                                  name_lines)
            # disk cache: same evidence + same model ⇒ same verdict. Keyed
            # on the full prompt hash, so corpus / threshold / model changes
            # invalidate it naturally (echo-scan cache pattern).
            import hashlib
            cache_key = [hashlib.md5(user_msg.encode("utf-8")).hexdigest(),
                         req_settings.model_name]
            cache_path = Path("data/cache/universe") / (
                re.sub(r"[^\w\u4e00-\u9fff-]+", "_", artist) + ".json")
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
            if cached and cached.get("key") == cache_key:
                yield (render_universe_html(
                           parse_universe(cached.get("payload"), scope))
                       + '<div class="preview-hint">⚡ 来自缓存 —— '
                       '语料或模型变更后会自动重新推理</div>')
                return
            if public and not req_settings.api_key:
                yield _uni_msg(_PUBLIC_KEY_HINT)
                return
            yield _uni_msg(f"🕵️ 正在勘查 {len(graph.edges)} 条呼应线索，"
                           "推理故事宇宙……（约 10-30 秒）")
            from .llm import LLMClient
            try:
                data = LLMClient(req_settings).generate_json(system, user_msg)
            except Exception as exc:
                logger.exception("Universe detective failed")
                yield _uni_msg(f"⚠️ AI 推理失败：{str(exc)[:200]}")
                return
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"key": cache_key, "payload": data},
                               ensure_ascii=False),
                    encoding="utf-8")
            except OSError:
                logger.warning("universe cache write failed", exc_info=True)
            yield render_universe_html(parse_universe(data, scope))

        def on_letter(artist: str, pair_label: str, user_cfg):
            """One echo edge → a letter from song A's narrator to song B."""
            if not artist or not pair_label:
                yield _uni_msg("⚠️ 请先选择歌手和歌曲对。"), gr.skip()
                return
            graph, _net = _map_graph(artist)
            edge = None
            if graph is not None:
                labels = _pair_choices(artist)
                if pair_label in labels:
                    edge = graph.edges[labels.index(pair_label)]
            if edge is None:
                yield _uni_msg("⚠️ 未找到该歌曲对，请重新选择。"), gr.skip()
                return
            req_settings = _request_settings(user_cfg)
            if public and not req_settings.api_key:
                yield _uni_msg(_PUBLIC_KEY_HINT), gr.skip()
                return
            yield _uni_msg("💌 正在代笔写信……（约 5-15 秒）"), gr.skip()
            from .universe import letter_messages, render_letter_html
            system, user_msg = letter_messages(
                edge.song_a, edge.song_b,
                edge.example.line_a, edge.example.line_b, edge.count)
            from .llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(system, user_msg)
            except Exception as exc:
                logger.exception("Letter failed")
                yield _uni_msg(f"⚠️ LLM 调用失败：{str(exc)[:200]}"), gr.skip()
                return
            body = (resp.reply_text or "").strip()
            if not body:
                yield _uni_msg("⚠️ AI 未返回内容，请重试。"), gr.skip()
                return
            yield (render_letter_html(edge.song_a, edge.song_b, body,
                                      edge.example.line_a,
                                      edge.example.line_b),
                   {"song_a": edge.song_a, "song_b": edge.song_b,
                    "body": body, "line_a": edge.example.line_a,
                    "line_b": edge.example.line_b})

        def on_letter_card(state: dict):
            state = state or {}
            if not state.get("body"):
                return (gr.Image(visible=False),
                        "⚠️ 请先点「💌 写信」生成一封信。")
            from .share_card import render_letter_card
            try:
                path = render_letter_card(
                    state["song_a"], state["song_b"], state["body"],
                    state.get("line_a", ""), state.get("line_b", ""))
            except Exception as exc:
                logger.exception("Letter card failed")
                return (gr.Image(visible=False),
                        f"⚠️ 卡片生成失败：{_esc(str(exc)[:150])}")
            return (gr.Image(value=path, visible=True),
                    f"✅ 已保存：`{path}`")

        uni_artist.input(on_uni_artist, [uni_artist], [letter_pair])
        uni_btn.click(on_universe, [uni_artist, user_llm], [uni_html])
        letter_card_btn.click(on_letter_card, [letter_state],
                              [letter_card_img, letter_card_status])
        letter_btn.click(on_letter, [uni_artist, letter_pair, user_llm],
                         [letter_html, letter_state])

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

        # ── 歌名挖空 ──

        def on_blank_new(state: dict):
            from .quiz import make_blank_question
            q = make_blank_question(_quiz_pool())
            if q is None:
                return (dict(state or {}, answer="", reveal=""),
                        '<div class="chat-empty">曲库里还没有「歌词唱到歌名」'
                        '的歌（且至少需要 2 首歌）。</div>',
                        gr.Radio(choices=[], visible=False), "")
            state = dict(state or {}, answer=q.answer, reveal=q.original)
            html_q = (f'<div class="quiz-line blank-line">“{_esc(q.line)}”</div>'
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
                verdict = f"✅ 答对了！挖掉的正是《{answer}》。"
            else:
                verdict = f"❌ 不对，挖掉的是《{answer}》。"
            reveal = state.get("reveal", "")
            state["answer"] = ""  # one submission per question
            return (state, f"{verdict}\n\n> {reveal}\n\n当前战绩 "
                    f"**{state.get('score', 0)} / {state['total']}**")

        blank_new_btn.click(on_blank_new, [blank_state],
                            [blank_state, blank_html, blank_options,
                             blank_result])
        blank_submit_btn.click(on_blank_submit, [blank_state, blank_options],
                               [blank_state, blank_result])

        # ── 彩蛋猜猜乐 ──

        def on_egg_quiz_new(artist: str, state: dict):
            state = dict(state or {}, answer="", reveal="")
            if not artist:
                return (state,
                        '<div class="chat-empty">请先选择歌手。</div>',
                        gr.Radio(choices=[], visible=False), "")
            graph, _net = _map_graph(artist)
            from .egg_quiz import make_echo_question
            q = make_echo_question(graph)
            if q is None:
                return (state,
                        '<div class="chat-empty">该范围的彩蛋呼应不足以'
                        '出题，换一位歌手试试。</div>',
                        gr.Radio(choices=[], visible=False), "")
            reveal = (f"《{q.source_song}》唱道：“{q.line}”\n\n"
                      f"《{q.answer}》回应：“{q.echo_line}”\n\n"
                      f"这两首歌之间共有 {q.count} 处呼应。")
            state.update(answer=q.answer, reveal=reveal)
            html_q = (f'<div class="quiz-line">“{_esc(q.line)}”</div>'
                      f'<div class="quiz-meta">出自《{_esc(q.source_song)}》'
                      '——这句歌词的回声藏在哪首歌里？</div>')
            return (state, html_q,
                    gr.Radio(choices=q.options, value=None, visible=True),
                    "")

        def on_egg_quiz_submit(state: dict, choice: str):
            state = dict(state or {})
            answer = state.get("answer", "")
            if not answer:
                return state, "⚠️ 先点「抽一题」抽题。"
            if not choice:
                return state, "⚠️ 请先选择一个选项。"
            state["total"] = state.get("total", 0) + 1
            if choice == answer:
                state["score"] = state.get("score", 0) + 1
                verdict = f"✅ 答对了！回声就在《{answer}》。"
            else:
                verdict = f"❌ 不对，回声在《{answer}》。"
            reveal = state.get("reveal", "")
            state["answer"] = ""
            return (state, f"{verdict}\n\n{reveal}\n\n当前战绩 "
                    f"**{state.get('score', 0)} / {state['total']}**")

        egg_quiz_new_btn.click(
            on_egg_quiz_new, [egg_quiz_artist, egg_quiz_state],
            [egg_quiz_state, egg_quiz_html, egg_quiz_options,
             egg_quiz_result])
        egg_quiz_submit_btn.click(
            on_egg_quiz_submit, [egg_quiz_state, egg_quiz_options],
            [egg_quiz_state, egg_quiz_result])

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
                artist=info.get("artist", ""),
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

        def on_gen_mv(choice: str, user_cfg):
            from .mv_eggs import (
                load_mv, mv_messages, parse_mv, render_mv_html, save_mv)
            if not ctx["songs"]:
                yield MV_EMPTY
                return
            info = find_song(choice)
            title = info.get("title", "")
            artist = info.get("artist", "")
            existing = load_mv(info["dir"])
            if existing is not None:
                yield render_mv_html(parse_mv(existing), title, artist)
                return
            req_settings = _request_settings(user_cfg)
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
            save_mv(info["dir"], data)
            yield render_mv_html(parse_mv(data), title, artist)

        if not public:
            intro_btn.click(on_gen_intro, [song_radio, user_llm], [intro_html])
            mv_btn.click(on_gen_mv, [song_radio, user_llm], [mv_html])

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

        def _cat_filter(q: str) -> list[str]:
            q = (q or "").strip().lower()
            items = catalog if not q else [
                c for c in catalog
                if q in c["title"].lower() or q in c["album"].lower()
                or q in c["artist"].lower()
            ]
            return [f"{c['title']} — {c['artist']}" for c in items]

        def on_cat_search(q: str):
            labels = _cat_filter(q)
            return gr.CheckboxGroup(choices=labels, value=[],
                                    label=f"曲库歌曲（{len(labels)} 首）")

        def on_cat_all(q: str):
            # select-all applies to the CURRENT search filter
            labels = _cat_filter(q)
            return gr.CheckboxGroup(choices=labels, value=labels,
                                    label=f"曲库歌曲（{len(labels)} 首）")

        def on_cat_none():
            return gr.CheckboxGroup(value=[])

        if not public:
            cat_search.change(on_cat_search, [cat_search], [cat_radio])
            cat_all_btn.click(on_cat_all, [cat_search], [cat_radio])
            cat_none_btn.click(on_cat_none, None, [cat_radio])

        def on_cat_add(labels, sort: str):
            if isinstance(labels, str):  # defensive: single-select payloads
                labels = [labels]
            labels = [l for l in (labels or []) if l]
            if not labels:
                return ("⚠️ 请先在曲库中勾选至少一首歌。",
                        gr.skip(), gr.skip(), gr.skip())
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
                return "　".join(parts), gr.skip(), gr.skip(), gr.skip()
            refresh_library()
            new_choices = song_choices(sort)
            new_song = next(
                (s for s in ctx["songs"] if s["name"] == last_slug), None)
            new_label = song_choice_label(new_song) if new_song else None
            parts.append("已切换到最后新增的一首；🪄 批注按钮只作用于它。")
            return ("　".join(parts),
                    gr.Radio(choices=new_choices, value=new_label), last_slug,
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
        else:
            # role gating: viewers don't see management tabs. With login
            # disabled (no data/users.json) role_of() says admin for all.
            _admin_tabs = [t for t in (tab_add, tab_settings) if t is not None]

            def _apply_role(request: gr.Request):
                from .auth import role_of
                admin = role_of(getattr(request, "username", None)) == "admin"
                return [gr.Tab(visible=admin) for _ in _admin_tabs]

            app.load(_apply_role, None, _admin_tabs)
            app.load(lambda: render_evolution_html(ctx["evolution"], lang="zh"),
                     None, [evolution_html])

    return app
