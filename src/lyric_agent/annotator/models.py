"""Data models for songs and annotations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SongMetadata:
    title: str
    artist: str = "Taylor Swift"
    album: str = ""
    year: int = 0
    era: str = ""
    genre: str = ""
    themes: list[str] = field(default_factory=list)


@dataclass
class RelatedLine:
    song: str
    album: str
    line: str
    similarity: float = 0.0


@dataclass
class Annotation:
    line_index: int
    lyric_text: str
    summary: str = ""
    metaphor_analysis: str | None = None
    allusions: list[str] = field(default_factory=list)
    wordplay: str | None = None
    emotional_tone: str = ""
    cultural_context: str | None = None
    taylor_swift_context: str | None = None
    related_lines: list[RelatedLine] = field(default_factory=list)
    emotion_valence: float = 0.5
    emotion_arousal: float = 0.5
    emotion_category: str = ""

    @property
    def rhetoric_density(self) -> float:
        """Fraction of non-empty analysis fields (0.0-1.0)."""
        fields_present = [
            bool(self.summary),
            bool(self.metaphor_analysis),
            bool(self.allusions),
            bool(self.wordplay),
            bool(self.cultural_context),
            bool(self.taylor_swift_context),
            bool(self.related_lines),
        ]
        return sum(fields_present) / len(fields_present)


@dataclass
class AudioSource:
    type: str = "none"  # "local" | "url" | "none"
    path_or_url: str | None = None
    is_preview: bool = False
    duration_seconds: float | None = None


@dataclass
class Song:
    metadata: SongMetadata
    annotations: list[Annotation] = field(default_factory=list)
    audio_path: str = ""
    lrc_path: str = ""
    emotion_arc: list[dict] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        data = {
            "song": asdict(self.metadata),
            "annotations": [asdict(a) for a in self.annotations],
            "emotion_arc": self.emotion_arc,
        }
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> Song:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        meta = SongMetadata(**raw["song"])
        annotations = []
        for a in raw.get("annotations", []):
            related = [RelatedLine(**r) for r in a.pop("related_lines", [])]
            annotations.append(Annotation(**a, related_lines=related))
        return cls(
            metadata=meta,
            annotations=annotations,
            emotion_arc=raw.get("emotion_arc", []),
        )
