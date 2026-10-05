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


def _entry_from_lookup(word: str, translation: str = "",
                       phonetic: str = "", **extra) -> dict:
    """标准单词本条目：词典规范词形打底，调用方字段覆盖。
    add_word / import_words 共用，保证两条插入路径的条目形状一致。"""
    hit = lookup(word) or {"word": word, "phonetic": "", "translation": ""}
    return {"word": hit["word"],
            "phonetic": (phonetic or "").strip() or hit.get("phonetic", ""),
            "translation": (translation or "").strip()
            or hit.get("translation", ""),
            "line": "", "song": "", "label": "", "line_index": -1,
            "ai": "", **extra}


def update_entry(word: str, mutate) -> list[dict]:
    """找到词条并就地修改（mutate(entry)），保存后返回单词本；
    词不存在时静默跳过——wordbook 变更的唯一通道。"""
    book = load_wordbook()
    key = (word or "").lower()
    for e in book:
        if e.get("word", "").lower() == key:
            mutate(e)
            save_wordbook(book)
            break
    return book


def add_word(word: str, line: str = "", song: str = "",
             label: str = "", line_index: int = -1,
             ai: str = "") -> list[dict]:
    """Add a looked-up word to the wordbook (idempotent). Returns the book.

    label/line_index locate the source line for click-to-jump; ai is the
    in-context AI explanation generated in the popup (kept with the entry).
    Re-collecting an existing entry backfills a missing ai explanation."""
    book = load_wordbook()
    entry = _entry_from_lookup(word, line=line, song=song,
                               label=label, line_index=line_index, ai=ai)
    key = entry["word"].lower()
    for e in book:
        if e.get("word", "").lower() == key:
            if ai and not e.get("ai"):
                return update_entry(e["word"],
                                    lambda x: x.update(ai=ai))
            return book
    book.append(entry)
    save_wordbook(book)
    return book


def parse_wordlist_file(path: str) -> list[dict]:
    """解析用户从其他词典导出的单词表（.csv/.tsv/.txt/.xlsx）。

    返回 [{word, translation, phonetic}]。列识别：有表头时按名字匹配
    （word/单词、translation/释义/meaning/翻译、phonetic/音标），无表头
    按位置（第 1 列词、第 2 列释义、第 3 列音标）。xlsx 需要 openpyxl，
    缺了就抛 ValueError 提示另存为 CSV。"""
    import csv
    from pathlib import Path as _P

    p = _P(path)
    if p.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            raise ValueError("读取 Excel 需要 openpyxl（pip install "
                             "openpyxl），或把文件另存为 CSV 再导入。")
        ws = openpyxl.load_workbook(p, read_only=True).active
        raw = [["" if c is None else str(c) for c in row]
               for row in ws.iter_rows(values_only=True)]
    else:
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = p.read_text(encoding="gbk", errors="replace")
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel_tab if "\t" in sample else csv.excel
        raw = [row for row in csv.reader(text.splitlines(), dialect)]

    raw = [r for r in raw if any((c or "").strip() for c in r)]
    if not raw:
        return []
    # 表头识别与列映射
    _W = {"word", "单词", "词", "term", "headword", "name"}
    _T = {"translation", "trans", "释义", "意思", "meaning", "翻译",
          "解释", "definition"}
    _P2 = {"phonetic", "音标", "发音", "ipa"}
    head = [(c or "").strip().lower() for c in raw[0]]
    col = {"word": 0, "translation": 1, "phonetic": 2}
    rows = raw
    if any(h in _W for h in head):
        for i, h in enumerate(head):
            if h in _W:
                col["word"] = i
            elif h in _T:
                col["translation"] = i
            elif h in _P2:
                col["phonetic"] = i
        rows = raw[1:]

    def cell(r: list, i: int) -> str:
        return (r[i] or "").strip() if i < len(r) else ""

    return [{"word": cell(r, col["word"]),
             "translation": cell(r, col["translation"]),
             "phonetic": cell(r, col["phonetic"])} for r in rows]


def import_words(rows: list[dict], group: str) -> tuple[int, int]:
    """把解析出的单词表并入单词本（带分组）。返回 (新增, 跳过)。

    跳过：空词/不含字母/已在单词本。缺释义/音标时查本地词典补全。"""
    book = load_wordbook()
    have = {e.get("word", "").lower() for e in book}
    added = skipped = 0
    for r in rows:
        word = (r.get("word") or "").strip()
        if (not word or len(word) > 48
                or not any(c.isalpha() for c in word)
                or word.lower() in have):
            skipped += 1
            continue
        entry = _entry_from_lookup(
            word, translation=r.get("translation") or "",
            phonetic=r.get("phonetic") or "", group=group)
        if entry["word"].lower() in have:   # 词典规范化后的词形也要查重
            skipped += 1
            continue
        book.append(entry)
        have.add(word.lower())
        have.add(entry["word"].lower())
        added += 1
    if added:
        save_wordbook(book)
    return added, skipped


def word_groups(book: list[dict] | None = None) -> list[str]:
    """单词本里出现过的分组名（导入时自定义），排序稳定。"""
    book = load_wordbook() if book is None else book
    return sorted({(e.get("group") or "").strip()
                   for e in book} - {""}, key=str.lower)


def set_note(word: str, note: str) -> list[dict]:
    """写/改/清空某个词的个人笔记，返回更新后的单词本。"""
    def _mutate(e: dict) -> None:
        if (note or "").strip():
            e["note"] = note.strip()
        else:
            e.pop("note", None)
    return update_entry(word, _mutate)


def remove_word(word: str) -> list[dict]:
    book = [e for e in load_wordbook()
            if e.get("word", "").lower() != (word or "").lower()]
    save_wordbook(book)
    return book
