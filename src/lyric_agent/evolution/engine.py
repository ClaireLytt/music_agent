"""Era aggregation engine for the artist evolution map (PRD F-17).

Aggregates data/songs/*/metadata.json + annotations.json into an
ArtistEvolution structure. Era AI summaries are pre-written (curated);
an LLM can regenerate them when an API key is configured.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from ..annotator.models import Song
from .models import ArtistEvolution, EraProfile

logger = logging.getLogger(__name__)

# Full career registry: timeline shows every era even without demo songs.
ERA_REGISTRY: list[dict] = [
    {"era": "debut", "emoji": "🦋", "years": "2006", "albums": ["Taylor Swift"], "genre": "country"},
    {"era": "fearless", "emoji": "💛", "years": "2008", "albums": ["Fearless"], "genre": "country pop"},
    {"era": "speak now", "emoji": "💜", "years": "2010", "albums": ["Speak Now"], "genre": "country pop"},
    {"era": "red", "emoji": "🧣", "years": "2012 / 2021", "albums": ["Red", "Red (Taylor's Version)"], "genre": "pop / country"},
    {"era": "1989", "emoji": "🌊", "years": "2014", "albums": ["1989"], "genre": "synth-pop"},
    {"era": "reputation", "emoji": "🐍", "years": "2017", "albums": ["reputation"], "genre": "electro-pop"},
    {"era": "lover", "emoji": "🦋", "years": "2019", "albums": ["Lover"], "genre": "pop"},
    {"era": "folklore", "emoji": "🍂", "years": "2020", "albums": ["folklore"], "genre": "indie folk"},
    {"era": "evermore", "emoji": "🍃", "years": "2020", "albums": ["evermore"], "genre": "indie folk / alt"},
    {"era": "midnights", "emoji": "🌙", "years": "2022", "albums": ["Midnights"], "genre": "synth-pop / alt"},
]

# Curated era interpretations (used when no LLM is configured).
CURATED_ERA_SUMMARIES: dict[str, str] = {
    "red": (
        "Red 是 Taylor 从乡村转向流行的第一次全面越界——「像一段心碎那样五彩斑斓」。"
        "情感表达直白而炽烈：围巾、秋叶、深夜车灯构成她第一套成熟的意象系统。"
        "All Too Well 在十年后以 10 分钟版本重生，标志着 Taylor's Version 重录运动的核心宣言：夺回叙事权。"
    ),
    "folklore": (
        "隔离期间的文学转向——从自传体写作跳到虚构叙事，第一次大规模使用第三人称视角。"
        "与 Aaron Dessner 的合作带来极简的室内民谣美学，歌词密度与隐喻复杂度达到生涯峰值。"
        "Betty–James–Augustine 三部曲证明：她不再只写自己的故事，而是在建造一个可以住进去的世界。"
    ),
    "evermore": (
        "folklore 的「姊妹专辑」，虚构叙事进一步深化：拒婚的新娘、谋杀悬案、祖母的幽灵。"
        "情绪比 folklore 更冷冽苍凉，champagne problems 用一场没有发生的求婚，"
        "把「拒绝」写成了双方共同承受的哀悼。阶级、婚姻、精神健康成为新的主题词。"
    ),
    "midnights": (
        "「13 个不眠之夜」的概念专辑——从虚构叙事收回到自我剖析，但带着 folklore 时期锻炼出的距离感。"
        "Anti-Hero 用会议点名式的自嘲（It's me, hi）把自我厌恶写成全球热单，"
        "反讽与真诚的比例控制是这个时期最显著的作者签名。合成器音色下是最赤裸的深夜独白。"
    ),
}

DEFAULT_THEME_KEYS = ["love", "nostalgia", "loss", "identity", "pain", "irony"]

# Map free-form metadata themes onto the canonical timeline keys.
_THEME_ALIASES: dict[str, str] = {
    "lost love": "loss", "heartbreak": "pain", "betrayal": "pain",
    "memory": "nostalgia", "youth": "nostalgia", "the past": "nostalgia",
    "being chosen": "love", "romance": "love",
    "self-doubt": "identity", "self-awareness": "identity", "insecurity": "identity",
    "self-criticism": "identity", "fame": "identity",
    "sarcasm": "irony", "self-deprecation": "irony", "anti-heroism": "irony",
    "regret": "loss", "separation": "loss", "rejection": "loss", "grief": "loss",
    "miscommunication": "pain", "anger": "pain",
    "rejected proposal": "loss", "letting go": "loss", "emotional exile": "loss",
    "class and wealth": "identity", "mental health": "identity",
    "self-sabotage": "identity", "self-loathing": "identity",
    "anxiety": "pain", "imposter syndrome": "identity",
    "ironic self-awareness": "irony", "midnight introspection": "identity",
    "age gap": "pain", "power imbalance": "pain", "vivid memory": "nostalgia",
    "reclaiming narrative": "identity", "communication breakdown": "pain",
    "dual perspectives": "irony", "misunderstanding": "pain",
}


def _canon_theme(theme: str) -> str:
    t = theme.lower().strip()
    if t in DEFAULT_THEME_KEYS:
        return t
    return _THEME_ALIASES.get(t, "")


def build_evolution(songs_dir: str | Path, artist: str = "Taylor Swift") -> ArtistEvolution:
    base = Path(songs_dir)
    era_songs: dict[str, list[tuple[str, dict, Song | None]]] = defaultdict(list)

    for d in sorted(base.iterdir()) if base.exists() else []:
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        song = None
        ann_path = d / "annotations.json"
        if ann_path.exists():
            try:
                song = Song.load(ann_path)
            except Exception as exc:
                logger.warning("Failed loading %s: %s", ann_path, exc)
        era = meta.get("era", "").lower()
        if era:
            era_songs[era].append((d.name, meta, song))

    eras: list[EraProfile] = []
    for reg in ERA_REGISTRY:
        era = reg["era"]
        entries = era_songs.get(era, [])

        theme_weights: dict[str, float] = {}
        densities: list[float] = []
        valences: list[float] = []
        arousals: list[float] = []

        theme_counts: dict[str, int] = defaultdict(int)
        for _, meta, song in entries:
            for t in meta.get("themes", []):
                key = _canon_theme(t)
                if key:
                    theme_counts[key] += 1
            if song:
                if song.annotations:
                    densities.append(
                        sum(a.rhetoric_density for a in song.annotations) / len(song.annotations)
                    )
                if song.emotion_arc:
                    valences.append(sum(p["valence"] for p in song.emotion_arc) / len(song.emotion_arc))
                    arousals.append(sum(p["arousal"] for p in song.emotion_arc) / len(song.emotion_arc))

        if theme_counts:
            max_count = max(theme_counts.values())
            theme_weights = {k: round(v / max_count, 2) for k, v in theme_counts.items()}

        eras.append(EraProfile(
            era=era,
            era_emoji=reg["emoji"],
            years=reg["years"],
            albums=reg["albums"],
            genre_tags=[g.strip() for g in reg["genre"].split("/")],
            theme_weights=theme_weights,
            avg_rhetoric_density=round(sum(densities) / len(densities), 3) if densities else 0.0,
            ai_summary=CURATED_ERA_SUMMARIES.get(era, ""),
            songs=[name for name, _, _ in entries],
            avg_emotion={
                "valence": round(sum(valences) / len(valences), 3) if valences else 0.0,
                "arousal": round(sum(arousals) / len(arousals), 3) if arousals else 0.0,
            },
        ))

    theme_timeline: dict[str, list[float]] = {}
    for key in DEFAULT_THEME_KEYS:
        theme_timeline[key] = [e.theme_weights.get(key, 0.0) for e in eras]

    genre_flow = []
    prev_genre = None
    for reg in ERA_REGISTRY:
        g = reg["genre"].split("/")[0].strip()
        if prev_genre and g != prev_genre:
            genre_flow.append({
                "from": prev_genre, "to": g,
                "year": reg["years"].split("/")[0].strip(),
            })
        prev_genre = g

    return ArtistEvolution(
        artist=artist,
        eras=eras,
        theme_timeline=theme_timeline,
        genre_flow=genre_flow,
    )


def build_and_save(songs_dir: str | Path, out_path: str | Path) -> ArtistEvolution:
    evolution = build_evolution(songs_dir)
    evolution.save(out_path)
    return evolution


def _songs_mtime(songs_dir: str | Path) -> float:
    """Latest mtime across all song metadata/annotation files."""
    latest = 0.0
    base = Path(songs_dir)
    if base.exists():
        for pattern in ("*/metadata.json", "*/annotations.json"):
            for f in base.glob(pattern):
                latest = max(latest, f.stat().st_mtime)
    return latest


def load_or_build(songs_dir: str | Path, evolution_path: str | Path) -> ArtistEvolution:
    p = Path(evolution_path)
    if p.exists():
        if _songs_mtime(songs_dir) > p.stat().st_mtime:
            logger.info("evolution.json is stale (songs data changed) — rebuilding")
            return build_and_save(songs_dir, p)
        try:
            return ArtistEvolution.load(p)
        except Exception as exc:
            logger.warning("Failed loading evolution data, rebuilding: %s", exc)
    return build_and_save(songs_dir, p)
