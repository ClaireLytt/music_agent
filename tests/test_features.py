"""Tests for insights / rhyme / quiz / fingerprint modules."""

from __future__ import annotations

import datetime
import random
from dataclasses import dataclass

import numpy as np
import pytest

from lyric_agent.insights import (
    daily_quote,
    find_chorus_ts,
    word_frequencies,
)
from lyric_agent.quiz import make_question
from lyric_agent.rhyme import line_rhyme_groups


@dataclass
class _Line:
    text: str
    timestamp_ms: int
    line_index: int = 0


def test_word_frequencies_filters_stopwords():
    lines = [("I'm the scarf and the scarf again", "X")] * 3 + [
        ("scarf midnight rain", "X"), ("其他歌手的歌词", "Y")]
    freqs = dict(word_frequencies(lines, "X"))
    assert freqs.get("scarf", 0) >= 4
    assert "im" not in freqs and "the" not in freqs and "and" not in freqs


def test_word_frequencies_chinese():
    lines = [("童年的纸飞机 飞回童年", "周杰伦")] * 2
    freqs = dict(word_frequencies(lines, "周杰伦"))
    assert freqs.get("童年", 0) >= 2


def test_find_chorus_ts():
    lines = [
        _Line("verse one line here", 1000),
        _Line("this is the chorus line", 5000),
        _Line("another verse content", 9000),
        _Line("this is the chorus line", 13000),
    ]
    assert find_chorus_ts(lines) == 5000
    assert find_chorus_ts([_Line("only once", 0)]) is None


def test_rhyme_groups_english_and_chinese():
    g = line_rhyme_groups([
        "walking in the night", "nothing feels right",  # night/right rhyme
        "totally different word",
    ])
    assert g[0] is not None and g[0] == g[1] and g[2] is None
    g_zh = line_rhyme_groups(["北京昨夜下了雪", "思念在心中凝结", "无关的一行歌词啊"])
    assert g_zh[0] is not None and g_zh[0] == g_zh[1]


def test_quiz_question():
    pool = {
        "Song A": ("X", ["a memorable lyric line one", "second line of song a"]),
        "Song B": ("X", ["completely different lyric here"]),
        "Song C": ("Y", ["third song line goes here"]),
    }
    q = make_question(pool, random.Random(7))
    assert q is not None
    assert q.answer in q.options and len(set(q.options)) == len(q.options)
    # the line must actually belong to the answer song
    assert q.line in pool[q.answer][1]
    assert make_question({"only": ("X", ["one line only here"])}) is None


def test_quiz_line_never_contains_title():
    pool = {
        "Betty": ("X", ["betty I know where it all went wrong", "long lyric without the name"]),
        "Second": ("X", ["a completely usable lyric line"]),
    }
    for seed in range(10):
        q = make_question(pool, random.Random(seed))
        assert q is not None
        assert q.answer.lower().replace(" ", "") not in \
            q.line.lower().replace(" ", "")


def test_daily_quote_deterministic(tmp_path):
    import json
    d = tmp_path / "song_x"
    d.mkdir()
    (d / "annotations.json").write_text(json.dumps({
        "annotations": [
            {"line_index": i, "lyric_text": f"candidate lyric line {i}",
             "summary": "insight"} for i in range(5)
        ]}), encoding="utf-8")
    songs = [{"dir": str(d), "title": "X", "artist": "A", "album": ""}]
    day = datetime.date(2026, 9, 28)
    assert daily_quote(songs, day) == daily_quote(songs, day)
    assert daily_quote([], day) is None


