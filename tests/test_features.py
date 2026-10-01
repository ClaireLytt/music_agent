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


def test_blank_quiz_question():
    from lyric_agent.quiz import make_blank_question
    pool = {
        "cardigan": ("Taylor Swift",
                     ["and when I felt like I was an old cardigan",
                      "under someone's bed"]),
        "betty": ("Taylor Swift", ["betty, I won't make assumptions"]),
        "exile": ("Taylor Swift", ["I think I've seen this film before"]),
    }
    q = make_blank_question(pool, random.Random(3))
    assert q is not None
    assert q.answer in q.options
    assert len(q.options) <= 4
    assert "＿" in q.line
    assert q.answer.lower() not in q.line.lower()
    assert q.answer.lower() in q.original.lower()


def test_blank_quiz_guards():
    from lyric_agent.quiz import make_blank_question
    # no line sings its own title -> no question
    pool = {"a1": ("X", ["no title in here at all"]),
            "b2": ("X", ["nothing matching either"])}
    assert make_blank_question(pool, random.Random(1)) is None
    # a single song is not enough for options
    only = {"cardigan": ("X", ["I was an old cardigan at your door"])}
    assert make_blank_question(only, random.Random(1)) is None
