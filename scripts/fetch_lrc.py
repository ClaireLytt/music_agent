#!/usr/bin/env python3
"""Thin wrapper: use `lyric-agent fetch-lrc <song_dir>` instead.

Usage:
    python scripts/fetch_lrc.py              # fetch all songs with metadata.json
    python scripts/fetch_lrc.py cardigan     # fetch one song by directory name
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyric_agent.cli import _fetch_lrc_for  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "songs"


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None
    dirs = [d for d in sorted(DATA_DIR.iterdir())
            if d.is_dir() and (d / "metadata.json").exists()]
    if target:
        dirs = [d for d in dirs if d.name == target]
        if not dirs:
            print(f"Unknown song: {target}")
            sys.exit(1)

    for d in dirs:
        print(f"Fetching: {d.name}")
        try:
            n = _fetch_lrc_for(d)
            print(f"  Saved lyrics.lrc ({n} lines)")
        except Exception as exc:
            print(f"  SKIPPED - {exc}")
        time.sleep(1)  # be polite to the API


if __name__ == "__main__":
    main()