def test_fingerprint_roundtrip(tmp_path):
    from scipy.io import wavfile

    from lyric_agent.fingerprint import build_index, match_sample

    sr = 11025
    rng = np.random.default_rng(0)
    # broadband noise has dense, unique spectral peaks — ideal fingerprint
    # material (pure sine tones are pathological: identical hashes repeat
    # for seconds and votes smear across offsets)
    signal = rng.standard_normal(20 * sr).astype(np.float32)
    signal /= np.abs(signal).max()  # int16 write below must not clip
    wav = tmp_path / "audio.wav"
    wavfile.write(str(wav), sr, (signal * 32767).astype(np.int16))

    songs = [{"title": "Synth Song", "audio_type": "local",
              "audio_src": str(wav)}]
    index = build_index(songs)
    assert index.indexed == ["Synth Song"]

    # a 5-second excerpt starting at t=8s must match with the right offset
    sample = signal[8 * sr: 13 * sr]
    result = match_sample(index, sr, sample)
    assert result is not None
    title, offset, conf = result
    assert title == "Synth Song"
    assert offset == pytest.approx(8.0, abs=1.0)
    # random noise must NOT match
    noise = rng.standard_normal(5 * sr).astype(np.float32)
    assert match_sample(index, sr, noise) is None


def test_title_puzzle():
    from lyric_agent.quiz import make_title_puzzle
    pool = [("Love Story", "Taylor Swift"), ("Blank Space", "Taylor Swift"),
            ("Paper Rings", "Taylor Swift"), ("Shape of You", "Ed Sheeran")]
    q = make_title_puzzle(pool, random.Random(7))
    assert q is not None
    assert "____" in q.masked
    assert q.answer in q.options and len(q.options) <= 4
    assert q.masked.replace("____", q.answer, 1) == q.title


def test_title_puzzle_cjk_and_guards():
    from lyric_agent.quiz import make_title_puzzle
    pool = [("晴天", "周杰伦"), ("告白气球", "周杰伦"), ("夜曲", "周杰伦")]
    q = make_title_puzzle(pool, random.Random(5))
    assert q is not None and "____" in q.masked
    assert q.masked.replace("____", q.answer, 1) == q.title
    # one maskable title is not a game
    assert make_title_puzzle([("Hi", "X")], random.Random(1)) is None


def test_render_favorites():
    from lyric_agent.ui_helpers import _render_favorites
    html = _render_favorites([{"line": "a <b> line", "title": "s&1",
                               "label": "s&1"}])
    assert "a &lt;b&gt; line" in html and "s&amp;1" in html
    # id-based (stable) actions, not positional indices
    assert 'data-fav="jump:' in html and 'data-fav="del:' in html
    assert 'jump:0"' not in html  # no longer index-based
    assert "还没有收藏" in _render_favorites([])


def test_letter_card_renders(tmp_path):
    import pytest
    pytest.importorskip("PIL")  # share cards are an optional extra; CI
    # installs the slim dependency set without Pillow
    from pathlib import Path

    from lyric_agent.share_card import render_letter_card
    body = "致《cardigan》：\n你唱过 line b echo。\n我也唱过 line a echo。\n——《betty》"
    p = render_letter_card("betty", "cardigan", body,
                           "line a echo", "line b echo",
                           out_dir=str(tmp_path))
    f = Path(p)
    assert f.exists() and f.suffix == ".png" and f.stat().st_size > 10000


def test_artist_overview_enriched(tmp_path):
    """Overview shows stat tiles + imagery words + per-album line counts."""
    from lyric_agent.ui_helpers import render_artist_overview

    # two songs, one album, with real timed lyrics so stats compute
    lrc = "[00:01.00] love is a losing game\n[00:03.00] love and heartbreak\n"
    for name in ("s1", "s2"):
        d = tmp_path / name
        d.mkdir()
        (d / "lyrics.lrc").write_text(lrc, encoding="utf-8")
    songs = [{"dir": str(tmp_path / n), "name": n, "title": n.upper(),
              "artist": "A", "album": "AL", "themes": []}
             for n in ("s1", "s2")]
    html = render_artist_overview(songs, "A")
    assert 'ov-tile-num">2' in html       # 2 songs
    assert 'ov-tile-num">1' in html       # 1 album
    assert 'ov-tile-num">4' in html       # 4 lyric lines total
    assert "高频意象" in html and "love" in html  # imagery from lyrics
    assert "行歌词" in html                # per-album line count
    assert render_artist_overview(songs, "nobody").count("chat-empty") == 1


