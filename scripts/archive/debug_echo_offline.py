# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "src")
from lyric_agent.config import load_settings
from lyric_agent.intertextuality.embeddings import load_embeddings
from lyric_agent.intertextuality.search import search_similar

s = load_settings()
emb, corpus = load_embeddings(s.corpus_dir)
queries = [
    "Dancin' in your Levi's",
    "And you call me up again just to break me like a promise",
    "But I keep cryin', 'cause I love him",
]
for q in queries:
    print("Q:", q)
    for r in search_similar(q, emb, corpus, top_k=4, exclude_song="cardigan",
                            min_similarity=0.0, artist="Taylor Swift"):
        print(f"  {r.similarity:.3f} [{r.song}] {r.line}")
    print()
