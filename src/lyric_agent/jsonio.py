"""Shared JSON-file helpers for the small data/cache stores.

write_json_atomic uses mcp_channel's os.replace pattern so concurrent
readers (and a second process) never see a partially-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_json(path: str | Path, default=None):
    """Parsed JSON at path, or `default` ({} if unset) on any failure."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def write_json_atomic(path: str | Path, obj, indent: int = 1) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
