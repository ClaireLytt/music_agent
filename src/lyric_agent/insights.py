"""Library insight helpers: word cloud, emotion map, daily quote, chorus.

Pure computation over the library / corpus — no LLM calls here.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_WORD_RE = re.compile(r"[a-zA-Z']{3,}")
_CJK_RE = re.compile(r"[一-鿿]")

# function words that would otherwise dominate every word cloud
_STOP_EN = {
    "the", "and", "you", "your", "yours", "youre", "but", "for", "with",
    "that", "this", "was", "are", "were", "not", "all", "can", "cant",
    "dont", "didnt", "wont", "couldnt", "wouldnt", "shouldnt", "aint",
    "just", "like", "when", "what", "who", "why", "how", "out", "now",
    "never", "ever", "back", "down", "got", "get", "gets", "gotta",
    "gonna", "wanna", "cause", "than", "then", "them", "they", "theyre",
    "she", "shes", "her", "hers", "him", "his", "hes", "its", "our",
    "ours", "into", "onto", "about", "there", "theres", "here", "been",
    "being", "have", "has", "had", "will", "would", "could", "should",
    "know", "knew", "known", "said", "say", "says", "one", "two", "too",
    "from", "wasnt", "isnt", "ill", "ive", "youll", "youve", "youd",
    "thats", "theres", "whats", "hed", "shed", "wed", "theyd", "theyve",
    "youre", "were", "weve", "its", "im", "dont", "cant", "wont",
    "well", "still", "yeah", "ooh", "whoa", "come", "came", "let", "lets",
    "make", "made", "take", "took", "every", "some", "only", "even",
    "want", "wanted", "see", "saw", "say", "tell", "told", "thing",
    "things", "way", "did", "does", "doing", "were", "weve", "off",
    "over", "again", "around", "right", "left", "keep", "kept", "put",
}
_STOP_ZH = {
    "我们", "你们", "他们", "她们", "自己", "什么", "怎么", "这样", "那样",
    "没有", "不是", "就是", "还是", "只是", "可是", "但是", "因为", "所以",
    "如果", "也许", "或许", "已经", "曾经", "现在", "以后", "然后", "终于",
    "一个", "一些", "那个", "这个", "这些", "那些", "一样", "一起", "不要",
    "不会", "不能", "可以", "知道", "觉得", "看见", "听见", "起来", "下来",
    "出来", "回来", "过去", "身边", "心里", "心中", "让我", "给我", "对我",
}


def _tokenize(text: str) -> list[str]:
    """English words (len>=3) + Chinese words via jieba (len>=2).

    English tokens are compared apostrophe-free ("i'm" → "im") so the
    stopword list catches contractions.
    """
    tokens = [
        w.lower().replace("'", "") for w in _WORD_RE.findall(text)
    ]
    tokens = [w for w in tokens if len(w) >= 3]
    if _CJK_RE.search(text):
        import jieba
        tokens += [
            w for w in jieba.cut("".join(_CJK_RE.findall(text)))
            if len(w) >= 2
        ]
    return tokens


def word_frequencies(
    lines: list[tuple[str, str]],  # (text, artist)
    artist: str | None = None,
    top_n: int = 60,
) -> list[tuple[str, int]]:
    """Top imagery words for an artist (or the whole corpus)."""
    from .intertextuality.search import artist_matches

    counter: Counter = Counter()
    for text, line_artist in lines:
        if artist and not artist_matches(artist, line_artist):
            continue
        for tok in _tokenize(text):
            if tok in _STOP_EN or tok in _STOP_ZH:
                continue
            counter[tok] += 1
    return [(w, n) for w, n in counter.most_common(top_n) if n >= 2]


# ── Emotion map ───────────────────────────────────────────

@dataclass
class SongEmotion:
    title: str
    artist: str
    album: str
    valence: float  # 0 negative .. 1 positive
    arousal: float  # 0 calm .. 1 energetic
    tone: str       # most common emotion_category


def library_emotions(songs: list[dict]) -> list[SongEmotion]:
    """Song-level mean valence/arousal from pre-generated annotations."""
    out: list[SongEmotion] = []
    for s in songs:
        ann_path = Path(s["dir"]) / "annotations.json"
        if not ann_path.exists():
            continue
        try:
            data = json.loads(ann_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        anns = data.get("annotations", [])
        vals = [a.get("emotion_valence") for a in anns
                if isinstance(a.get("emotion_valence"), (int, float))]
        aros = [a.get("emotion_arousal") for a in anns
                if isinstance(a.get("emotion_arousal"), (int, float))]
        if not vals or not aros:
            continue
        tones = Counter(
            a.get("emotion_category", "") for a in anns
            if a.get("emotion_category"))
        out.append(SongEmotion(
            title=s["title"], artist=s["artist"], album=s["album"],
            valence=sum(vals) / len(vals), arousal=sum(aros) / len(aros),
            tone=tones.most_common(1)[0][0] if tones else "",
        ))
    return out


# ── Daily quote ───────────────────────────────────────────

def daily_quote(songs: list[dict],
                today: _dt.date | None = None) -> dict | None:
    """Deterministic line-of-the-day: same date always picks the same line.

    Prefers annotated lines so the quote comes with an insight.
    """
    today = today or _dt.date.today()
    candidates: list[dict] = []
    for s in songs:
        ann_path = Path(s["dir"]) / "annotations.json"
        if not ann_path.exists():
            continue
        try:
            data = json.loads(ann_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for a in data.get("annotations", []):
            text = (a.get("lyric_text") or "").strip()
            summary = (a.get("summary") or "").strip()
            if len(text) >= 8 and summary:
                candidates.append({
                    "song": s["title"], "artist": s["artist"],
                    "line": text, "insight": summary,
                    "line_index": a.get("line_index", -1),
                })
    if not candidates:
        return None
    seed = int(hashlib.md5(today.isoformat().encode()).hexdigest(), 16)
    return candidates[seed % len(candidates)]


# ── Chorus detection ─────────────────────────────────────

def find_chorus_ts(timed_lines) -> int | None:
    """Timestamp (ms) of the most likely chorus start.

    Heuristic: the most-repeated normalized line (>=2 occurrences, len>=6)
    marks the chorus; jump to its first occurrence.
    """
    norm = lambda t: re.sub(r"[\W\s]+", "", (t or "").lower())
    counts: Counter = Counter()
    for ln in timed_lines:
        key = norm(ln.text)
        if len(key) >= 6:
            counts[key] += 1
    repeated = [(n, k) for k, n in counts.items() if n >= 2]
    if not repeated:
        return None
    best_key = max(repeated, key=lambda x: (x[0], len(x[1])))[1]
    for ln in timed_lines:
        if norm(ln.text) == best_key:
            return ln.timestamp_ms
    return None