def test_title_puzzle_no_mixed_script_garbage():
    """Mixed-script titles must not produce garbage pieces like ' (' or 'e)'."""
    import random

    from lyric_agent.quiz import _title_piece
    for seed in range(40):
        for title in ("晴天 (Live)", "告白气球 (Remix)", "七里香feat.X"):
            piece = _title_piece(title, random.Random(seed))
            if piece is None:
                continue
            # a valid piece is a clean latin word OR a pure-CJK run,
            # never containing spaces/parens/punctuation
            assert piece.strip() == piece
            assert not any(c in piece for c in " ()（）.-"), (title, piece)


def test_debate_speak_fills_persona_placeholders(monkeypatch):
    """speak() must send persona_system() output, never the raw template
    (the {fan_scope}/{artist_scope} placeholders)."""
    from lyric_agent import debate
    from lyric_agent.config import Settings

    sent = {}

    class FakeResp:
        reply_text = "ok"

    class FakeClient:
        def __init__(self, settings):
            pass

        def generate(self, system_prompt, user_message, on_text_delta):
            sent["system"] = system_prompt
            on_text_delta("ok")
            return FakeResp()

    import lyric_agent.llm as llm
    monkeypatch.setattr(llm, "LLMClient", FakeClient)
    session = debate.DebateSession(
        lyric_line="line", song_title="song", artist="Taylor Swift")
    settings = Settings(api_key="test-key")
    list(debate.speak(settings, session, "fan"))
    assert "{fan_scope}" not in sent["system"]
    assert "Taylor Swift" in sent["system"]


def test_dictionary_lookup_and_lemma():
    """Offline dict: direct hit, plural via lemma, dancin' suffix, miss."""
    from lyric_agent.dictionary import lookup
    assert "围巾" in lookup("scarf")["translation"]
    assert lookup("cobblestones")["word"] == "cobblestone"
    assert lookup("dancin'")["word"] == "dancing"
    assert lookup("Crestfallen")["word"] == "crestfallen"
    assert lookup("xyzzyqq") is None
    assert lookup("不是英文") is None


def test_wordbook_roundtrip(tmp_path, monkeypatch):
    from lyric_agent import dictionary as d
    monkeypatch.setattr(d, "_WORDBOOK_PATH", tmp_path / "wb.json")
    book = d.add_word("scarf", line="left my scarf there", song="All Too Well")
    assert len(book) == 1 and book[0]["word"] == "scarf"
    assert d.add_word("Scarf") == book  # idempotent, case-insensitive
    # re-collecting backfills a missing AI explanation (and only that)
    book = d.add_word("Scarf", ai="①语境义：围巾")
    assert book[0]["ai"] == "①语境义：围巾"
    book = d.add_word("Scarf", ai="另一个解释不覆盖")
    assert book[0]["ai"] == "①语境义：围巾"
    assert d.remove_word("SCARF") == []


def test_render_wordbook_escapes():
    from lyric_agent.ui_helpers import render_wordbook
    html = render_wordbook([{"word": "a<b", "phonetic": "x&y",
                             "translation": "n. 释义\n第二行",
                             "line": "<script>", "song": "s",
                             "ai": "①语境义：<x>\n②整句：好"}])
    assert "a&lt;b" in html and "x&amp;y" in html and "&lt;script&gt;" in html
    assert "data-wb=" in html
    assert "wb-ai" in html and "&lt;x&gt;" in html   # AI 解释展示且转义
    assert "①语境义：&lt;x&gt;<br>②整句：好" in html  # 换行渲染
    assert "wb-ai" not in render_wordbook([{"word": "w", "song": "s"}])
    assert "还没有收藏的单词" in render_wordbook([])


