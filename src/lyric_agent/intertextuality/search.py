"""Similarity search across lyrics corpus using embeddings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from .corpus import CorpusLine

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, object] = {}

_FEAT_SPLIT_RE = re.compile(
    r"\s+(?:ft\.?|feat\.?|featuring|x|×)\s+|、|/|&|,", re.IGNORECASE)


def _primary_artist(name: str) -> str:
    return _FEAT_SPLIT_RE.split(name or "")[0].strip().lower()


def artist_matches(want: str, have: str) -> bool:
    """Match by primary artist so 'Taylor Swift ft. Bon Iver' == 'Taylor Swift'."""
    w, h = _primary_artist(want), _primary_artist(have)
    return bool(w) and w == h


def get_model(model_name: str = "all-MiniLM-L6-v2"):
    """Shared, cached SentenceTransformer instance (used by both search layers)."""
    if model_name not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading sentence-transformer model: %s", model_name)
        _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
    return _MODEL_CACHE[model_name]


@dataclass
class SearchResult:
    song: str
    album: str
    line: str
    similarity: float
    artist: str = ""


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between vector a and matrix b."""
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-8)
    return b_norm @ a_norm


def find_echo_lines(
    texts: list[str],
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    model_name: str = "all-MiniLM-L6-v2",
    exclude_song: str | None = None,
    min_similarity: float = 0.62,
    artist: str | None = None,
) -> list[bool]:
    """Batch check: for each input line, does the corpus hold an echo?

    Returns one bool per input text. Much faster than per-line search_similar
    for whole-song scans (single encode call + one matrix product).
    """
    if not texts:
        return []
    mask = np.ones(len(corpus), dtype=bool)
    for i, line in enumerate(corpus):
        if exclude_song and line.song.lower() == exclude_song.lower():
            mask[i] = False
        elif artist and not artist_matches(artist, line.artist):
            mask[i] = False
    if not mask.any():
        return [False] * len(texts)

    model = get_model(model_name)
    query = model.encode(texts, convert_to_numpy=True)
    query = query / (np.linalg.norm(query, axis=1, keepdims=True) + 1e-8)
    corpus_emb = embeddings[mask]
    corpus_emb = corpus_emb / (np.linalg.norm(corpus_emb, axis=1, keepdims=True) + 1e-8)
    best = (query @ corpus_emb.T).max(axis=1)
    return [float(s) >= min_similarity for s in best]


def search_similar(
    query_text: str,
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    model_name: str = "all-MiniLM-L6-v2",
    top_k: int = 5,
    exclude_song: str | None = None,
    min_similarity: float = 0.3,
    artist: str | None = None,
) -> list[SearchResult]:
    """Find the most similar lyrics lines to the query text.

    Args:
        query_text: The lyric line to search for.
        embeddings: Pre-computed embedding matrix.
        corpus: Corpus lines matching the embedding rows.
        model_name: Sentence transformer model for encoding the query.
        top_k: Number of results to return.
        exclude_song: Exclude results from this song title.
        min_similarity: Minimum cosine similarity threshold.
        artist: Only return results from this artist (case-insensitive).
    """
    model = get_model(model_name)
    query_emb = model.encode([query_text], convert_to_numpy=True)[0]

    similarities = cosine_similarity(query_emb, embeddings)

    indices = np.argsort(similarities)[::-1]

    results: list[SearchResult] = []
    for idx in indices:
        if len(results) >= top_k:
            break

        sim = float(similarities[idx])
        if sim < min_similarity:
            break

        line = corpus[idx]
        if exclude_song and line.song.lower() == exclude_song.lower():
            continue
        if artist and not artist_matches(artist, line.artist):
            continue
        if any(r.song == line.song and r.line == line.text for r in results):
            continue

        results.append(SearchResult(
            song=line.song,
            album=line.album,
            line=line.text,
            similarity=round(sim, 3),
            artist=line.artist,
        ))

    return results
