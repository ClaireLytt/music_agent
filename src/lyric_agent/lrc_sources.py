"""Synced-lyrics lookup on LRCLIB (the single implementation — UI, CLI and
pipeline scripts all fetch through here)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_USER_AGENT = "lyric-agent/0.1 (https://github.com/ClaireLytt/lyric_agent)"
_MAX_ATTEMPTS = 3
_MAX_RETRY_AFTER_S = 10.0


def _get_json(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    from .jsonio import V4FirstHTTPSHandler
    opener = urllib.request.build_opener(V4FirstHTTPSHandler())
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            last_exc = e
            if attempt == _MAX_ATTEMPTS - 1:
                break
            retry_after = e.headers.get("Retry-After")
            try:
                delay = min(float(retry_after), _MAX_RETRY_AFTER_S) \
                    if retry_after else 2.0 ** attempt
            except (TypeError, ValueError):
                delay = 2.0 ** attempt
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def fetch_synced_lyrics(title: str, artist: str = "",
                        timeout: int = 15) -> str | None:
    """Best-effort synced-LRC lookup; None when nothing usable is found."""
    params = {"track_name": title.strip()}
    if artist.strip():
        params["artist_name"] = artist.strip()
    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(params)
    try:
        results = _get_json(url, timeout)
    except Exception:
        logger.warning("LRCLIB lookup failed for %r / %r",
                       title, artist, exc_info=True)
        return None
    candidates = [e for e in results
                  if e.get("syncedLyrics") and not e.get("instrumental")]
    exact = next(
        (e for e in candidates
         if (e.get("trackName") or "").casefold() == title.strip().casefold()),
        None)
    pick = exact or (candidates[0] if candidates else None)
    return pick["syncedLyrics"] if pick else None
