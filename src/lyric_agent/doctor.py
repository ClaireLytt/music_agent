"""Library & corpus health checks (`lyric-agent doctor`).

Finds the data problems that quietly degrade features: polluted corpus
entries (the same recording under two titles), placeholder/empty lyrics,
missing metadata, a stale corpus, and out-of-sync embeddings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# fraction of identical lines above which two corpus entries are considered
# the same recording (matches the echo-map duplicate-work guard)
DUPLICATE_OVERLAP = 0.5

_PLACEHOLDER_MARK = "暂无歌词"


@dataclass
class Finding:
    severity: str  # "error" | "warn"
    area: str      # "corpus" | "library" | "embeddings"
    message: str


def _load_corpus_entries(corpus_dir: str | Path) -> list[dict]:
    path = Path(corpus_dir) / "discography.jsonl"
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            entries.append(json.loads(raw))
    return entries


def check_corpus_duplicates(corpus_dir: str | Path) -> list[Finding]:
    """Pairs of corpus songs sharing most lines verbatim (data pollution)."""
    entries = _load_corpus_entries(corpus_dir)
    sets = {
        (e["title"], e.get("artist", "")): set(e.get("lyrics_lines", []))
        for e in entries
    }
    keys = list(sets)
    findings = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = sets[keys[i]], sets[keys[j]]
            if not a or not b:
                continue
            overlap = len(a & b) / min(len(a), len(b))
            if overlap >= DUPLICATE_OVERLAP:
                findings.append(Finding(
                    "error", "corpus",
                    f"《{keys[i][0]}》({keys[i][1]}) 与《{keys[j][0]}》"
                    f"({keys[j][1]}) 歌词重复 {overlap:.0%} — 疑似同一录音"
                    "被收录成两首歌，请修正曲库数据后重建语料库"))
    return findings


def check_library(songs_dir: str | Path) -> list[Finding]:
    """Per-song issues: missing/placeholder lyrics, incomplete metadata."""
    findings = []
    base = Path(songs_dir)
    if not base.exists():
        return [Finding("error", "library", f"歌曲目录不存在：{base}")]
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        lrc = d / "lyrics.lrc"
        if not lrc.exists():
            findings.append(Finding(
                "warn", "library", f"{d.name}: 缺少 lyrics.lrc（不会显示在列表中）"))
            continue
        text = lrc.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            findings.append(Finding("error", "library", f"{d.name}: lyrics.lrc 为空"))
        elif _PLACEHOLDER_MARK in text:
            findings.append(Finding(
                "warn", "library", f"{d.name}: 歌词仍是占位内容，可编辑 lyrics.lrc 补充"))
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            findings.append(Finding(
                "warn", "library", f"{d.name}: 缺少 metadata.json"))
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            findings.append(Finding(
                "error", "library", f"{d.name}: metadata.json 不是合法 JSON"))
            continue
        for field_name in ("title", "artist"):
            if not str(meta.get(field_name, "")).strip():
                findings.append(Finding(
                    "warn", "library",
                    f"{d.name}: metadata 缺少 {field_name}（影响彩蛋检索的歌手过滤）"))
        if not (d / "annotations.json").exists():
            findings.append(Finding(
                "warn", "library",
                f"{d.name}: 尚无 AI 批注（lyric-agent generate 可生成）"))
    return findings


def check_corpus_freshness(songs_dir: str | Path,
                           corpus_dir: str | Path) -> list[Finding]:
    """Library songs missing from the corpus (echo features won't see them)."""
    entries = _load_corpus_entries(corpus_dir)
    if not entries:
        return [Finding(
            "error", "corpus",
            f"语料库不存在或为空（{Path(corpus_dir) / 'discography.jsonl'}）— "
            "运行 python scripts/build_corpus.py 构建")]
    corpus_titles = {e["title"].strip().lower() for e in entries}
    findings = []
    base = Path(songs_dir)
    if not base.exists():
        return findings
    for d in sorted(base.iterdir()):
        meta_path = d / "metadata.json"
        if not d.is_dir() or not (d / "lyrics.lrc").exists() \
                or not meta_path.exists():
            continue
        try:
            title = json.loads(
                meta_path.read_text(encoding="utf-8")).get("title", "")
        except Exception:
            continue
        if title and title.strip().lower() not in corpus_titles:
            findings.append(Finding(
                "warn", "corpus",
                f"《{title}》不在语料库中（彩蛋/互文检索不覆盖它）— "
                "重建语料库与 embeddings 可纳入"))
    return findings


def check_embeddings(corpus_dir: str | Path) -> list[Finding]:
    """Embeddings exist and match the corpus row count."""
    emb_path = Path(corpus_dir) / "embeddings.npy"
    if not emb_path.exists():
        return [Finding(
            "error", "embeddings",
            f"未找到 {emb_path} — 运行 lyric-agent embed 生成")]
    try:
        import numpy as np
        from .intertextuality.corpus import load_corpus
        rows = np.load(str(emb_path), mmap_mode="r").shape[0]
        corpus_rows = len(load_corpus(str(corpus_dir)))
    except Exception as exc:
        return [Finding("error", "embeddings", f"embeddings 加载失败：{exc}")]
    if rows != corpus_rows:
        return [Finding(
            "error", "embeddings",
            f"embeddings 行数（{rows}）与语料库行数（{corpus_rows}）不一致 — "
            "语料库已变更，运行 lyric-agent embed 重建")]
    return []


def run_all(songs_dir: str | Path, corpus_dir: str | Path) -> list[Finding]:
    return (check_library(songs_dir)
            + check_corpus_duplicates(corpus_dir)
            + check_corpus_freshness(songs_dir, corpus_dir)
            + check_embeddings(corpus_dir))
