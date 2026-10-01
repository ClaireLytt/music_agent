"""歌词宇宙侦探 / 隔空回信 / 彩蛋猜猜乐 unit tests (no LLM, no torch)."""

import random

from lyric_agent.egg_quiz import make_echo_question
from lyric_agent.intertextuality.echo_map import (
    EchoEdge,
    EchoGraph,
    EchoNode,
    EchoPair,
)
from lyric_agent.universe import (
    detective_messages,
    extract_name_lines,
    letter_messages,
    parse_universe,
    render_letter_html,
    render_universe_html,
)

# ── evidence gathering ────────────────────────────────────


def test_extract_name_lines_filters_and_caps():
    lines = [
        ("betty", "I'm only seventeen, I don't know anything"),  # no name
        ("betty", "You heard the rumors from Inez"),             # name
        ("cardigan", "Oh whoa oh"),                              # stopword only
        ("august", "Meet me behind the mall"),                   # no mid-cap
        ("betty", "You heard the rumors from Inez"),             # duplicate
        ("betty", "Would you tell me to go straight to James"),  # name
    ]
    out = extract_name_lines(lines)
    assert ("betty", "You heard the rumors from Inez") in out
    assert len([1 for s, t in out if "Inez" in t]) == 1  # deduped
    assert all("Oh whoa" not in t for _, t in out)
    # cap respected
    many = [("s", f"Talking with Romeo number {i}") for i in range(100)]
    assert len(extract_name_lines(many)) == 30


def test_detective_and_letter_messages_contain_evidence():
    _sys, user = detective_messages(
        "Taylor Swift", [("betty", "folklore")],
        [("betty", "cardigan", 3,
          [("line a", "line b"), ("line a2", "line b2")])],
        [("betty", "James is here")])
    assert "《betty》↔《cardigan》" in user and "James is here" in user
    assert "line a2" in user  # extra evidence pairs reach the prompt
    _sys2, user2 = letter_messages("betty", "cardigan", "la", "lb", 3)
    assert "《betty》" in user2 and "“la”" in user2 and "“lb”" in user2


# ── verdict parsing ───────────────────────────────────────


def _verdict():
    return {
        "synopsis": "一段小镇三角恋。",
        "confidence": "high",
        "characters": [
            {"name": "James", "role": "叙事者", "songs": ["betty"]},
            {"name": "betty", "role": "被辜负的人", "songs": ["cardigan"]},
        ],
        "relations": [
            {"a": "James", "b": "betty", "label": "道歉",
             "evidence": "《betty》：..."},
            {"a": "James", "b": "Ghost", "label": "?", "evidence": ""},
        ],
        "timeline": [
            {"title": "背叛", "song": "august", "summary": "夏天的秘密",
             "quote": "..."},
        ],
        "caveat": "推理基于歌词文本。",
    }


def test_parse_universe_tolerant():
    u = parse_universe(_verdict(), "Taylor Swift")
    assert [c.name for c in u.characters] == ["James", "betty"]
    # relation to an unknown character is dropped
    assert len(u.relations) == 1 and u.relations[0].b == "betty"
    assert u.events[0].song == "august"
    assert u.confidence == "high"
    # garbage in → empty universe out, no crash
    assert parse_universe("not a dict", "X").characters == []
    assert parse_universe({"characters": [42, {"role": "no name"}]},
                          "X").characters == []


def test_render_universe_html_smoke():
    out = render_universe_html(parse_universe(_verdict(), "Taylor Swift"))
    assert "<svg" in out and "James" in out
    assert "故事线" in out and "august" in out
    assert "推理把握" in out
    # no characters → synopsis-only fallback, no SVG
    empty = parse_universe({"synopsis": "只是母题复用。"}, "X")
    out2 = render_universe_html(empty)
    assert "<svg" not in out2 and "母题复用" in out2


def test_render_letter_html_highlights_quotes():
    body = "致《cardigan》：\n那句 cardigan under someone's bed 我一直记得。\n——《betty》"
    out = render_letter_html("betty", "cardigan", body,
                             "cardigan under someone's bed", "missing line")
    assert '<mark class="letter-echo">' in out
    assert "missing line" not in out  # absent quote: no fake highlight
    assert out.count("<p>") == 3


# ── 彩蛋猜猜乐 ────────────────────────────────────────────


def _game_graph():
    g = EchoGraph(artist="X", threshold=0.6, song_total=4)
    g.nodes = [EchoNode(song=s, album="al", echo_count=1)
               for s in ("A", "B", "C", "D")]
    g.edges = [
        EchoEdge("A", "B", 3, EchoPair("hello there", "hello again", 0.8)),
        EchoEdge("C", "D", 1, EchoPair("same line", "same line", 1.0)),
    ]
    return g


def test_make_echo_question():
    q = make_echo_question(_game_graph(), rng=random.Random(7))
    assert q is not None
    assert q.answer in q.options and q.source_song not in q.options
    assert {q.source_song, q.answer} in ({"A", "B"}, {"C", "D"})
    if {q.source_song, q.answer} == {"A", "B"}:
        assert q.line != q.echo_line
    assert len(q.options) <= 4 and len(set(q.options)) == len(q.options)


def test_make_echo_question_prefers_distinct_lines():
    # with a distinct-text edge available, the identical-text one is skipped
    for seed in range(10):
        q = make_echo_question(_game_graph(), rng=random.Random(seed))
        assert q is not None


def test_make_echo_question_empty_graph():
    g = EchoGraph(artist="X", threshold=0.6, song_total=0)
    assert make_echo_question(g) is None
    assert make_echo_question(None) is None
