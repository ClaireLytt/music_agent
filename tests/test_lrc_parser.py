"""Tests for LRC parser."""

from lyric_agent.lrc_parser import parse_lrc


def test_parse_basic():
    content = """\
[ti:Test Song]
[ar:Test Artist]
[al:Test Album]
[00:05.20]First line
[00:10.50]Second line
[00:15.00]Third line
"""
    meta, lines = parse_lrc(content)
    assert meta.title == "Test Song"
    assert meta.artist == "Test Artist"
    assert meta.album == "Test Album"
    assert len(lines) == 3
    assert lines[0].timestamp_ms == 5200
    assert lines[0].text == "First line"
    assert lines[1].timestamp_ms == 10500
    assert lines[2].timestamp_ms == 15000


def test_parse_three_digit_ms():
    content = "[01:23.456]High precision\n"
    _, lines = parse_lrc(content)
    assert len(lines) == 1
    assert lines[0].timestamp_ms == 83456


def test_parse_no_ms():
    content = "[02:30]No milliseconds\n"
    _, lines = parse_lrc(content)
    assert len(lines) == 1
    assert lines[0].timestamp_ms == 150000


def test_parse_sorts_by_timestamp():
    content = """\
[00:20.00]Second
[00:05.00]First
[00:35.00]Third
"""
    _, lines = parse_lrc(content)
    assert lines[0].text == "First"
    assert lines[1].text == "Second"
    assert lines[2].text == "Third"
    assert lines[0].line_index == 0
    assert lines[1].line_index == 1


def test_parse_skips_empty_text():
    content = """\
[00:05.00]Real line
[00:10.00]
[00:15.00]Another line
"""
    _, lines = parse_lrc(content)
    assert len(lines) == 2


def test_parse_multiple_timestamps():
    content = "[00:05.00][01:05.00]Repeated line\n"
    _, lines = parse_lrc(content)
    assert len(lines) == 2
    assert lines[0].text == "Repeated line"
    assert lines[1].text == "Repeated line"
    assert lines[0].timestamp_ms == 5000
    assert lines[1].timestamp_ms == 65000


def test_parse_enhanced_lrc_word_timestamps():
    content = "[00:05.00]<00:05.00>Vintage <00:05.40>tee, <00:05.90>brand <00:06.30>new <00:06.70>phone\n"
    _, lines = parse_lrc(content)
    assert len(lines) == 1
    assert lines[0].text == "Vintage tee, brand new phone"
    assert lines[0].timestamp_ms == 5000


def test_parse_enhanced_lrc_word_only_line_skipped():
    content = "[00:05.00]<00:05.00> <00:05.40>\n"
    _, lines = parse_lrc(content)
    assert len(lines) == 0
