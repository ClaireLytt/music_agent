"""页签「🎧 播放解读」：布局 + 核心 handler（选歌/点句/问答/收藏/查词/笔记）.

⚙️ 歌曲工具子坞的组件也在这里创建（必须常驻播放页 DOM），
但其 handler 接线在 tab_play_tools.py。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import gradio as gr

from ..audio_provider import resolve as resolve_audio
from ..debate import DebateSession, speak as ai_speak
from ..dictionary import (add_word, is_phrase, load_wordbook,
                          lookup as dict_lookup, remove_word)

from ..ui_helpers import (
    _ANN_HINT,
    _CHAT_HINT,
    _CHAT_TOPIC_DEFAULT,
    _INTRO_EMPTY,
    _INTRO_FILENAME,
    _chat_topic_html,
    _esc,
    _load_chat_history,
    _load_favorites,
    _load_intro,
    _load_notes,
    _load_song_data,
    _render_chat,
    _render_favorites,
    _render_intro,
    _render_lyrics_html,
    _render_notes,
    _save_chat_history,
    _save_favorites,
    _save_notes,
    render_annotation_card,
    render_wordbook,
)
from .runtime import PUBLIC_KEY_HINT as _PUBLIC_KEY_HINT, Runtime

logger = logging.getLogger(__name__)


def build(rt: Runtime, ui) -> None:
    """布局：三栏 + 侧边图标坞 + 隐藏 JS 通道（组件挂到 ui 命名空间）。"""
    public = rt.public
    with gr.Tab("🎧 播放解读", id="play"):
        with gr.Row(elem_id="ll-play-row"):
            # ── 左栏: 歌曲 + 搜索 ──
            with gr.Column(scale=1, min_width=230,
                           elem_id="ll-sidebar",
                           elem_classes=["ll-card"]):
                choices = rt.song_choices()
                # 黄金路径：默认落在主打歌 cardigan（不在库时回退第一首）
                default_choice = next(
                    (c for c in choices
                     if c == "cardigan"
                     or c.startswith("cardigan — ")),
                    choices[0] if choices else None,
                )
                with gr.Accordion(
                        "🎵 歌曲列表" if choices
                        else "🎵 歌曲列表（空 — 去「添加歌曲」页签）",
                        open=True, elem_id="ll-songs-acc"):
                    # 筛选 + 排序收进一个折叠面板，默认收起
                    with gr.Accordion("🎛 筛选 / 排序", open=False,
                                      elem_id="ll-tools-acc"):
                        with gr.Row(elem_id="ll-filter-row"):
                            ui.song_filter = gr.Textbox(
                                placeholder="筛选歌名 / 歌手 / 搜歌词 …",
                                show_label=False, container=False,
                                elem_id="ll-song-filter", scale=5)
                            ui.filter_clear_btn = gr.Button(
                                "✕", size="sm", scale=1, min_width=36,
                                elem_id="ll-filter-clear")
                        ui.sort_mode = gr.Radio(
                            choices=[
                                ("添加顺序（最早在前）", "added_asc"),
                                ("添加顺序（最新在前）", "added_desc"),
                                ("专辑（按字母排序）", "album_asc"),
                                ("歌手（按字母排序）", "artist_asc"),
                            ],
                            value="added_desc", label="🎛️ 排序")
                    ui.song_radio = gr.Radio(
                        choices=choices,
                        show_label=False,
                        value=default_choice,
                        elem_id="ll-songs",
                    )
                if not public:
                    # delete rides the per-song ⋯ menu (JS):
                    # the menu confirms, then writes the label here
                    ui.del_box = gr.Textbox(
                        value="", visible=True,
                        elem_id="ll-del-song",
                        elem_classes=["ll-hidden"],
                        show_label=False, container=False)
                    # 隐藏通道必须常驻 DOM：之前随工具搬进 ⚙️
                    # 懒加载子页签后，歌词区按钮写通道静默落空
                    # backend -> JS: 偏移实时预览值
                    ui.offset_box = gr.Textbox(
                        value="", visible=True,
                        elem_id="ll-offset-set",
                        elem_classes=["ll-hidden"],
                        show_label=False, container=False)
                    # JS -> backend: 视频 搜索/候选/解绑
                    ui.bvid_box = gr.Textbox(
                        value="", visible=True,
                        elem_id="ll-bvid-act",
                        elem_classes=["ll-hidden"],
                        show_label=False, container=False)
            # ── 中栏: 歌词 ──
            with gr.Column(scale=3, elem_classes=["ll-card"]):
                ui.lyrics_html = gr.HTML("")

            # ── 右栏: AI 助手 ──
            with gr.Column(scale=2, min_width=320,
                           elem_classes=["ll-card"]):
                gr.HTML('<div class="side-panel-title">💬 AI 助手</div>')
                ui.chat_state = gr.State(None)
                ui.chat_topic = gr.HTML(_CHAT_TOPIC_DEFAULT)
                ui.chat_html = gr.HTML(_CHAT_HINT)
                with gr.Row():
                    ui.chat_input = gr.Textbox(
                        placeholder="针对这句歌词提问 ...",
                        show_label=False, scale=4, container=False)
                    ui.chat_send = gr.Button("提问", scale=1,
                                             variant="primary")
                # side panel: one flat content per icon, the
                # icon dock sits at the BOTTOM (CSS column-reverse
                # on #ll-side-dock)
                with gr.Tabs(elem_id="ll-side-dock",
                             elem_classes=["ll-icon-dock"]):
                    with gr.Tab("✏️"):
                        with gr.Column(elem_id="ll-ann"):
                            gr.HTML('<div class="side-panel-title">'
                                    '✏️ 本句 AI 批注</div>')
                            ui.ann_html = gr.HTML(_ANN_HINT)
                            # JS -> backend: 确认后为本句生成批注
                            # ("<idx>	<ts>")
                            ui.gen_ann_box = gr.Textbox(
                                value="", visible=True,
                                elem_id="ll-gen-ann",
                                elem_classes=["ll-hidden"],
                                show_label=False, container=False)
                    with gr.Tab("📖"):
                        with gr.Column(elem_id="ll-intro"):
                            gr.HTML('<div class="side-panel-title">'
                                    '📖 歌曲导读</div>')
                            ui.intro_html = gr.HTML(_INTRO_EMPTY)
                            if not public:
                                ui.intro_btn = gr.Button(
                                    "🪄 生成 30 秒导读", size="sm")
                    if not public:
                        with gr.Tab("⭐"):
                            with gr.Column(elem_id="ll-favs"):
                                gr.HTML('<div class="side-panel-title">'
                                        '⭐ 歌词收藏夹</div>')
                                ui.fav_add_btn = gr.Button(
                                    "⭐ 收藏当前选中的歌词", size="sm")
                                ui.fav_status = gr.Markdown("")
                                ui.favs_html = gr.HTML(
                                    _render_favorites(_load_favorites()))
                    # 📒/🧩 共享同一次单词本读取(一次 IO)
                    _book0 = load_wordbook()
                    with gr.Tab("📒"):
                        with gr.Column(elem_id="ll-wordbook"):
                            gr.HTML('<div class="side-panel-title">'
                                    '📒 单词本</div>')
                            ui.wordbook_html = gr.HTML(
                                render_wordbook(_book0))
                    with gr.Tab("🧩"):
                        with gr.Column(elem_id="ll-phrasebook"):
                            gr.HTML('<div class="side-panel-title">'
                                    '🧩 词组本</div>')
                            ui.phrasebook_html = gr.HTML(
                                render_wordbook(_book0,
                                                phrases=True))
                    with gr.Tab("📝"):
                        with gr.Column(elem_id="ll-notes"):
                            gr.HTML('<div class="side-panel-title">'
                                    '📝 听歌笔记</div>')
                            ui.notes_html = gr.HTML(_render_notes([]))
                            with gr.Row():
                                ui.note_input = gr.Textbox(
                                    placeholder="在当前播放位置记一句感想…",
                                    show_label=False, scale=4,
                                    container=False)
                                ui.note_add_btn = gr.Button(
                                    "添加", scale=1, size="sm")
                    if not public:
                        with gr.Tab("⚙️"):
                            with gr.Accordion("🎵 为当前歌曲上传音频",
                                              open=False,
                                              elem_id="ll-audio-up"):
                                ui.audio_file_up = gr.File(
                                    label="拖拽 mp3 / wav / flac 文件到这里",
                                    file_types=[".mp3", ".wav", ".flac",
                                                ".ogg", ".m4a"])
                                ui.audio_up_status = gr.Markdown("")
                            with gr.Accordion("🎚 歌词时间校准", open=False):
                                gr.Markdown(
                                    "歌词快/慢半拍时微调（正值 = 歌词提前）。"
                                    "拖动即实时预览，满意后保存。",
                                    elem_id=None)
                                ui.offset_slider = gr.Slider(
                                    minimum=-5000, maximum=5000, step=50,
                                    value=0, label="偏移 (ms)")
                                ui.offset_save_btn = gr.Button("保存偏移",
                                                               size="sm")
                                ui.offset_status = gr.Markdown("")
                            with gr.Accordion("📺 关联 B 站视频（BV 号/链接）",
                                              open=False):
                                ui.bvid_input = gr.Textbox(
                                    placeholder="粘贴 BV 号或视频链接；"
                                                "留空保存 = 解绑",
                                    show_label=False, container=False)
                                ui.bvid_save_btn = gr.Button("保存",
                                                             size="sm")
                                gr.HTML(
                                    '<a class="bv-goto" '
                                    'href="https://www.bilibili.com/" '
                                    'target="_blank" rel="noopener">'
                                    '↗ 跳转到 B 站</a>')
                                ui.bvid_status = gr.Markdown("")
                            ui.trans_btn = gr.Button(
                                "🀄 显示中文翻译（英文歌·首次生成调用 LLM，"
                                "之后永久缓存）", size="sm")
                            ui.manage_refresh_btn = gr.Button(
                                "🔄 刷新曲库（手动增删过歌曲目录后同步）",
                                size="sm", elem_id="ll-refresh-btn")
                ui.line_pick = gr.Textbox(
                    value="", visible=True, elem_id="ll-line-pick",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                # backend -> JS channel: whole-song echo map (🥚 markers)
                # JS -> backend: current audio position (for notes)
                ui.cur_time_box = gr.Textbox(
                    value="0", visible=True, elem_id="ll-cur-time",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                # JS -> backend: favorite entry clicks
                # ("jump:<i>" / "del:<i>")
                ui.fav_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-fav-act",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                # JS -> backend: evidence-card citation jumps
                # ("<label>\t<line_index>\t<ts>")
                ui.cite_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-cite-jump",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                if not public:
                    # backend -> JS: MCP play-command relay
                    # (`lyric-agent mcp` writes a command file; a
                    # timer polls it and JS starts playback)
                    ui.mcp_play_box = gr.Textbox(
                        value="", visible=True, elem_id="ll-mcp-play",
                        elem_classes=["ll-hidden"], show_label=False,
                        container=False)
                # JS -> backend: double-clicked word ("word\tline\tsong\tts")
                ui.dict_pick_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-dict-pick",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                # backend -> JS: dictionary/AI result JSON for the popover
                ui.dict_out_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-dict-out",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                # JS -> backend: "✨ AI 语境解释" requests
                ui.dict_ai_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-dict-ai",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)
                if not public:
                    # JS -> backend: wordbook add/del
                    ui.wb_act_box = gr.Textbox(
                        value="", visible=True, elem_id="ll-wb-act",
                        elem_classes=["ll-hidden"], show_label=False,
                        container=False)
                # JS -> backend: delete-note clicks (note index)
                ui.note_del_box = gr.Textbox(
                    value="", visible=True, elem_id="ll-note-del",
                    elem_classes=["ll-hidden"], show_label=False,
                    container=False)


def wire(rt: Runtime, ui) -> None:
    """核心 handler 接线（选歌/筛选/点句/问答/收藏/查词/笔记/引文跳转）。"""
    public = rt.public
    ctx = rt.cache
    find_song = rt.find_song
    song_choices = rt.song_choices
    song_choice_label = rt.song_choice_label
    _request_settings = rt.request_settings
    find_echoes = rt.find_echoes
    _artist_motifs = rt.artist_motifs
    _label_of = rt.label_of
    _quote_verifier = rt.quote_verifier
    _filtered_labels = rt.filtered_labels

    song_radio, sort_mode, song_filter = (ui.song_radio, ui.sort_mode,
                                          ui.song_filter)
    lyrics_html, user_llm = ui.lyrics_html, ui.user_llm

    def _collections_for(title: str) -> tuple:
        """收藏歌词 + 单词本, both scoped to the open song."""
        if public:
            return ()
        book = load_wordbook()
        return (_render_favorites(_load_favorites(), song_title=title),
                render_wordbook(book, song_title=title),
                render_wordbook(book, song_title=title, phrases=True))

    def on_song_select(choice: str):
        if not ctx["songs"]:
            return ("", None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT,
                    _INTRO_EMPTY,
                    _render_notes([]), _ANN_HINT) + _collections_for("")
        info = find_song(choice)
        audio = resolve_audio(info["dir"])
        info["audio_type"], info["audio_src"] = (audio.type,
                                                 audio.path_or_url or "")
        data = _load_song_data(info["dir"])
        lyrics = _render_lyrics_html(data, info, public=public)
        intro = _render_intro(_load_intro(info["dir"]))
        return (lyrics, None, _CHAT_TOPIC_DEFAULT, _CHAT_HINT,
                intro, _notes_for(info),
                _ANN_HINT) + _collections_for(info["title"])

    song_outputs = [lyrics_html, ui.chat_state, ui.chat_topic, ui.chat_html,
                    ui.intro_html, ui.notes_html,
                    ui.ann_html]
    if not public:
        # the two per-song collections re-render on every song switch
        song_outputs += [ui.favs_html, ui.wordbook_html, ui.phrasebook_html]

    # 跨 tab 复用：管理/添加歌曲的 .then 链、app.load 启动序列都要它们
    ui.on_song_select = on_song_select
    ui.song_outputs = song_outputs
    ui.collections_for = _collections_for

    song_radio.change(on_song_select, [song_radio], song_outputs)

    # ── 歌单筛选 / 排序 ──

    def on_song_filter(q: str, sort: str):
        # choices-only update: the current selection (and playback)
        # stays untouched even while filtered out of view
        return gr.Radio(choices=_filtered_labels(sort, q))

    # .change, not .input: mirrors cat_search — .input never reached
    # the backend for this textbox (zero API calls observed)
    song_filter.change(on_song_filter, [song_filter, sort_mode],
                       [song_radio])
    # ✕ 取消筛选：清空输入 → 上面的 .change 自然恢复完整列表
    ui.filter_clear_btn.click(lambda: "", None, [song_filter])

    def on_sort(sort: str, choice: str, q: str):
        labels = _filtered_labels(sort, q)
        value = choice if choice in labels else (labels[0] if labels
                                                 else None)
        return gr.Radio(choices=labels, value=value)

    sort_mode.change(on_sort, [sort_mode, song_radio, song_filter],
                     [song_radio])

    # ── AI 助手（行级问答）──

    def _line_dossier(line_text: str, info: dict,
                      echoes: list[dict] | None) -> str:
        """机器检索到的行级互文档案 for the AI context."""
        parts = []
        for r in (echoes or [])[:3]:
            parts.append(f"- 《{r['song']}》：“{r['line']}”"
                         f"（相似度 {r['similarity']}）")
        motifs = _artist_motifs(info.get("artist", ""))
        words = [w for w in re.findall(
                     r"[a-zA-Z']{3,}|[一-鿿]{2,}",
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
                    gr.skip())
        idx = int(idx_str)
        info = find_song(choice)
        data = _load_song_data(info["dir"])
        line = next((ln for ln in data["timed_lines"]
                     if ln.line_index == idx), None)
        if line is None:
            return (session, _CHAT_TOPIC_DEFAULT, _render_chat(session),
                    gr.skip())
        if session is not None and session.lyric_line == line.text \
                and session.line_index == idx:
            return (session, _chat_topic_html(line.text),
                    _render_chat(session), gr.skip())
        # annotations stay out of the UI but still feed the AI as context
        ann = data["annotations"].get(idx)
        # public mode: visitors must not see each other's saved Q&A
        saved = None if public \
            else _load_chat_history(info["dir"]).get(str(idx))
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
        return (session, _chat_topic_html(line.text), _render_chat(session),
                render_annotation_card(ann, idx, can_generate=not public))

    ui.line_pick.change(on_line_pick,
                        [ui.line_pick, song_radio, ui.chat_state],
                        [ui.chat_state, ui.chat_topic, ui.chat_html,
                         ui.ann_html])

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
        from ..annotator.engine import regenerate_annotation
        from ..annotator.models import Song, SongMetadata
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

    ui.gen_ann_box.change(on_gen_ann,
                          [ui.gen_ann_box, song_radio, user_llm],
                          [ui.ann_html])

    def on_chat_send(session, user_text: str, choice: str, user_cfg):
        text = (user_text or "").strip()
        if not text:
            yield session, _render_chat(session), user_text
            return
        if session is None:
            yield (session,
                   '<div class="chat-empty">请先点击左侧一句歌词，'
                   '再提问。</div>',
                   user_text)
            return
        req_settings = _request_settings(user_cfg)
        if public and not req_settings.api_key:
            yield (session, _render_chat(session, live=_PUBLIC_KEY_HINT),
                   user_text)
            return
        session.history.append({"speaker": "user", "text": text})
        partial = ""
        for delta in ai_speak(req_settings, session, "assistant",
                              user_prompt=text):
            partial += delta
            yield session, _render_chat(session, live=partial), ""
        # speak() skips history append on warning/error paths — keep the
        # rendered transcript consistent by appending whatever streamed
        if partial and session.history \
                and session.history[-1]["speaker"] == "user":
            session.history.append({"speaker": "🤖 AI 助手",
                                    "text": partial})
        if not public and session.line_index >= 0 and partial \
                and not partial.startswith("⚠️"):
            info = find_song(choice)
            if info.get("dir"):
                _save_chat_history(info["dir"], session.line_index,
                                   session.lyric_line, session.history)
        yield session, _render_chat(session), ""

    ui.chat_send.click(on_chat_send,
                       [ui.chat_state, ui.chat_input, song_radio, user_llm],
                       [ui.chat_state, ui.chat_html, ui.chat_input])
    ui.chat_input.submit(on_chat_send,
                         [ui.chat_state, ui.chat_input, song_radio,
                          user_llm],
                         [ui.chat_state, ui.chat_html, ui.chat_input])

    # ── 歌曲导读 ──

    def on_gen_intro(choice: str, user_cfg):
        if not ctx["songs"]:
            yield _INTRO_EMPTY
            return
        info = find_song(choice)
        req_settings = _request_settings(user_cfg)
        if not req_settings.api_key:
            yield ('<div class="chat-empty">⚠️ 未配置 API Key，'
                   '无法生成导读。请到「⚙️ 设置」页签填写。</div>')
            return
        existing = _load_intro(info["dir"])
        if existing:
            yield _render_intro(existing)
            return
        yield ('<div class="chat-empty">🪄 AI 正在通读整首歌词，'
               '生成导读……</div>')
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
        from ..llm import LLMClient
        try:
            resp = LLMClient(req_settings).generate(
                system_prompt=("你是精通流行音乐与歌词分析的电台 DJ，"
                               "用简体中文写作，克制而准确。"),
                user_message=user_msg,
            )
            text = (resp.reply_text or "").strip()
        except Exception as exc:
            logger.exception("Intro generation failed")
            yield (f'<div class="chat-empty">⚠️ 生成失败：'
                   f'{_esc(str(exc)[:150])}</div>')
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
        ui.intro_btn.click(on_gen_intro, [song_radio, user_llm],
                           [ui.intro_html])

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
        from ..ui_helpers import _fav_id
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
            from ..intertextuality.search import artist_matches
            fav = next((f for f in favs if f.get("id") == fid), None)
            if fav:
                # re-resolve by title(+artist): the stored label can go
                # stale (a same-title cover added later), so recompute
                want_t, want_a = fav.get("title"), fav.get("artist", "")
                song = next(
                    (s for s in ctx["songs"]
                     if s["title"] == want_t
                     and (not want_a
                          or artist_matches(want_a,
                                            s.get("artist", "")))),
                    None)
                if song and song_choice_label(song) in song_choices(sort):
                    return (gr.skip(),
                            gr.Radio(value=song_choice_label(song)), "")
                return (gr.skip(), gr.skip(),
                        "⚠️ 这首歌已不在列表中（可能已删除）。")
        return gr.skip(), gr.skip(), gr.skip()

    if not public:
        ui.fav_add_btn.click(on_fav_add, [ui.line_pick, song_radio],
                             [ui.fav_status, ui.favs_html])
        ui.fav_box.change(on_fav_act, [ui.fav_box, sort_mode, song_radio],
                          [ui.favs_html, song_radio, ui.fav_status])

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
            # 之前生成过的 AI 语境解释直接带出（弹卡被关/重开也不丢）
            "ai": _cached_dict_ai(word, parts[1] if len(parts) > 1 else ""),
        }
        return gr.Textbox(value=json.dumps(result, ensure_ascii=False))

    ui.dict_pick_box.change(on_dict_pick, [ui.dict_pick_box],
                            [ui.dict_out_box])

    _AI_CACHE_PATH = (Path(rt.settings.songs_dir).parent / "dict"
                      / "ai_cache.json")

    def _cached_dict_ai(word: str, line: str) -> str:
        """The popup's AI explanation for word+line, if one was generated
        (same cache key derivation as on_dict_ai)."""
        import hashlib
        key = hashlib.md5(f"v3:{word}\x00{line}".encode()).hexdigest()
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
        # v3: strict three-line template with a few-shot example
        key = hashlib.md5(f"v3:{word}\x00{line}".encode()).hexdigest()
        try:
            cache = json.loads(_AI_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        if key not in cache:
            from ..llm import LLMClient
            try:
                resp = LLMClient(req_settings).generate(
                    system_prompt=(
                        "你是英语歌词阅读助手。用户双击了歌词里的一个单词。"
                        "用简体中文回答，不超过 120 字。严格按下面模板输出"
                        "三行，不得增删行、加标题、加 markdown 或任何"
                        "模板外内容：\n"
                        "①语境义：<这个词在这句歌词里的含义>\n"
                        "②整句：<这句歌词的通顺翻译>\n"
                        "③用法：<常见用法/搭配>。例：<简短英文例句> "
                        "<例句中文翻译>\n"
                        "示例（单词 resist，歌词句 'Cause I can't "
                        "resist it no more）：\n"
                        "①语境义：再也忍不住、无法克制（想挣脱的冲动）\n"
                        "②整句：因为我再也忍不住了\n"
                        "③用法：can't resist (doing) sth 忍不住做某事。"
                        "例：I can't resist checking my phone. "
                        "我忍不住看手机。"),
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

    ui.dict_ai_box.change(on_dict_ai, [ui.dict_ai_box, user_llm],
                          [ui.dict_out_box])

    if not public:
        def _wb_renders(book, cur: str) -> tuple:
            return (render_wordbook(book, song_title=cur),
                    render_wordbook(book, song_title=cur, phrases=True))

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
                kind = "词组" if is_phrase(word) else "单词"
                gr.Info(f"📒 已收藏{kind} {word}。")
                return _wb_renders(book, cur)
            if head.startswith("note:"):
                from ..dictionary import set_note
                book = set_note(head[5:],
                                act[1] if len(act) > 1 else "")
                return _wb_renders(book, cur)
            if head.startswith("del:"):
                book = remove_word(head[4:])
                return _wb_renders(book, cur)
            return gr.skip(), gr.skip()

        ui.wb_act_box.change(on_wb_act, [ui.wb_act_box, song_radio],
                             [ui.wordbook_html, ui.phrasebook_html])

    # ── 听歌笔记 ──

    _NOTES_PUBLIC_HINT = ('<div class="chat-empty">公开体验版不提供听歌笔记'
                          '（不写服务器磁盘）。</div>')

    def _notes_for(info: dict) -> str:
        if public:
            return _NOTES_PUBLIC_HINT
        return (_render_notes(_load_notes(info["dir"]))
                if info.get("dir") else _render_notes([]))

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

    ui.note_add_btn.click(on_add_note,
                          [song_radio, ui.note_input, ui.cur_time_box],
                          [ui.notes_html, ui.note_input])
    ui.note_input.submit(on_add_note,
                         [song_radio, ui.note_input, ui.cur_time_box],
                         [ui.notes_html, ui.note_input])
    ui.note_del_box.change(on_del_note, [ui.note_del_box, song_radio],
                           [ui.notes_html])

    # ── 证据卡引用跳转：切歌并高亮那一行（行号由 JS 记忆并滚动）──

    def _resolve_jump_label(key: str, sort: str, q: str) -> str:
        """跳转键 → 当前歌单 label（歌迷考据的做法抽成公共函数）。

        key 可以是实时 label、歌名、或收藏时存下的陈旧 label
        （格式/曲库变化后会失配）——一律按当前状态重新解析。"""
        key = (key or "").strip()
        if not key:
            return ""
        labels = _filtered_labels(sort, q)
        if key in labels:
            return key
        by_title = _label_of()
        label = by_title.get(key, "")           # key 是歌名
        if label in labels:
            return label
        # 陈旧 label（如 "title — artist"）：取歌名部分再解析
        label = by_title.get(key.split(" — ")[0], "")
        return label if label in labels else ""

    def on_cite_jump(payload: str, sort: str, q: str):
        key = (payload or "").split("\t")[0].strip()
        label = _resolve_jump_label(key, sort, q)
        if label:
            return gr.Radio(value=label)
        if key:
            gr.Warning("该歌曲不在当前列表中（可能被筛选或已删除）。")
        return gr.skip()

    ui.cite_box.change(
        on_cite_jump, [ui.cite_box, sort_mode, song_filter], [song_radio],
    ).then(on_song_select, [song_radio], song_outputs)
