"""跨 Tab 基础设施通道：MCP 播放命令轮询.

隐藏 Textbox 通道组件本身在 tab_play.build 创建（必须常驻播放页 DOM，
与 ui_assets._HEAD_JS 的 JS 侧一一配对）；这里只放与具体 Tab 无关的
MCP 命令文件轮询（`lyric-agent mcp` 写命令文件 → Timer 读 → JS 播放）。
"""

from __future__ import annotations

import json

import gradio as gr

from ..mcp_channel import MCP_COMMAND_PATH, read_mcp_command
from .runtime import Runtime


def wire(rt: Runtime, ui) -> None:
    if rt.public:
        return
    # ── MCP 播放命令通道（lyric-agent mcp 写命令文件，这里轮询）──
    mcp_seen = gr.State(0.0)
    mcp_timer = gr.Timer(1.0)

    def on_mcp_tick(seen: float):
        mtime, cmd = read_mcp_command(seen)
        if cmd is None:
            return ((mtime if mtime != seen else gr.skip()),
                    gr.skip(), gr.skip())
        payload = json.dumps(
            {"cmd": cmd.get("cmd"), "title": cmd.get("title", ""),
             "line": cmd.get("line_index"), "ts": cmd.get("ts")},
            ensure_ascii=False)
        label = rt.label_of().get(cmd.get("title", ""))
        if cmd.get("cmd") == "play" and label:
            return mtime, gr.Radio(value=label), payload
        return mtime, gr.skip(), payload

    # programmatic Radio updates fire song_radio.change in this
    # build (the overview-chip jump relies on the same mechanism),
    # so no explicit re-render chain here — and none is wanted:
    # a .then would re-render on every tick, not just on commands
    mcp_timer.tick(on_mcp_tick, [mcp_seen],
                   [mcp_seen, ui.song_radio, ui.mcp_play_box])

    # a page opened later must not replay an old command
    ui.app.load(
        lambda: (MCP_COMMAND_PATH.stat().st_mtime
                 if MCP_COMMAND_PATH.exists() else 0.0),
        None, [mcp_seen])
