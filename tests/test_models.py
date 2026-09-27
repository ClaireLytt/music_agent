"""Tests for annotation data models."""

import json
import tempfile
from pathlib import Path

from lyric_agent.annotator.models import Annotation, RelatedLine, Song, SongMetadata


def test_song_save_and_load():
    meta = SongMetadata(
        title="cardigan",
        artist="Taylor Swift",
        album="folklore",
        year=2020,
        era="folklore",
    )
    ann = Annotation(
        line_index=0,
        lyric_text="Vintage tee, brand new phone",
        summary="Juxtaposition of old and new.",
        emotional_tone="wistful",
        related_lines=[
            RelatedLine(song="All Too Well", album="Red", line="test line", similarity=0.8)
        ],
    )
    song = Song(metadata=meta, annotations=[ann])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "annotations.json"
        song.save(path)

        loaded = Song.load(path)
        assert loaded.metadata.title == "cardigan"
        assert loaded.metadata.year == 2020
        assert len(loaded.annotations) == 1
        assert loaded.annotations[0].lyric_text == "Vintage tee, brand new phone"
        assert len(loaded.annotations[0].related_lines) == 1
        assert loaded.annotations[0].related_lines[0].song == "All Too Well"
