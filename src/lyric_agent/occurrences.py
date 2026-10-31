from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import dictionary
from .intertextuality.corpus import load_corpus
from .intertextuality.search import is_cjk_text

_WORD_RE = re.compile(r"[A-Za-z']+")


@lru_cache(maxsize=4)
def _index(corpus_dir: str, mtime: float) -> dict[str, list[tuple[str, int, str]]]:
    idx: dict[str, list[tuple[str, int, str]]] = {}
    for cl in load_corpus(corpus_dir):
        if is_cjk_text(cl.text):
            continue
        keys: set[str] = set()
        for token in _WORD_RE.findall(cl.text):
            keys.update(dictionary.candidates(token))
        for key in keys:
            idx.setdefault(key, []).append((cl.song, cl.line_index, cl.text))
    return idx


def _annotated(songs_dir: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    base = Path(songs_dir)
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        ann_path = d / "annotations.json"
        if not d.is_dir() or not ann_path.exists():
            continue
        try:
            raw = json.loads(ann_path.read_text(encoding="utf-8"))
            meta_path = d / "metadata.json"
            title = (json.loads(meta_path.read_text(encoding="utf-8"))
                     .get("title", "") if meta_path.exists()
                     else raw.get("song", {}).get("title", ""))
            indices = {int(a["line_index"]) for a in raw.get("annotations", [])
                       if "line_index" in a}
        except (OSError, ValueError, TypeError):
            continue
        if title:
            out.setdefault(title.lower(), set()).update(indices)
    return out


def find_occurrences(word: str, corpus_dir: str, songs_dir: str,
                     song: str = "", line: str = "",
                     limit: int = 20) -> dict:
    path = Path(corpus_dir) / "discography.jsonl"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    idx = _index(corpus_dir, mtime)
    hits: list[tuple[str, int, str]] = []
    seen_ids: set[tuple[str, int]] = set()
    for cand in dictionary.candidates(word):
        for hit in idx.get(cand, []):
            if (hit[0], hit[1]) not in seen_ids:
                seen_ids.add((hit[0], hit[1]))
                hits.append(hit)
    dedup: dict[tuple[str, str], tuple[str, int, str]] = {}
    for h in sorted(hits, key=lambda h: (h[0], h[1])):
        if line and h[2] == line and (not song or h[0] == song):
            continue
        dedup.setdefault((h[0], h[2]), h)
    annotated = _annotated(songs_dir)
    ordered = sorted(dedup.values(), key=lambda h: (
        0 if song and h[0] == song else 1,
        0 if h[1] in annotated.get(h[0].lower(), set()) else 1,
        h[0], h[1],
    ))
    return {
        "word": word,
        "lemma": dictionary.lemma_of(word),
        "total": len(ordered),
        "items": [{"song": s, "line_index": i, "line": t}
                  for s, i, t in ordered[:max(limit, 0)]],
    }
