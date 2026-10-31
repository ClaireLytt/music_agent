"""Enhanced LRC（行内 <mm:ss.xx> 词级时间戳）解析。"""
from __future__ import annotations

from lyric_agent.lrc_parser import parse_lrc

ENHANCED = """[ti: demo]
[00:10.00]<00:10.00>I <00:10.50>stay <00:11.40>out
[00:20.00]plain line without word tags
"""


def test_word_timeline_parsed():
    _, lines = parse_lrc(ENHANCED)
    assert lines[0].text == "I stay out"          # 文本行为不变
    assert lines[0].words == [(10000, "I "), (10500, "stay "), (11400, "out")]


def test_plain_line_has_no_words():
    _, lines = parse_lrc(ENHANCED)
    assert lines[1].words is None


def test_single_word_tag_degrades_to_line_level():
    _, lines = parse_lrc("[00:05.00]<00:05.00>hello\n")
    assert lines[0].text == "hello"
    assert lines[0].words is None   # 只有一个词标签没有词级意义
