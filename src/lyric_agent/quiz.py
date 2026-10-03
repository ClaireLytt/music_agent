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


@dataclass
class TitlePuzzle:
    masked: str            # the title with one piece replaced by ____
    answer: str            # the missing piece
    title: str             # full title, revealed after answering
    artist: str
    options: list[str] = field(default_factory=list)  # shuffled pieces


_WORDY_RE = re.compile(r"[A-Za-z']+")
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _title_piece(title: str, rng: random.Random) -> str | None:
    """A maskable piece of a title: a >=3-letter word for spaced titles,
    or a contiguous CJK run of 2 chars (1 for two-char titles). Pieces are
    always drawn from a single script so a mixed title like '晴天 (Live)'
    never yields garbage like ' (' or 'e)'."""
    title = (title or "").strip()
    words = [w for w in _WORDY_RE.findall(title) if len(w) >= 3]
    if len(words) >= 2:
        return rng.choice(words)
    # CJK: pick from a contiguous run of Han characters only
    runs = re.findall(r"[\u4e00-\u9fff]+", title)
    long_runs = [r for r in runs if len(r) >= 2]
    if long_runs:
        run = rng.choice(long_runs)
        i = rng.randrange(len(run) - 1)
        return run[i:i + 2]
    if len(title) == 2 and _CJK_CHAR_RE.search(title) and " " not in title:
        return title[rng.randrange(2)]
    return None


def make_title_puzzle(
    pool: list[tuple[str, str]],
    rng: random.Random | None = None,
    n_options: int = 4,
) -> TitlePuzzle | None:
    """歌名拼图: mask one piece of a song title; the player puts it back.

    pool: [(title, artist), ...]. Distractor pieces come from other
    titles of the same script (latin words with latin, CJK runs with
    CJK) so the options look plausible.
    """
    rng = rng or random.Random()
    cands = []
    for title, artist in pool:
        piece = _title_piece(title, rng)
        if piece:
            cands.append((title, artist, piece))
    if len(cands) < 2:
        return None
    title, artist, piece = rng.choice(cands)
    masked = title.replace(piece, "____", 1)
    cjk = bool(_CJK_CHAR_RE.search(piece))
    distractors = [p for t, _a, p in cands
                   if t != title and p != piece
                   and bool(_CJK_CHAR_RE.search(p)) == cjk]
    rng.shuffle(distractors)
    options = [piece] + list(dict.fromkeys(distractors))[: n_options - 1]
    if len(options) < 2:
        return None
    rng.shuffle(options)
    return TitlePuzzle(masked=masked, answer=piece, title=title,
                       artist=artist, options=options)


def make_question(
    song_lines: dict[str, tuple[str, list[str]]],
    rng: random.Random | None = None,
    n_options: int = 4,
) -> QuizQuestion | None:
    """Build one question from {title: (artist, [lines])}.

    Needs at least 2 songs; prefers distractors by the same artist.
    """
    rng = rng or random.Random()
    # anchors keep their position in the ORIGINAL line list so the question
    # can show a passage (anchor ± neighbours) instead of one bare line —
    # a lone "(No more baby, oooh)" is unguessable
    pool = {
        t: (a, lines,
            [i for i, l in enumerate(lines)
             if len(l) >= _MIN_LINE_LEN and _norm(t) not in _norm(l)])
        for t, (a, lines) in song_lines.items()
    }
    pool = {t: v for t, v in pool.items() if v[2]}
    if len(pool) < 2:
        return None
    answer = rng.choice(list(pool))
    artist, all_lines, anchors = pool[answer]
    i = rng.choice(anchors)
    passage = [
        l for j in range(max(0, i - 1), min(len(all_lines), i + 2))
        # neighbours that would leak the title are dropped, not the anchor
        if (l := all_lines[j]) and (j == i or _norm(answer) not in _norm(l))
    ]
    line = "\n".join(dict.fromkeys(passage))  # dedupe repeated chorus lines
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
