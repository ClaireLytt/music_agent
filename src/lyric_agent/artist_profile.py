"""Artist profile sections for the 🗺️ 艺术家图谱 tab.

Three zero-LLM renderers (pure HTML, token-based CSS):
motif fingerprint / per-album echo heat / album timeline.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # heavy intertextuality deps stay lazy (embeddings extra)
    from .intertextuality.echo_map import EchoGraph


from .evidence import cite_jump_attrs, esc_html as _esc  # noqa: E402


_EMPTY = '<div class="chat-empty">{}</div>'


# ── 🏺 母题指纹 ──────────────────────────────────────────────────────────

def render_motif_section(motifs: list[dict], label_of: dict[str, str]) -> str:
    """Motif chips with spread bars and two example lines each.

    `motifs` is archaeology.mine_motifs output; `label_of` maps library song
    titles to radio labels — hits on library songs get the data-cite-label
    jump (same channel as the archaeology report citations).
    """
    if not motifs:
        return _EMPTY.format("母题不足——需要同一意象出现在至少 3 首歌里"
                             "（语料未建或歌曲太少时也会出现）。")
    max_n = max(m["n_songs"] for m in motifs)
    parts = ['<div class="apm-wrap">']
    for m in motifs:
        pct = round(100 * m["n_songs"] / max_n)
        parts.append(
            f'<div class="apm-motif">'
            f'<div class="apm-word">「{_esc(m["word"])}」'
            f'<span class="apm-n">出现于 {m["n_songs"]} 首歌 · '
            f'共 {m["total"]} 次</span></div>'
            f'<div class="apm-bar"><i style="width:{pct}%"></i></div>')
        for h in m["hits"][:2]:
            label = label_of.get(h["song"], "")
            jump = cite_jump_attrs(label, h["line_index"])
            cls = "apm-hit apm-hit-link" if label else "apm-hit"
            parts.append(
                f'<div class="{cls}"{jump}>“{_esc(h["text"])}”'
                f'<span class="apm-src">——《{_esc(h["song"])}》'
                f'· {_esc(h["album"] or "未知专辑")}'
                f'{"（点击跳转）" if label else ""}</span></div>')
        parts.append('</div>')
    parts.append('</div>')
    return "".join(parts)


# ── 🥚 专辑互文热度 ──────────────────────────────────────────────────────

def render_echo_heat(graph: "EchoGraph | None") -> str:
    """Per-album echo totals as a ranked bar list + top-3 pair cards."""
    from .intertextuality.echo_map import _album_colors, _sim_tag
    if graph is None:
        return _EMPTY.format("互文索引未就绪——先运行 build-corpus / embed。")
    if not graph.edges:
        return _EMPTY.format("这位歌手暂无专辑级互文（彩蛋阈值下没有强呼应）。")
    totals: dict[str, int] = {}
    for node in graph.nodes:
        album = node.album or "未知专辑"
        totals[album] = totals.get(album, 0) + node.echo_count
    colors = _album_colors(graph.nodes)
    max_total = max(totals.values()) or 1
    rows = []
    for album, n in sorted(totals.items(), key=lambda kv: -kv[1]):
        pct = round(100 * n / max_total)
        dot = colors.get(album, "#57606a")
        rows.append(
            f'<div class="aph-row"><i class="aph-dot" '
            f'style="background:{dot}"></i>'
            f'<span class="aph-album" title="{_esc(album)}">{_esc(album)}'
            f'</span><span class="aph-bar"><i style="width:{pct}%"></i>'
            f'</span><span class="aph-n">{n}</span></div>')
    cards = []
    for edge in sorted(graph.edges, key=lambda e: -e.count)[:3]:
        p = edge.example
        cards.append(
            f'<div class="aph-pair"><div class="aph-pair-head">'
            f'《{_esc(edge.song_a)}》 ↔ 《{_esc(edge.song_b)}》'
            f' · {edge.count} 处呼应 {_sim_tag(p)}</div>'
            f'<div class="aph-pair-line">“{_esc(p.line_a)}”</div>'
            f'<div class="aph-pair-line">“{_esc(p.line_b)}”</div></div>')
    return ('<div class="aph-wrap">'
            '<div class="ov-section-title">专辑互文热度（彩蛋总数）</div>'
            + "".join(rows)
            + '<div class="ov-section-title" style="margin-top:12px">'
              '最强呼应 Top 3</div>'
            + "".join(cards) + '</div>')


# ── 📅 专辑时间轴 ────────────────────────────────────────────────────────

def _album_year(album: str, year: int) -> int:
    """Metadata year, else Taylor's curated era registry, else 0."""
    if year:
        return year
    from .evolution.engine import ERA_REGISTRY
    want = album.lower()
    for era in ERA_REGISTRY:
        if any(a.lower() == want for a in era.get("albums", [])):
            try:
                return int(era["years"][:4])
            except (ValueError, KeyError):
                return 0
    return 0


