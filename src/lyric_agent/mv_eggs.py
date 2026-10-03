"""MV easter eggs: what the LLM reliably knows about a song's official
music video, rendered as a card.

No video is ever fetched or watched — for well-known MVs (Taylor Swift,
周杰伦…) the model's public knowledge of directors, imagery and hidden
details is rich. The schema forces honesty: when the model has no solid
knowledge of the MV it must say so (known=false) instead of inventing
shots, and the card then shows search links only.

universe.py's no-heavy-deps pattern: prompts + JSON parsing + HTML only.
Results are persisted per song as mv_eggs.json (generated once, reused).
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

MV_FILENAME = "mv_eggs.json"
MAX_EGGS = 6

MV_EMPTY = ('<div class="chat-empty">点「生成 MV 彩蛋」，让 AI 整理这支'
            '官方 MV 的导演、隐藏细节与歌词呼应。</div>')

MV_SYSTEM = (
    "你是熟悉欧美与华语流行音乐 MV 的研究者。你只依据自己确实掌握的"
    "公开信息作答：导演、画面意象、致敬与彩蛋，确定的才写；对这支 MV "
    "没有可靠了解（或这首歌可能没有官方 MV）时，如实把 known 设为 "
    "false，宁缺毋滥，绝不编造画面细节。"
    "输出必须是合法 JSON，不要输出 JSON 以外的任何文字。"
)

_MV_SCHEMA = (
    "请输出 JSON：\n"
    "{\n"
    '  "known": true/false,  // 是否确实了解这支官方 MV\n'
    '  "director": "导演名，不确定则留空字符串",\n'
    '  "eggs": [\n'
    '    {"detail": "一个彩蛋 / 值得注意的画面细节",\n'
    '     "moment": "画面出现的位置，只能从这些词里选：'
    '片头/主歌/副歌/桥段/结尾/贯穿全片；不确定就留空",\n'
    '     "lyric_link": "它呼应的歌词原句——必须逐字照抄歌词，'
    '不得改写/翻译/缩略；没有明确对应句就留空"}\n'
    "  ],\n"
    '  "caveat": "不确定之处的说明，可空"\n'
    "}\n"
    f"eggs 最多 {MAX_EGGS} 条；known 为 false 时 eggs 必须为空数组。"
)


def mv_messages(title: str, artist: str, album: str = "",
                year: int | str | None = None) -> tuple[str, str]:
    """(system_prompt, user_message) for the MV-eggs call."""
    meta = f"歌曲：《{title}》\n歌手：{artist}\n"
    if album:
        meta += f"专辑：{album}\n"
    if year:
        meta += f"年份：{year}\n"
    user = (meta + "\n请基于你对这首歌官方 MV 的了解，整理它的导演与彩蛋"
            "（隐藏细节、反复出现的意象、与歌词或歌手其他作品的呼应）。\n\n"
            + _MV_SCHEMA)
    return MV_SYSTEM, user


_MOMENTS = {"片头", "主歌", "副歌", "桥段", "结尾", "贯穿全片"}


@dataclass
class MvEggs:
    known: bool = False
    director: str = ""
    # (detail, lyric_link, timestamp) — older caches carry 2-tuples
    eggs: list[tuple] = field(default_factory=list)
    caveat: str = ""


def parse_mv(data) -> MvEggs:
    """Tolerant parse of the LLM verdict (parse_universe's approach)."""
    if not isinstance(data, dict):
        return MvEggs()
    m = MvEggs(known=bool(data.get("known")))
    director = data.get("director")
    if isinstance(director, str):
        m.director = director.strip()
    eggs = data.get("eggs")
    if isinstance(eggs, list):
        for e in eggs:
            if not isinstance(e, dict):
                continue
            detail = str(e.get("detail") or "").strip()
            if not detail:
                continue
            link = e.get("lyric_link")
            ts = e.get("moment") or e.get("timestamp")
            ts = ts.strip() if isinstance(ts, str) else ""
            if ts not in _MOMENTS:
                ts = ""  # enum-validated: anything else was invented
            m.eggs.append(
                (detail, link.strip() if isinstance(link, str) else "", ts))
            if len(m.eggs) == MAX_EGGS:
                break
    caveat = data.get("caveat")
    if isinstance(caveat, str):
        m.caveat = caveat.strip()
    return m


def load_mv(song_dir: str | Path, model: str | None = None):
    """Saved raw verdict for this song, or None.

    Verdicts are cached per model: switching the LLM invalidates the
    cache so a better model gets to re-answer. Legacy files (saved
    before the model key existed) stay valid for any model.
    """
    try:
        p = Path(song_dir) / MV_FILENAME
        if not p.exists():
            return None
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Failed reading %s in %s", MV_FILENAME, song_dir)
        return None
    if isinstance(raw, dict) and "payload" in raw and "model" in raw:
        if model and raw["model"] != model:
            return None
        return raw["payload"]
    return raw  # legacy format


def save_mv(song_dir: str | Path, data, model: str = "") -> None:
    try:
        (Path(song_dir) / MV_FILENAME).write_text(
            json.dumps({"model": model, "payload": data},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        logger.exception("Failed saving %s in %s", MV_FILENAME, song_dir)


def _esc(t) -> str:
    return html.escape(str(t), quote=True)


def search_links(title: str, artist: str) -> str:
    q = quote(f"{artist} {title} MV")
    return (f'<a href="https://search.bilibili.com/all?keyword={q}" '
            f'target="_blank" rel="noopener">▶ B 站搜 MV</a> · '
            f'<a href="https://www.youtube.com/results?search_query={q}" '
            f'target="_blank" rel="noopener">▶ YouTube</a>')


def render_mv_html(m: MvEggs, title: str, artist: str,
                   verifier=None, label_of: dict | None = None,
                   video: tuple[str, str] | None = None) -> str:
    """verifier: callable(quote, song_hint) -> hit dict | None (evidence.
    QuoteIndex.verify). With it, each lyric_link is checked against the
    library: verified quotes get a ✅ + clickable jump, unverified ⚠️."""
    links = search_links(title, artist)
    head = f'<div class="mv-head">🎬 MV 彩蛋 · {_esc(title)}</div>'
    if not m.known or not m.eggs:
        note = m.caveat or ("AI 对这支 MV 没有可靠了解（也可能它没有"
                            "官方 MV），所以不乱编。可以直接去看：")
        return (f'<div class="mv-card">{head}'
                f'<div class="mv-none">{_esc(note)}</div>'
                f'<div class="mv-foot">{links}</div></div>')
    def _link_html(link: str) -> str:
        if not link:
            return ""
        if verifier is None:
            return f'<span class="mv-link">↔ {_esc(link)}</span>'
        hit = verifier(link, title)
        if hit:
            label = (label_of or {}).get(hit["song_title"], "")
            jump = (f' data-cite-label="{_esc(label)}" '
                    f'data-cite-line="{hit["line_index"]}"' if label else "")
            return (f'<span class="mv-link ev-ok"{jump}>↔ ✅ '
                    f'“{_esc(hit["line_text"])}”——《{_esc(hit["song_title"])}》'
                    f'第 {hit["line_index"] + 1} 行'
                    f'{"（点击跳转）" if label else ""}</span>')
        return (f'<span class="mv-link ev-bad">↔ ⚠️ “{_esc(link)}”'
                f'（未在曲库中找到，此句可能是 AI 编造）</span>')

    rows = []
    for egg in m.eggs:
        detail, link, ts = (tuple(egg) + ("", ""))[:3]
        stamp = ""
        if ts:
            seek = ""
            if video and video[1]:
                from .bilibili import ts_to_seconds
                secs = ts_to_seconds(ts)
                if secs is not None:
                    seek = (f' data-mv-label="{_esc(video[0])}" '
                            f'data-mv-bvid="{_esc(video[1])}" '
                            f'data-mv-t="{secs}"')
            stamp = (f'<span class="mv-ts{" mv-seek" if seek else ""}"'
                     f'{seek} title="'
                     f'{"点击在视频模式中跳到此处" if seek else "画面在 MV 中的位置"}'
                     f'">🎞️ {_esc(ts)}</span>')
        rows.append('<li class="mv-egg">' + stamp + _esc(detail)
                    + _link_html(link) + "</li>")
    rows = "".join(rows)
    director = (f'<div class="mv-meta">导演：{_esc(m.director)}</div>'
                if m.director else "")
    caveat = (f'<div class="mv-caveat">⚖️ {_esc(m.caveat)}</div>'
              if m.caveat else "")
    return (f'<div class="mv-card">{head}{director}'
            f'<ul class="mv-eggs">{rows}</ul>{caveat}'
            f'<div class="mv-foot">⚠️ AI 整理，细节请以原 MV 为准 · '
            f'{links}</div></div>')


MV_CSS = """
/* ── MV easter-egg card ── */
.mv-card {
  padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-card);
}
.mv-head { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.mv-meta { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.mv-eggs { margin: 8px 0 0; padding-left: 18px; }
.mv-egg { font-size: 13px; color: var(--text-primary); line-height: 1.7; margin-bottom: 6px; }
.mv-link { display: block; font-size: 12px; font-style: italic; color: var(--accent); }
.mv-ts {
  display: inline-block; margin-right: 6px; padding: 0 7px;
  border-radius: 999px; font-size: 11.5px; line-height: 1.7;
  background: var(--accent-soft); color: var(--text-primary);
}
.mv-caveat { font-size: 12px; color: var(--text-secondary); margin-top: 8px; }
.mv-none { font-size: 13px; color: var(--text-secondary); margin-top: 6px; line-height: 1.7; }
.mv-foot { font-size: 11.5px; color: var(--text-secondary); margin-top: 10px; }
.mv-foot a { color: var(--accent); text-decoration: none; }
.mv-foot a:hover { text-decoration: underline; }
"""
