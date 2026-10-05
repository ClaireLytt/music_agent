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
    # the passage's lines must all belong to the answer song, in order
    passage = q.line.split("\n")
    assert all(ln in pool[q.answer][1] for ln in passage)
    idxs = [pool[q.answer][1].index(ln) for ln in passage]
    assert idxs == sorted(idxs)
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

    q = rv.round_queue(book)
    assert q == ["hard", "old", "stale", "fresh"]   # 整轮一人一次、按优先级
    assert len(q) == len(set(q))                    # 轮内零重复
    assert rv.round_queue([]) == []
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
    assert 'class="ll-type-card tp-blind"' in html   # 默认盲打首帧
    assert "data-tp-eye" in html
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
                    "author": "up主", "duration": "4:29", "play": 0}]
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
    # 音频照常 + 视频始终展开（带 src），📺 按钮只做收起/展开
    assert 'id="ll-audio"' in html and "data-video-toggle" in html
    assert 'data-embed="https://player.bilibili.com' in html
    assert 'src="https://player.bilibili.com' in html
    assert '"bv-frame" style="display:none"' not in html


def test_ts_to_seconds():
    from lyric_agent.bilibili import ts_to_seconds

    assert ts_to_seconds("1:32") == 92
    assert ts_to_seconds("01:02:03") == 3723
    assert ts_to_seconds("约 2:05 处") == 125
    assert ts_to_seconds("开头") is None
    assert ts_to_seconds("") is None


def test_export_anki_format():
    from lyric_agent.review import export_anki

    book = [{"word": "scarf", "phonetic": "skɑːf",
             "translation": "n. 围巾\\nvt. 披上",
             "line": "left my\tscarf", "song": "All Too Well",
             "ai": "①语境义：围巾\n②整句：好"},
            {"word": "", "translation": "skip"}]
    out = export_anki(book)
    lines = out.strip().splitlines()
    assert lines[0] == "#separator:tab" and lines[1] == "#html:true"
    assert len(lines) == 3
    front, back = lines[2].split("\t")
    assert front == "scarf /skɑːf/"
    assert "围巾；vt. 披上" in back          # 字面 \n 折叠
    assert "left my scarf" in back           # 字段内 tab 折叠
    assert "①语境义：围巾<br>②整句：好" in back  # 真实换行转 <br>
    assert "《All Too Well》" in back




def test_bilibili_pick_best():
    from lyric_agent.bilibili import pick_best

    def c(title, play, bvid="BVx"):
        return {"title": title, "play": play, "bvid": bvid,
                "author": "", "duration": ""}

    cands = [c("晴天 翻唱", 9_000_000), c("周杰伦《晴天》官方MV", 500_000),
             c("reaction 看晴天", 100), c("无关视频", 99_999_999)]
    # 含歌名的候选里播放量最高者当选（用户决定：播放量优先）
    best = pick_best(cands, "晴天", "周杰伦")
    assert best["title"] == "晴天 翻唱"
    best2 = pick_best(cands, "晴天", "")
    assert best2["title"] == "晴天 翻唱"
    # 歌名全不含 -> 退回相关性第一条
    assert pick_best(cands, "七里香", "周杰伦")["title"] == "晴天 翻唱"
    assert pick_best([], "晴天", "周杰伦") is None


