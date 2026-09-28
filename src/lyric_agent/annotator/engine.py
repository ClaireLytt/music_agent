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
from .prompts import ANNOTATION_SYSTEM_PROMPT, build_annotation_prompt

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10


def generate_annotations(
    settings: Settings,
    song_dir: str | Path,
    chunk_size: int = CHUNK_SIZE,
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

    all_annotations: list[Annotation] = []
    chunks = _chunk_lines(timed_lines, chunk_size)

    for i, chunk in enumerate(chunks):
        logger.info(
            "Annotating %s chunk %d/%d (%d lines)",
            metadata.title, i + 1, len(chunks), len(chunk),
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
        )

        try:
            raw = client.generate_json(ANNOTATION_SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            logger.error("LLM call failed for chunk %d: %s", i + 1, exc)
            for ln in chunk:
                all_annotations.append(Annotation(
                    line_index=ln.line_index,
                    lyric_text=ln.text,
                    summary="[Annotation generation failed]",
                    emotional_tone="unknown",
                ))
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
                all_annotations.append(Annotation(
                    line_index=ln.line_index,
                    lyric_text=ln.text,
                    summary="[Annotation generation failed]",
                    emotional_tone="unknown",
                ))

    song = Song(metadata=metadata, annotations=all_annotations, lrc_path=str(lrc_path))
    song.save(out_path)
    logger.info("Saved annotations to %s (%d lines)", out_path, len(all_annotations))
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
    raw = client.generate_json(ANNOTATION_SYSTEM_PROMPT, user_msg)
    if isinstance(raw, dict):
        raw = raw.get("annotations", [raw] if "summary" in raw else [])
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise RuntimeError("LLM returned no usable annotation")
    ann = _parse_annotation(raw[0])
    ann.line_index = line_index
    ann.lyric_text = lyric_text
    return ann


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
