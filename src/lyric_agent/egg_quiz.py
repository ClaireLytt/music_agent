"""彩蛋猜猜乐: guess which song echoes a given lyric line.

Zero-cost gamification of the echo graph — every question is one edge of
the artist's echo network (see intertextuality/echo_map.py), so no LLM
call and no extra data are needed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class EchoQuizQuestion:
    line: str               # the prompt lyric
    source_song: str        # the song the prompt lyric comes from
    answer: str             # the song holding its echo
    echo_line: str          # the echoing lyric in the answer song
    count: int              # total echoes between the two songs
    similarity: float
    options: list[str] = field(default_factory=list)  # shuffled titles


def make_echo_question(
    graph,                  # EchoGraph (duck-typed: .edges / .nodes)
    rng: random.Random | None = None,
    n_options: int = 4,
) -> EchoQuizQuestion | None:
    """One question from a random echo edge; None when the graph is too thin.

    The prompt line comes from a random side of the edge; distractors are
    other songs on the map (they all *have* echoes, so titles alone don't
    give the answer away).
    """
    rng = rng or random.Random()
    if graph is None or not graph.edges:
        return None
    # skip identical-text examples: the echo line would equal the prompt
    # line and the reveal would teach nothing
    edges = [e for e in graph.edges
             if e.example.line_a.strip().casefold()
             != e.example.line_b.strip().casefold()] or list(graph.edges)
    e = rng.choice(edges)
    if rng.random() < 0.5:
        src, ans = e.song_a, e.song_b
        line, echo_line = e.example.line_a, e.example.line_b
    else:
        src, ans = e.song_b, e.song_a
        line, echo_line = e.example.line_b, e.example.line_a
    others = [n.song for n in graph.nodes if n.song not in (src, ans)]
    rng.shuffle(others)
    options = [ans] + others[: n_options - 1]
    if len(options) < 2:
        return None
    rng.shuffle(options)
    return EchoQuizQuestion(
        line=line, source_song=src, answer=ans, echo_line=echo_line,
        count=e.count, similarity=e.example.similarity, options=options)
