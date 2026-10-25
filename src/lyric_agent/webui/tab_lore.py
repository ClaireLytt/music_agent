"""互动页签「🕵️ 歌迷考据」：LLM 考据长文 + 页内 AI 助手.

生成遵循 CLAUDE.md「长耗时 LLM 调用的交付铁律」：后台 daemon 线程
落盘缓存 + ctx 记 in-flight 状态 + gr.Timer 轮询刷新——
结果绝不押在一条长连接的最后一个 yield 上。
"""

from __future__ import annotations

import json
import logging
import threading

import gradio as gr

from ..debate import DebateSession, speak as ai_speak
from ..fanlore import FANLORE_EMPTY
from ..ui_helpers import _esc, _load_song_data, _render_chat
from .runtime import PUBLIC_KEY_HINT as _PUBLIC_KEY_HINT, Runtime

logger = logging.getLogger(__name__)

_LORE_CHAT_HINT = ('<div class="chat-empty">考据页'
                   '哪里看不懂，随时在这里问——'
                   'AI 会结合本页内容回答。</div>')


def build(rt: Runtime, ui) -> None:
    with gr.Tab("🕵️ 歌迷考据") as lore_tab:
        with gr.Row():
            with gr.Column(scale=3,
                           elem_id="ll-lore-main"):
                ui.lore_song_dd = gr.Dropdown(
                    choices=rt.song_choices(), value=None,
                    label="选择歌曲", allow_custom_value=True,
                    elem_id="ll-lore-song")
                ui.lore_html = gr.HTML(FANLORE_EMPTY)
                if not rt.public:
                    ui.lore_btn = gr.Button(
                        "🕵️ 生成考据故事（调用 1 次 LLM，"
                        "之后永久缓存）", size="sm",
                        elem_id="ll-lore-gen")
            with gr.Column(scale=1, elem_id="ll-lore-chat"):
                gr.HTML('<div class="side-panel-title">'
                        '💬 AI 助手</div>')
                ui.lore_chat_state = gr.State(None)
                ui.lore_chat_html = gr.HTML(_LORE_CHAT_HINT)
                with gr.Row():
                    ui.lore_chat_input = gr.Textbox(
                        placeholder="针对本页考据提问 ...",
                        show_label=False, scale=4, container=False)
                    ui.lore_chat_send = gr.Button(
                        "提问", scale=1, variant="primary")
        # library may grow while the app runs
        lore_tab.select(
            lambda: gr.Dropdown(choices=rt.song_choices()),
            None, [ui.lore_song_dd])


