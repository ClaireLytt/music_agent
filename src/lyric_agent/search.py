"""Lyrics search across all songs (PRD F-09).

Two modes:
  keyword  — full-text substring match, millisecond-fast
  semantic — embedding search (requires sentence-transformers; falls back
             to keyword mode when unavailable)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .lrc_parser import load_lrc_file

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    song_name: str
    song_title: str
    album: str
    line_index: int
    timestamp_ms: int
    text: str
    score: float = 1.0


class LyricsSearcher:
    def __init__(self, songs: list[dict], model_name: str | None = None) -> None:
        """songs: list of song-info dicts from the UI discovery step."""
        self._model_name = model_name
        self._entries: list[SearchHit] = []
        for s in songs:
            lrc = Path(s["dir"]) / "lyrics.lrc"
            if not lrc.exists():
                continue
            try:
                _, lines = load_lrc_file(str(lrc))
            except Exception as exc:
                logger.warning("Failed parsing %s: %s", lrc, exc)
                continue
            for ln in lines:
                self._entries.append(SearchHit(
                    song_name=s["name"],
                    song_title=s["title"],
                    album=s["album"],
                    line_index=ln.line_index,
                    timestamp_ms=ln.timestamp_ms,
                    text=ln.text,
                ))
        self._embeddings = None
        self._embed_model = None

    # ── keyword ──
    def keyword(self, query: str, limit: int = 10) -> list[SearchHit]:
        q = query.strip().lower()
        if not q:
            return []
        hits = [e for e in self._entries if q in e.text.lower()]
        return hits[:limit]

    # ── semantic ──
    def _ensure_embeddings(self) -> bool:
        if self._embeddings is not None:
            return True
        try:
            from .intertextuality.search import get_model
            self._embed_model = (get_model(self._model_name)
                                 if self._model_name else get_model())
            texts = [e.text for e in self._entries]
            self._embeddings = self._embed_model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False)
            return True
        except ImportError:
            return False
        except Exception as exc:
            logger.warning("Embedding init failed: %s", exc)
            return False

    def warm_up(self) -> None:
        """Pre-load the embedding model + entry embeddings (call from a background thread)."""
        self._ensure_embeddings()

    def semantic(self, query: str, limit: int = 10) -> tuple[list[SearchHit], str]:
        """Returns (hits, mode_used)."""
        if not self._ensure_embeddings():
            return self.keyword(query, limit), "keyword"
        import numpy as np
        q_vec = self._embed_model.encode([query], normalize_embeddings=True)[0]
        sims = np.asarray(self._embeddings) @ q_vec
        order = np.argsort(-sims)[:limit]
        hits = []
        for i in order:
            hit = self._entries[int(i)]
            hits.append(SearchHit(**{**hit.__dict__, "score": float(sims[int(i)])}))
        return hits, "semantic"
