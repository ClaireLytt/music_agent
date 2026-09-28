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
_META_RE = re.compile(r"\[(ti|ar|al|by|offset|length):([^\]]*)\]", re.IGNORECASE)


@dataclass
class TimedLine:
    timestamp_ms: int
    timestamp_str: str
    text: str
    line_index: int = 0


@dataclass
class LrcMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""


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

        text = _TIMESTAMP_RE.sub("", raw_line)
        text = _WORD_TS_RE.sub("", text)
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
            ))

    lines.sort(key=lambda ln: ln.timestamp_ms)
    for i, ln in enumerate(lines):
        ln.line_index = i

    return metadata, lines


def load_lrc_file(path: str) -> tuple[LrcMetadata, list[TimedLine]]:
    """Read and parse an LRC file from disk."""
    with open(path, encoding="utf-8") as f:
        return parse_lrc(f.read())