def test_auto_bind_missing(tmp_path, monkeypatch):
    import json
    from lyric_agent import bilibili as b

    d = tmp_path / "songA"
    d.mkdir()
    (d / "metadata.json").write_text(json.dumps(
        {"title": "A", "artist": "X"}, ensure_ascii=False), encoding="utf-8")
    manual = tmp_path / "songB"
    manual.mkdir()
    (manual / "metadata.json").write_text(json.dumps(
        {"title": "B", "artist": "X", "bvid": "BVmanual9999"},
        ensure_ascii=False), encoding="utf-8")
    songs = [
        {"title": "A", "artist": "X", "dir": str(d), "bvid": ""},
        {"title": "B", "artist": "X", "dir": str(manual),
         "bvid": "BVmanual9999"},
        {"title": "FailSong", "artist": "X", "dir": str(tmp_path / "nope"),
         "bvid": ""},
    ]
    monkeypatch.setattr(b, "_THROTTLE_S", 0)
    monkeypatch.setattr(b, "_AUTOBIND_FAIL_PATH",
                        str(tmp_path / "fails.json"))
    monkeypatch.setattr(b, "search_mv", lambda t, a: (
        [] if t == "FailSong" else
        [{"title": f"X - {t} MV", "play": 10, "bvid": "BV1xx411c7mD",
          "author": "", "duration": ""}]))
    n = b.auto_bind_missing(songs, lambda: True)
    assert n == 1
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    assert meta["bvid"] == "BV1xx411c7mD" and meta["bvid_source"] == "auto"
    # 手动绑定未被碰
    metaB = json.loads((manual / "metadata.json").read_text(encoding="utf-8"))
    assert metaB["bvid"] == "BVmanual9999" and "bvid_source" not in metaB
    # 失败被记忆 -> 第二轮零新绑定且不重试失败项
    calls = []
    monkeypatch.setattr(b, "search_mv",
                        lambda t, a: calls.append(t) or [])
    songs2 = [dict(songs[0], bvid="BV1xx411c7mD"),
              songs[1], songs[2]]
    assert b.auto_bind_missing(songs2, lambda: True) == 0
    assert calls == []   # songA 已绑、songB 手动、FailSong 在 24h 冷却中


def test_quiz_passage_context():
    """长歌里锚点应带上邻句成段，且去掉泄露歌名的邻句。"""
    pool = {
        "Target": ("X", ["intro line long enough here",
                         "(No more baby, oooh)",
                         "the memorable anchor lyric line",
                         "Target appears in this neighbour line",
                         "closing line long enough too"]),
        "Other": ("Y", ["a completely different lyric line"]),
    }
    import random as _r
    for seed in range(12):
        q = make_question(pool, _r.Random(seed))
        if q.answer != "Target":
            continue
        passage = q.line.split("\n")
        assert 1 <= len(passage) <= 3
        assert all("target" not in ln.lower() for ln in passage)
        if len(passage) > 1:   # 邻句确实被带上了
            break
    else:
        raise AssertionError("passage never grew beyond one line")


def test_render_annotation_card():
    from lyric_agent.annotator.models import Annotation, RelatedLine
    from lyric_agent.ui_helpers import render_annotation_card

    ann = Annotation(line_index=3, lyric_text="x", summary="核心<隐喻>",
                     metaphor_analysis="本体喻体", wordplay="",
                     emotional_tone="tenderness",
                     related_lines=[RelatedLine(song="All Too Well",
                                                album="Red", line="old scarf")])
    html = render_annotation_card(ann, 3, can_generate=True)
    assert "核心&lt;隐喻&gt;" in html and "本体喻体" in html
    assert "tenderness" in html and "All Too Well" in html
    assert "data-gen-ann" not in html          # 有批注不出生成按钮
    assert "文字游戏" not in html              # 空字段不渲染
    # 空态：非公开带确认按钮，公开不带
    empty = render_annotation_card(None, 7, can_generate=True)
    assert 'data-gen-ann="7"' in empty and "调用 1 次 LLM" in empty
    assert "data-gen-ann" not in render_annotation_card(
        None, 7, can_generate=False)


