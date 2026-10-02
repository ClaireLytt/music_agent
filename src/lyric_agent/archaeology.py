"""彩蛋考古报告 (P1): motif mining + evidence-linked narrative.

The machine does the digging (zero-LLM): recurring motif words across an
artist's corpus, with每个母题在每首歌的首个原句命中, grouped by album.
The LLM only narrates the arcs over this mined evidence — it never picks
the quotes, so the report inherits P0's verifiability by construction.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from .dictionary import rank as dict_rank
from .insights import _STOP_EN, _STOP_ZH, _tokenize
from .intertextuality.search import artist_matches

logger = logging.getLogger(__name__)

# motif words must carry imagery, not glue — extra blocklist on top of the
# insights stopwords: generic pop-lyric words that are topics, not motifs,
# plus traditional-Chinese function words (the corpus keeps原文繁体)
_FLAT = {
    # lyric fillers (frequency rank can't catch these)
    "yeah", "gonna", "wanna", "gotta", "cause", "ooh", "whoa", "woah",
    "mmm", "nah", "hey", "til", "till", "mine", "yours", "ours", "babe",
    "outta", "lovin", "livin", "ain't",
    # chinese function/generic words, simplified + traditional (the corpus
    # keeps原文繁体; jieba's freq table is simplified-only so a rank filter
    # does not work for CJK)
    "身边", "知道", "没有", "不是", "现在", "还是", "可以", "因为",
    "已经", "怎么", "什么", "我们", "你们", "他们", "自己", "一起",
    "一直", "不会", "不要", "这样", "那样", "时候", "世界", "爱情",
    "離開", "沒有", "現在", "還是", "可以", "因為", "已經", "怎麼",
    "什麼", "我們", "你們", "他們", "這樣", "那樣", "時候", "愛情",
    "知道", "身邊",
}

# english tokens below this corpus-frequency rank are everyday vocabulary,
# not motifs (rain=1491 in, town=433 out — see dictionary.rank)
_RANK_MIN = 1200


def mine_motifs(corpus, artist: str, top_n: int = 6,
                min_songs: int = 3) -> list[dict]:
    """Top recurring motifs for an artist, with one quote per song.

    corpus: iterable of objects with .song/.album/.line_index/.text/.artist
    (the intertextuality corpus). Returns
    [{word, n_songs, total, hits: [{song, album, line_index, text}]}],
    ranked by song-spread then total count.
    """
    counts: Counter = Counter()
    songs_of: dict[str, set[str]] = defaultdict(set)
    first_hit: dict[tuple[str, str], dict] = {}
    for row in corpus:
        if not artist_matches(artist, row.artist):
            continue
        for tok in set(_tokenize(row.text)):
            if (tok in _STOP_EN or tok in _STOP_ZH or tok in _FLAT
                    or len(tok) < 3 and not re.search(r"[一-鿿]", tok)):
                continue
            if re.match(r"^[a-z']+$", tok):
                r = dict_rank(tok)
                if 0 < r < _RANK_MIN:
                    continue  # everyday vocabulary, not a motif
            counts[tok] += 1
            songs_of[tok].add(row.song)
            first_hit.setdefault((tok, row.song), {
                "song": row.song, "album": row.album,
                "line_index": row.line_index, "text": row.text,
            })
    def _score(w: str) -> float:
        # spread x rarity: a motif should recur across songs AND be a
        # distinctive word (rank capped so unranked/rare doesn't dominate)
        r = dict_rank(w) if re.match(r"^[a-z']+$", w) else 0
        return len(songs_of[w]) * min(r or 4000, 6000)

    ranked = sorted(
        (w for w in counts if len(songs_of[w]) >= min_songs),
        key=lambda w: (-_score(w), -counts[w], w))
    motifs = []
    for w in ranked[:top_n]:
        hits = sorted((first_hit[(w, s)] for s in songs_of[w]),
                      key=lambda h: (h["album"], h["song"]))
        motifs.append({"word": w, "n_songs": len(songs_of[w]),
                       "total": counts[w], "hits": hits})
    return motifs


# ── report cache ────────────────────────────────────────────

def _slug(artist: str) -> str:
    return re.sub(r"[^\w]+", "_", artist.lower()).strip("_") or "artist"


def report_path(reports_dir: str | Path, artist: str, model: str) -> Path:
    model_slug = re.sub(r"[^\w]+", "_", model)[:40]
    return Path(reports_dir) / f"{_slug(artist)}__{model_slug}.json"


def load_report(reports_dir: str | Path, artist: str, model: str) -> dict | None:
    try:
        return json.loads(report_path(reports_dir, artist, model)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_report(reports_dir: str | Path, artist: str, model: str,
                data: dict) -> None:
    p = report_path(reports_dir, artist, model)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")


# ── LLM prompt ──────────────────────────────────────────────

def report_messages(artist: str, motifs: list[dict]) -> tuple[str, str]:
    """(system, user) for the narrative pass. The LLM narrates arcs over
    mined evidence; it must not invent quotes (we never render its quotes)."""
    lines = []
    for m in motifs:
        lines.append(f"母题「{m['word']}」出现在 {m['n_songs']} 首歌：")
        for h in m["hits"]:
            lines.append(f"  - 《{h['song']}》(专辑 {h['album'] or '未知'})："
                         f"“{h['text']}”")
    system = ("你是一位音乐考古学家，研究歌手如何在多年创作中反复埋藏同一个"
              "意象。只基于用户提供的证据写作，不得引入列表之外的歌曲或歌词。"
              "严格输出 JSON。")
    user = (
        f"歌手：{artist}\n以下是机器从全部歌词中挖掘出的母题证据：\n\n"
        + "\n".join(lines)
        + "\n\n请输出 JSON（不要多余文字）：\n"
        '{"overview": "2-3 句总述这位歌手的母题版图",\n'
        ' "motifs": [{"word": "母题词（必须来自上面的列表）",\n'
        '   "arc": "2-3 句叙事弧线：这个意象如何跨专辑演化/呼应"}]}\n'
        "motifs 覆盖上面每个母题各一条，arc 用简体中文。"
    )
    return system, user


def parse_report(raw: str) -> dict | None:
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (raw or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    arcs = {}
    for m in data.get("motifs") or []:
        if isinstance(m, dict) and m.get("word"):
            arcs[str(m["word"]).strip()] = str(m.get("arc") or "").strip()
    return {"overview": str(data.get("overview") or "").strip(), "arcs": arcs}


# ── rendering ───────────────────────────────────────────────

def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_report(artist: str, motifs: list[dict], narrative: dict,
                  verifier=None, label_of: dict | None = None) -> str:
    """HTML archaeology report. Quotes are machine-mined (verified by
    construction); verifier/label_of add click-to-jump for library songs."""
    if not motifs:
        return ('<div class="chat-empty">这位歌手的语料不足以挖掘母题'
                '（每个母题至少要出现在 3 首歌里）。</div>')
    label_of = label_of or {}
    parts = [f'<div class="arch-report"><div class="arch-head">🏺 '
             f'{_esc(artist)} · 彩蛋考古报告</div>']
    if narrative.get("overview"):
        parts.append(f'<div class="arch-overview">'
                     f'{_esc(narrative["overview"])}</div>')
    for m in motifs:
        arc = narrative.get("arcs", {}).get(m["word"], "")
        parts.append(f'<div class="arch-motif">'
                     f'<div class="arch-word">「{_esc(m["word"])}」'
                     f'<span class="arch-n">出现于 {m["n_songs"]} 首歌 · '
                     f'共 {m["total"]} 次</span></div>')
        if arc:
            parts.append(f'<div class="arch-arc">{_esc(arc)}</div>')
        for h in m["hits"]:
            hit = verifier(h["text"], h["song"]) if verifier else None
            if hit:
                label = label_of.get(hit["song_title"], "")
                jump = (f' data-cite-label="{_esc(label)}" '
                        f'data-cite-line="{hit["line_index"]}"'
                        if label else "")
                parts.append(
                    f'<div class="arch-hit ev-ok"{jump}>✅ '
                    f'“{_esc(hit["line_text"])}”'
                    f'<span class="ev-src">——《{_esc(h["song"])}》'
                    f'· {_esc(h["album"] or "未知专辑")}'
                    f'{"（点击跳转）" if label else ""}</span></div>')
            else:
                parts.append(
                    f'<div class="arch-hit">“{_esc(h["text"])}”'
                    f'<span class="ev-src">——《{_esc(h["song"])}》'
                    f'· {_esc(h["album"] or "未知专辑")}</span></div>')
        parts.append("</div>")
    parts.append('<div class="arch-foot">母题与引句由机器全库挖掘，'
                 '叙事由 AI 基于以上证据生成 · ✅ = 可点击跳转到原句</div>')
    parts.append("</div>")
    return "".join(parts)
