#!/usr/bin/env python3
"""Build artist evolution data (data/evolution/evolution.json).

Run:  python scripts/build_evolution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lyric_agent.evolution.engine import build_and_save  # noqa: E402


def main() -> None:
    out = ROOT / "data" / "evolution" / "evolution.json"
    evo = build_and_save(ROOT / "data" / "songs", out)
    demo = [e for e in evo.eras if e.songs]
    print(f"Built evolution data: {len(evo.eras)} eras total, "
          f"{len(demo)} with demo songs -> {out}")
    for e in demo:
        print(f"  {e.era}: songs={e.songs} themes={e.theme_weights}")


if __name__ == "__main__":
    main()
