"""⌨️ 单词练习 — typing-practice review over the collected wordbook.

Pure logic lives here (word ordering, result recording, stats, qwerty-learner
export, per-word pronunciation). The UI card renderer is in ui_helpers and the
keystroke loop in ui_assets; everything in this module is zero-LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from .dictionary import load_wordbook, save_wordbook

logger = logging.getLogger(__name__)

TTS_CACHE_DIR = Path("data/cache/tts")
TTS_VOICE = "en-US-AriaNeural"


def _review(entry: dict) -> dict:
    return entry.get("review") or {}


def _wrong_rate(entry: dict) -> float:
    r = _review(entry)
    attempts = r.get("correct", 0) + r.get("wrong", 0)
    return r.get("wrong", 0) / attempts if attempts else 0.0


def order_words(book: list[dict]) -> list[dict]:
    """Review priority: wrong-heavy first, then never/least-recently
    practiced (unseen entries have last_ts 0), freshly-mastered last."""
    return sorted(book, key=lambda e: (-_wrong_rate(e),
                                       _review(e).get("last_ts", 0.0),
                                       e.get("word", "").lower()))


def round_queue(book: list[dict]) -> list[str]:
    """One practice round = every collected word exactly once, in priority
    order (wrong-heavy first, then never-practiced, then least-recent).
    No repeats inside a round; the next round reorders on fresh stats."""
    return [e["word"] for e in order_words(book) if e.get("word")]


def record_result(word: str, correct: bool,
                  now: float | None = None) -> list[dict]:
    """Persist one attempt (correct = completed with zero mistakes)."""
    book = load_wordbook()
    key = word.lower()
    for e in book:
        if e.get("word", "").lower() == key:
            r = e.get("review") or {}
            r["correct" if correct else "wrong"] = (
                r.get("correct" if correct else "wrong", 0) + 1)
            r["last_ts"] = now if now is not None else time.time()
            e["review"] = r
            save_wordbook(book)
            break
    return book


def book_stats(book: list[dict]) -> dict:
    """{total, practiced, mastered} — mastered: ≥3 clean passes, ≥80% rate."""
    practiced = mastered = 0
    for e in book:
        r = _review(e)
        attempts = r.get("correct", 0) + r.get("wrong", 0)
        if attempts:
            practiced += 1
            if r.get("correct", 0) >= 3 and r["correct"] / attempts >= 0.8:
                mastered += 1
    return {"total": len(book), "practiced": practiced, "mastered": mastered}


def export_qwerty(book: list[dict]) -> list[dict]:
    """qwerty-learner dictionary format: [{"name": word, "trans": [...]}].

    ECDICT uses a literal backslash-n (two characters) between senses."""
    out = []
    for e in book:
        word = e.get("word", "")
        if not word:
            continue
        senses = [s.strip() for s in
                  (e.get("translation", "") or "").split("\\n") if s.strip()]
        out.append({"name": word, "trans": senses or [""]})
    return out


def _anki_field(s: str) -> str:
    """One Anki TSV field: tabs/newlines folded (HTML is allowed)."""
    return (s or "").replace("\t", " ").replace("\\n", "；") \
                    .replace("\n", "<br>").strip()


def export_anki(book: list[dict]) -> str:
    """Anki-importable TSV: front = word + phonetic, back = gloss +
    source lyric + the saved AI explanation. One note per line."""
    lines = ["#separator:tab", "#html:true"]
    for e in book:
        word = e.get("word", "")
        if not word:
            continue
        phon = e.get("phonetic", "")
        front = f"{word} /{phon}/" if phon else word
        back = [_anki_field(e.get("translation", ""))]
        if e.get("line"):
            back.append(_anki_field(
                f"「{e['line']}」·《{e.get('song', '')}》"))
        if e.get("ai"):
            back.append("✨ " + _anki_field(e["ai"]))
        lines.append(f"{_anki_field(front)}\t"
                     + "<br>".join(p for p in back if p))
    return "\n".join(lines) + "\n"


_EXAMPLES_CACHE = Path("data/cache/word_examples.json")
_CORPUS_PATH = Path("data/corpus/discography.jsonl")


def _examples_from_youdao(word: str, limit: int) -> list[str]:
    """有道 jsonapi 的中英双语例句（国内可达、覆盖率高）。"""
    import urllib.parse
    import urllib.request

    url = "https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(word)
    with urllib.request.urlopen(url, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pairs = (data.get("blng_sents_part") or {}).get("sentence-pair") or []
    out = []
    for p in pairs:
        en = (p.get("sentence") or "").strip()
        zh = (p.get("sentence-translation") or "").strip()
        if en:
            out.append(f"{en} {zh}".strip())
        if len(out) >= limit:
            break
    return out


def _examples_from_api(word: str, limit: int) -> list[str]:
    import urllib.parse
    import urllib.request

    url = ("https://api.dictionaryapi.dev/api/v2/entries/en/"
           + urllib.parse.quote(word))
    with urllib.request.urlopen(url, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for entry in data if isinstance(data, list) else []:
        for m in entry.get("meanings", []):
            for d in m.get("definitions", []):
                ex = (d.get("example") or "").strip()
                if ex and ex not in out:
                    out.append(ex)
                if len(out) >= limit:
                    return out
    return out


def _examples_from_corpus(word: str, exclude_song: str, limit: int,
                          corpus_path: Path | None = None) -> list[str]:
    pat = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    out = []
    with (corpus_path or _CORPUS_PATH).open(encoding="utf-8") as f:
        for raw in f:
            try:
                song = json.loads(raw)
            except ValueError:
                continue
            if song.get("title", "") == exclude_song:
                continue
            for line in song.get("lyrics_lines", []):
                if pat.search(line):
                    out.append(f"{line} ——《{song.get('title', '')}》")
                    break  # 每首歌最多取一句
            if len(out) >= limit:
                break
    return out


def word_examples(word: str, exclude_song: str = "",
                  limit: int = 3,
                  corpus_dir: str | None = None) -> list[str]:
    """零 LLM 真例句：有道 jsonapi（中英双语）优先，退 dictionaryapi.dev，
    再退曲库其他歌的歌词句；全失败返回 []，绝不抛。
    结果（含空结果）落盘缓存，离线/限流只打一次。
    LL_WORD_EXAMPLES=0 彻底关闭（探针环境零外网请求）。"""
    import os

    word = (word or "").strip().lower()
    if not word or os.getenv("LL_WORD_EXAMPLES", "1") == "0":
        return []
    from .jsonio import read_json, write_json_atomic
    cache = read_json(_EXAMPLES_CACHE, {})
    if not isinstance(cache, dict):
        cache = {}
    if word in cache:
        return cache[word][:limit]
    examples: list[str] = []
    try:
        examples = _examples_from_youdao(word, limit)
    except Exception:
        logger.info("youdao jsonapi unavailable for %r", word)
    if not examples:
        try:
            examples = _examples_from_api(word, limit)
        except Exception:
            logger.info("dictionary API unavailable for %r", word)
    if not examples:
        corpus_path = (Path(corpus_dir) / "discography.jsonl"
                       if corpus_dir else _CORPUS_PATH)
        try:
            examples = _examples_from_corpus(word, exclude_song, 2,
                                             corpus_path)
        except OSError:
            pass
    try:
        cache[word] = examples
        write_json_atomic(_EXAMPLES_CACHE, cache)
    except OSError:
        pass
    return examples


def synthesize_word(word: str, voice: str = TTS_VOICE) -> Path | None:
    """Cached edge-tts pronunciation for one word; None on any failure
    (offline practice stays usable, just silent)."""
    slug = re.sub(r"[^a-z0-9]+", "_", word.lower()).strip("_")
    if not slug:
        return None
    out = TTS_CACHE_DIR / f"{slug}.mp3"
    if out.exists() and out.stat().st_size > 0:
        return out
    try:
        import edge_tts

        async def _run() -> None:
            await asyncio.wait_for(
                edge_tts.Communicate(word, voice).save(str(out)), timeout=8)

        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(_run())
        except RuntimeError:
            # already inside an event loop (e.g. some gradio setups)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()
        if out.exists() and out.stat().st_size > 0:
            return out
    except BaseException:
        logger.info("word TTS unavailable for %r", word, exc_info=True)
    out.unlink(missing_ok=True)  # never cache a partial/empty file
    return None
