"""Mini EN→ZH dictionary for the in-lyrics word translator (双击取词).

Data: data/dict/ecdict_mini.csv.gz — a filtered subset of ECDICT
(https://github.com/skywind3000/ECDICT, MIT) keeping word/phonetic/中文释义
for ~58k quality-signalled words, plus lemma.en.txt.gz mapping inflected
forms back to their lemma (cobblestones → cobblestone). Fully offline.

The wordbook (收藏的单词) lives in data/wordbook.json.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DICT_DIR = Path(__file__).resolve().parents[2] / "data" / "dict"
_WORDBOOK_PATH = Path(__file__).resolve().parents[2] / "data" / "wordbook.json"

_WORD_RE = re.compile(r"^[a-zA-Z][a-zA-Z'\-]*$")

_lock = threading.Lock()
_dict: dict[str, tuple[str, str, str]] | None = None   # key -> (word, ipa, zh)
_lemma: dict[str, str] | None = None                   # inflected -> lemma


def _load() -> None:
    global _dict, _lemma
    with _lock:
        if _dict is not None:
            return
        d: dict[str, tuple[str, str, str]] = {}
        lem: dict[str, str] = {}
        try:
            with gzip.open(_DICT_DIR / "ecdict_mini.csv.gz", "rt",
                           encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    d[row["word"].lower()] = (
                        row["word"], row["phonetic"], row["translation"],
                        int(row.get("frq") or 0))
            with gzip.open(_DICT_DIR / "lemma.en.txt.gz", "rt",
                           encoding="utf-8") as f:
                for line in f:
                    lemma, _, forms = line.strip().partition("\t")
                    for form in forms.split(","):
                        # first lemma wins (file is frequency-ordered)
                        lem.setdefault(form, lemma)
        except OSError:
            logger.exception("dictionary data missing or unreadable")
        _dict, _lemma = d, lem


def _candidates(word: str) -> list[str]:
    """Lookup keys to try, best first: as-is, lemma, suffix heuristics."""
    w = word.lower().strip("'-")
    out = [w]
    if w.endswith("in") and len(w) >= 5:    # dancin(') → dancing
        out.append(w + "g")
    cands = list(out)
    for c in list(cands):
        lemma = (_lemma or {}).get(c)
        if lemma:
            out.append(lemma)
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""),
                     ("ing", "e"), ("ed", ""), ("ed", "e")):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            out.append(w[: len(w) - len(suf)] + rep)
    seen: set[str] = set()
    return [x for x in out if x and not (x in seen or seen.add(x))]


def lookup(word: str) -> dict | None:
    """Offline lookup. Returns {word, phonetic, translation} or None."""
    word = (word or "").strip()
    if not word or not _WORD_RE.match(word):
        return None
    _load()
    assert _dict is not None
    for key in _candidates(word):
        hit = _dict.get(key)
        if hit:
            return {"word": hit[0], "phonetic": hit[1], "translation": hit[2]}
    return None


def rank(word: str) -> int:
    """Corpus-frequency rank of a word (ECDICT frq/BNC; smaller = more
    common). Inflections resolve through the lemma map; 0 = unranked
    (rare or unknown)."""
    _load()
    assert _dict is not None
    ranks = [hit[3] for key in _candidates(word or "")
             for hit in [_dict.get(key)]
             if hit and len(hit) > 3 and hit[3] > 0]
    # min across inflection candidates: "dancing" is as common as "dance"
    return min(ranks) if ranks else 0


# ── wordbook (collected words) ──────────────────────────────

def load_wordbook() -> list[dict]:
    try:
        data = json.loads(_WORDBOOK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_wordbook(entries: list[dict]) -> None:
    _WORDBOOK_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def add_word(word: str, line: str = "", song: str = "",
             label: str = "", line_index: int = -1,
             ai: str = "") -> list[dict]:
    """Add a looked-up word to the wordbook (idempotent). Returns the book.

    label/line_index locate the source line for click-to-jump; ai is the
    in-context AI explanation generated in the popup (kept with the entry).
    Re-collecting an existing entry backfills a missing ai explanation."""
    book = load_wordbook()
    hit = lookup(word) or {"word": word, "phonetic": "", "translation": ""}
    key = hit["word"].lower()
    for e in book:
        if e.get("word", "").lower() == key:
            if ai and not e.get("ai"):
                e["ai"] = ai
                save_wordbook(book)
            return book
    book.append({**hit, "line": line, "song": song,
                 "label": label, "line_index": line_index, "ai": ai})
    save_wordbook(book)
    return book


def remove_word(word: str) -> list[dict]:
    book = [e for e in load_wordbook()
            if e.get("word", "").lower() != (word or "").lower()]
    save_wordbook(book)
    return book
