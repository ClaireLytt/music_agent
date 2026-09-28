"""Data models for artist evolution map (PRD 7.2)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class EraProfile:
    era: str
    era_emoji: str = ""
    years: str = ""
    albums: list[str] = field(default_factory=list)
    genre_tags: list[str] = field(default_factory=list)
    theme_weights: dict[str, float] = field(default_factory=dict)
    avg_rhetoric_density: float = 0.0
    ai_summary: str = ""
    songs: list[str] = field(default_factory=list)
    avg_emotion: dict[str, float] = field(default_factory=dict)


@dataclass
class ArtistEvolution:
    artist: str
    eras: list[EraProfile] = field(default_factory=list)
    theme_timeline: dict[str, list[float]] = field(default_factory=dict)
    genre_flow: list[dict] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        data = {
            "artist": self.artist,
            "eras": [asdict(e) for e in self.eras],
            "theme_timeline": self.theme_timeline,
            "genre_flow": self.genre_flow,
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> ArtistEvolution:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            artist=raw["artist"],
            eras=[EraProfile(**e) for e in raw.get("eras", [])],
            theme_timeline=raw.get("theme_timeline", {}),
            genre_flow=raw.get("genre_flow", []),
        )
