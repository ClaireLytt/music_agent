"""歌词宇宙侦探 (🕵️ tab): reconstruct the story hidden in an echo network.

The echo map says *which* songs echo each other; this module asks *why*.
It feeds the artist's strongest echo pairs (plus name-bearing lyric lines
as clues) to the LLM as an evidence dossier, gets back a structured
verdict — characters, relations, timeline — and renders it as a pure
server-side SVG relationship map + a storyboard, every claim pinned to a
quoted lyric. Also hosts 隔空回信 (💌): a letter one song's narrator
writes to another, built on one echoing pair.

No heavy deps here: prompts + JSON parsing + HTML rendering only.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ── data model ────────────────────────────────────────────

MAX_CHARACTERS = 6
MAX_RELATIONS = 8
MAX_EVENTS = 6


@dataclass
class UChar:
    name: str
    role: str = ""
    songs: list[str] = field(default_factory=list)


@dataclass
class URelation:
    a: str
    b: str
    label: str = ""
    evidence: str = ""


@dataclass
class UEvent:
    title: str
    song: str = ""
    summary: str = ""
    quote: str = ""


@dataclass
class Universe:
    artist: str
    synopsis: str = ""
    confidence: str = ""  # high / medium / low
    characters: list[UChar] = field(default_factory=list)
    relations: list[URelation] = field(default_factory=list)
    events: list[UEvent] = field(default_factory=list)
    caveat: str = ""


def _esc(s: str) -> str:
    return html.escape(str(s))


# ── evidence gathering ────────────────────────────────────

# a capitalized word mid-line in an (english) lyric is a decent proper-noun
# signal — most lyric lines only capitalize the first word. CJK lyrics have
# no casing, so CJK universes lean on the echo pairs alone.
_NAME_TOKEN_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
_NAME_STOPWORDS = {
    "Oh", "Ooh", "Whoa", "Hey", "Yeah", "Nah", "Mmm", "Ahh", "Lala",
    "But", "And", "The", "You", "She", "His", "Her", "They", "Baby",
}
MAX_NAME_LINES = 30


def extract_name_lines(lines: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """(song, text) pairs whose text likely mentions a name or place.

    Deduped by text, capped at MAX_NAME_LINES — this is a clue sheet for
    the detective prompt, not a corpus dump.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for song, text in lines:
        text = (text or "").strip()
        if not text or len(text) > 80 or text in seen:
            continue
        tokens = [t for t in _NAME_TOKEN_RE.findall(text)
                  if t not in _NAME_STOPWORDS]
        if not tokens:
            continue
        seen.add(text)
        out.append((song, text))
        if len(out) >= MAX_NAME_LINES:
            break
    return out


# ── detective prompt / parse ──────────────────────────────

DETECTIVE_SYSTEM = (
    "你是一位精通歌词文本细读的音乐侦探。你的任务：根据同一范围内不同歌曲之间"
    "互相呼应的歌词（彩蛋证据），推理这些歌曲背后是否隐藏着一个连贯的故事宇宙"
    "（同一批人物、同一段往事的不同视角）。只依据给出的歌词证据推理，"
    "把握不足就调低 confidence 并在 caveat 里说明；"
    "输出必须是合法 JSON，不要输出 JSON 以外的任何文字。"
)

_DETECTIVE_SCHEMA = (
    '请输出 JSON（内容用简体中文，键名保持英文）：\n'
    '{\n'
    '  "synopsis": "两三句话概括你推理出的故事；若不存在连贯故事，'
    '说明这些呼应的真实性质（自我引用/母题/巧合）",\n'
    '  "confidence": "high 或 medium 或 low",\n'
    '  "characters": [{"name": "角色名", "role": "身份与在故事中的位置", '
    '"songs": ["出现的歌"]}],\n'
    '  "relations": [{"a": "角色1", "b": "角色2", "label": "关系，'
    '如 恋人/背叛/旁观者", "evidence": "最能证明该关系的一句歌词及出处"}],\n'
    '  "timeline": [{"title": "章节标题", "song": "对应歌曲", '
    '"summary": "这一幕发生了什么", "quote": "关键歌词"}],\n'
    '  "caveat": "一句话说明这次推理的局限"\n'
    '}\n'
    f'characters 最多 {MAX_CHARACTERS} 个、relations 最多 {MAX_RELATIONS} 条、'
    f'timeline 最多 {MAX_EVENTS} 幕；角色名之间不要互相包含；'
    '证据歌词必须来自上面给出的句子，不得编造。'
)


