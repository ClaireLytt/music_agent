"""互动页签「🎯 歌词竞猜」与「🧩 歌名拼图」."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from ..evidence import cite_jump_attrs
from ..ui_helpers import _esc, _load_song_data
from .runtime import Runtime


def build(rt: Runtime, ui) -> None:
    with gr.Tab("🎯 歌词竞猜"), gr.Column(elem_id="ll-quiz-wrap"):
        ui.quiz_state = gr.State(
            {"score": 0, "total": 0, "answer": ""})
        ui.quiz_html = gr.HTML(
            '<div class="chat-empty">点「开始/下一题」'
            '抽一句歌词。</div>')
        ui.quiz_options = gr.Radio(choices=[],
                                   label="它出自哪首歌？",
                                   visible=False)
        with gr.Row():
            ui.quiz_new_btn = gr.Button("🎲 开始 / 下一题",
                                        variant="primary", scale=1)
            ui.quiz_submit_btn = gr.Button("提交答案", scale=1)
        gr.HTML('<div class="quiz-hint">按 1-4 选选项、'
                'Enter 提交答案，看完答案再按一次 Enter '
                '下一题。</div>')
        ui.quiz_result = gr.HTML("", elem_id="ll-quiz-result")
    with gr.Tab("🧩 歌名拼图"), gr.Column(elem_id="ll-blank-wrap"):
        ui.blank_state = gr.State(
            {"score": 0, "total": 0, "answer": "", "reveal": ""})
        ui.blank_html = gr.HTML(
            '<div class="chat-empty">点「来一题」抽一个'
            '缺了一块的歌名。</div>')
        ui.blank_options = gr.Radio(choices=[],
                                    label="被挖掉的是哪一块？",
                                    visible=False)
        with gr.Row():
            ui.blank_new_btn = gr.Button("🧩 来一题",
                                         variant="primary", scale=1)
            ui.blank_submit_btn = gr.Button("🧩 拼好了", scale=1)
        gr.HTML('<div class="quiz-hint">按 1-4 选选项、'
                'Enter 提交，看完答案再按一次 Enter '
                '下一题。</div>')
        ui.blank_result = gr.Markdown("", elem_id="ll-blank-result")


def wire(rt: Runtime, ui) -> None:
    ctx = rt.cache

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
        from ..quiz import make_question
        q = make_question(_quiz_pool())
        if q is None:
            # drop any previous question so 提交 can't grade a stale one
            return (dict(state or {}, answer=""),
                    '<div class="chat-empty">歌曲列表至少需要 2 首歌'
                    '才能出题。</div>',
                    gr.Radio(choices=[], visible=False), "")
        state = dict(state or {}, answer=q.answer,
                     line_index=q.line_index)
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
            verdict = f"✅ 答对了！正是《{_esc(answer)}》。"
        else:
            verdict = f"❌ 不对，这句出自《{_esc(answer)}》。"
        # 「去听这句」：跳到对应歌曲的那一行（复用 cite 跳转委托，
        # cite-go-play 让委托顺带切回播放页）
        label = rt.label_of().get(answer, "")
        jump = (f' <button class="ptool cite-go-play"'
                f'{cite_jump_attrs(label, state.get("line_index", -1))}>'
                '🎧 去听这句</button>' if label else "")
        state["answer"] = ""  # one submission per question
        return (state, f'<div>{verdict}{jump}　当前战绩 '
                f'<b>{state.get("score", 0)} / {state["total"]}</b>'
                '</div>')

    ui.quiz_new_btn.click(on_quiz_new, [ui.quiz_state],
                          [ui.quiz_state, ui.quiz_html, ui.quiz_options,
                           ui.quiz_result])
    ui.quiz_submit_btn.click(on_quiz_submit,
                             [ui.quiz_state, ui.quiz_options],
                             [ui.quiz_state, ui.quiz_result])

    # ── 歌名挖空 ──

    def on_blank_new(state: dict):
        from ..quiz import make_title_puzzle
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

    ui.blank_new_btn.click(on_blank_new, [ui.blank_state],
                           [ui.blank_state, ui.blank_html,
                            ui.blank_options, ui.blank_result])
    ui.blank_submit_btn.click(on_blank_submit,
                              [ui.blank_state, ui.blank_options],
                              [ui.blank_state, ui.blank_result])