def wire(rt: Runtime, ui) -> None:
    public = rt.public
    ctx = rt.cache
    find_song = rt.find_song

    def _render_lore(info: dict) -> str:
        from ..fanlore import (load_fanlore, parse_fanlore,
                               render_fanlore_html)
        cached = load_fanlore(info["dir"])
        if cached is None:
            return (FANLORE_EMPTY if not public else
                    '<div class="chat-empty">该歌曲还没有考据'
                    '（公开版不提供现场生成）。</div>')
        return render_fanlore_html(
            parse_fanlore(cached), info.get("title", ""),
            verifier=rt.quote_verifier(), label_of=rt.label_of())

    # 生成放后台线程 + 定时器轮询取结果：长 LLM 调用的最后一个 yield
    # 在长连接上经常送不到（SSE 断/用户刷新），同步阻塞还会在重启时
    # 白白丢掉整次调用（CLAUDE.md「长耗时 LLM 调用的交付铁律」）
    _LORE_WAIT = ('<div class="chat-empty">🕵️ AI 正在整理这首歌的'
                  '官方信息、歌词呼应与 AI 推测——生成在服务器后台'
                  '进行，切歌/刷新页面都不会中断；慢的模型可能要一两'
                  '分钟，完成后本页自动显示结果。</div>')

    def _lore_state(song_dir: str) -> dict | None:
        return (ctx.get("lore_inflight") or {}).get(song_dir)

    def on_lore_song(choice: str):
        # 切歌：换内容 + 重置右侧助手会话
        info = find_song(choice) if choice else {}
        if not info.get("dir"):
            return FANLORE_EMPTY, None, _LORE_CHAT_HINT
        st = _lore_state(info["dir"])
        html = (_LORE_WAIT if st and st.get("status") == "running"
                else _render_lore(info))
        return html, None, _LORE_CHAT_HINT

    ui.lore_song_dd.change(on_lore_song, [ui.lore_song_dd],
                           [ui.lore_html, ui.lore_chat_state,
                            ui.lore_chat_html])

    def _lore_session(choice: str):
        """助手会话：把本页考据内容作为上下文（无考据时退回歌名）。"""
        info = find_song(choice) if choice else {}
        if not info.get("dir"):
            return None
        from ..fanlore import load_fanlore, parse_fanlore
        cached = load_fanlore(info["dir"])
        ctx_txt = ""
        if cached is not None:
            f = parse_fanlore(cached)
            bits = []
            if f.hook:
                bits.append(f"一句话看懂：{f.hook}")
            bits += [f"线索[{c.type}]{c.title}：{c.body}"
                     for c in f.clues]
            if f.chain:
                bits.append("剧情推测链：" + " → ".join(
                    f"《{s}》（{b}）" for s, b in f.chain))
            if f.summary:
                bits.append(f"总结：{f.summary}")
            ctx_txt = ("用户正在看的考据页内容：\n"
                       + "\n".join(bits))[:1500]
        return DebateSession(
            lyric_line="（用户在看这首歌的考据页，可能就页面任何内容提问）",
            song_title=info.get("title", ""),
            artist=info.get("artist", ""),
            annotation_context=ctx_txt)

    def on_lore_chat(session, user_text: str, choice: str, user_cfg):
        text = (user_text or "").strip()
        if not text:
            yield session, gr.skip(), user_text
            return
        if session is None:
            session = _lore_session(choice)
        if session is None:
            yield (None, '<div class="chat-empty">请先选择一首歌。</div>',
                   user_text)
            return
        req_settings = rt.request_settings(user_cfg)
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
        if partial and session.history \
                and session.history[-1]["speaker"] == "user":
            session.history.append({"speaker": "🤖 AI 助手",
                                    "text": partial})
        yield session, _render_chat(session), ""

    ui.lore_chat_send.click(
        on_lore_chat,
        [ui.lore_chat_state, ui.lore_chat_input, ui.lore_song_dd,
         ui.user_llm],
        [ui.lore_chat_state, ui.lore_chat_html, ui.lore_chat_input])
    ui.lore_chat_input.submit(
        on_lore_chat,
        [ui.lore_chat_state, ui.lore_chat_input, ui.lore_song_dd,
         ui.user_llm],
        [ui.lore_chat_state, ui.lore_chat_html, ui.lore_chat_input])

    if not public:
        def _lore_generate_bg(info: dict, req) -> None:
            """Daemon-thread worker: LLM call + disk cache; the timer
            below delivers the result to whoever is looking."""
            from ..fanlore import fanlore_messages, save_fanlore
            flight = ctx.setdefault("lore_inflight", {})
            try:
                # 曲库呼应 = 喂给模型的硬证据
                payload, _ov = rt.build_echo_map(info)
                try:
                    lines = (json.loads(payload).get("lines", [])
                             if payload else [])
                except ValueError:
                    lines = []
                data = _load_song_data(info["dir"])
                by_idx = {ln.line_index: ln.text
                          for ln in data["timed_lines"]}
                pairs = [(by_idx.get(o["i"], ""), o["song"],
                          o.get("target", ""))
                         for o in sorted(
                             lines,
                             key=lambda o: -o.get("sim", 0))[:5]]
                from ..intertextuality.search import artist_matches
                titles = [s["title"] for s in ctx["songs"]
                          if artist_matches(info.get("artist", ""),
                                            s.get("artist", ""))]
                system, user_msg = fanlore_messages(
                    info.get("title", ""), info.get("artist", ""),
                    info.get("album", ""), info.get("year"),
                    echo_pairs=pairs, library_titles=titles)
                from ..llm import LLMClient

                buf: list[str] = []

                def _on_delta(piece: str) -> None:
                    # 流式进度：timer 把它实时刷到页面，像聊天一样能
                    # 看到模型在动（JSON 半成品不直接展示，翻译成人话）
                    from ..fanlore import progress_stage
                    buf.append(piece)
                    s = "".join(buf)
                    flight[info["dir"]] = {
                        "status": "running",
                        "progress": progress_stage(s),
                        "chars": len(s),
                    }

                verdict = LLMClient(req).generate_json(
                    system, user_msg, on_text_delta=_on_delta)
                save_fanlore(info["dir"], verdict, req.model_name)
                flight[info["dir"]] = {"status": "done"}
            except Exception as exc:
                logger.exception("fanlore generation failed")
                flight[info["dir"]] = {"status": "error",
                                       "msg": str(exc)[:150]}

        def on_gen_lore(choice: str, user_cfg):
            from ..fanlore import load_fanlore
            info = find_song(choice) if choice else {}
            if not info.get("dir"):
                return '<div class="chat-empty">⚠️ 请先选择一首歌。</div>'
            if load_fanlore(info["dir"]) is not None:
                return _render_lore(info)   # 已有缓存：零调用直接展示
            st = _lore_state(info["dir"])
            if st and st.get("status") == "running":
                return _LORE_WAIT           # 已在生成，别重复起线程
            req = rt.request_settings(user_cfg)
            if not req.api_key:
                return ('<div class="chat-empty">⚠️ 未配置 API Key，'
                        '无法生成。请到「⚙️ 设置」页签填写。</div>')
            ctx.setdefault("lore_inflight", {})[info["dir"]] = \
                {"status": "running"}
            threading.Thread(target=_lore_generate_bg,
                             args=(dict(info), req), daemon=True,
                             name="ll-fanlore").start()
            return _LORE_WAIT

        ui.lore_btn.click(on_gen_lore, [ui.lore_song_dd, ui.user_llm],
                          [ui.lore_html])

        # 轮询交付：只在状态翻转（done/error）时各刷一次 UI
        lore_timer = gr.Timer(2.0)

        def on_lore_tick(choice: str):
            info = find_song(choice) if choice else {}
            st = _lore_state(info.get("dir", ""))
            if not info.get("dir") or not st:
                return gr.skip()
            if st.get("status") == "done":
                ctx["lore_inflight"].pop(info["dir"], None)
                return _render_lore(info)
            if st.get("status") == "error":
                ctx["lore_inflight"].pop(info["dir"], None)
                return (f'<div class="chat-empty">⚠️ 生成失败：'
                        f'{_esc(st.get("msg", ""))}</div>')
            if st.get("chars"):   # 流式进度实时可见
                return ('<div class="chat-empty">🕵️ '
                        f'{_esc(st.get("progress", "正在生成"))}…'
                        f'（已生成 {st["chars"]} 字 · 后台进行，'
                        '切歌/刷新不中断）</div>')
            return gr.skip()

        lore_timer.tick(on_lore_tick, [ui.lore_song_dd], [ui.lore_html])
