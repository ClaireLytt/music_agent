"""Load and manage lyrics corpus for intertextuality similarity search."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_LRC_TAG_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")


@dataclass
class CorpusLine:
    song: str
    album: str
    line_index: int
    text: str
    artist: str = ""


def _lrc_text_to_lines(lrc_text: str) -> list[str]:
    """Strip LRC timestamps and return deduplicated plain lyric lines."""
    lines: list[str] = []
    for raw in lrc_text.splitlines():
        text = _LRC_TAG_RE.sub("", raw).strip()
        if text and not text.startswith("[") and text not in lines:
            lines.append(text)
    return lines


def build_corpus(
    songs_dir: str | Path,
    corpus_dir: str | Path,
    bulk_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
) -> tuple[int, int]:
    """Build discography.jsonl from demo songs, the built-in catalog and
    an optional bulk JSONL.

    Returns (song_count, total_line_count).
    """
    from ..lrc_parser import load_lrc_file

    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(title: str, artist: str, album: str, lines: list[str]) -> None:
        # drop placeholder lyrics (songdata._PLACEHOLDER_LRC) so they never
        # pollute the corpus/embeddings as if they were real lines
        lines = [l for l in lines if "暂无歌词" not in l]
        key = (title.strip().lower(), artist.strip().lower())
        if not lines or key in seen:
            return
        seen.add(key)
        entries.append({
            "title": title,
            "artist": artist,
            "album": album,
            "lyrics_lines": lines,
        })

    base = Path(songs_dir)
    if base.exists():
        for song_dir in sorted(base.iterdir()):
            if not song_dir.is_dir():
                continue
            lrc = song_dir / "lyrics.lrc"
            if not lrc.exists():
                continue
            meta_path = song_dir / "metadata.json"
            meta = (
                json.loads(meta_path.read_text(encoding="utf-8"))
                if meta_path.exists() else {}
            )
            _, timed = load_lrc_file(str(lrc))
            lines: list[str] = []
            for ln in timed:
                if ln.text and ln.text not in lines:
                    lines.append(ln.text)
            _add(
                meta.get("title", song_dir.name.replace("_", " ").title()),
                meta.get("artist", ""),
                meta.get("album", ""),
                lines,
            )

    if catalog_path and Path(catalog_path).exists():
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        for item in catalog:
            _add(
                item.get("title", ""),
                item.get("artist", ""),
                item.get("album", ""),
                _lrc_text_to_lines(item.get("lrc", "")),
            )

    if bulk_path:
        for raw_line in Path(bulk_path).read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            entry = json.loads(raw_line)
            lines = [l.strip() for l in entry.get("lyrics", "").split("\n") if l.strip()]
            _add(entry.get("title", ""), entry.get("artist", ""),
                 entry.get("album", ""), lines)

    out_dir = Path(corpus_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "discography.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return len(entries), sum(len(e["lyrics_lines"]) for e in entries)


def load_corpus(corpus_dir: str) -> list[CorpusLine]:
    """Load discography.jsonl into a list of CorpusLine objects.

    Expected JSONL format per line:
    {"title": "...", "artist": "...", "album": "...", "lyrics_lines": [...]}
    """
    path = Path(corpus_dir) / "discography.jsonl"
    if not path.exists():
        return []

    lines: list[CorpusLine] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        entry = json.loads(raw_line)
        title = entry["title"]
        album = entry.get("album", "")
        artist = entry.get("artist", "")
        for i, text in enumerate(entry.get("lyrics_lines", [])):
            text = text.strip()
            if not text:
                continue
            lines.append(CorpusLine(
                song=title,
                album=album,
                line_index=i,
                text=text,
                artist=artist,
            ))

    return lines
