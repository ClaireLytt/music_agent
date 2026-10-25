"""Gradio UI — 歌词透镜 Lyric Lens（兼容转发层）.

实现已按 Tab 拆进 webui/ 包（见 docs/architecture.md）：
    webui/app.py        create_app / launch_kwargs（组装 + 启动序列）
    webui/runtime.py    跨 Tab 共享状态与后台任务
    webui/tab_*.py      各页签的布局与 handler
    webui/channels.py   MCP 播放命令轮询

本模块保留为公共导入面：cli.py / 旧脚本 继续 `from .ui import ...`。
"""

from __future__ import annotations

from .ui_helpers import _discover_songs  # noqa: F401 — re-export for cli.py
from .webui.app import create_app, launch_kwargs  # noqa: F401

__all__ = ["create_app", "launch_kwargs", "_discover_songs"]