def detective_messages(
    scope: str,
    songs: list[tuple[str, str]],       # (title, album)
    edges: list[tuple[str, str, int, list[tuple[str, str]]]],
        # a, b, count, [(line_a, line_b), ...] strongest first (≤3 used)
    name_lines: list[tuple[str, str]],  # (song, text)
) -> tuple[str, str]:
    """(system_prompt, user_message) for the detective call."""
    song_list = "、".join(
        f"《{t}》({al})" if al else f"《{t}》" for t, al in songs[:40])

    def fmt_edge(a: str, b: str, n: int,
                 pairs: list[tuple[str, str]]) -> str:
        head = f"- 《{a}》↔《{b}》（{n} 处呼应）："
        quoted = [f"“{la}” ↔ “{lb}”" for la, lb in pairs[:3]]
        if len(quoted) <= 1:
            return head + (quoted[0] if quoted else "")
        return head + "\n" + "\n".join(f"  · {q}" for q in quoted)

    edge_lines = "\n".join(fmt_edge(*e) for e in edges[:15])
    clue_lines = "\n".join(
        f"- 《{s}》：“{t}”" for s, t in name_lines) or "（无）"
    user = (
        f"检索范围：{scope}\n"
        f"涉及曲目：{song_list}\n\n"
        f"歌曲之间呼应最强的歌词对（彩蛋证据）：\n{edge_lines}\n\n"
        f"可能包含人名/地点的歌词线索：\n{clue_lines}\n\n"
        + _DETECTIVE_SCHEMA
    )
    return DETECTIVE_SYSTEM, user


def _s(v: Any) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) else ""


def parse_universe(data: Any, artist: str) -> Universe:
    """Tolerant parse of the LLM verdict — bad entries dropped, counts capped."""
    u = Universe(artist=artist)
    if not isinstance(data, dict):
        return u
    u.synopsis = _s(data.get("synopsis"))
    conf = _s(data.get("confidence")).lower()
    u.confidence = conf if conf in ("high", "medium", "low") else ""
    u.caveat = _s(data.get("caveat"))

    for c in data.get("characters") or []:
        if not isinstance(c, dict) or not _s(c.get("name")):
            continue
        songs = [_s(x) for x in (c.get("songs") or [])
                 if _s(x)] if isinstance(c.get("songs"), list) else []
        u.characters.append(
            UChar(name=_s(c.get("name")), role=_s(c.get("role")), songs=songs))
        if len(u.characters) >= MAX_CHARACTERS:
            break

    names = {c.name for c in u.characters}
    for r in data.get("relations") or []:
        if not isinstance(r, dict):
            continue
        a, b = _s(r.get("a")), _s(r.get("b"))
        if a in names and b in names and a != b:
            u.relations.append(URelation(
                a=a, b=b, label=_s(r.get("label")),
                evidence=_s(r.get("evidence"))))
        if len(u.relations) >= MAX_RELATIONS:
            break

    for ev in data.get("timeline") or []:
        if not isinstance(ev, dict) or not (_s(ev.get("title"))
                                            or _s(ev.get("summary"))):
            continue
        u.events.append(UEvent(
            title=_s(ev.get("title")), song=_s(ev.get("song")),
            summary=_s(ev.get("summary")), quote=_s(ev.get("quote"))))
        if len(u.events) >= MAX_EVENTS:
            break
    return u


# ── universe rendering ────────────────────────────────────

