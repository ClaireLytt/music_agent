"""页签「⚙️ 设置」：📊 用量 / 🔑 API 密钥 / 🧠 Embedding 模型与重建."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace

import gradio as gr

from ..config import default_model_for, save_user_settings
from ..ui_helpers import _CATALOG_PATH
from .runtime import Runtime

logger = logging.getLogger(__name__)


def build(rt: Runtime, ui) -> None:
    public = rt.public
    settings = rt.settings
    app = ui.app
    with gr.Tab("⚙️ 设置"):
        with gr.Tabs(elem_classes=["ll-icon-dock"]):
            with gr.Tab("📊"):
                gr.Markdown("### 📊 API 用量\n本机记录的 LLM 调用"
                            "与 token 消耗（批注/翻译/问答等全部"
                            "计入；按模型方计费口径为准）。",
                            elem_id="ll-usage-head")
                usage_md = gr.Markdown("")
                usage_refresh_btn = gr.Button("🔄 刷新", size="sm")

                def on_usage_refresh():
                    from ..llm import load_usage
                    u = load_usage()
                    tot = u.get("total", {})
                    if not tot.get("calls"):
                        return "还没有任何 LLM 调用记录。"
                    day = time.strftime("%Y-%m-%d")
                    today = u.get("days", {}).get(day, {})
                    rows = ["| | 调用 | 输入 tokens | 输出 tokens |",
                            "|---|---|---|---|"]
                    for label, b in (("今天", today), ("累计", tot)):
                        rows.append(
                            f"| {label} | {b.get('calls', 0)} | "
                            f"{b.get('input_tokens', 0):,} | "
                            f"{b.get('output_tokens', 0):,} |")
                    for model, b in sorted(
                            u.get("models", {}).items()):
                        rows.append(
                            f"| `{model}` | {b.get('calls', 0)} | "
                            f"{b.get('input_tokens', 0):,} | "
                            f"{b.get('output_tokens', 0):,} |")
                    return "\n".join(rows)

                usage_refresh_btn.click(on_usage_refresh, None,
                                        [usage_md])
                app.load(on_usage_refresh, None, [usage_md])
            with gr.Tab("🔑"):
                # 仿「添加歌曲」页：手风琴可收起 + 居中窄框
                with gr.Accordion(
                        "🔑 API 设置（公开体验版）" if public
                        else "🔑 API 设置",
                        open=False, elem_id="ll-apiset"):
                    if public:
                        gr.Markdown(
                            "请填入**你自己的**大模型 API Key。"
                            "Key 只会保存在你当前浏览器的本地存储"
                            "（localStorage）中，**不会上传或写入"
                            "服务器**，其他访客也看不到。"
                        )
                    else:
                        gr.Markdown(
                            "在这里填入你自己的大模型 API Key，"
                            "点保存后**立即生效**，无需改任何文件、"
                            "无需重启。"
                        )
                    ui.set_provider = gr.Radio(
                        choices=[
                            ("OpenAI 兼容接口（DeepSeek / 通义 / "
                             "Kimi 等）", "openai"),
                            ("Anthropic（Claude）", "anthropic"),
                        ],
                        value=("openai" if public
                               else settings.llm_provider),
                        label="接口类型")
                    ui.set_key = gr.Textbox(
                        label="API Key（必填）", type="password",
                        value="" if public else settings.api_key)
                    ui.set_base = gr.Textbox(
                        label="接口地址（选填 — OpenAI 兼容接口才"
                              "需要，例如 https://api.deepseek.com）",
                        value="" if public else settings.llm_base_url)
                    ui.set_model = gr.Textbox(
                        label="模型名称（选填 — 留空自动使用默认模型）",
                        value="" if public else settings.model_name)
                    ui.set_btn = gr.Button("💾 保存设置",
                                           variant="primary")
                    ui.set_status = gr.Markdown("")

            if not public:
                with gr.Tab("🧠"):
                    gr.Markdown(
                        "### 🧠 语料库与 Embedding 模型\n"
                        "彩蛋/互文/语义搜索使用本地 embedding 模型。"
                        "默认英文模型对中文歌词区分度差；曲库以中文为主时，"
                        "建议切换到多语模型后**重建索引**"
                        "（首次会下载模型，重建需 1-3 分钟）。"
                    )
                    ui.emb_model_dd = gr.Dropdown(
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
                    ui.rebuild_btn = gr.Button(
                        "🔨 重建语料库索引（含新添加的歌曲）")
                    ui.rebuild_status = gr.Markdown("")


def wire(rt: Runtime, ui) -> None:
    public = rt.public

    # ── 语料库索引重建 ──

    def on_rebuild(model_name: str):
        model_name = (model_name or "").strip() \
            or rt.settings.embedding_model
        try:
            yield "⏳ 1/2 正在重建语料库（曲库歌曲 + 内置曲库）……"
            from ..intertextuality.corpus import build_corpus
            n_songs, n_lines = build_corpus(
                rt.settings.songs_dir, rt.settings.corpus_dir,
                catalog_path=_CATALOG_PATH if _CATALOG_PATH.exists()
                else None,
            )
            yield (f"⏳ 2/2 语料库完成（{n_songs} 首 / {n_lines} 行），"
                   f"正在用 {model_name} 生成 embeddings"
                   "（首次使用该模型会先下载，需 1-3 分钟）……")
            from ..intertextuality.embeddings import generate_embeddings
            embeddings, _corpus = generate_embeddings(
                rt.settings.corpus_dir, model_name=model_name)
        except Exception as exc:
            logger.exception("Rebuild index failed")
            yield f"⚠️ 重建失败：{str(exc)[:200]}"
            return
        rt.settings = replace(rt.settings, embedding_model=model_name)
        # persist so a restart keeps using this model (merge, don't clobber)
        from ..config import user_settings_path
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
        rt.cache.invalidate_echo_index()
        rt.refresh_library()  # rebuilds the searcher on the new model
        yield (f"✅ 索引已重建：{embeddings.shape[0]} 行 × "
               f"{embeddings.shape[1]} 维（模型：{model_name}）。"
               "彩蛋/互文/语义搜索已切换到新索引。")

    if not public:
        ui.rebuild_btn.click(on_rebuild, [ui.emb_model_dd],
                             [ui.rebuild_status])

    # ── 设置 ──

    def on_save_settings(provider: str, key: str, base: str, model: str):
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
        rt.settings = replace(
            rt.settings, api_key=key, llm_provider=provider,
            llm_base_url=base, model_name=model)
        save_user_settings({
            "api_key": key, "llm_provider": provider,
            "llm_base_url": base, "model_name": model,
        })
        return f"✅ 已保存并生效（模型：{model}）。", gr.skip()

    ui.set_btn.click(on_save_settings,
                     [ui.set_provider, ui.set_key, ui.set_base,
                      ui.set_model],
                     [ui.set_status, ui.user_llm])

    if public:
        def load_user_cfg(cfg):
            cfg = cfg if isinstance(cfg, dict) else {}
            return (cfg.get("llm_provider") or "openai",
                    cfg.get("api_key") or "",
                    cfg.get("llm_base_url") or "",
                    cfg.get("model_name") or "")

        ui.app.load(load_user_cfg, [ui.user_llm],
                    [ui.set_provider, ui.set_key, ui.set_base,
                     ui.set_model])