def _evidence_fixture(tmp_path):
    songs = []
    for name, lines in (
        ("all_too_well", ["I walked through the door with you",
                          "And I, left my scarf there at your sister's house"]),
        ("red", ["Losing him was blue like I'd never known"]),
    ):
        d = tmp_path / name
        d.mkdir()
        lrc = "\n".join(f"[00:0{i+1}.00] {t}" for i, t in enumerate(lines))
        (d / "lyrics.lrc").write_text(lrc, encoding="utf-8")
        songs.append({"title": name.replace("_", " ").title(),
                      "dir": str(d)})
    return songs


def test_evidence_verify_quote(tmp_path):
    from lyric_agent.evidence import QuoteIndex
    idx = QuoteIndex(_evidence_fixture(tmp_path))
    # exact (normalized: case/punctuation-insensitive)
    hit = idx.verify("left my scarf there at your sister's house",
                     song_hint="All Too Well")
    assert hit and hit["song_title"] == "All Too Well"
    assert hit["line_index"] == 1
    # containment fallback (>=15 normalized chars)
    assert idx.verify("losing him was blue like") is not None
    # hallucinated quote -> None
    assert idx.verify("the moon is made of synthwave") is None
    assert idx.verify("") is None


def test_evidence_parse_claims():
    from lyric_agent.evidence import parse_claims
    raw = """```json
{"conclusion": "围巾是信物", "quotes": [{"text": "left my scarf", "song": "ATW"},
 "bare string quote"], "facts": ["Red 2012"], "speculation": ["指向某前任"]}
```"""
    c = parse_claims(raw)
    assert c["conclusion"] == "围巾是信物"
    assert len(c["quotes"]) == 2 and c["quotes"][1]["song"] == ""
    assert c["facts"] == ["Red 2012"] and c["speculation"] == ["指向某前任"]
    assert parse_claims("not json at all") is None
    assert parse_claims("") is None


def test_evidence_card_layers_and_interception(tmp_path):
    from lyric_agent.evidence import QuoteIndex, render_evidence_card
    idx = QuoteIndex(_evidence_fixture(tmp_path))
    claims = {
        "conclusion": "结论<script>",
        "quotes": [
            {"text": "left my scarf there at your sister's house",
             "song": "All Too Well"},
            {"text": "a fabricated quote that never existed", "song": "Red"},
        ],
        "facts": ["Red 发行于 2012"],
        "speculation": ["<img onerror=x> 推测内容"],
    }
    html = render_evidence_card(claims, idx,
                                {"All Too Well": "All Too Well"})
    # verified quote: ✅ + clickable jump with the line index
    assert "✅" in html and 'data-cite-label="All Too Well"' in html
    assert 'data-cite-line="1"' in html
    # hallucinated quote intercepted: ⚠️, no jump attrs on it
    assert "⚠️" in html and "未在曲库中找到" in html
    assert html.count("data-cite-label") == 1
    # layers + confidence (1 verified -> 中)
    assert "💭 推测" in html and "📅" in html and "置信度：中" in html
    # hostile input never reaches HTML unescaped
    assert "<script>" not in html and "<img" not in html


def test_archaeology_mine_motifs():
    from collections import namedtuple
    from lyric_agent.archaeology import mine_motifs
    Row = namedtuple("Row", "song album line_index text artist")
    corpus = []
    # "scarf" recurs in 3 songs; "the"/"first" are glue; one other artist
    for i, song in enumerate(("A", "B", "C")):
        corpus.append(Row(song, "Alb", 0,
                          f"the scarf on the first chair {i}", "X"))
        corpus.append(Row(song, "Alb", 1, "we walked home", "X"))
    corpus.append(Row("D", "Alb", 0, "scarf scarf scarf", "Other"))
    motifs = mine_motifs(corpus, "X", min_songs=3)
    words = [m["word"] for m in motifs]
    assert "scarf" in words             # recurs across >=3 songs
    assert "first" not in words         # everyday rank filtered
    m = motifs[words.index("scarf")]
    assert m["n_songs"] == 3 and len(m["hits"]) == 3
    assert mine_motifs(corpus, "Nobody") == []


