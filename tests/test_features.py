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
    assert d.remove_word("SCARF") == []


def test_render_wordbook_escapes():
    from lyric_agent.ui_helpers import render_wordbook
    html = render_wordbook([{"word": "a<b", "phonetic": "x&y",
                             "translation": "n. 释义\n第二行",
                             "line": "<script>", "song": "s"}])
    assert "a&lt;b" in html and "x&amp;y" in html and "&lt;script&gt;" in html
    assert "data-wb=" in html
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
