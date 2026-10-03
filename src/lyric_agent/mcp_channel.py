"""File-based command bridge between the MCP server and the running UI.

The MCP process (`lyric-agent mcp`) atomically writes a command file;
the Gradio UI polls it with a gr.Timer and applies the command. Both
sides share this module; no gradio or mcp imports here.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

MCP_COMMAND_PATH = Path("data/cache/mcp_command.json")


def write_mcp_command(cmd: str, *, title: str = "",
                      line_index: int | None = None,
                      path: Path | None = None) -> dict:
    """Atomically write a command for the UI poller; returns the payload."""
    path = path or MCP_COMMAND_PATH  # resolved at call time (testable)
    payload = {"cmd": cmd, "title": title, "line_index": line_index,
               "ts": time.time(), "nonce": uuid.uuid4().hex}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{payload['nonce']}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic — the poller never sees partial JSON
    return payload


def read_mcp_command(after_mtime: float, path: Path | None = None
                     ) -> tuple[float, dict | None]:
    """Cheap poll: (mtime, payload) only when the file is newer than
    after_mtime and parses; otherwise (latest known mtime, None).
    Never raises — this runs on every timer tick."""
    path = path or MCP_COMMAND_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return after_mtime, None
    if mtime <= after_mtime:
        return mtime, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return mtime, None
        return mtime, payload
    except (OSError, ValueError):
        return mtime, None
