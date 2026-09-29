# -*- coding: utf-8 -*-
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")
from lyric_agent.intertextuality.corpus import load_corpus

corpus = load_corpus(Path("data/corpus/discography.jsonl"))
c = Counter(cl.artist for cl in corpus)
for artist, n in c.most_common(20):
    print(f"{artist!r}: {n}")
print("total lines:", len(corpus))
