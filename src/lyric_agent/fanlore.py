"""歌迷考据 (fan lore): the AI as a fan-archivist, not an egg counter.

For one song the LLM organizes what it reliably knows — official facts,
in-library lyric parallels (fed in as hard evidence from the echo scan)
and fan theories — into a story page: hook → labeled clues → a plot-
theory chain → a fan-video style summary. The schema forces honesty the
structurally: every clue carries a source type, quoted lyrics
are verified against the library at render time, and when the model has
no solid lore it must say so (known=false) instead of inventing any.

No heavy deps: prompts + JSON parsing + HTML only.
Results are persisted per song as fanlore.json (generated once, reused).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FANLORE_FILENAME = "fanlore.json"
MAX_CLUES = 4
MAX_CHAIN = 6

FANLORE_EMPTY = ''

_CLUE_TYPES = ("official", "lyric_parallel", "fan_theory")

FANLORE_SYSTEM = (
    "你是资深的歌词考据作者。你把一首歌的零散线索整理成好读的考据页，"
    "但有铁律："
    "① official 类线索只写你确实掌握的公开事实（创作灵感来源、歌手自述、"
    "公开报道），没把握的事实绝不写；"
    "② fan_theory 类是你基于歌词文本的大胆推测（联想、剧情解读），"
    "必须以明确的推测口吻书写，不得冒充事实或粉丝共识；"
    "③ lyric_parallel 类优先使用用户提供的曲库呼应对（那是程序算出的硬"
    "证据），引用歌词必须逐字照抄，不得改写/翻译；"
    "④ 对这首歌没有可靠考据时把 known 设为 false 并在 caveat 说明，"
    "宁缺毋滥。全部用简体中文。"
    "输出必须是合法 JSON，不要输出 JSON 以外的任何文字。"
)

_FANLORE_SCHEMA = (
    "请输出 JSON：\n"
    "{\n"
    '  "known": true/false,  // 是否确实有值得讲的考据\n'
    '  "hook": "一句话看懂这首歌（抓人，<=40字）",\n'
    '  "clues": [\n'
    '    {"type": "official | lyric_parallel | fan_theory"  （fan_theory = 基于歌词的推测）,\n'
    '     "title": "线索小标题（像粉丝视频的小节名）",\n'
    '     "body": "60-100字，讲成有发现感的小故事，惜字如金",\n'
    '     "quote_a": {"song": "歌名", "line": "歌词原句，逐字"},  // 可省\n'
    '     "quote_b": {"song": "歌名", "line": "歌词原句，逐字"}}  // 可省\n'
    "  ],\n"
    '  "chain": [  // 基于歌词推测的多首歌连续剧情；没有可讲的则为 []\n'
    '    {"song": "歌名", "beat": "这一站的一句剧情"}\n'
    "  ],\n"
    '  "summary": "粉丝视频式收尾：这首歌最有意思的地方（<=80字）",\n'
    '  "caveat": "不确定之处的说明，可空"\n'
    "}\n"
    f"clues 最多 {MAX_CLUES} 条、chain 最多 {MAX_CHAIN} 站；"
    "known 为 false 时 clues 和 chain 必须为空数组。全文精炼，总字数控制在 500 字以内。"
)


def progress_stage(buffer: str) -> str:
    """把流式 JSON buffer 翻译成人话进度（粗粒度启发式，纯展示用）。"""
    if '"summary"' in buffer:
        return "正在写收尾总结"
    if '"chain"' in buffer:
        return "正在整理剧情推测"
    n = buffer.count('"type"')
    if n:
        return f"正在写第 {n} 条线索"
    if '"hook"' in buffer:
        return "正在写一句话看懂"
    return "正在构思"


def fanlore_messages(title: str, artist: str, album: str = "",
                     year: int | str | None = None,
                     echo_pairs: list[tuple[str, str, str]] | None = None,
                     library_titles: list[str] | None = None,
                     ) -> tuple[str, str]:
    """(system_prompt, user_message).

    echo_pairs: (本歌歌词句, 对方歌名, 对方歌词句) — 程序算出的硬证据。
    library_titles: chain 里尽量使用这些曲库歌名（能点击跳转）。
    """
    meta = f"歌曲：《{title}》\n歌手：{artist}\n"
    if album:
        meta += f"专辑：{album}\n"
    if year:
        meta += f"年份：{year}\n"
    if echo_pairs:
        meta += "\n曲库检索出的歌词呼应（硬证据，可直接用作 lyric_parallel）：\n"
        for src, song, dst in echo_pairs[:5]:
            meta += f"- 本歌「{src}」 ↔ 《{song}》「{dst}」\n"
    if library_titles:
        meta += ("\n曲库中该歌手的其他歌（chain 尽量用这些歌名）："
                 + "、".join(sorted(library_titles)[:40]) + "\n")
    user = (meta + "\n请把这首歌的考据整理成一页：官方信息、歌词呼应、"
            "基于歌词的推测，各归各的标签。\n\n" + _FANLORE_SCHEMA)
    return FANLORE_SYSTEM, user


@dataclass
class Clue:
    type: str = "fan_theory"
    title: str = ""
    body: str = ""
    quote_a: tuple[str, str] | None = None  # (song, line)
    quote_b: tuple[str, str] | None = None


@dataclass
class Fanlore:
    known: bool = False
    hook: str = ""
    clues: list[Clue] = field(default_factory=list)
    chain: list[tuple[str, str]] = field(default_factory=list)  # (song, beat)
    summary: str = ""
    caveat: str = ""


def _parse_quote(q) -> tuple[str, str] | None:
    if not isinstance(q, dict):
        return None
    song = str(q.get("song") or "").strip()
    line = str(q.get("line") or "").strip()
    return (song, line) if line else None


def parse_fanlore(data) -> Fanlore:
    """Tolerant parse of the LLM verdict (parse_mv's approach)."""
    if not isinstance(data, dict):
        return Fanlore()
    f = Fanlore(known=bool(data.get("known")))
    for key in ("hook", "summary", "caveat"):
        v = data.get(key)
        if isinstance(v, str):
            setattr(f, key, v.strip())
    clues = data.get("clues")
    if isinstance(clues, list):
        for c in clues:
            if not isinstance(c, dict):
                continue
            body = str(c.get("body") or "").strip()
            if not body:
                continue
            ctype = c.get("type")
            if ctype not in _CLUE_TYPES:
                ctype = "fan_theory"  # 未知来源按最弱可信度处理
            f.clues.append(Clue(
                type=ctype,
                title=str(c.get("title") or "").strip(),
                body=body,
                quote_a=_parse_quote(c.get("quote_a")),
                quote_b=_parse_quote(c.get("quote_b")),
            ))
            if len(f.clues) == MAX_CLUES:
                break
    chain = data.get("chain")
    if isinstance(chain, list):
        for s in chain:
            if not isinstance(s, dict):
                continue
            song = str(s.get("song") or "").strip()
            beat = str(s.get("beat") or "").strip()
            if song and beat:
                f.chain.append((song, beat))
            if len(f.chain) == MAX_CHAIN:
                break
    return f


def load_fanlore(song_dir: str | Path):
    """Saved raw verdict for this song, or None (model-agnostic cache)."""
    try:
        p = Path(song_dir) / FANLORE_FILENAME
        if not p.exists():
            return None
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Failed reading %s in %s", FANLORE_FILENAME, song_dir)
        return None
    if isinstance(raw, dict) and "payload" in raw:
        return raw["payload"]
    return raw


def save_fanlore(song_dir: str | Path, data, model: str = "") -> None:
    try:
        from .jsonio import write_json_atomic
        write_json_atomic(Path(song_dir) / FANLORE_FILENAME,
                          {"model": model, "payload": data}, indent=2)
    except OSError:
        logger.exception("Failed saving %s in %s", FANLORE_FILENAME, song_dir)


from .evidence import cite_jump_attrs, esc_html as _esc  # noqa: E402


_BADGES = {
    "official": ("📖 官方信息", "lore-official"),
    "lyric_parallel": ("🔎 歌词对照", "lore-parallel"),
    "fan_theory": ("💭 AI 推测", "lore-theory"),
}

_DISCLAIM = ('<div class="lore-disclaim">考据由 AI 整理：歌词对照经曲库'
             '验证（✅ 可点击跳转）；官方信息来自 AI 训练语料、可能有误，'
             '推测仅基于歌词 · 均非官方设定</div>')


def _quote_html(q: tuple[str, str], verifier, label_of: dict) -> str:
    song, line = q
    hit = verifier(line, song) if verifier else None
    if hit:
        jump = cite_jump_attrs((label_of or {}).get(hit["song_title"], ""),
                               hit["line_index"])
        return (f'<div class="lore-quote ev-ok"{jump}>'
                f'“{_esc(hit["line_text"])}”'
                f'<span class="lore-quote-src">——《'
                f'{_esc(hit["song_title"])}》 ✅</span></div>')
    return (f'<div class="lore-quote ev-bad">“{_esc(line)}”'
            f'<span class="lore-quote-src">——《{_esc(song)}》'
            ' ⚠️ 未在曲库验证</span></div>')


def render_fanlore_html(f: Fanlore, title: str,
                        verifier=None,
                        label_of: dict | None = None) -> str:
    """verifier: callable(quote, song_hint) -> hit dict | None（evidence.
    QuoteIndex.verify）；label_of: 歌名 -> 歌单 label（跳转用）。"""
    head = f'<div class="lore-head">🕵️《{_esc(title)}》歌迷考据</div>'
    if not f.known:
        note = f.caveat or ("AI 对这首歌没有可靠的考据素材（官方信息太少"
                            "或过于冷门），所以不乱编。")
        return (f'<div class="lore-page">{head}'
                f'<div class="chat-empty">{_esc(note)}</div>'
                f'{_DISCLAIM}</div>')
    parts = [head]
    if f.hook:
        parts.append(f'<div class="lore-hook">{_esc(f.hook)}</div>')
    if f.clues:
        parts.append(f'<div class="lore-sec">🔎 {len(f.clues)} 条'
                     '有意思的线索</div>')
    for c in f.clues:
        badge, cls = _BADGES[c.type]
        inner = [f'<span class="lore-badge {cls}">{badge}</span>']
        if c.title:
            inner.append(f'<div class="lore-clue-title">{_esc(c.title)}'
                         '</div>')
        inner.append(f'<div class="lore-clue-body">{_esc(c.body)}</div>')
        for q in (c.quote_a, c.quote_b):
            if q:
                inner.append(_quote_html(q, verifier, label_of or {}))
        if c.type == "fan_theory":
            inner.append('<div class="lore-theory-note">⚠️ AI 基于歌词'
                         '的推测，非官方设定</div>')
        parts.append(f'<div class="lore-clue">{"".join(inner)}</div>')
    if f.caveat:
        parts.append(f'<div class="lore-caveat">📝 {_esc(f.caveat)}</div>')
    parts.append(_DISCLAIM)
    return f'<div class="lore-page">{"".join(parts)}</div>'
