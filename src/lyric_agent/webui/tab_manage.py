"""页签「➕ 添加歌曲」+ 曲库管理（刷新 / 删除 / 目录导入）.

添加/删除后要刷新播放页的 song_radio 并重走 on_song_select——
这些跨 tab 的组件与 handler 经 ui 命名空间取自 tab_play。
整页 if not public。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

import gradio as gr

from ..lrc_parser import parse_lrc
from ..ui_helpers import (_SONG_DATA_CACHE, _fetch_lrc_from_lrclib,
                          _load_catalog, _PLACEHOLDER_LRC)
from .runtime import Runtime

logger = logging.getLogger(__name__)


def build(rt: Runtime, ui) -> None:
    if rt.public:
        return
    with gr.Tab("➕ 添加歌曲"):
        ui.catalog = _load_catalog()
        cat_labels = [f"{c['title']} — {c['artist']}" for c in ui.catalog]
        # 空锚点：CSS 靠 #ll-add-head 给本页签做缩放/定宽
        gr.HTML("", elem_id="ll-add-head")
        with gr.Accordion(
                f"📚 从内置曲库挑选（{len(cat_labels)} 首）",
                open=False):
            ui.cat_search = gr.Textbox(
                label="搜索曲库（歌名 / 歌手 / 专辑）",
                elem_id="ll-cat-search")
            with gr.Row():
                ui.cat_all_btn = gr.Button("☑️ 全选", size="sm",
                                           scale=1)
                ui.cat_none_btn = gr.Button("⬜ 取消全选", size="sm",
                                            scale=1)
            ui.cat_radio = gr.CheckboxGroup(
                choices=cat_labels, value=[],
                label=f"曲库歌曲（{len(cat_labels)} 首）",
                elem_id="ll-catalog")
            ui.cat_add_btn = gr.Button("＋ 添加勾选的歌曲",
                                       variant="primary")
        ui.add_state = gr.State("")  # last added song dir name

        with gr.Accordion("✍️ 手动添加曲库以外的歌曲", open=False):
            with gr.Row():
                ui.add_title = gr.Textbox(label="歌曲标题（必填）",
                                          elem_id="ll-add-title")
                ui.add_artist = gr.Dropdown(
                    choices=[], value=None,
                    label="歌手（选填 — 可从已有歌手里选，"
                          "也可直接输入）",
                    allow_custom_value=True,
                    elem_id="ll-add-artist")
                ui.add_album = gr.Textbox(label="专辑（选填）")
            ui.add_lrc = gr.Textbox(
                label="LRC 歌词（选填 — 格式如 [00:12.34] 歌词内容，"
                      "留空将自动从 LRCLIB 获取）",
                lines=8, elem_id="ll-add-lrc")
            with gr.Row():
                ui.add_lrc_file = gr.File(
                    label="或上传 .lrc 文件（可选，优先于文本框）",
                    file_types=[".lrc", ".txt"])
                ui.add_audio_file = gr.File(
                    label="音频文件（可选）",
                    file_types=[".mp3", ".wav", ".m4a", ".ogg",
                                ".flac"])
            ui.add_btn = gr.Button("💾 保存歌曲", variant="primary")
        ui.add_status = gr.Markdown("", elem_classes=["add-status"])


def wire(rt: Runtime, ui) -> None:
    if rt.public:
        return
    ctx = rt.cache
    song_choices = rt.song_choices
    song_choice_label = rt.song_choice_label
    refresh_library = rt.refresh_library
    _filtered_labels = rt.filtered_labels
    song_radio, sort_mode, song_filter = (ui.song_radio, ui.sort_mode,
                                          ui.song_filter)
    catalog = ui.catalog

    # ── 添加歌曲 ──

    def on_add_song(title, artist, album, lrc_text, lrc_file, audio_file,
                    sort):
        def fail(msg):
            return msg, gr.skip(), ""

        title = (title or "").strip()
        if not title:
            return fail("⚠️ 请填写歌曲标题（唯一必填项，其余均可留空）。")

        slug = re.sub(r"[^\w]+", "_", title.lower()).strip("_") \
            or f"song_{int(time.time())}"
        d = Path(rt.settings.songs_dir) / slug
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
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8")
        if audio_file:
            ext = Path(audio_file).suffix.lower() or ".mp3"
            shutil.copy(audio_file, d / f"audio{ext}")

        refresh_library()
        rt.kick_corpus_rebuild()
        new_song = next((s for s in ctx["songs"] if s["name"] == slug),
                        None)
        new_label = song_choice_label(new_song) if new_song else None
        status = f"✅ 已添加《{title}》（{lrc_note}）"
        return (status,
                gr.Radio(choices=song_choices("added_desc"),
                         value=new_label), slug)

    ui.add_btn.click(
        on_add_song,
        [ui.add_title, ui.add_artist, ui.add_album,
         ui.add_lrc, ui.add_lrc_file, ui.add_audio_file, sort_mode],
        [ui.add_status, song_radio, ui.add_state],
    ).then(
        # choices come pre-sorted newest-first so the new song is at
        # the TOP; rebuilding choices doesn't fire song_radio.change,
        # so load it explicitly here. song_filter is intentionally
        # NOT an output: clearing it cascades through on_song_filter
        # and re-sorts the list, undoing the newest-first order
        ui.on_song_select, [song_radio], ui.song_outputs,
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
        n_add = sum(1 for _d, v in choices
                    if not v.startswith("__have__"))
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

    ui.cat_search.change(on_cat_search, [ui.cat_search], [ui.cat_radio])
    ui.cat_all_btn.click(on_cat_all, [ui.cat_search], [ui.cat_radio])
    ui.cat_none_btn.click(on_cat_none, None, [ui.cat_radio])

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
            d = Path(rt.settings.songs_dir) / slug
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
                d = Path(rt.settings.songs_dir) / slug
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
        return ("　".join(parts),
                gr.Radio(choices=song_choices("added_desc"),
                         value=last_label),
                last_slug)

    ui.cat_add_btn.click(on_cat_add, [ui.cat_radio, sort_mode],
                         [ui.add_status, song_radio, ui.add_state]).then(
        # newest-first choices + explicit load; song_filter left out
        # on purpose (see on_add_song wiring)
        ui.on_song_select, [song_radio], ui.song_outputs,
    ).then(lambda: gr.Radio(value="added_desc"), None, [sort_mode])

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
        ctx.invalidate_echo_scans()
        gr.Info(f"🔄 已刷新，共 {len(ctx['songs'])} 首歌。")
        return _library_updates(choice, sort, q)

    def on_del_song(payload: str, sort: str, q: str):
        # payload: '<label>\t<ts>' from the ⋯ menu, already confirmed
        # by a native dialog in the browser
        label = (payload or "").split("\t")[0].strip()
        if not label:
            return gr.skip()
        info = next(
            (s for s in ctx["songs"]
             if song_choice_label(s) == label), None)
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
        ctx.invalidate_song(info["dir"])
        refresh_library()
        rt.kick_corpus_rebuild()
        gr.Info(f"🗑️ 已删除《{label}》。")
        return _library_updates(None, sort, q)

    # rebuilding Radio choices never fires .change, so chain the
    # full select pipeline (incl. echo map) explicitly — otherwise
    # deleting the selected song leaves the previous song's 🥚
    # markers/overview on screen
    ui.manage_refresh_btn.click(
        on_manage_refresh, [song_radio, sort_mode, song_filter],
        [song_radio],
    ).then(ui.on_song_select, [song_radio], ui.song_outputs)
    ui.del_box.change(
        on_del_song, [ui.del_box, sort_mode, song_filter],
        [song_radio],
    ).then(ui.on_song_select, [song_radio], ui.song_outputs)