def test_archaeology_parse_and_render():
    from lyric_agent.archaeology import parse_report, render_report
    n = parse_report('```json\n{"overview": "总述<b>", '
                     '"motifs": [{"word": "scarf", "arc": "弧线"}]}\n```')
    assert n["overview"] == "总述<b>" and n["arcs"]["scarf"] == "弧线"
    assert parse_report("junk") is None
    motifs = [{"word": "scarf", "n_songs": 3, "total": 5, "hits": [
        {"song": "A", "album": "Alb", "line_index": 0,
         "text": "the scarf on the chair"}]}]
    def verifier(quote, hint):
        return {"song_title": "A", "line_index": 0,
                "line_text": quote, "dir": ""}
    html = render_report("X<y>", motifs, n, verifier, {"A": "A"})
    # jumpable verified hit + escaped hostile narrative + artist
    assert 'data-cite-label="A"' in html and "✅" in html
    assert "<b>" not in html and "X&lt;y&gt;" in html
    assert "弧线" in html
    assert "语料不足" in render_report("X", [], {}, None, None)


def test_debate_context_carries_line_dossier(monkeypatch):
    """The per-line dossier (echoes + motifs) must reach every persona."""
    from lyric_agent import debate
    from lyric_agent.config import Settings

    sent = {}

    class FakeResp:
        reply_text = "ok"

    class FakeClient:
        def __init__(self, settings):
            pass

        def generate(self, system_prompt, user_message, on_text_delta):
            sent["user"] = user_message
            on_text_delta("ok")
            return FakeResp()

    import lyric_agent.llm as llm
    monkeypatch.setattr(llm, "LLMClient", FakeClient)
    session = debate.DebateSession(
        lyric_line="left my scarf there", song_title="All Too Well",
        artist="Taylor Swift",
        annotation_context="围巾是信物　修辞：转喻",
        echo_context="- 《ATW10》：“you keep my old scarf”（相似度 0.7）")
    list(debate.speak(Settings(api_key="k"), session, "assistant"))
    assert "you keep my old scarf" in sent["user"]
    assert "围巾是信物" in sent["user"] and "转喻" in sent["user"]


def test_generate_annotations_resume(tmp_path, monkeypatch):
    """Chunk persistence + resume: failed lines are redone on rerun, good
    lines are reused without new LLM calls."""
    import json
    from lyric_agent.annotator import engine
    from lyric_agent.config import Settings

    d = tmp_path / "song"
    d.mkdir()
    (d / "lyrics.lrc").write_text(
        "[00:01.00] line zero\n[00:02.00] line one\n", encoding="utf-8")
    (d / "metadata.json").write_text(json.dumps(
        {"title": "T", "artist": "A"}), encoding="utf-8")

    calls = {"n": 0}

    class FlakyClient:
        def __init__(self, settings):
            pass

        def generate_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("proxy died")
            return [{"line_index": i, "lyric_text": t, "summary": f"ok {i}",
                     "emotional_tone": "calm"}
                    for i, t in enumerate(("line zero", "line one"))]

    monkeypatch.setattr(engine, "LLMClient", FlakyClient)
    monkeypatch.setattr(engine, "_mine_song_echoes",
                        lambda *a, **k: {})
    settings = Settings(api_key="k")

    song = engine.generate_annotations(settings, d, chunk_size=10)
    assert all(a.summary == engine.FAILED_MARKER for a in song.annotations)
    assert (d / "annotations.json").exists()  # persisted despite failure

    song2 = engine.generate_annotations(settings, d, chunk_size=10)
    assert [a.summary for a in song2.annotations] == ["ok 0", "ok 1"]
    n_after_success = calls["n"]

    # third run: everything good -> zero LLM calls
    engine.generate_annotations(settings, d, chunk_size=10)
    assert calls["n"] == n_after_success


