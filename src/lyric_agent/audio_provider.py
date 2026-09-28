"""Multi-backend audio source resolution (PRD F-01).

Resolution order:
  1. Local file  (audio.mp3/wav/flac/ogg/m4a in the song directory)
  2. Online URL  (audio_url in metadata.json)
  3. None        (lyrics-only browsing mode, graceful degradation)
"""

from __future__ import annotations

import json
from pathlib import Path

from .annotator.models import AudioSource

_AUDIO_EXTS = ("mp3", "wav", "flac", "ogg", "m4a")


def resolve(song_dir: str | Path) -> AudioSource:
    d = Path(song_dir)

    for ext in _AUDIO_EXTS:
        candidate = d / f"audio.{ext}"
        if candidate.exists():
            return AudioSource(type="local", path_or_url=str(candidate))

    meta_path = d / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        url = meta.get("audio_url", "")
        if url:
            return AudioSource(
                type="url",
                path_or_url=url,
                is_preview=bool(meta.get("audio_is_preview", False)),
            )

    return AudioSource(type="none", path_or_url=None)
