"""End-rhyme detection for lyric lines (韵脚高亮).

Chinese: pinyin final (韵母) of the last CJK character, via pypinyin.
English: rhyming part of the last word's first pronunciation, via the CMU
dictionary (pronouncing); falls back to a trailing-vowel-cluster heuristic
for words the dictionary doesn't know.

Both libraries are optional — without them the toggle simply shows nothing.
"""

from __future__ import annotations

import re

_LAST_EN_WORD_RE = re.compile(r"[a-zA-Z']+(?=[^a-zA-Z']*$)")
_CJK_RE = re.compile(r"[一-鿿]")
_VOWEL_TAIL_RE = re.compile(r"[aeiouy]+[a-z]*$")

# pinyin finals that rhyme with each other in common practice (十三辙-ish,
# collapsed): map each final to its rhyme class
_FINAL_CLASSES = {
    "a": "a", "ia": "a", "ua": "a",
    "o": "o", "uo": "o", "e": "o",
    "ie": "ie", "ve": "ie", "üe": "ie", "ue": "ie",
    "ai": "ai", "uai": "ai",
    "ei": "ei", "ui": "ei", "uei": "ei",
    "ao": "ao", "iao": "ao",
    "ou": "ou", "iu": "ou", "iou": "ou",
    "an": "an", "ian": "an", "uan": "an", "van": "an", "üan": "an",
    "en": "en", "in": "en", "un": "en", "vn": "en", "ün": "en",
    "ang": "ang", "iang": "ang", "uang": "ang",
    "eng": "eng", "ing": "eng", "ong": "eng", "iong": "eng",
    "i": "i", "er": "er", "u": "u", "v": "u", "ü": "u",
}


def _zh_rhyme_key(text: str) -> str | None:
    chars = _CJK_RE.findall(text)
    if not chars:
        return None
    try:
        from pypinyin import Style, pinyin
    except ImportError:
        return None
    finals = pinyin(chars[-1], style=Style.FINALS, strict=False)
    final = finals[0][0] if finals and finals[0] else ""
    if not final:
        return None
    return "zh:" + _FINAL_CLASSES.get(final, final)


def _en_rhyme_key(text: str) -> str | None:
    m = _LAST_EN_WORD_RE.search(text or "")
    if not m:
        return None
    word = m.group(0).strip("'").lower()
    if len(word) < 2:
        return None
    try:
        import pronouncing
        phones = pronouncing.phones_for_word(word)
        if phones:
            return "en:" + pronouncing.rhyming_part(phones[0])
    except ImportError:
        pass
    tail = _VOWEL_TAIL_RE.search(word)
    return ("en~" + tail.group(0)) if tail else None


def line_rhyme_groups(texts: list[str]) -> list[int | None]:
    """Group index per line (None = no rhyme partner).

    Lines sharing an end-rhyme get the same group number; groups are only
    assigned when at least two lines share the key.
    """
    keys = [
        (_zh_rhyme_key(t) if _CJK_RE.search(t or "") else _en_rhyme_key(t))
        for t in texts
    ]
    counts: dict[str, int] = {}
    for k in keys:
        if k:
            counts[k] = counts.get(k, 0) + 1
    group_of: dict[str, int] = {}
    for k in counts:
        if counts[k] >= 2:
            group_of[k] = len(group_of)
    return [group_of.get(k) if k else None for k in keys]
