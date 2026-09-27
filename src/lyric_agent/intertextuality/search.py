"""Similarity search across lyrics corpus using embeddings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from ..config import (
    DEFAULT_ECHO_MIN_SIMILARITY,
    DEFAULT_ECHO_MIN_SIMILARITY_CJK,
    DEFAULT_ECHO_SEARCH_SIMILARITY,
    DEFAULT_ECHO_SEARCH_SIMILARITY_CJK,
    DEFAULT_EMBEDDING_MODEL,
)
from .corpus import CorpusLine

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, object] = {}

_FEAT_SPLIT_RE = re.compile(
    r"\s+(?:ft\.?|feat\.?|featuring|x|×)\s+|、|/|&|,", re.IGNORECASE)

_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")

# above this similarity, two *different* texts mean the encoder collapsed
# them onto (nearly) the same vector — a model artifact (typical for CJK
# lines under the default English MiniLM), not a real echo
NEAR_IDENTICAL_SIMILARITY = 0.99


def primary_artist(name: str) -> str:
    return _FEAT_SPLIT_RE.split(name or "")[0].strip().lower()


def is_cjk_text(text: str) -> bool:
    """True when CJK characters dominate the line (>30% of non-space chars)."""
    chars = [c for c in (text or "") if not c.isspace()]
    if not chars:
        return False
    return len(_CJK_RE.findall("".join(chars))) / len(chars) > 0.3


# minimum length of a verbatim shared phrase for a CJK line pair to count
# as an echo — embedding distances alone are not trustworthy for CJK under
# the default English model, so CJK echoes must be text-anchored
CJK_SHARED_PHRASE_LEN = 3


def _cjk_ngrams(text: str, n: int) -> set[str]:
    chars = "".join(_CJK_RE.findall(text or ""))
    return {chars[i:i + n] for i in range(len(chars) - n + 1)}


def cjk_pair_anchored(a: str, b: str, n: int = CJK_SHARED_PHRASE_LEN) -> bool:
    """True when two CJK lines share a verbatim phrase of >= n characters."""
    return bool(_cjk_ngrams(a, n) & _cjk_ngrams(b, n))


def artist_matches(want: str, have: str) -> bool:
    """Match by primary artist so 'Taylor Swift ft. Bon Iver' == 'Taylor Swift'."""
    w, h = primary_artist(want), primary_artist(have)
    return bool(w) and w == h


def get_model(model_name: str = DEFAULT_EMBEDDING_MODEL):
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


@dataclass
class EchoLine:
    """Strongest cross-song echo found for one lyric line of a song."""
    song: str
    album: str
    line: str
    similarity: float


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between vector a and matrix b."""
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-8)
    return b_norm @ a_norm


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Row-normalize so a plain matrix product yields cosine similarities."""
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8)


def find_song_echoes(
    texts: list[str],
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    exclude_song: str | None = None,
    min_similarity: float = DEFAULT_ECHO_MIN_SIMILARITY,
    min_similarity_cjk: float = DEFAULT_ECHO_MIN_SIMILARITY_CJK,
    artist: str | None = None,
) -> list[EchoLine | None]:
    """Batch scan: the strongest echo per input line, None below threshold.

    Much faster than per-line search_similar for whole-song scans
    (single encode call + one matrix product). Pairs where either side is
    mostly CJK use the stricter min_similarity_cjk cutoff (see config).
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
        return [None] * len(texts)
    kept = np.flatnonzero(mask)

    model = get_model(model_name)
    query = normalize_rows(model.encode(texts, convert_to_numpy=True))
    corpus_emb = normalize_rows(embeddings[kept])
    sims = query @ corpus_emb.T
    best_cols = sims.argmax(axis=1)

    echoes: list[EchoLine | None] = []
    for row, col in enumerate(best_cols):
        sim = float(sims[row, col])
        line = corpus[int(kept[col])]
        cjk_pair = is_cjk_text(texts[row]) or is_cjk_text(line.text)
        threshold = min_similarity_cjk if cjk_pair else min_similarity
        if sim < threshold or (
                sim > NEAR_IDENTICAL_SIMILARITY and texts[row] != line.text):
            echoes.append(None)
            continue
        if cjk_pair and not cjk_pair_anchored(texts[row], line.text):
            echoes.append(None)
            continue
        echoes.append(EchoLine(
            song=line.song, album=line.album,
            line=line.text, similarity=round(sim, 3),
        ))
    return echoes


def search_similar(
    query_text: str,
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 5,
    exclude_song: str | None = None,
    min_similarity: float = DEFAULT_ECHO_SEARCH_SIMILARITY,
    min_similarity_cjk: float = DEFAULT_ECHO_SEARCH_SIMILARITY_CJK,
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
        min_similarity_cjk: Stricter threshold when either line is mostly CJK.
        artist: Only return results from this artist (case-insensitive).
    """
    model = get_model(model_name)
    query_emb = model.encode([query_text], convert_to_numpy=True)[0]

    similarities = cosine_similarity(query_emb, embeddings)

    indices = np.argsort(similarities)[::-1]

    query_cjk = is_cjk_text(query_text)
    results: list[SearchResult] = []
    for idx in indices:
        if len(results) >= top_k:
            break

        sim = float(similarities[idx])
        if sim < min_similarity:
            break

        line = corpus[idx]
        if (query_cjk or is_cjk_text(line.text)) and sim < min_similarity_cjk:
            continue
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


# ── Imagery trace (意象追踪) ──────────────────────────────

DEFAULT_IMAGERY_TOP_K = 40


@dataclass
class ImageryHit:
    """One lyric line matching a traced image/motif."""
    song: str
    album: str
    line: str
    similarity: float
    artist: str = ""
    keyword: bool = False  # literal substring match (vs semantic-only)


def trace_imagery(
    query: str,
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    artist: str | None = None,
    top_k: int = DEFAULT_IMAGERY_TOP_K,
    min_similarity: float = DEFAULT_ECHO_SEARCH_SIMILARITY,
    min_similarity_cjk: float = DEFAULT_ECHO_SEARCH_SIMILARITY_CJK,
) -> list[ImageryHit]:
    """Every line carrying an image/motif: literal hits + semantic neighbours.

    Keyword (substring) matches always count; semantic matches obey the
    similarity thresholds. Sorted keyword-first, then by similarity.
    """
    query = (query or "").strip()
    if not query:
        return []
    hits: dict[tuple[str, str], ImageryHit] = {}
    q_lower = query.lower()
    for line in corpus:
        if artist and not artist_matches(artist, line.artist):
            continue
        if q_lower in line.text.lower():
            hits[(line.song, line.text)] = ImageryHit(
                song=line.song, album=line.album, line=line.text,
                similarity=1.0, artist=line.artist, keyword=True)

    for r in search_similar(
            query, embeddings, corpus, model_name=model_name,
            top_k=top_k, min_similarity=min_similarity,
            min_similarity_cjk=min_similarity_cjk, artist=artist):
        key = (r.song, r.line)
        if key not in hits:
            hits[key] = ImageryHit(
                song=r.song, album=r.album, line=r.line,
                similarity=r.similarity, artist=r.artist)

    ordered = sorted(
        hits.values(), key=lambda h: (not h.keyword, -h.similarity))
    return ordered[:top_k]