def test_motif_section_renders():
    """Motif chips: spread counts, cite jumps only for library songs, escaping."""
    from lyric_agent.artist_profile import render_motif_section

    motifs = [{"word": "雨", "n_songs": 4, "total": 9, "hits": [
        {"song": "晴天", "album": "叶惠美", "line_index": 3,
         "text": "雨下整夜 <my love>"},
        {"song": "库外歌", "album": "", "line_index": 0, "text": "大雨落下"},
    ]}]
    html = render_motif_section(motifs, {"晴天": "晴天"})
    assert "「雨」" in html and "出现于 4 首歌" in html and "共 9 次" in html
    assert 'data-cite-label="晴天"' in html and 'data-cite-line="3"' in html
    assert html.count("data-cite-label") == 1      # 库外歌 has no jump
    assert "&lt;my love&gt;" in html and "<my love>" not in html
    assert "chat-empty" in render_motif_section([], {})


def test_echo_heat_aggregates():
    """Per-album totals from node echo_count; at most 3 pair cards."""
    from lyric_agent.artist_profile import render_echo_heat
    from lyric_agent.intertextuality.echo_map import (
        EchoEdge, EchoGraph, EchoNode, EchoPair,
    )

    pair = EchoPair(line_a="a", line_b="b", similarity=0.8)
    graph = EchoGraph(
        artist="A", threshold=0.75, song_total=3,
        nodes=[EchoNode("s1", "AL1", 3), EchoNode("s2", "AL1", 2),
               EchoNode("s3", "AL2", 1)],
        edges=[EchoEdge("s1", "s2", 2, pair), EchoEdge("s1", "s3", 1, pair),
               EchoEdge("s2", "s3", 1, pair), EchoEdge("s3", "s1", 1, pair)],
    )
    html = render_echo_heat(graph)
    assert "AL1" in html and "AL2" in html
    assert '<span class="aph-n">5</span>' in html   # AL1 = 3 + 2
    assert html.count("aph-pair-head") == 3          # top-3 cap
    assert "chat-empty" in render_echo_heat(None)
    empty = EchoGraph(artist="A", threshold=0.75, song_total=0)
    assert "chat-empty" in render_echo_heat(empty)


def test_album_timeline_order():
    """Known years ascending, registry fallback, unknowns clustered last."""
    from lyric_agent.artist_profile import render_album_timeline

    songs = [
        {"title": "t1", "artist": "A", "album": "新碟", "year": 2010},
        {"title": "t2", "artist": "A", "album": "Red", "year": 0},     # registry: 2012
        {"title": "t3", "artist": "A", "album": "谜之专辑", "year": 0},  # unknown
    ]
    html = render_album_timeline(songs, "A")
    assert html.index("新碟") < html.index("Red") < html.index("谜之专辑")
    assert "2010" in html and "2012" in html and "年份未知" in html
    assert "ovt-divider" in html
    assert "chat-empty" in render_album_timeline(songs, "nobody")


def test_review_order_and_pick(tmp_path, monkeypatch):
    from lyric_agent import review as rv

    book = [
        {"word": "old"},                                          # 旧条目无 review
        {"word": "hard", "review": {"correct": 1, "wrong": 3, "last_ts": 50}},
        {"word": "stale", "review": {"correct": 2, "wrong": 0, "last_ts": 10}},
        {"word": "fresh", "review": {"correct": 5, "wrong": 0, "last_ts": 99}},
    ]
    ordered = [e["word"] for e in rv.order_words(book)]
    # 错误率最高 > 未练过(ts=0) > 久未练 > 刚练熟
    assert ordered == ["hard", "old", "stale", "fresh"]

    import random
    rng = random.Random(7)
    picks = {rv.pick_word(book, rng)["word"] for _ in range(20)}
    assert picks <= {"hard", "old", "stale"}          # top-3 之内随机
    only = [{"word": "solo"}]
    assert rv.pick_word(only, rng, exclude="solo")["word"] == "solo"
    assert rv.pick_word([], rng) is None


