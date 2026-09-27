"""Emotion-arc based next-song recommendation (PRD F-18).

Three modes:
  smooth   — end emotion of current song closest to start emotion of candidate
  contrast — most distant (dramatic transition)
  thematic — highest metadata theme overlap
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

_TAIL = 5  # lines sampled from song end / start


@dataclass
class Recommendation:
    song_name: str          # directory name
    title: str
    album: str
    era_emoji: str
    score: float            # 0..1, higher = better fit for the mode
    mode: str               # "smooth" | "contrast" | "thematic"
    end_emotion: dict[str, float] = field(default_factory=dict)
    start_emotion: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


def _avg_emotion(points: list[dict]) -> dict[str, float]:
    if not points:
        return {"valence": 0.5, "arousal": 0.5}
    return {
        "valence": sum(p["valence"] for p in points) / len(points),
        "arousal": sum(p["arousal"] for p in points) / len(points),
    }


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["valence"] - b["valence"], a["arousal"] - b["arousal"])


def _describe(v: float) -> str:
    if v >= 0.6:
        return "明亮"
    if v >= 0.45:
        return "温柔怅惘"
    if v >= 0.3:
        return "低回"
    return "沉郁"


def _make_explanation(cur_title: str, cand_title: str, mode: str,
                      end_e: dict, start_e: dict) -> str:
    end_d, start_d = _describe(end_e["valence"]), _describe(start_e["valence"])
    if mode == "smooth":
        return (f"《{cur_title}》在{end_d}的情绪中收尾，"
                f"《{cand_title}》以相近的{start_d}基调开场——像同一个夜晚的两段故事。")
    if mode == "contrast":
        return (f"《{cur_title}》结尾{end_d}，《{cand_title}》开场{start_d}——"
                f"情绪的急转制造出戏剧性的听感落差。")
    return f"《{cand_title}》与《{cur_title}》共享核心主题，是叙事上的延续。"


def recommend_next(
    current: dict[str, Any],
    candidates: list[dict[str, Any]],
    mode: str = "smooth",
    top_k: int = 3,
) -> list[Recommendation]:
    """Each song dict needs: name, title, album, era_emoji, themes, emotion_arc."""
    end_e = _avg_emotion(current.get("emotion_arc", [])[-_TAIL:])
    cur_themes = set(t.lower() for t in current.get("themes", []))

    scored: list[Recommendation] = []
    for cand in candidates:
        if cand["name"] == current.get("name"):
            continue
        start_e = _avg_emotion(cand.get("emotion_arc", [])[:_TAIL])
        dist = _distance(end_e, start_e)  # max possible = sqrt(2)

        if mode == "contrast":
            score = min(1.0, dist / 1.2)
        elif mode == "thematic":
            cand_themes = set(t.lower() for t in cand.get("themes", []))
            union = cur_themes | cand_themes
            score = len(cur_themes & cand_themes) / len(union) if union else 0.0
        else:  # smooth
            score = max(0.0, 1.0 - dist / 1.2)

        scored.append(Recommendation(
            song_name=cand["name"],
            title=cand["title"],
            album=cand["album"],
            era_emoji=cand.get("era_emoji", "🎵"),
            score=round(score, 3),
            mode=mode,
            end_emotion={k: round(v, 3) for k, v in end_e.items()},
            start_emotion={k: round(v, 3) for k, v in start_e.items()},
            explanation=_make_explanation(
                current.get("title", ""), cand["title"], mode, end_e, start_e),
        ))

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]
