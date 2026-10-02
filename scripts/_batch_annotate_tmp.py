# -*- coding: utf-8 -*-
"""Batch-annotate every song missing good annotations, sequentially (to
avoid the connection resets parallel calls triggered), with a retry pass.
Resumable: re-running only touches songs still lacking clean annotations.
Delete after use."""
import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "src")

from lyric_agent.annotator.engine import generate_annotations  # noqa: E402
from lyric_agent.config import load_settings  # noqa: E402

settings = load_settings(require_api_key=True)
base = Path(settings.songs_dir)


def needs(song_dir: Path) -> bool:
    if not (song_dir / "lyrics.lrc").exists():
        return False
    ann = song_dir / "annotations.json"
    if not ann.exists():
        return True
    try:
        data = json.loads(ann.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return any("failed" in str(a.get("summary", "")).lower()
               for a in data.get("annotations", []))


todo = [d for d in sorted(base.iterdir()) if d.is_dir() and needs(d)]
print(f"{len(todo)} songs need annotation", flush=True)

for i, d in enumerate(todo, 1):
    for attempt in (1, 2, 3):
        try:
            song = generate_annotations(settings, d)
            bad = sum(1 for a in song.annotations
                      if "failed" in str(a.summary).lower())
            if bad:
                raise RuntimeError(f"{bad} failed chunks")
            print(f"[{i}/{len(todo)}] {d.name}: "
                  f"{len(song.annotations)} ok", flush=True)
            break
        except Exception as exc:
            print(f"[{i}/{len(todo)}] {d.name}: attempt {attempt} "
                  f"{type(exc).__name__}: {str(exc)[:60]}", flush=True)
            time.sleep(3 * attempt)
    else:
        print(f"[{i}/{len(todo)}] {d.name}: GAVE UP after 3 tries", flush=True)

left = [d for d in sorted(base.iterdir()) if d.is_dir() and needs(d)]
print(f"DONE. still incomplete: {len(left)}"
      + (" -> re-run this script to finish them" if left else ""), flush=True)
