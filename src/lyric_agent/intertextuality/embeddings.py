"""Generate and store sentence embeddings for lyrics corpus."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..config import DEFAULT_EMBEDDING_MODEL
from .corpus import CorpusLine, load_corpus

logger = logging.getLogger(__name__)


def generate_embeddings(
    corpus_dir: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> tuple[np.ndarray, list[CorpusLine]]:
    """Generate embeddings for all corpus lines and save to disk.

    Returns (embeddings_matrix, corpus_lines).
    """
    corpus = load_corpus(corpus_dir)
    if not corpus:
        raise ValueError(f"No corpus data found in {corpus_dir}/discography.jsonl")

    logger.info("Generating embeddings for %d lines with %s", len(corpus), model_name)

    from .search import get_model
    model = get_model(model_name)
    texts = [line.text for line in corpus]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    out_path = Path(corpus_dir) / "embeddings.npy"
    np.save(str(out_path), embeddings)
    logger.info("Saved embeddings to %s (shape: %s)", out_path, embeddings.shape)

    return embeddings, corpus


def load_embeddings(corpus_dir: str) -> tuple[np.ndarray, list[CorpusLine]]:
    """Load pre-computed embeddings and corpus from disk."""
    emb_path = Path(corpus_dir) / "embeddings.npy"
    if not emb_path.exists():
        raise FileNotFoundError(
            f"No embeddings found at {emb_path}. Run `generate_embeddings()` first."
        )

    embeddings = np.load(str(emb_path))
    corpus = load_corpus(corpus_dir)

    if len(corpus) != embeddings.shape[0]:
        raise ValueError(
            f"Corpus size ({len(corpus)}) != embedding rows ({embeddings.shape[0]}). "
            "Regenerate embeddings."
        )

    return embeddings, corpus
