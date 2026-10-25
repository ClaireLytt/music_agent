"""页签「🔤 歌曲寻词」：打字练习 / 分组导入导出 / 数据分析.

整页 if not public——公开版不渲染。
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import gradio as gr

from ..dictionary import is_phrase, load_wordbook
from ..ui_helpers import _file_url, render_practice_card
from .runtime import Runtime

logger = logging.getLogger(__name__)


def build(rt: Runtime, ui) -> None:
    if rt.public:
        return
    with gr.Tab("🔤 歌曲寻词") as review_tab:
        ui.review_tab = review_tab
        gr.Markdown(
            "💡 打错整词重来 · Tab 提示单词 · "
            "Enter 跳过换词 · 点卡片可继续输入；"
            "错得多的词会更频繁出现。",
            elem_id="ll-review-hint")
        with gr.Row():
            with gr.Column(scale=3):
                ui.review_group_dd = gr.Dropdown(
                    choices=["全部", "📖 歌词收藏",
                             "🔤 单词", "🧩 词组"], value="全部",
                    label="练习范围", allow_custom_value=True,
                    elem_id="ll-review-group")
            with gr.Column(scale=2,
                           elem_id="ll-review-topright"):
                ui.review_stats_md = gr.Markdown(
                    "", elem_id="ll-review-stats")
                # 展开时浮在页面上方（CSS absolute），
                # 不把下方的单词卡片往下挤
                with gr.Accordion("⋯", open=False,
                                  elem_id="ll-review-more"):
                    ui.import_file = gr.File(
                        label="选择 .csv / .tsv / .txt / .xlsx",
                        file_types=[".csv", ".tsv", ".txt",
                                    ".xlsx"],
                        elem_id="ll-import-file")
                    ui.import_group_box = gr.Textbox(
                        label="分组名（留空 = 文件名）")
                    ui.import_btn = gr.Button("📥 导入到单词本",
                                              size="sm")
                    ui.group_del_btn = gr.Button(
                        "🗑 删除当前分组", size="sm")
                    ui.review_export_btn = gr.Button(
                        "📤 导出 JSON 词典", size="sm")
                    ui.anki_export_btn = gr.Button(
                        "🗂️ 导出 Anki 牌组", size="sm")
                    # 点导出即直接下载：隐藏的下载锚点由 JS
                    # 侦测 href 变化后自动代点（见 ui_assets）
                    ui.review_download = gr.DownloadButton(
                        "⬇️", visible=False,
                        elem_id="ll-dl-json")
                    ui.anki_download = gr.DownloadButton(
                        "⬇️", visible=False,
                        elem_id="ll-dl-anki")
                    # backend -> JS：导出完成信号
                    # （"json|anki \t ts"），JS 代点下载按钮
                    ui.dl_tick_box = gr.Textbox(
                        value="", visible=True,
                        elem_id="ll-dl-tick",
                        elem_classes=["ll-hidden"],
                        show_label=False, container=False)
                    ui.analysis_btn = gr.Button(
                        "📊 数据分析", size="sm",
                        elem_id="ll-analysis-btn")
                    ui.import_status = gr.Markdown("")
                    ui.review_export_status = gr.Markdown("")
        ui.review_state = gr.State(
            {"word": "", "words": 0, "perfect": 0,
             "chars": 0, "ms": 0, "queue": [], "group": "全部"})
        ui.review_html = gr.HTML("")
        # 📊 数据分析输出放主列（右侧 ⋯ 面板只有 ~330px，
        # 年历热力图宽 ~710px 会被横向裁掉）
        ui.analysis_html = gr.HTML("", elem_id="ll-analysis")
        with gr.Row(elem_id="ll-review-startrow"):
            ui.review_start_btn = gr.Button(
                "⌨️ 开始 / 换一词", size="sm",
                variant="primary", min_width=130)
            # 暂停/继续（纯前端，JS 驱动；悬停显示快捷键）
            gr.HTML(
                '<button type="button" id="ll-ds-pause" '
                'data-ds-tip="暂停 / 继续（Space）">⏸ 暂停'
                '</button>')
        # qwerty-learner 式统计条：时间/输入数/WPM/正确数/正确率
        # （纯前端会话统计；切出本页签即本轮结束并清零）
        gr.HTML(
            '<div id="ll-drill-stats">'
            + "".join(
                f'<div class="ds-tile">'
                f'<div class="ds-num" id="ll-ds-{k}">{v}</div>'
                f'<div class="ds-label">{label}</div></div>'
                for k, v, label in [
                    ("time", "00:00", "时间"),
                    ("input", "0", "输入数"),
                    ("wpm", "0", "WPM"),
                    ("correct", "0", "正确数"),
                    ("acc", "0%", "正确率"),
                ])
            + '</div>')
        # JS -> backend: word done ("word	mistakes	ms	ts")
        ui.review_done_box = gr.Textbox(
            value="", visible=True,
            elem_id="ll-review-done",
            elem_classes=["ll-hidden"], show_label=False,
            container=False)


def wire(rt: Runtime, ui) -> None:
    if rt.public:
        return

    def _review_stats_line(state) -> str:
        from ..review import book_stats
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

    def _review_next(state, exclude: str = "",
                     group: str = "全部"):
        from ..review import round_queue, synthesize_word
        book = load_wordbook()
        if group == "📖 歌词收藏":
            book = [e for e in book if not e.get("group")]
        elif group == "🔤 单词":   # 不含空格的纯单词
            book = [e for e in book
                    if not is_phrase(e.get("word", ""))]
        elif group == "🧩 词组":   # 拖选收藏的多词词组
            book = [e for e in book if is_phrase(e.get("word", ""))]
        elif group and group != "全部":
            book = [e for e in book if e.get("group") == group]
        if state.get("group") != group:   # 换范围 → 重开一轮
            state["group"] = group
            state["queue"] = []
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
            hint = ("这个分组没有单词。" if group not in ("全部",)
                    else "单词本是空的——先去「🎧 播放解读」双击"
                    "歌词里的英文单词收藏几个，或在下方导入"
                    "单词表。")
            return (state,
                    f'<div class="chat-empty">{hint}</div>',
                    _review_stats_line(state))
        mp3 = synthesize_word(entry["word"])
        url = _file_url(mp3) if mp3 else ""
        state["word"] = entry["word"]
        from ..review import word_examples
        examples = word_examples(
            entry["word"], exclude_song=entry.get("song", ""),
            corpus_dir=rt.settings.corpus_dir)
        return (state,
                render_practice_card(entry, url, uuid.uuid4().hex,
                                     examples=examples),
                _review_stats_line(state))

    def on_review_start(state, group: str):
        return _review_next(state, exclude=state.get("word", ""),
                            group=group or "全部")

    def on_review_done(payload: str, state, group: str):
        parts = (payload or "").split("\t")
        if len(parts) < 3:
            return gr.skip(), gr.skip(), gr.skip()
        word, mistakes, ms = parts[0], parts[1], parts[2]
        if not word or word != state.get("word", "").lower():
            return gr.skip(), gr.skip(), gr.skip()  # stale payload
        from ..review import record_result
        clean = mistakes == "0"
        # 第 4/5 段：盲打标记 + Tab 偷看次数（旧前端缺省为非盲打）
        blind = len(parts) > 4 and parts[3] == "1"
        try:
            peeks = int(parts[4]) if len(parts) > 4 else 0
        except ValueError:
            peeks = 0
        record_result(word, clean, blind=blind, peeks=peeks)
        state["words"] += 1
        state["perfect"] += 1 if clean else 0
        state["chars"] += len(word)
        try:
            state["ms"] += max(0, int(ms))
        except ValueError:
            pass
        # 不自动跳下一个词：用户按 Enter 才换（JS 侧放行）
        return state, gr.skip(), _review_stats_line(state)

    def on_review_export():
        from ..review import export_qwerty
        book = load_wordbook()
        if not book:
            return (gr.DownloadButton(visible=False),
                    "单词本是空的，没有可导出的词。", gr.skip())
        # 时间戳文件名：每次导出 href 都变化，前端代点逻辑才能
        # 识别到"新文件"并再次触发下载
        import time as _t
        out = Path(f"data/cache/dict_export_{int(_t.time())}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(export_qwerty(book),
                                  ensure_ascii=False, indent=2),
                       encoding="utf-8")
        return (gr.DownloadButton(value=str(out), visible=True),
                f"已导出 {len(book)} 词的 JSON 词典，浏览器开始下载。",
                f"json\t{_t.time()}")

    def _group_choices() -> list[str]:
        from ..dictionary import word_groups
        return (["全部", "📖 歌词收藏", "🔤 单词", "🧩 词组"]
                + word_groups())

    def on_review_tab_select(group: str):
        choices = _group_choices()
        return gr.Dropdown(
            choices=choices,
            value=group if group in choices else "全部")

    ui.review_tab.select(on_review_tab_select, [ui.review_group_dd],
                         [ui.review_group_dd])

    def on_import_words(file, group_name: str, state):
        from ..dictionary import import_words, parse_wordlist_file
        if not file:
            return ("⚠️ 请先选择一个单词表文件。",
                    gr.skip(), gr.skip(), gr.skip(), gr.skip())
        group = (group_name or "").strip() or Path(file).stem
        try:
            rows = parse_wordlist_file(file)
        except ValueError as exc:
            return (f"⚠️ {exc}", gr.skip(), gr.skip(),
                    gr.skip(), gr.skip())
        except Exception:
            logger.exception("wordlist parse failed")
            return ("⚠️ 文件解析失败——请确认是 CSV/TSV/XLSX，"
                    "第 1 列为单词。", gr.skip(), gr.skip(),
                    gr.skip(), gr.skip())
        added, skipped = import_words(rows, group)
        if not added:
            return (f"⚠️ 没有新词可导入（跳过 {skipped} 行："
                    "空词/非英文/已在单词本）。",
                    gr.skip(), gr.skip(), gr.skip(), gr.skip())
        # 导入成功：切到该分组并立刻发一张练习卡
        state, card, stats = _review_next(state, group=group)
        return (f"✅ 已导入 **{added}** 个词到分组「{group}」"
                f"（跳过 {skipped} 行）。已切到该分组，"
                "直接开打！",
                gr.Dropdown(choices=_group_choices(), value=group),
                state, card, stats)

    ui.import_btn.click(on_import_words,
                        [ui.import_file, ui.import_group_box,
                         ui.review_state],
                        [ui.import_status, ui.review_group_dd,
                         ui.review_state, ui.review_html,
                         ui.review_stats_md])

    def on_delete_group(group: str, state):
        from ..dictionary import delete_group
        if not (group or "").strip() or group in ("全部",
                                                  "📖 歌词收藏"):
            gr.Warning("先在「练习范围」选中一个导入的分组。")
            return (gr.skip(), gr.skip(), gr.skip(),
                    gr.skip(), gr.skip())
        n = delete_group(group)
        if not n:
            gr.Warning(f"分组「{group}」没有单词。")
            return (gr.skip(), gr.skip(), gr.skip(),
                    gr.skip(), gr.skip())
        gr.Info(f"🗑 已删除分组「{group}」的 {n} 个单词。")
        state, card, stats = _review_next(state, group="全部")
        return (f"🗑 已删除分组「{group}」（{n} 个词）。",
                gr.Dropdown(choices=_group_choices(), value="全部"),
                state, card, stats)

    ui.group_del_btn.click(on_delete_group,
                           [ui.review_group_dd, ui.review_state],
                           [ui.import_status, ui.review_group_dd,
                            ui.review_state, ui.review_html,
                            ui.review_stats_md])

    ui.review_start_btn.click(on_review_start,
                              [ui.review_state, ui.review_group_dd],
                              [ui.review_state, ui.review_html,
                               ui.review_stats_md])
    ui.review_done_box.change(on_review_done,
                              [ui.review_done_box, ui.review_state,
                               ui.review_group_dd],
                              [ui.review_state, ui.review_html,
                               ui.review_stats_md])
    ui.review_export_btn.click(on_review_export, None,
                               [ui.review_download,
                                ui.review_export_status,
                                ui.dl_tick_box])

    def on_anki_export():
        from ..review import export_anki
        book = load_wordbook()
        if not book:
            return (gr.DownloadButton(visible=False),
                    "单词本是空的，没有可导出的词。", gr.skip())
        import time as _t
        out = Path(f"data/cache/anki_export_{int(_t.time())}.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(export_anki(book), encoding="utf-8")
        return (gr.DownloadButton(value=str(out), visible=True),
                f"已导出 {len(book)} 词的 Anki TSV，浏览器开始下载"
                "——Anki 里「文件 → 导入」选择它即可。",
                f"anki\t{_t.time()}")

    ui.anki_export_btn.click(on_anki_export, None,
                             [ui.anki_download, ui.review_export_status,
                              ui.dl_tick_box])

    def on_analysis():
        """📊 数据分析：打开全屏页（✕ 在前端自行移除节点，
        所以每次都附时间戳注释强制 Gradio 重挂 DOM）。"""
        import time as _t
        from ..ui_helpers import render_analysis
        return render_analysis(load_wordbook()) + f"<!--{_t.time()}-->"

    ui.analysis_btn.click(on_analysis, None, [ui.analysis_html])