def render_album_timeline(songs: list[dict], artist: str) -> str:
    """Horizontal career timeline: albums by year, unknowns clustered last."""
    from .intertextuality.search import artist_matches
    mine = [s for s in songs
            if artist_matches(artist, s.get("artist", ""))]
    if not mine:
        return _EMPTY.format("曲库里还没有这位歌手的歌。")
    albums: dict[str, list[dict]] = {}
    for s in mine:
        albums.setdefault(s.get("album") or "未知专辑", []).append(s)
    entries = []
    for album, items in albums.items():
        year = max(int(s.get("year") or 0) for s in items)
        entries.append((_album_year(album, year), album, len(items)))
    known = sorted([e for e in entries if e[0]], key=lambda e: (e[0], e[1]))
    unknown = sorted([e for e in entries if not e[0]], key=lambda e: e[1])
    cells = []
    for year, album, n in known:
        cells.append(
            f'<div class="ovt-album" title="{_esc(album)} · {n} 首">'
            f'<div class="ovt-year">{year}</div><i class="ovt-dot"></i>'
            f'<div class="ovt-name">{_esc(album)}</div>'
            f'<div class="ovt-n">{n} 首</div></div>')
    if unknown:
        cells.append('<div class="ovt-divider"></div>')
    for _, album, n in unknown:
        cells.append(
            f'<div class="ovt-album ovt-unknown" '
            f'title="{_esc(album)} · {n} 首">'
            f'<div class="ovt-year">年份未知</div><i class="ovt-dot"></i>'
            f'<div class="ovt-name">{_esc(album)}</div>'
            f'<div class="ovt-n">{n} 首</div></div>')
    return ('<div class="ovt-wrap"><div class="ovt-track">'
            + "".join(cells) + '</div></div>')


ARTIST_PROFILE_CSS = """
/* 艺术家图谱 · 母题指纹 */
.apm-wrap { display: flex; flex-direction: column; gap: 12px; }
.apm-motif { padding: 10px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); }
.apm-word { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.apm-n { font-size: 12px; font-weight: 400; color: var(--text-secondary);
  margin-left: 8px; }
.apm-bar { height: 6px; border-radius: 100px; background: var(--accent-soft);
  margin: 6px 0 8px; overflow: hidden; }
.apm-bar i { display: block; height: 100%; border-radius: 100px;
  background: var(--accent); }
.apm-hit { font-size: 13px; color: var(--text-primary); margin: 3px 0; }
.apm-hit-link { cursor: pointer; }
.apm-hit-link:hover { color: var(--accent); }
.apm-src { font-size: 12px; color: var(--text-secondary); margin-left: 6px; }
/* 艺术家图谱 · 专辑互文热度 */
.aph-wrap { display: flex; flex-direction: column; gap: 6px; }
.aph-row { display: flex; align-items: center; gap: 8px; }
.aph-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.aph-album { flex: 0 0 180px; font-size: 13px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aph-bar { flex: 1; height: 8px; border-radius: 100px;
  background: var(--accent-soft); overflow: hidden; }
.aph-bar i { display: block; height: 100%; border-radius: 100px;
  background: var(--accent); }
.aph-n { flex: 0 0 32px; text-align: right; font-size: 12px;
  color: var(--text-secondary); }
.aph-pair { padding: 10px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); margin-top: 6px; }
.aph-pair-head { font-size: 13px; font-weight: 700;
  color: var(--text-primary); margin-bottom: 4px; }
.aph-pair-line { font-size: 13px; color: var(--text-primary); margin: 2px 0; }
/* 艺术家图谱 · 专辑时间轴 */
.ovt-wrap { overflow-x: auto; padding: 6px 2px 10px; }
.ovt-track { display: flex; gap: 18px; align-items: flex-start;
  position: relative; padding-top: 24px; min-width: min-content; }
.ovt-track::before { content: ""; position: absolute; left: 0; right: 0;
  top: 40px; border-top: 2px solid var(--border); }
.ovt-album { flex: 0 0 auto; width: 108px; text-align: center;
  position: relative; }
.ovt-year { font-size: 12px; font-weight: 700; color: var(--accent);
  margin-bottom: 4px; }
.ovt-dot { display: block; width: 12px; height: 12px; border-radius: 50%;
  background: var(--accent); border: 2px solid var(--bg-primary);
  margin: 0 auto 6px; position: relative; z-index: 1; }
.ovt-name { font-size: 13px; font-weight: 600; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ovt-n { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.ovt-divider { flex: 0 0 2px; align-self: stretch;
  border-left: 2px dashed var(--border); }
.ovt-unknown .ovt-year { color: var(--text-secondary); font-weight: 400; }
.ovt-unknown .ovt-dot { background: var(--text-secondary); }
"""