def test_llm_usage_accounting(monkeypatch, tmp_path):
    """记账挂在重试包装器上：成功调用必入账，且绝不炸正常返回。"""
    pytest.importorskip("openai")  # 最小环境跳过而非报错
    from lyric_agent import llm
    from lyric_agent.config import Settings

    monkeypatch.setattr(llm, "_USAGE_PATH", tmp_path / "usage.json")
    s = Settings(api_key="x", llm_provider="openai", model_name="m-test")
    c = llm.LLMClient(s)
    resp = llm.LLMResponse(reply_text="ok",
                           usage={"input_tokens": 3, "output_tokens": 5})
    out = c._call_with_retry(lambda: resp)
    assert out.reply_text == "ok"
    u = llm.load_usage()
    assert u["total"] == {"calls": 1, "input_tokens": 3, "output_tokens": 5}
    assert u["models"]["m-test"]["output_tokens"] == 5   # 按模型分桶
    assert u["last_model"] == "m-test"
    # 全局精简规则注入到 system prompt（挂在 generate 入口）
    seen = {}
    monkeypatch.setattr(c, "_call_openai",
                        lambda sp, msgs: seen.update(sp=sp) or resp)
    c.generate("你是测试", "hi")
    assert seen["sp"].startswith("你是测试") and "精简直接" in seen["sp"]


def test_echo_overview_hero_and_fold():
    from types import SimpleNamespace as NS
    from lyric_agent.ui_helpers import _render_echo_overview

    hits = [(NS(line_index=1, text="src one"),
             NS(song="S1", album="", line="dst one", similarity=0.5)),
            (NS(line_index=4, text="src two"),
             NS(song="S2", album="A", line="dst two", similarity=0.9))]
    html = _render_echo_overview(hits, "歌手")
    assert "你可能没注意到" in html and "echo-hero" in html
    # 最强相似度的一对成为 hero
    assert html.index("dst two") < html.index("dst one")
    assert "<details" in html and "展开全部 2 处" in html
    # 单条命中时没有折叠区
    assert "<details" not in _render_echo_overview(hits[:1], "")


def test_echo_story_render_states():
    from lyric_agent.ui_helpers import render_echo_story

    assert "echo-story" in render_echo_story("两首歌写同一场雨。", False)
    btn = render_echo_story("", True)
    assert "data-echo-story" in btn and "1 次 LLM" in btn
    assert render_echo_story("", False) == ""


def test_echo_card_comment_and_word(tmp_path):
    from lyric_agent.share_card import render_echo_card

    path = render_echo_card(
        "Artist", "songA", "I can see the rain fall",
        "songB", "the rain falls on me", similarity=0.7,
        out_dir=tmp_path, comment="同一场雨的开头与结局",
        learn_word="rain", learn_gloss="n. 雨")
    from pathlib import Path
    assert Path(path).exists() and Path(path).stat().st_size > 10000


def test_word_examples_sources(tmp_path, monkeypatch):
    import json as J

    from lyric_agent import review as rv

    monkeypatch.setattr(rv, "_EXAMPLES_CACHE", tmp_path / "ex.json")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        J.dumps({"title": "SongX",
                 "lyrics_lines": ["the rain falls hard", "other line"]})
        + "\n"
        + J.dumps({"title": "Home", "lyrics_lines": ["rain on me"]}) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(rv, "_CORPUS_PATH", corpus)
    # 有道成功（后备 API 不该被调用）
    monkeypatch.setattr(rv, "_examples_from_youdao",
                        lambda w, n: ["It began to rain."])
    monkeypatch.setattr(rv, "_examples_from_api", lambda w, n: 1 / 0)
    assert rv.word_examples("Rain") == ["It began to rain."]
    # 缓存命中（两个 API 改成会炸也不该被调用）
    monkeypatch.setattr(rv, "_examples_from_youdao", lambda w, n: 1 / 0)
    assert rv.word_examples("rain") == ["It began to rain."]
    # 两个 API 都失败 -> 语料退回（排除出处歌），空结果也缓存
    (tmp_path / "ex.json").unlink()
    out = rv.word_examples("rain", exclude_song="Home")
    assert out and "SongX" in out[0] and "Home" not in "".join(out)
    # 全失败 -> []
    monkeypatch.setattr(rv, "_CORPUS_PATH", tmp_path / "nope.jsonl")
    assert rv.word_examples("zzzneverseen") == []
    # kill switch
    monkeypatch.setenv("LL_WORD_EXAMPLES", "0")
    assert rv.word_examples("rain") == []


