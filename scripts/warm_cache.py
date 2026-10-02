#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo warm-up: pre-generate every LLM-backed cache so a live demo never
waits on the proxy.

    python scripts/warm_cache.py                 # all artists' reports
    python scripts/warm_cache.py --mv cardigan --mv cruel_summer

Warms, in order:
  1. embedding model + corpus index (the 10-20s first-query stall)
  2. 🏺 archaeology narrative per corpus artist (skips cached)
  3. 🎬 MV eggs for the given --mv song dirs (skips cached)
Safe to re-run: everything is cache-checked first.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "src")

from lyric_agent.archaeology import (load_report, mine_motifs,  # noqa: E402
                                     parse_report, report_messages,
                                     save_report)
from lyric_agent.config import load_settings  # noqa: E402
from lyric_agent.llm import LLMClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mv", action="append", default=[],
                    help="song dir name under data/songs to warm MV eggs for")
    ap.add_argument("--skip-reports", action="store_true")
    args = ap.parse_args()

    settings = load_settings(require_api_key=True)
    reports_dir = Path(settings.songs_dir).parent / "reports"

    print("1/3 warming embedding model + corpus index …")
    from lyric_agent.intertextuality.embeddings import load_embeddings
    from lyric_agent.intertextuality.search import get_model
    embeddings, corpus = load_embeddings(settings.corpus_dir,
                                         settings.embedding_model)
    get_model(settings.embedding_model)
    artists = sorted({r.artist for r in corpus if r.artist})
    print(f"   index ready: {len(corpus)} lines, {len(artists)} artists")

    client = LLMClient(settings)

    if not args.skip_reports:
        print("2/3 archaeology reports …")
        for artist in artists:
            if load_report(reports_dir, artist, settings.model_name):
                print(f"   ✓ cached: {artist}")
                continue
            motifs = mine_motifs(corpus, artist)
            if not motifs:
                print(f"   - no motifs (corpus too small): {artist}")
                continue
            system, user = report_messages(artist, motifs)
            try:
                resp = client.generate(system_prompt=system, user_message=user)
                narrative = parse_report(resp.reply_text)
                if narrative and narrative.get("arcs"):
                    save_report(reports_dir, artist, settings.model_name,
                                narrative)
                    print(f"   ✚ generated: {artist} "
                          f"({len(narrative['arcs'])} arcs)")
                else:
                    print(f"   ⚠ unparseable narrative: {artist}")
            except Exception as exc:
                print(f"   ⚠ failed: {artist}: {str(exc)[:100]}")

    print("3/3 MV eggs …")
    from lyric_agent.mv_eggs import load_mv, mv_messages, save_mv
    for name in args.mv:
        d = Path(settings.songs_dir) / name
        meta_p = d / "metadata.json"
        if not meta_p.exists():
            print(f"   ⚠ no such song dir: {name}")
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if load_mv(d, settings.model_name) is not None:
            print(f"   ✓ cached: {name}")
            continue
        system, user = mv_messages(meta.get("title", name),
                                   meta.get("artist", ""),
                                   meta.get("album", ""), meta.get("year"))
        try:
            data = client.generate_json(system, user)
            save_mv(d, data, settings.model_name)
            eggs = data.get("eggs") or []
            print(f"   ✚ generated: {name} ({len(eggs)} eggs)")
        except Exception as exc:
            print(f"   ⚠ failed: {name}: {str(exc)[:100]}")

    print("done — demo caches are warm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