def test_review_record_persists(tmp_path, monkeypatch):
    from lyric_agent import dictionary as d
    from lyric_agent import review as rv

    monkeypatch.setattr(d, "_WORDBOOK_PATH", tmp_path / "wb.json")
    d.add_word("scarf", line="l", song="s")
    book = rv.record_result("SCARF", correct=True, now=123.0)
    assert book[0]["review"] == {"correct": 1, "last_ts": 123.0}
    book = rv.record_result("scarf", correct=False, now=456.0)
    assert book[0]["review"] == {"correct": 1, "wrong": 1, "last_ts": 456.0}
    assert rv.book_stats(book) == {"total": 1, "practiced": 1, "mastered": 0}


def test_export_qwerty_format():
    from lyric_agent.review import export_qwerty

    book = [{"word": "use", "translation": "n. 运用\\nvt. 使用"},
            {"word": "bare", "translation": ""},
            {"word": "", "translation": "skipme"}]
    out = export_qwerty(book)
    assert out == [{"name": "use", "trans": ["n. 运用", "vt. 使用"]},
                   {"name": "bare", "trans": [""]}]
    import json
    assert json.dumps(out)


def test_synthesize_word_offline(tmp_path, monkeypatch):
    from lyric_agent import review as rv

    monkeypatch.setattr(rv, "TTS_CACHE_DIR", tmp_path)

    class Boom:
        def __init__(self, *a, **k): ...
        async def save(self, path):
            Path(path).write_bytes(b"")          # 模拟残片
            raise OSError("no network")

    import sys, types
    monkeypatch.setitem(sys.modules, "edge_tts",
                        types.SimpleNamespace(Communicate=Boom))
    from pathlib import Path
    assert rv.synthesize_word("hello") is None
    assert not (tmp_path / "hello.mp3").exists()  # 无残片


def test_render_practice_card_escapes():
    from lyric_agent.ui_helpers import render_practice_card

    html = render_practice_card(
        {"word": "a<b", "phonetic": "x&y", "translation": "n. 甲",
         "line": "<i>", "song": "s", "ai": "①<z>"},
        mp3_url="/gradio_api/file=C:/t.mp3", nonce="n1")
    assert 'data-word="a&lt;b"' in html and 'data-nonce="n1"' in html
    assert 'data-ch="a"' in html and '&lt;i&gt;' in html and '&lt;z&gt;' in html
    assert "ll-type-input" in html and "data-ll-say" in html
    # 无发音时不渲染重播按钮
    silent = render_practice_card({"word": "w"}, mp3_url="", nonce="n2")
    assert "data-ll-say" not in silent


def test_bilibili_extract_and_embed():
    from lyric_agent.bilibili import embed_url, extract_bvid

    assert extract_bvid("BV1xx411c7mD") == "BV1xx411c7mD"
    assert extract_bvid(
        "https://www.bilibili.com/video/BV1xx411c7mD/?p=1") == "BV1xx411c7mD"
    assert extract_bvid("杰伦 晴天") == ""
    assert extract_bvid("") == ""
    url = embed_url("BV1xx411c7mD")
    assert url.startswith("https://player.bilibili.com/player.html?bvid=BV1")
    assert "autoplay=0" in url and "danmaku=0" in url


