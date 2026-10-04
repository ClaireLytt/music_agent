"""⌨️ 单词练习 — typing-practice review over the collected wordbook.

Pure logic lives here (word ordering, result recording, stats, qwerty-learner
export, per-word pronunciation). The UI card renderer is in ui_helpers and the
keystroke loop in ui_assets; everything in this module is zero-LLM.
"""
from __future__ import annotations

import asyncio
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
