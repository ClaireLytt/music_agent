"""Batch annotation generation pipeline.

Sends lyrics to LLM in chunks, collects structured annotations,
and saves them as JSON per song.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import LLMClient
from ..lrc_parser import TimedLine, load_lrc_file
from .models import Annotation, Song, SongMetadata
from .prompts import annotation_system_prompt, build_annotation_prompt

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10


FAILED_MARKER = "[Annotation generation failed]"


def generate_annotations(
    settings: Settings,
    song_dir: str | Path,
    chunk_size: int = CHUNK_SIZE,
    fresh: bool = False,
) -> Song:
    """Generate annotations for a song and save to annotations.json.

    Expects song_dir to contain:
      - lyrics.lrc
      - metadata.json (SongMetadata fields)
    """
    song_dir = Path(song_dir)
    lrc_path = song_dir / "lyrics.lrc"
    meta_path = song_dir / "metadata.json"
    out_path = song_dir / "annotations.json"

    if not lrc_path.exists():
        raise FileNotFoundError(f"No lyrics.lrc in {song_dir}")

    import json
    meta_raw = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    import dataclasses
    known = {f.name for f in dataclasses.fields(SongMetadata)}
    metadata = SongMetadata(**{k: v for k, v in meta_raw.items() if k in known})

    _lrc_meta, timed_lines = load_lrc_file(str(lrc_path))
    if not metadata.title and _lrc_meta.title:
        metadata.title = _lrc_meta.title
    if not metadata.artist and _lrc_meta.artist:
        metadata.artist = _lrc_meta.artist

    client = LLMClient(settings)

    # resume/repair: lines already annotated (and not failure placeholders)
    # are reused verbatim; only missing/failed lines cost LLM calls
    done: dict[int, Annotation] = {}
    if not fresh and out_path.exists():
        try:
            prev = Song.load(out_path)
            done = {a.line_index: a for a in prev.annotations
                    if a.summary and a.summary != FAILED_MARKER}
        except Exception:
            logger.exception("Unreadable existing annotations — regenerating")
    chunks = _chunk_lines(timed_lines, chunk_size)
    todo = [c for c in chunks
            if any(ln.line_index not in done for ln in c)]
    if done:
        logger.info("Resume: %d/%d lines already annotated, %d/%d chunks "
                    "to run", len(done), len(timed_lines), len(todo),
                    len(chunks))
    echoes = (_mine_song_echoes(settings, metadata, timed_lines)
              if todo else {})

    all_annotations: list[Annotation] = []

    def _persist() -> Song:
        merged = dict(done)
        for a in all_annotations:
            merged[a.line_index] = a
        song = Song(metadata=metadata,
                    annotations=[merged[k] for k in sorted(merged)],
                    lrc_path=str(lrc_path))
        song.save(out_path)
        return song

    for i, chunk in enumerate(todo):
        logger.info(
            "Annotating %s chunk %d/%d (%d lines)",
            metadata.title, i + 1, len(todo), len(chunk),
        )

        lyrics_chunk = [(ln.line_index, ln.text) for ln in chunk]
        user_msg = build_annotation_prompt(
            title=metadata.title,
            artist=metadata.artist,
            album=metadata.album,
            year=metadata.year,
            era=metadata.era,
            themes=metadata.themes,
            lyrics_chunk=lyrics_chunk,
            echoes=echoes,
        )

        try:
            raw = client.generate_json(
            annotation_system_prompt(metadata.artist), user_msg)
        except Exception as exc:
            logger.error("LLM call failed for chunk %d: %s", i + 1, exc)
            for ln in chunk:
                if ln.line_index in done:
                    continue
                all_annotations.append(Annotation(
                    line_index=ln.line_index,
                    lyric_text=ln.text,
                    summary=FAILED_MARKER,
                    emotional_tone="unknown",
                ))
            _persist()  # keep earlier chunks even if this one failed
            continue

        if isinstance(raw, dict):
            raw = raw.get("annotations", [])
        if not isinstance(raw, list):
            logger.error(
                "Unexpected LLM response type for chunk %d: %s",
                i + 1, type(raw).__name__,
            )
            raw = []
        parsed = [_parse_annotation(a) for a in raw if isinstance(a, dict)]
        if parsed:
            all_annotations.extend(parsed)
        else:
            logger.error("No valid annotations parsed for chunk %d", i + 1)
            for ln in chunk:
                if ln.line_index in done:
                    continue
                all_annotations.append(Annotation(
                    line_index=ln.line_index,
                    lyric_text=ln.text,
                    summary=FAILED_MARKER,
                    emotional_tone="unknown",
                ))
        _persist()  # chunk-level persistence: a crash never loses progress

    song = _persist()
    logger.info("Saved annotations to %s (%d lines)", out_path,
                len(song.annotations))
    return song


def regenerate_annotation(
    settings: Settings,
    metadata: SongMetadata,
    line_index: int,
    lyric_text: str,
) -> Annotation:
    """Regenerate the annotation for a single lyric line via the LLM."""
    client = LLMClient(settings)
    user_msg = build_annotation_prompt(
        title=metadata.title,
        artist=metadata.artist,
        album=metadata.album,
        year=metadata.year,
        era=metadata.era,
        themes=metadata.themes,
        lyrics_chunk=[(line_index, lyric_text)],
    )
    raw = client.generate_json(annotation_system_prompt(metadata.artist), user_msg)
    if isinstance(raw, dict):
        raw = raw.get("annotations", [raw] if "summary" in raw else [])
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise RuntimeError("LLM returned no usable annotation")
    ann = _parse_annotation(raw[0])
    ann.line_index = line_index
    ann.lyric_text = lyric_text
    return ann


def _mine_song_echoes(settings: Settings, metadata: SongMetadata,
                      timed_lines: list[TimedLine],
                      top_k: int = 2) -> dict[int, list[dict]]:
    """Per-line intertextual echoes from the artist's other songs, mined
    once before annotation so the LLM can weave real connections in
    (guideline 8). Any failure degrades to no echoes — annotation must
    never be blocked by the corpus index."""
    try:
        from ..intertextuality.embeddings import load_embeddings
        from ..intertextuality.search import search_similar
        embeddings, corpus = load_embeddings(
            settings.corpus_dir, settings.embedding_model)
    except Exception:
        logger.info("No intertextuality index — annotating without echoes")
        return {}
    echoes: dict[int, list[dict]] = {}
    for ln in timed_lines:
        try:
            hits = search_similar(
                ln.text, embeddings, corpus,
                model_name=settings.embedding_model, top_k=top_k,
                exclude_song=metadata.title, artist=metadata.artist)
        except Exception:
            logger.exception("echo mining failed for line %d", ln.line_index)
            continue
        if hits:
            echoes[ln.line_index] = [
                {"song": h.song, "album": h.album, "line": h.line,
                 "similarity": round(h.similarity, 2)} for h in hits]
    if echoes:
        logger.info("Mined echoes for %d/%d lines of %s",
                    len(echoes), len(timed_lines), metadata.title)
    return echoes


def _chunk_lines(lines: list[TimedLine], size: int) -> list[list[TimedLine]]:
    return [lines[i:i + size] for i in range(0, len(lines), size)]


def _parse_annotation(raw: dict[str, Any]) -> Annotation:
    return Annotation(
        line_index=raw.get("line_index", 0),
        lyric_text=raw.get("lyric_text", ""),
        summary=raw.get("summary", ""),
        metaphor_analysis=raw.get("metaphor_analysis"),
        allusions=raw.get("allusions", []),
        wordplay=raw.get("wordplay"),
        emotional_tone=raw.get("emotional_tone", ""),
        cultural_context=raw.get("cultural_context"),
        taylor_swift_context=raw.get("taylor_swift_context"),
    )