_UNI_W, _UNI_H = 860, 400
_UNI_PALETTE = ["#0969da", "#bf3989", "#1a7f37", "#bc4c00", "#8250df",
                "#9a6700"]
_CONF_ZH = {"high": ("推理把握：高", "uni-conf-high"),
            "medium": ("推理把握：中", "uni-conf-mid"),
            "low": ("推理把握：低（仅供玩味）", "uni-conf-low")}

UNIVERSE_EMPTY = ('<div class="chat-empty">选择歌手后点「开始破案」，'
                  'AI 侦探会根据歌曲之间的歌词呼应，推理背后隐藏的故事宇宙。'
                  '</div>')


def render_universe_html(u: Universe) -> str:
    """Verdict box + character relationship SVG + evidence + storyboard."""
    conf_txt, conf_cls = _CONF_ZH.get(u.confidence, ("", ""))
    head = (f'<div class="egg-headline">🕵️ {_esc(u.artist)} 的歌词宇宙'
            + (f'<span class="uni-conf {conf_cls}">{conf_txt}</span>'
               if conf_txt else "")
            + '</div>')
    if not u.characters:
        body = (u.synopsis or "AI 没能从这些呼应中推理出稳定的角色与故事，"
                "换一位歌手或先重建语料库索引试试。")
        return (head + f'<div class="uni-synopsis">{_esc(body)}</div>'
                + (f'<div class="uni-caveat">{_esc(u.caveat)}</div>'
                   if u.caveat else ""))

    parts: list[str] = []
    n = len(u.characters)
    cx, cy = _UNI_W / 2, _UNI_H / 2
    ring = 90.0 if n <= 2 else 130.0
    pos: dict[str, tuple[float, float]] = {}
    start = 0.0 if n == 2 else -math.pi / 2
    for i, c in enumerate(u.characters):
        angle = start + 2 * math.pi * i / n
        pos[c.name] = (cx + ring * math.cos(angle),
                       cy + ring * math.sin(angle))

    for r in u.relations:
        (x1, y1), (x2, y2) = pos[r.a], pos[r.b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        tip = f"{r.a} — {r.label or '关联'} — {r.b}"
        if r.evidence:
            tip += f"\n证据：{r.evidence}"
        parts.append(
            f'<g class="uni-rel-g"><line x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" class="uni-rel-line"/>'
            f'<text x="{mx:.1f}" y="{my - 5:.1f}" text-anchor="middle" '
            f'class="uni-rel-label">{_esc(r.label or "关联")}</text>'
            f'<title>{_esc(tip)}</title></g>'
        )

    for i, c in enumerate(u.characters):
        x, y = pos[c.name]
        color = _UNI_PALETTE[i % len(_UNI_PALETTE)]
        tip = c.name
        if c.role:
            tip += f"：{c.role}"
        if c.songs:
            tip += "（出现在 " + "、".join(f"《{s}》" for s in c.songs[:6]) + "）"
        initial = c.name[:1].upper()
        parts.append(
            f'<g class="uni-char"><circle cx="{x:.1f}" cy="{y:.1f}" r="24" '
            f'fill="{color}"/>'
            f'<text x="{x:.1f}" y="{y + 6:.1f}" text-anchor="middle" '
            f'class="uni-char-initial">{_esc(initial)}</text>'
            f'<text x="{x:.1f}" y="{y + 44:.1f}" text-anchor="middle" '
            f'class="uni-char-name">{_esc(c.name)}</text>'
            f'<title>{_esc(tip)}</title></g>'
        )

    svg = (f'<svg viewBox="0 0 {_UNI_W} {_UNI_H}" class="egg-svg" '
           'role="img">' + "".join(parts) + '</svg>')

    char_cards = "".join(
        '<div class="uni-char-card">'
        f'<span class="uni-char-dot" '
        f'style="background:{_UNI_PALETTE[i % len(_UNI_PALETTE)]}"></span>'
        f'<b>{_esc(c.name)}</b>'
        + (f' — {_esc(c.role)}' if c.role else "")
        + (('<span class="uni-char-songs">'
            + "、".join(f"《{_esc(s)}》" for s in c.songs[:6]) + '</span>')
           if c.songs else "")
        + '</div>'
        for i, c in enumerate(u.characters))

    rel_cards = "".join(
        '<div class="uni-rel-card">'
        f'<div class="uni-rel-head">{_esc(r.a)} ↔ {_esc(r.b)}'
        + (f' · {_esc(r.label)}' if r.label else "")
        + '</div>'
        + (f'<div class="uni-rel-ev">📎 {_esc(r.evidence)}</div>'
           if r.evidence else "")
        + '</div>'
        for r in u.relations)

    story = "".join(
        '<div class="uni-event">'
        f'<span class="uni-step">{i + 1}</span>'
        '<div class="uni-event-body">'
        f'<div class="uni-event-title">{_esc(ev.title)}'
        + (f'<span class="uni-event-song">《{_esc(ev.song)}》</span>'
           if ev.song else "")
        + '</div>'
        + (f'<div class="uni-event-sum">{_esc(ev.summary)}</div>'
           if ev.summary else "")
        + (f'<div class="uni-event-quote">“{_esc(ev.quote)}”</div>'
           if ev.quote else "")
        + '</div></div>'
        for i, ev in enumerate(u.events))

    return (
        head
        + (f'<div class="uni-synopsis">📖 {_esc(u.synopsis)}</div>'
           if u.synopsis else "")
        + svg
        + '<div class="uni-section">👥 人物档案</div>' + char_cards
        + (('<div class="uni-section">🔗 关系与证据</div>' + rel_cards)
           if rel_cards else "")
        + (('<div class="uni-section">🎬 故事线（每一幕对应一首歌）</div>'
            + story) if story else "")
        + (f'<div class="uni-caveat">⚖️ {_esc(u.caveat)}</div>'
           if u.caveat else "")
    )


# ── 隔空回信 (letter between two echoing songs) ───────────

LETTER_SYSTEM = (
    "你是歌词叙事者的代笔人。以第一人称、贴合原曲情绪的口吻写信，"
    "语言自然、有画面感，不堆砌辞藻，不解释背景。"
    "只输出信的正文（含称呼与落款），不要任何额外说明。"
)


def letter_messages(song_a: str, song_b: str, line_a: str, line_b: str,
                    count: int) -> tuple[str, str]:
    """(system_prompt, user_message): song_a's narrator writes to song_b."""
    user = (
        f"请以《{song_a}》的叙事者口吻，给《{song_b}》的叙事者写一封"
        "150~250 字的简体中文信（歌词引用保持原语言）。\n"
        f"这两首歌共有 {count} 处歌词互相呼应，其中最强的一对：\n"
        f"《{song_a}》唱道：“{line_a}”\n"
        f"《{song_b}》唱道：“{line_b}”\n\n"
        "要求：\n"
        f"1. 信中必须原样引用“{line_a}”这句歌词（一字不改），自然融入行文；\n"
        f"2. 明确呼应或回应对方那句“{line_b}”；\n"
        f"3. 以「致《{song_b}》：」开头，以「——《{song_a}》」落款。"
    )
    return LETTER_SYSTEM, user


def render_letter_html(song_a: str, song_b: str, body: str,
                       line_a: str, line_b: str) -> str:
    """Letter-paper card; the two echoing lyric lines are highlighted."""
    text = _esc((body or "").strip())
    for quote in (line_a, line_b):
        q = _esc(quote)
        if q and q in text:
            text = text.replace(q, f'<mark class="letter-echo">{q}</mark>')
    paras = "".join(f"<p>{p.strip()}</p>"
                    for p in text.split("\n") if p.strip())
    return (
        '<div class="letter-card">'
        f'<div class="letter-title">💌 《{_esc(song_a)}》'
        f'&nbsp;→&nbsp;《{_esc(song_b)}》</div>'
        f'<div class="letter-body">{paras}</div>'
        '<div class="letter-hint">高亮处为两首歌互相呼应的原句歌词</div>'
        '</div>'
    )


# ── CSS ───────────────────────────────────────────────────

UNIVERSE_CSS = """
.uni-synopsis {
  font-size: 14px; line-height: 1.8; color: var(--text-primary);
  background: var(--accent-soft); border-radius: 10px; padding: 10px 14px;
  margin: 8px 0 6px;
}
.uni-conf {
  font-size: 12px; font-weight: 600; margin-left: 12px;
  padding: 2px 10px; border-radius: 10px; vertical-align: 2px;
}
.uni-conf-high { background: rgba(26,127,55,0.12); color: #1a7f37; }
.uni-conf-mid { background: rgba(154,103,0,0.12); color: #9a6700; }
.uni-conf-low { background: rgba(207,34,46,0.10); color: #cf222e; }
.uni-rel-line { stroke: var(--accent); stroke-opacity: 0.4; stroke-width: 2; }
.uni-rel-g:hover .uni-rel-line { stroke-opacity: 0.9; }
.uni-rel-label {
  font-size: 11.5px; fill: var(--text-secondary);
  paint-order: stroke; stroke: var(--bg-main, #ffffff); stroke-width: 4px;
}
.uni-char-initial { fill: #ffffff; font-size: 17px; font-weight: 700; }
.uni-char-name { fill: var(--text-primary); font-size: 13px; font-weight: 600; }
.uni-section {
  font-size: 13.5px; font-weight: 700; color: var(--text-primary);
  margin: 12px 0 6px;
}
.uni-char-card, .uni-rel-card {
  padding: 7px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); margin-bottom: 5px; font-size: 13px;
  color: var(--text-primary);
}
.uni-char-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-right: 7px;
}
.uni-char-songs {
  display: block; font-size: 11.5px; color: var(--text-secondary);
  margin-top: 2px;
}
.uni-rel-head { font-weight: 600; }
.uni-rel-ev {
  font-size: 12px; font-style: italic; color: var(--text-secondary);
  margin-top: 3px;
}
.uni-event { display: flex; gap: 10px; margin-bottom: 8px; }
.uni-step {
  flex: none; width: 24px; height: 24px; border-radius: 50%;
  background: var(--accent); color: #ffffff; font-size: 13px;
  font-weight: 700; text-align: center; line-height: 24px; margin-top: 6px;
}
.uni-event-body {
  flex: 1; padding: 8px 12px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--bg-card);
}
.uni-event-title { font-size: 13.5px; font-weight: 700; color: var(--text-primary); }
.uni-event-song { font-weight: 400; color: var(--text-secondary); margin-left: 8px; font-size: 12.5px; }
.uni-event-sum { font-size: 13px; color: var(--text-primary); margin-top: 3px; line-height: 1.6; }
.uni-event-quote { font-size: 12.5px; font-style: italic; color: var(--accent); margin-top: 4px; }
.uni-caveat { font-size: 12px; color: var(--text-secondary); margin-top: 10px; }

/* 隔空回信 */
.letter-card {
  max-width: 640px; margin: 8px 0; padding: 26px 30px;
  border: 1px solid var(--border); border-radius: 12px;
  background:
    linear-gradient(var(--bg-card), var(--bg-card)) padding-box,
    repeating-linear-gradient(180deg, transparent 0 30px,
      rgba(140,149,159,0.12) 30px 31px) border-box;
  background-color: var(--bg-card);
}
.letter-title {
  font-size: 15px; font-weight: 700; color: var(--text-primary);
  margin-bottom: 12px;
}
.letter-body { font-size: 14.5px; line-height: 2.05; color: var(--text-primary); }
.letter-body p { margin: 0 0 10px; }
.letter-echo {
  background: rgba(212,167,44,0.22); color: inherit; border-radius: 4px;
  padding: 0 3px; font-style: italic;
}
.letter-hint { font-size: 11.5px; color: var(--text-secondary); margin-top: 10px; }
"""
