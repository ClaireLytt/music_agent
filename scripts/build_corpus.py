#!/usr/bin/env python3
"""Thin wrapper: use `lyric-agent build-corpus` instead.

Usage:
    python scripts/build_corpus.py [--bulk lyrics.jsonl]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyric_agent.cli import cli  # noqa: E402

if __name__ == "__main__":
    args = ["build-corpus"]
    if "--bulk" in sys.argv:
        idx = sys.argv.index("--bulk")
        if idx + 1 < len(sys.argv):
            args += ["--bulk", sys.argv[idx + 1]]
    cli(args)