def test_bilibili_mixin_and_strip():
    from lyric_agent.bilibili import _mixin_key, _strip_em

    # deterministic reorder: same inputs -> same 32-char key
    k = _mixin_key("a" * 32, "b" * 32)
    assert len(k) == 32 and k == _mixin_key("a" * 32, "b" * 32)
    assert set(k) <= {"a", "b"} and "b" in k
    assert _strip_em('<em class="keyword">晴天</em>&amp;周杰伦') == "晴天&周杰伦"


def test_bilibili_search_offline(monkeypatch):
    from lyric_agent import bilibili as b

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(b, "_get_json", boom)
    assert b.search_mv("晴天", "周杰伦") == []


def test_bilibili_search_parses_and_ladders(monkeypatch):
    from lyric_agent import bilibili as b

    calls = []

    def fake_get(url, headers):
        calls.append(url)
        if len(calls) == 1:          # bare attempt rejected
            return {"code": -412}
        if "nav" in url:
            return {"data": {"wbi_img": {
                "img_url": "https://i/x/abc.png",
                "sub_url": "https://i/x/def.png"}}}
        if "spi" in url:
            return {"data": {"b_3": "fakebuvid"}}
        return {"code": 0, "data": {"result": [
            {"type": "video", "bvid": "BV1xx411c7mD",
             "title": '<em class="keyword">晴天</em> MV', "author": "up主",
             "duration": "4:29"},
            {"type": "ketang", "bvid": "BV1zz411c7zZ", "title": "课堂"},
        ]}}

    monkeypatch.setattr(b, "_get_json", fake_get)
    b._cache.clear()
    out = b.search_mv("晴天", "周杰伦", limit=3)
    assert out == [{"bvid": "BV1xx411c7mD", "title": "晴天 MV",
                    "author": "up主", "duration": "4:29"}]
    assert any("w_rid=" in u for u in calls)   # signed retry happened


def test_render_audio_html_video_branches():
    from lyric_agent.ui_helpers import _render_audio_html

    base = {"audio_type": "none", "audio_src": "", "dir": "", "title": "t",
            "artist": "a", "album": "", "name": "t"}
    # 无 bvid + 非公开 -> 横幅 + 搜索按钮，无 iframe
    html = _render_audio_html(dict(base), public=False)
    assert "no-audio-hint" in html and "data-bvid-search" in html
    assert "bv-frame" not in html
    # 无 bvid + 公开 -> 只有横幅，无绑定入口
    pub = _render_audio_html(dict(base), public=True)
    assert "data-bvid-search" not in pub and "bv-frame" not in pub
    # 有 bvid + 无音频 -> 直接 iframe + 降级说明，横幅消失
    bound = _render_audio_html(dict(base, bvid="BV1xx411c7mD"), public=True)
    assert "bv-frame" in bound and "player.bilibili.com" in bound
    assert "no-audio-hint" not in bound and "视频模式" in bound
    # 候选卡渲染 + 转义
    cands = [{"bvid": "BV1xx411c7mD", "title": "<晴天> MV",
              "author": "up&主", "duration": "4:29"}]
    with_c = _render_audio_html(dict(base, bvid_cands=cands), public=False)
    assert 'data-bvid-pick="BV1xx411c7mD"' in with_c
    assert "&lt;晴天&gt;" in with_c and "up&amp;主" in with_c


def test_render_audio_html_video_toggle_with_audio(tmp_path):
    from lyric_agent.ui_helpers import _render_audio_html

    info = {"audio_type": "local", "audio_src": str(tmp_path / "a.mp3"),
            "dir": str(tmp_path), "title": "t", "artist": "a", "album": "",
            "name": "t", "bvid": "BV1xx411c7mD"}
    html = _render_audio_html(info, public=False)
    # 音频照常 + 懒加载 iframe（无 src，embed 存 data 属性）
    assert 'id="ll-audio"' in html and "data-video-toggle" in html
    assert 'data-embed="https://player.bilibili.com' in html
    assert "<iframe allowfullscreen" in html and 'src="https://player' not in html
