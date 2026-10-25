"""App factory：组装各 Tab 模块 + 启动序列.

布局阶段（build）与接线阶段（wire）分开跑：wire 里跨 Tab 引用的组件
（song_radio / song_outputs / on_song_select…）经 ui 命名空间传递，
全部 build 完后一定存在。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import gradio as gr

from ..config import Settings
from ..ui_assets import _CSS, _HEAD_JS
from . import (channels, tab_games, tab_lore, tab_manage, tab_play,
               tab_play_tools, tab_review, tab_settings)
from .runtime import Runtime

try:
    from ..intertextuality.echo_map import ECHO_MAP_CSS
except ImportError:  # embeddings extra not installed — tab shows a hint
    ECHO_MAP_CSS = ""

logger = logging.getLogger(__name__)


def launch_kwargs() -> dict:
    """Style/head kwargs for app.launch() (Gradio 6 moved them off Blocks)."""
    return {
        "css": (_CSS + ECHO_MAP_CSS),
        "head": _HEAD_JS,
        "theme": gr.themes.Base(primary_hue="teal", neutral_hue="slate"),
    }


def create_app(settings: Settings) -> gr.Blocks:
    rt = Runtime(settings)
    rt.start_warm_up()
    public = rt.public

    with gr.Blocks(title="歌词透镜 — AI 歌词批注播放器",
                   fill_width=True) as app:
        ui = SimpleNamespace(app=app)
        # per-visitor LLM config, persisted in the visitor's own browser
        ui.user_llm = gr.BrowserState(
            {"api_key": "", "llm_provider": "openai",
             "llm_base_url": "", "model_name": ""},
            storage_key="lyric_lens_llm")
        gr.HTML(
            '<div class="app-header"><h1>🔍 歌词透镜</h1>'
            '<p>听英文歌，点一句歌词问懂它，把生词练会带走</p></div>'
        )
        # backend -> JS: the login role ("admin"/"viewer"); _HEAD_JS hides
        # the management tabs for non-admins (gradio 6 ignores Tab
        # visibility updates, so this goes through the JS channel instead)
        ui.role_box = gr.Textbox(value="", visible=True, elem_id="ll-role",
                                 elem_classes=["ll-hidden"],
                                 show_label=False, container=False)

        with gr.Tabs():
            tab_play.build(rt, ui)        # ══ 页签 1: 播放解读 ══
            tab_review.build(rt, ui)      # ══ 页签 2: 歌曲寻词 ══
            # ══ 页签 3: 互动（考据 / 竞猜 / 拼图） ══
            with gr.Tab("🎮 互动"), gr.Tabs():
                tab_lore.build(rt, ui)
                tab_games.build(rt, ui)
            tab_manage.build(rt, ui)      # ══ 页签 4: 添加歌曲 ══
            tab_settings.build(rt, ui)    # ══ 页签 5: 设置 ══

        # ── Handlers ──
        tab_play.wire(rt, ui)
        tab_lore.wire(rt, ui)
        tab_games.wire(rt, ui)
        tab_review.wire(rt, ui)
        tab_play_tools.wire(rt, ui)
        channels.wire(rt, ui)
        tab_manage.wire(rt, ui)
        tab_settings.wire(rt, ui)

        # ── 启动序列 ──
        if rt.cache["songs"]:
            app.load(ui.on_song_select, [ui.song_radio], ui.song_outputs)

        if not public:
            # suggest existing artists in the manual-add artist field
            app.load(lambda: gr.Dropdown(choices=rt.corpus_artists()),
                     None, [ui.add_artist])

        # role gating (unconditional — the first version of this sat inside
        # the empty-library else-branch above and never ran with songs
        # present): viewers don't see management tabs. With login disabled
        # (no data/users.json) role_of() says admin for everyone. UI-level
        # only: the JS channel hides tab buttons — handlers are not
        # role-checked server-side (hackathon threat model).
        def _apply_role(request: gr.Request):
            from ..auth import role_of
            return role_of(getattr(request, "username", None))

        app.load(_apply_role, None, [ui.role_box])
        if not public:
            # favs_html was frozen at Blocks-construction time; refresh it
            # for each new session/reload from the current file
            def _reload_collections(choice: str):
                title = rt.find_song(choice).get("title", "")
                return ui.collections_for(title)
            app.load(_reload_collections, [ui.song_radio],
                     [ui.favs_html, ui.wordbook_html, ui.phrasebook_html])

    return app
