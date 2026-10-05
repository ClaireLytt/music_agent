#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo warm-up: pre-load the embedding model + corpus index so a live
demo never hits the 10-20s first-query stall.

    python scripts/warm_cache.py

Safe to re-run: loading an already-cached index is near-instant.
"""

from __future__ import annotations

import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "src")
from lyric_agent.config import load_settings  # noqa: E402


def main() -> int:
    settings = load_settings()

    print("warming embedding model + corpus index …")
    from lyric_agent.intertextuality.embeddings import load_embeddings
    from lyric_agent.intertextuality.search import get_model
    embeddings, corpus = load_embeddings(settings.corpus_dir,
                                         settings.embedding_model)
    get_model(settings.embedding_model)
    artists = sorted({r.artist for r in corpus if r.artist})
    print(f"index ready: {len(corpus)} lines, {len(artists)} artists")
    print("done — demo caches are warm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
