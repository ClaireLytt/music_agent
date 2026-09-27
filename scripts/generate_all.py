#!/usr/bin/env python3
"""Thin wrapper: use `lyric-agent pipeline` instead.

Usage:
    python scripts/generate_all.py [--skip-fetch] [--skip-embed]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyric_agent.cli import cli  # noqa: E402

if __name__ == "__main__":
    args = ["pipeline"]
    if "--skip-fetch" in sys.argv:
        args.append("--skip-fetch")
    if "--skip-embed" in sys.argv:
        args.append("--skip-embed")
    cli(args)
