"""Evidence cards for AI 彩蛋解读 (P0: 可追溯证据).

The LLM must *cite* lyric lines instead of narrating freely; every quote
is verified against the local library (hallucinated citations get flagged
instead of rendered as fact), verified quotes become clickable jumps to
the exact song + line, and speculation is rendered in its own layer.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .intertextuality.echo_map import norm_line
from .lrc_parser import load_lrc_file


def esc_html(t) -> str:
    """Shared HTML escaper for the renderer modules."""
    import html
    return html.escape(str(t), quote=True)


def cite_jump_attrs(label: str, line_index: int | str) -> str:
    """data-cite-label/line 跳转属性（_HEAD_JS 的 cite 委托消费）。
    label 为空（目标不在歌单）时返回空串 = 不可点。"""
    if not label:
        return ""
    return (f' data-cite-label="{esc_html(label)}"'
            f' data-cite-line="{line_index}"')

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ── quote verification ──────────────────────────────────────

class QuoteIndex:
    """Lazy per-song lyric index: song -> [(line_index, text, norm)]."""

    def __init__(self, songs: list[dict]):
        self._songs = songs
        self._lines: dict[str, list[tuple[int, str, str]]] = {}

    def _song_lines(self, info: dict) -> list[tuple[int, str, str]]:
        key = info.get("dir", "")
        if key not in self._lines:
            rows: list[tuple[int, str, str]] = []
            lrc = Path(key) / "lyrics.lrc"
            try:
                _, timed = load_lrc_file(str(lrc))
                rows = [(ln.line_index, ln.text, norm_line(ln.text))
                        for ln in timed]
            except OSError:
                logger.warning("evidence: no lyrics for %s", key)
            self._lines[key] = rows
        return self._lines[key]

    def verify(self, quote: str, song_hint: str = "") -> dict | None:
        """Locate a cited lyric line in the library.

        Exact normalized match first; then containment (either way) for
        norms of >=15 chars. Songs whose title matches the hint are tried
        first so同名句落在被引用的那首歌。
        """
        want = norm_line(quote or "")
        if not want:
            return None
        hint = (song_hint or "").strip().casefold()
        ordered = sorted(
            self._songs,
            key=lambda s: 0 if hint and hint in s.get("title", "").casefold()
            else 1)
        fallback: dict | None = None
        for info in ordered:
            for idx, text, norm in self._song_lines(info):
                if norm == want:
                    return {"song_title": info.get("title", ""),
                            "line_index": idx, "line_text": text,
                            "dir": info.get("dir", "")}
                if (fallback is None and len(want) >= 15 and len(norm) >= 15
                        and (want in norm or norm in want)):
                    fallback = {"song_title": info.get("title", ""),
                                "line_index": idx, "line_text": text,
                                "dir": info.get("dir", "")}
        return fallback


# ── LLM output parsing ──────────────────────────────────────

def parse_claims(raw: str) -> dict | None:
    """Tolerant parse of the structured verdict (parse_mv's approach)."""
    text = (raw or "").strip()
    if not text:
        return None
    text = _FENCE_RE.sub("", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    quotes = []
    for q in data.get("quotes") or []:
        if isinstance(q, dict) and str(q.get("text") or "").strip():
            quotes.append({"text": str(q["text"]).strip(),
                           "song": str(q.get("song") or "").strip()})
        elif isinstance(q, str) and q.strip():
            quotes.append({"text": q.strip(), "song": ""})
    def _strs(key: str) -> list[str]:
        return [str(x).strip() for x in (data.get(key) or [])
                if isinstance(x, (str, int, float)) and str(x).strip()]
    return {
        "conclusion": str(data.get("conclusion") or "").strip(),
        "quotes": quotes,
        "facts": _strs("facts"),
        "speculation": _strs("speculation"),
    }


# ── rendering ───────────────────────────────────────────────

def render_evidence_card(claims: dict, index: QuoteIndex,
                         label_of: dict[str, str] | None = None) -> str:
    """HTML card: conclusion, verified quotes (clickable), facts, 💭 layer.

    label_of maps song title -> radio label (for the jump payload); when a
    verified song has no label, the quote shows ✅ without a jump link.
    """
    label_of = label_of or {}
    rows = []
    n_ok = 0
    for q in claims.get("quotes", []):
        hit = index.verify(q["text"], q.get("song", ""))
        if hit:
            n_ok += 1
            label = label_of.get(hit["song_title"], "")
            jump = (f' data-cite-label="{_esc(label)}" '
                    f'data-cite-line="{hit["line_index"]}"'
                    if label else "")
            rows.append(
                f'<div class="ev-quote ev-ok"{jump}>'
                f'<span class="ev-mark">✅</span>'
                f'<span class="ev-text">“{_esc(hit["line_text"])}”</span>'
                f'<span class="ev-src">——《{_esc(hit["song_title"])}》'
                f'第 {hit["line_index"] + 1} 行'
                f'{"（点击跳转）" if label else ""}</span></div>')
        else:
            rows.append(
                f'<div class="ev-quote ev-bad">'
                f'<span class="ev-mark">⚠️</span>'
                f'<span class="ev-text">“{_esc(q["text"])}”</span>'
                f'<span class="ev-src">——未在曲库中找到，此句可能是 AI '
                f'编造，不作为证据</span></div>')
    conf = ("高" if n_ok >= 2 else "中" if n_ok == 1 else "低")
    parts = ['<div class="ev-card">']
    if claims.get("conclusion"):
        parts.append(f'<div class="ev-conclusion">'
                     f'{_esc(claims["conclusion"])}</div>')
    if rows:
        parts.append('<div class="ev-sec-title">📜 文本证据'
                     f'<span class="ev-conf">置信度：{conf}'
                     f'（{n_ok} 条已核验）</span></div>')
        parts.extend(rows)
    for fact in claims.get("facts", []):
        parts.append(f'<div class="ev-fact">📅 {_esc(fact)}</div>')
    if claims.get("speculation"):
        parts.append('<div class="ev-sec-title">💭 推测（粉丝理论，'
                     '未经证实）</div>')
        for s in claims["speculation"]:
            parts.append(f'<div class="ev-spec">{_esc(s)}</div>')
    parts.append("</div>")
    return "".join(parts)
