"""Parse LRC (Lyric) files into structured timed lines.

Supported formats:
  [mm:ss.xx] Lyric text
  [mm:ss]    Lyric text
  [mm:ss.xxx] Lyric text
  Enhanced LRC word timestamps (<mm:ss.xx>) are stripped from the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIMESTAMP_RE = re.compile(r"\[(\d{2}):(\d{2})(?:\.(\d{2,3}))?\]")
_WORD_TS_RE = re.compile(r"<\d{2}:\d{2}(?:\.\d{2,3})?>")
_WORD_SPLIT_RE = re.compile(r"<(\d{2}):(\d{2})(?:\.(\d{2,3}))?>")
_META_RE = re.compile(r"\[(ti|ar|al|by|offset|length):([^\]]*)\]", re.IGNORECASE)


@dataclass
class TimedLine:
    timestamp_ms: int
    timestamp_str: str
    text: str
    line_index: int = 0
    # 词级时间轴（Enhanced LRC 行内 <mm:ss.xx> 标签）：
    # [(词起始 ms, 词文本含尾随空格), ...]；行级歌词为 None
    words: list[tuple[int, str]] | None = None


@dataclass
class LrcMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""


def _parse_word_timeline(body: str) -> list[tuple[int, str]] | None:
    """行内 <mm:ss.xx> 词级标签 → [(ms, 词文本), ...]；
    少于 2 个标签没有词级意义，返回 None（行级）。"""
    parts = _WORD_SPLIT_RE.split(body)
    # split 产出 [前缀, mm, ss, cs, 词文本, mm, ss, cs, 词文本, ...]
    if len(parts) < 9:   # 至少 2 个标签
        return None
    words: list[tuple[int, str]] = []
    for i in range(1, len(parts) - 3, 4):
        mm, ss, cs = parts[i], parts[i + 1], parts[i + 2]
        ms = int(mm) * 60_000 + int(ss) * 1000
        if cs:
            ms += int(cs) * 10 if len(cs) == 2 else int(cs)
        word = parts[i + 3]
        if word.strip():
            words.append((ms, word))
    return words if len(words) >= 2 else None


def parse_lrc(content: str) -> tuple[LrcMetadata, list[TimedLine]]:
    """Parse an LRC file and return metadata + sorted timed lines."""
    metadata = LrcMetadata()
    lines: list[TimedLine] = []

    for raw_line in content.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        meta_match = _META_RE.match(raw_line)
        if meta_match:
            tag = meta_match.group(1).lower()
            value = meta_match.group(2).strip()
            if tag == "ti":
                metadata.title = value
            elif tag == "ar":
                metadata.artist = value
            elif tag == "al":
                metadata.album = value
            continue

        timestamps: list[int] = []
        text = raw_line
        for m in _TIMESTAMP_RE.finditer(raw_line):
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            centis = m.group(3)
            if centis:
                if len(centis) == 2:
                    ms = int(centis) * 10
                else:
                    ms = int(centis)
            else:
                ms = 0
            timestamps.append(minutes * 60_000 + seconds * 1000 + ms)

        body = _TIMESTAMP_RE.sub("", raw_line)
        words = _parse_word_timeline(body)
        text = _WORD_TS_RE.sub("", body)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if not text or not timestamps:
            continue

        for ts_ms in timestamps:
            mm = ts_ms // 60_000
            ss = (ts_ms % 60_000) // 1000
            cs = (ts_ms % 1000) // 10
            lines.append(TimedLine(
                timestamp_ms=ts_ms,
                timestamp_str=f"[{mm:02d}:{ss:02d}.{cs:02d}]",
                text=text,
                words=words,
            ))

    lines.sort(key=lambda ln: ln.timestamp_ms)
    for i, ln in enumerate(lines):
        ln.line_index = i

    return metadata, lines


def load_lrc_file(path: str) -> tuple[LrcMetadata, list[TimedLine]]:
    """Read and parse an LRC file from disk."""
    with open(path, encoding="utf-8") as f:
        return parse_lrc(f.read())
