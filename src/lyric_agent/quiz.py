"""歌词竞猜: guess which song a lyric line comes from."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_MIN_LINE_LEN = 8

# lines that literally contain the song title give the answer away
_NORM_RE = re.compile(r"[\W\s]+")


def _norm(t: str) -> str:
    return _NORM_RE.sub("", (t or "").lower())


@dataclass
class QuizQuestion:
    line: str
    answer: str            # correct song title
    artist: str
    options: list[str] = field(default_factory=list)  # shuffled titles


def make_question(
    song_lines: dict[str, tuple[str, list[str]]],
    rng: random.Random | None = None,
    n_options: int = 4,
) -> QuizQuestion | None:
    """Build one question from {title: (artist, [lines])}.

    Needs at least 2 songs; prefers distractors by the same artist.
    """
    rng = rng or random.Random()
    pool = {
        t: (a, [l for l in lines
                if len(l) >= _MIN_LINE_LEN and _norm(t) not in _norm(l)])
        for t, (a, lines) in song_lines.items()
    }
    pool = {t: v for t, v in pool.items() if v[1]}
    if len(pool) < 2:
        return None
    answer = rng.choice(list(pool))
    artist, lines = pool[answer]
    line = rng.choice(lines)
    others = [t for t in pool if t != answer]
    same_artist = [t for t in others if pool[t][0] == artist]
    rng.shuffle(same_artist)
    rest = [t for t in others if t not in same_artist]
    rng.shuffle(rest)
    distractors = (same_artist + rest)[: n_options - 1]
    options = [answer] + distractors
    rng.shuffle(options)
    return QuizQuestion(line=line, answer=answer, artist=artist,
                        options=options)
