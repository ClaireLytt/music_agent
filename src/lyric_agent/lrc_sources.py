"""Synced-lyrics lookup on LRCLIB (the single implementation — UI, CLI and
pipeline scripts all fetch through here)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_USER_AGENT = "lyric-agent/0.1"


def fetch_synced_lyrics(title: str, artist: str = "",
                        timeout: int = 15) -> str | None:
    """Best-effort synced-LRC lookup; None when nothing usable is found."""
    query = urllib.parse.quote(f"{artist} {title}".strip())
    req = urllib.request.Request(
        f"https://lrclib.net/api/search?q={query}",
        headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except Exception:
        logger.warning("LRCLIB lookup failed for %r / %r",
                       title, artist, exc_info=True)
        return None
    return next(
        (e["syncedLyrics"] for e in results if e.get("syncedLyrics")), None)
