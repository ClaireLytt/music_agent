"""播放页 ⚙️ 歌曲工具子坞的 handler：音频上传 / B 站绑定 / 翻译 / 偏移.

组件在 tab_play.build 里创建（必须常驻播放页 DOM），这里只接线。
全部 if not public——公开版不渲染这些组件。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

import gradio as gr

from ..ui_helpers import _load_song_data, _render_lyrics_html
from .runtime import Runtime

logger = logging.getLogger(__name__)


def wire(rt: Runtime, ui) -> None:
    if rt.public:
        return
    public = rt.public
    find_song = rt.find_song
    refresh_library = rt.refresh_library
    song_radio, lyrics_html = ui.song_radio, ui.lyrics_html

    # ── 听歌识曲 ──

    def on_audio_upload(fpath, choice: str):
        if not fpath:
            return gr.skip(), gr.skip(), gr.skip()
        info = find_song(choice)
        if not info.get("dir"):
            return "⚠️ 请先在列表中选择一首歌。", None, gr.skip()
        ext = Path(fpath).suffix.lower()
        if ext not in {".mp3", ".wav", ".flac", ".ogg", ".m4a"}:
            return ("⚠️ 仅支持 mp3 / wav / flac / ogg / m4a 格式。",
                    None, gr.skip())
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

    ui.audio_file_up.upload(on_audio_upload, [ui.audio_file_up, song_radio],
                            [ui.audio_up_status, ui.audio_file_up,
                             lyrics_html])

    # ── 📺 B 站视频绑定（官方嵌入播放器；搜索为便捷辅助）──

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
            from ..bilibili import search_mv
            cands = search_mv(info["title"], info.get("artist", ""))
            if not cands:
                gr.Warning("B 站搜索暂不可用——可在「📺 关联 B 站视频」"
                           "手风琴里手动粘 BV 号或链接。")
                return gr.skip()
            data = _load_song_data(info["dir"])
            return _render_lyrics_html(
                data, dict(info, bvid_cands=cands), public=public)
        if act == "pick" and len(parts) >= 2:
            from ..bilibili import extract_bvid
            bvid = extract_bvid(parts[1])
            if not bvid:
                return gr.skip()
            _save_bvid(info, bvid)
            gr.Info(f"📺 已为《{info['title']}》绑定 {bvid}")
            return _bvid_rerender(choice)
        return gr.skip()

    def on_bvid_save(text: str, choice: str):
        from ..bilibili import extract_bvid
        info = find_song(choice)
        if not info.get("dir"):
            return "⚠️ 请先在列表中选择一首歌。", gr.skip(), gr.skip()
        bvid = extract_bvid(text)
        if (text or "").strip() and not bvid:
            return ("⚠️ 没找到 BV 号——请粘贴形如 BV1xx411c7mD 的 ID "
                    "或完整视频链接。"), gr.skip(), gr.skip()
        _save_bvid(info, bvid)
        msg = f"✅ 已绑定 {bvid}，视频已在上方展开。" if bvid \
            else "✅ 已解绑视频。"
        return msg, _bvid_rerender(choice), gr.Textbox(value=bvid)

    def on_bvid_load(choice: str):
        # keep the accordion input mirroring the saved binding, so a
        # page refresh never looks like the link was lost
        return gr.Textbox(value=find_song(choice).get("bvid", ""))

    ui.bvid_box.change(on_bvid_act, [ui.bvid_box, song_radio],
                       [lyrics_html])
    ui.bvid_save_btn.click(on_bvid_save, [ui.bvid_input, song_radio],
                           [ui.bvid_status, lyrics_html, ui.bvid_input])
    song_radio.change(on_bvid_load, [song_radio], [ui.bvid_input])

    # ── 🀄 中文翻译对照（用户点按钮才生成/显示；译文永久缓存）──
    trans_state = gr.State("")   # 当前开着翻译的歌名，"" = 关

    _TRANS_SHOW = ("🀄 显示中文翻译（英文歌·首次生成调用 LLM，"
                   "之后永久缓存）")
    _TRANS_HIDE = "🙈 隐藏中文翻译"

    def on_trans_toggle(cur: str, choice: str, user_cfg):
        info = find_song(choice)
        if not info.get("dir"):
            return cur, gr.skip(), gr.skip()
        data = _load_song_data(info["dir"])
        title = info.get("title", "")
        if cur == title:   # 已开 → 关
            return ("", _render_lyrics_html(data, info, public=public),
                    gr.Button(value=_TRANS_SHOW))
        from ..ui_helpers import load_translation
        if not load_translation(info["dir"]):
            req = rt.request_settings(user_cfg)
            if not req.api_key:
                gr.Warning("需要 API Key 才能生成翻译（⚙️ 设置）。")
                return cur, gr.skip(), gr.skip()
            gr.Info("🀄 正在生成整首中文翻译……")
            lines = data["timed_lines"]
            out: dict[str, str] = {}
            from ..llm import LLMClient
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
                return cur, gr.skip(), gr.skip()
        return (title,
                _render_lyrics_html(data, info, public=public,
                                    show_trans=True),
                gr.Button(value=_TRANS_HIDE))

    ui.trans_btn.click(on_trans_toggle,
                       [trans_state, song_radio, ui.user_llm],
                       [trans_state, lyrics_html, ui.trans_btn])

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

    ui.offset_slider.change(on_offset_preview, [ui.offset_slider],
                            [ui.offset_box])
    ui.offset_save_btn.click(on_offset_save,
                             [ui.offset_slider, song_radio],
                             [ui.offset_status, lyrics_html])
    # 切歌时带出当前偏移（独立监听，不动 on_song_select 的输出位序）
    song_radio.change(on_offset_load, [song_radio], [ui.offset_slider])
