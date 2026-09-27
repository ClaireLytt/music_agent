"""Shared utility functions."""

from __future__ import annotations

import json
from typing import Any


def truncate(text: str, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def safe_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": "Failed to serialize result"})
