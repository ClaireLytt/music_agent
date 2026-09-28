# -*- coding: utf-8 -*-
"""Find a sensible min_similarity for the whole-song echo map."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np

from lyric_agent.intertextuality.corpus import load_corpus
from lyric_agent.intertextuality.search import artist_matches, get_model
from lyric_agent.lrc_parser import parse_lrc

corpus = load_corpus("data/corpus")
emb = np.load("data/corpus/embeddings.npy")

for song_dir in ["cardigan", "anti_hero", "exile"]:
    meta = json.loads(Path(f"data/songs/{song_dir}/metadata.json").read_text(encoding="utf-8"))
    _, lines = parse_lrc(Path(f"data/songs/{song_dir}/lyrics.lrc").read_text(encoding="utf-8"))
    texts = [ln.text for ln in lines if ln.text.strip()]

    title, artist = meta["title"], meta.get("artist", "")
    mask = np.ones(len(corpus), dtype=bool)
    for i, cl in enumerate(corpus):
        if cl.song.lower() == title.lower():
            mask[i] = False
        elif artist and not artist_matches(artist, cl.artist):
            mask[i] = False
    if not mask.any():
        print(f"\n{title}: EMPTY corpus after artist filter ({artist})")
        continue

    model = get_model()
    q = model.encode(texts, convert_to_numpy=True)
    q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-8)
    c = emb[mask]
    c = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-8)
    best = (q @ c.T).max(axis=1)

    print(f"\n{title}: {len(texts)} lines, best-sim stats: "
          f"min={best.min():.2f} med={np.median(best):.2f} max={best.max():.2f}")
    for th in [0.55, 0.6, 0.62, 0.65, 0.7]:
        n = int((best >= th).sum())
        print(f"  th={th}: {n} marked ({100*n/len(texts):.0f}%)")