def test_practice_card_jump_and_examples():
    from lyric_agent.ui_helpers import render_practice_card

    entry = {"word": "rain", "translation": "n. 雨",
             "line": "the Rain falls", "song": "SongX",
             "label": "SongX — Artist", "line_index": 7}
    html = render_practice_card(entry, "", "n1",
                                examples=["Dancing in the rain."])
    assert 'data-tp-jump="SongX' in html and 'data-tp-line="7"' in html
    # 例句里的目标词也要被盲打遮罩
    assert '<span class="tp-wline-word">rain</span>.' in html
    # 没有定位信息 -> 不可点
    entry2 = dict(entry, label="", line_index=-1)
    assert "data-tp-jump" not in render_practice_card(entry2, "", "n2")


def test_fanlore_progress_stage():
    from lyric_agent.fanlore import progress_stage

    assert progress_stage("") == "正在构思"
    assert progress_stage('{"known": true, "hook": "x') == "正在写一句话看懂"
    assert progress_stage('..."type": "a"..."type": "b"') == "正在写第 2 条线索"
    assert progress_stage('..."type": "a"..."chain": [') == "正在整理剧情推测"
    assert progress_stage('..."chain": []..."summary"') == "正在写收尾总结"


def test_parse_json_reply_fence():
    from lyric_agent.llm import parse_json_reply

    assert parse_json_reply('{"a": 1}') == {"a": 1}
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_fanlore_defensive():
    from lyric_agent.fanlore import parse_fanlore

    assert parse_fanlore(None).known is False
    assert parse_fanlore("garbage").known is False
    f = parse_fanlore({
        "known": True, "hook": " 一句话 ", "summary": "s", "caveat": "c",
        "clues": [
            {"type": "official", "title": "t", "body": "b",
             "quote_a": {"song": "A", "line": "la"}},
            {"type": "alien_source", "body": "b2"},   # 未知来源 → 最弱档
            {"type": "fan_theory"},                    # 没 body → 丢弃
            "not-a-dict",
        ],
        "chain": [{"song": "A", "beat": "x"}, {"song": "", "beat": "y"},
                  {"beat": "z"}, 42],
    })
    assert f.known and f.hook == "一句话"
    assert [c.type for c in f.clues] == ["official", "fan_theory"]
    assert f.clues[0].quote_a == ("A", "la") and f.clues[0].quote_b is None
    assert f.chain == [("A", "x")]


def test_render_fanlore_html():
    from lyric_agent.fanlore import Clue, Fanlore, render_fanlore_html

    # known=False → 诚实空态
    html = render_fanlore_html(Fanlore(known=False, caveat="太冷门"),
                               "SongX")
    assert "太冷门" in html and "lore-clue" not in html

    def verifier(line, song_hint):
        if line == "the rain falls":
            return {"song_title": "SongA", "line_index": 3,
                    "line_text": "the rain falls"}
        return None

    f = Fanlore(
        known=True, hook="一句话看懂", summary="总结",
        clues=[Clue(type="lyric_parallel", title="对上了", body="正文",
                    quote_a=("SongA", "the rain falls"),
                    quote_b=("SongB", "made up line")),
               Clue(type="fan_theory", body="理论正文")],
        chain=[("SongA", "第一站"), ("NotInLib", "第二站")])
    html = render_fanlore_html(f, "SongX", verifier=verifier,
                               label_of={"SongA": "SongA — Artist"})
    # 验证命中 → 可点跳转；未命中 → ⚠️
    assert 'data-cite-label="SongA — Artist"' in html
    assert "⚠️ 未在曲库验证" in html
    # fan_theory 自动带非官方标注
    assert "推测，非官方" in html
    # 剧情链：库内可点、库外灰显
    assert "lore-pill-out" in html and html.count("data-lore-vote") == 3
    assert "考据由 AI 整理" in html

