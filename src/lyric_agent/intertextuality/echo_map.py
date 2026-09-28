"""Artist-level easter-egg network map (🥚 彩蛋地图 tab).

Builds a song-to-song echo graph from the pre-computed corpus embeddings
(nodes = songs, edges = pairs of lyric lines whose similarity clears the
echo threshold) and renders it as a pure server-side SVG — same approach
as the evolution map, no external JS libraries.
"""

from __future__ import annotations

import html
import math
import re
import zlib
from dataclasses import dataclass, field

import numpy as np

from ..config import (
    DEFAULT_ECHO_MAP_MAX_NODES,
    DEFAULT_ECHO_MIN_SIMILARITY,
    DEFAULT_ECHO_MIN_SIMILARITY_CJK,
)
from .corpus import CorpusLine
from .search import (
    NEAR_IDENTICAL_SIMILARITY,
    artist_matches,
    cjk_pair_anchored,
    is_cjk_text,
    normalize_rows,
    primary_artist,
)

# strongest edges drawn on the map; beyond this the circle becomes a hairball
MAX_EDGES = 60
# example echo pairs listed under the map
TOP_PAIRS_SHOWN = 5
# two songs sharing this fraction of identical lines are the same recording
# under two titles (corpus pollution), not an intertextual pair
DUPLICATE_WORK_OVERLAP = 0.5

# strip bracketed suffixes so "All Too Well (10 Minute Version)" and
# "All Too Well" count as the same work, not as an echo pair
_BRACKET_RE = re.compile(r"[（(\[【].*?[)）\]】]")

# pure filler lines ("oh oh", "la la la", "yeah…") echo across half the
# discography and only add noise to the map
_FILLER_VOCAB = {
    "oh", "ooh", "ah", "aah", "la", "na", "da", "ba", "yeah", "yea", "hey",
    "uh", "huh", "whoa", "woah", "ey", "eh", "mm", "mmm", "hmm", "hm", "oo",
    "o", "ha", "ohh", "ay", "ai", "yo",
}
_WORD_RE = re.compile(r"[a-z']+")


def base_title(title: str) -> str:
    """Normalized work identity: lowercase, bracketed suffixes removed."""
    return _BRACKET_RE.sub("", title or "").strip().lower()


def is_filler(text: str) -> bool:
    """True for lines made only of vocalization filler ("Oh, oh, oh-oh")."""
    tokens = _WORD_RE.findall((text or "").lower())
    return bool(tokens) and all(t.strip("'") in _FILLER_VOCAB for t in tokens)


@dataclass
class EchoPair:
    """One concrete echoing line pair (the strongest example on an edge)."""
    line_a: str
    line_b: str
    similarity: float


@dataclass
class EchoEdge:
    song_a: str
    song_b: str
    count: int
    example: EchoPair


@dataclass
class EchoNode:
    song: str
    album: str
    echo_count: int  # sum of edge counts touching this song
    artist: str = ""
    in_library: bool = False


@dataclass
class EchoGraph:
    artist: str  # display name, or "" for the cross-artist mode
    threshold: float
    song_total: int  # corpus songs scanned (before node capping)
    cross_artist: bool = False
    nodes: list[EchoNode] = field(default_factory=list)
    edges: list[EchoEdge] = field(default_factory=list)


def build_echo_graph(
    embeddings: np.ndarray,
    corpus: list[CorpusLine],
    artist: str | None,
    min_similarity: float = DEFAULT_ECHO_MIN_SIMILARITY,
    min_similarity_cjk: float = DEFAULT_ECHO_MIN_SIMILARITY_CJK,
    max_nodes: int = DEFAULT_ECHO_MAP_MAX_NODES,
    library_titles: set[str] | None = None,
) -> EchoGraph:
    """Echoing song pairs, capped to the busiest songs.

    artist given  — self-intertextuality within that artist's corpus songs.
    artist None   — cross-artist mode: only pairs BETWEEN different artists
                    (references / homages), scanning the whole corpus.
    """
    cross = artist is None
    rows = [
        i for i, line in enumerate(corpus)
        if (cross or artist_matches(artist, line.artist))
        and not is_filler(line.text)
    ]

    # song identity: (title, primary artist) — cross-artist mode may hold
    # same-titled songs by different artists
    def skey(line: CorpusLine) -> tuple[str, str]:
        return (line.song, primary_artist(line.artist))

    song_lines: dict[tuple[str, str], int] = {}
    song_artist: dict[tuple[str, str], str] = {}
    for i in rows:
        k = skey(corpus[i])
        song_lines[k] = song_lines.get(k, 0) + 1
        song_artist.setdefault(k, corpus[i].artist)
    graph = EchoGraph(
        artist="" if cross else artist, threshold=min_similarity,
        song_total=len(song_lines), cross_artist=cross)
    if len(song_lines) < 2:
        return graph

    emb = normalize_rows(embeddings[rows])
    sims = emb @ emb.T
    # per-pair threshold: the stricter CJK cutoff when either line is CJK
    line_thr = np.array([
        min_similarity_cjk if is_cjk_text(corpus[i].text) else min_similarity
        for i in rows
    ])
    pairs = np.argwhere(np.triu(sims >= np.maximum.outer(line_thr, line_thr), k=1))

    # aggregate line pairs into song-pair edges, keeping the strongest example
    edge_count: dict[tuple, int] = {}
    edge_example: dict[tuple, EchoPair] = {}
    edge_identical: dict[tuple, int] = {}
    for a, b in pairs:
        la, lb = corpus[rows[int(a)]], corpus[rows[int(b)]]
        ka, kb = skey(la), skey(lb)
        if ka == kb or base_title(la.song) == base_title(lb.song):
            continue  # same work (re-recording / live version), not an echo
        if cross and ka[1] == kb[1]:
            continue  # cross-artist mode: same-artist pairs excluded
        key = tuple(sorted((ka, kb)))
        sim = float(sims[a, b])
        if sim > NEAR_IDENTICAL_SIMILARITY and la.text != lb.text:
            continue  # encoder collapse (see NEAR_IDENTICAL_SIMILARITY)
        if (is_cjk_text(la.text) or is_cjk_text(lb.text)) \
                and not cjk_pair_anchored(la.text, lb.text):
            continue  # CJK echoes must share a verbatim phrase (see search.py)
        edge_count[key] = edge_count.get(key, 0) + 1
        if la.text == lb.text:
            edge_identical[key] = edge_identical.get(key, 0) + 1
        best = edge_example.get(key)
        if best is None or sim > best.similarity:
            if key[0] == ka:
                pair = EchoPair(la.text, lb.text, round(sim, 3))
            else:
                pair = EchoPair(lb.text, la.text, round(sim, 3))
            edge_example[key] = pair

    # duplicate-work guard: the same recording indexed under two titles
    # (or a full cover) shares most lines verbatim — not an intertextual echo
    for key in list(edge_count):
        smaller = min(song_lines[key[0]], song_lines[key[1]])
        if edge_identical.get(key, 0) >= DUPLICATE_WORK_OVERLAP * smaller:
            del edge_count[key]

    if not edge_count:
        return graph

    degree: dict[tuple[str, str], int] = {}
    for (ka, kb), n in edge_count.items():
        degree[ka] = degree.get(ka, 0) + n
        degree[kb] = degree.get(kb, 0) + n
    kept_songs = set(sorted(degree, key=degree.get, reverse=True)[:max_nodes])

    # node/edge display label; unique even for same-titled songs in cross mode
    def label(k: tuple[str, str]) -> str:
        return f"{k[0]} · {song_artist.get(k, '')}" if cross else k[0]

    edges = [
        EchoEdge(label(ka), label(kb), n, edge_example[(ka, kb)])
        for (ka, kb), n in edge_count.items()
        if ka in kept_songs and kb in kept_songs
    ]
    edges.sort(key=lambda e: e.count, reverse=True)
    graph.edges = edges[:MAX_EDGES]

    # recompute degrees over the edges actually drawn so displayed numbers add up
    shown_degree: dict[str, int] = {}
    for e in graph.edges:
        shown_degree[e.song_a] = shown_degree.get(e.song_a, 0) + e.count
        shown_degree[e.song_b] = shown_degree.get(e.song_b, 0) + e.count
    albums: dict[str, str] = {}
    titles: dict[str, tuple[str, str]] = {}
    for i in rows:
        k = skey(corpus[i])
        albums.setdefault(label(k), corpus[i].album)
        titles.setdefault(label(k), k)
    library_titles = {t.lower() for t in (library_titles or set())}
    graph.nodes = sorted(
        (EchoNode(song=lb, album=albums.get(lb, ""), echo_count=n,
                  artist=song_artist.get(titles.get(lb, ("", "")), ""),
                  in_library=titles.get(lb, ("",))[0].lower() in library_titles)
         for lb, n in shown_degree.items()),
        key=lambda nd: (nd.album, nd.song),
    )
    return graph


# ── SVG rendering ─────────────────────────────────────────

_SVG_W, _SVG_H = 860, 620
_RING_R = 235
_LABEL_MAX_CHARS = 14

_NODE_PALETTE = [
    "#0969da", "#8250df", "#bf3989", "#cf222e", "#bc4c00",
    "#4d2d00", "#1a7f37", "#0550ae", "#6639ba", "#a40e26",
]


def _esc(s: str) -> str:
    return html.escape(str(s))


def _short(title: str) -> str:
    return title if len(title) <= _LABEL_MAX_CHARS else \
        title[: _LABEL_MAX_CHARS - 1] + "…"


def _album_color(album: str) -> str:
    # crc32, not hash(): str hashing is salted per process and would
    # reshuffle all the colors on every server restart
    return _NODE_PALETTE[zlib.crc32(album.encode("utf-8")) % len(_NODE_PALETTE)]


def render_echo_map_html(graph: EchoGraph) -> str:
    """Circular network SVG + a list of the strongest echo pairs."""
    scope = _esc(graph.artist) if graph.artist else "跨歌手模式（全部歌手）"
    if graph.song_total < 2:
        return ('<div class="chat-empty">语料库中该范围的歌曲不足 2 首，'
                '无法构建彩蛋网络。</div>')
    if not graph.edges:
        return (f'<div class="chat-empty">在 {scope} 的 '
                f'{graph.song_total} 首歌曲之间未发现相似度 ≥ '
                f'{graph.threshold} 的彩蛋呼应。</div>')

    n = len(graph.nodes)
    # small graphs: shrink the ring (and the canvas) and lay a pair out
    # horizontally, or two nodes end up at the far top/bottom of a huge
    # circle joined by one long vertical line
    ring = min(_RING_R, 70.0 + 28.0 * n)
    svg_h = min(_SVG_H, int(2 * ring) + 160)
    cx, cy = _SVG_W / 2, svg_h / 2
    start = 0.0 if n == 2 else -math.pi / 2
    pos: dict[str, tuple[float, float]] = {}
    for k, node in enumerate(graph.nodes):
        angle = start + 2 * math.pi * k / n
        pos[node.song] = (cx + ring * math.cos(angle),
                          cy + ring * math.sin(angle))

    max_count = max(e.count for e in graph.edges)
    edge_parts = []
    for e in graph.edges:
        (x1, y1), (x2, y2) = pos[e.song_a], pos[e.song_b]
        # bezier control point pulled toward the center keeps chords readable
        qx = cx + ((x1 + x2) / 2 - cx) * 0.35
        qy = cy + ((y1 + y2) / 2 - cy) * 0.35
        width = 1.0 + 3.0 * e.count / max_count
        tip = (f'《{e.song_a}》↔《{e.song_b}》{e.count} 处呼应\n'
               f'“{e.example.line_a}” ↔ “{e.example.line_b}”'
               f'（相似度 {e.example.similarity}）')
        edge_parts.append(
            f'<path d="M{x1:.1f},{y1:.1f} Q{qx:.1f},{qy:.1f} {x2:.1f},{y2:.1f}" '
            f'class="egg-edge" stroke-width="{width:.1f}">'
            f'<title>{_esc(tip)}</title></path>'
        )

    node_parts = []
    for node in graph.nodes:
        x, y = pos[node.song]
        r = 6 + 2.2 * math.sqrt(node.echo_count)
        anchor = "start" if x >= cx else "end"
        lx = x + (r + 6 if x >= cx else -(r + 6))
        ring = ' class="egg-node in-library"' if node.in_library \
            else ' class="egg-node"'
        artist_part = f' · {node.artist}' if graph.cross_artist and node.artist else ""
        tip = (f'《{node.song}》{artist_part} · {node.album or "未知专辑"}'
               f' · {node.echo_count} 处呼应')
        if node.in_library:
            tip += "（在你的歌曲列表中）"
        node_parts.append(
            f'<g{ring}><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{_album_color(node.album)}">'
            f'<title>{_esc(tip)}</title></circle>'
            f'<text x="{lx:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
            f'class="egg-label">{_esc(_short(node.song))}'
            f'<title>{_esc(tip)}</title></text></g>'
        )

    total_pairs = sum(e.count for e in graph.edges)
    summary = (
        f'<div class="egg-summary">🥚 {scope} · '
        f'{len(graph.nodes)} 首歌曲间共 {total_pairs} 处彩蛋呼应'
        f'（相似度 ≥ {graph.threshold}，语料库共 {graph.song_total} 首，'
        '图中为存在呼应的歌曲，呼应最密集者优先）'
        '· 悬停节点或连线查看具体歌词</div>'
    )

    top_items = []
    for e in graph.edges[:TOP_PAIRS_SHOWN]:
        top_items.append(
            '<div class="egg-pair">'
            f'<div class="egg-pair-songs">《{_esc(e.song_a)}》↔'
            f'《{_esc(e.song_b)}》 · {e.count} 处呼应</div>'
            f'<div class="egg-pair-lines">“{_esc(e.example.line_a)}” ↔ '
            f'“{_esc(e.example.line_b)}”'
            f'<span class="egg-pair-sim">{e.example.similarity}</span></div>'
            '</div>'
        )
    top_html = ('<div class="egg-pairs"><div class="egg-pairs-title">'
                '🔗 呼应最强的歌曲对</div>' + "".join(top_items) + '</div>')

    return (
        summary
        + f'<svg viewBox="0 0 {_SVG_W} {svg_h}" class="egg-svg" role="img">'
        + "".join(edge_parts) + "".join(node_parts) + '</svg>'
        + top_html
    )


ECHO_MAP_CSS = """
.egg-summary {
  font-size: 13px; color: var(--text-secondary); padding: 8px 12px;
  background: var(--bg-card); border-radius: 8px; margin-bottom: 8px;
}
.egg-svg { width: 100%; height: auto; display: block; }
.egg-edge {
  fill: none; stroke: var(--accent); stroke-opacity: 0.3;
  transition: stroke-opacity 0.15s ease;
}
.egg-edge:hover { stroke-opacity: 0.9; }
.egg-node circle { stroke: #ffffff; stroke-width: 1.5; cursor: default; }
.egg-node.in-library circle { stroke: #d4a72c; stroke-width: 3; }
.egg-label { font-size: 12px; fill: var(--text-primary); }
.egg-node.in-library .egg-label { font-weight: 700; }
.egg-pairs { margin-top: 10px; }
.egg-pairs-title { font-size: 13px; font-weight: 700; margin-bottom: 6px; }
.egg-pair {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); margin-bottom: 6px;
}
.egg-pair-songs { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.egg-pair-lines {
  font-size: 12px; font-style: italic; color: var(--text-secondary); margin-top: 3px;
}
.egg-pair-sim {
  font-style: normal; margin-left: 8px; font-size: 11px; color: var(--accent);
}

/* imagery trace timeline (意象追踪) */
.img-timeline { border-left: 3px solid var(--accent-soft); padding-left: 16px; }
.img-album { margin-bottom: 14px; }
.img-album-name {
  font-size: 14px; font-weight: 700; color: var(--text-primary);
  margin-bottom: 6px; position: relative;
}
.img-album-name::before {
  content: ""; position: absolute; left: -22px; top: 5px; width: 9px; height: 9px;
  border-radius: 50%; background: var(--accent);
}
.img-hit {
  padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); margin-bottom: 5px;
}
.img-line { font-size: 13px; font-style: italic; color: var(--text-primary); }
.img-meta { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.img-tag {
  font-style: normal; margin-left: 8px; font-size: 10px; padding: 1px 6px;
  border-radius: 8px; background: var(--accent-soft); color: var(--accent);
}
.img-tag.kw { background: rgba(212,167,44,0.15); color: #9a6700; }

/* focus (star) view */
.egg-focus { fill: #d4a72c; stroke: #ffffff; stroke-width: 2.5; }
.egg-focus-label { font-weight: 700; font-size: 14px; }
.egg-spoke { stroke: #ffffff; stroke-width: 1.5; }
.egg-badge { fill: var(--accent); opacity: 0.85; }
.egg-badge-text { fill: #ffffff; font-size: 11px; font-weight: 700; }
.egg-pair-quote {
  font-size: 12.5px; font-style: italic; color: var(--text-secondary); margin-top: 3px;
}
"""


# ── Imagery timeline rendering (意象追踪) ──────────────────

def render_imagery_timeline(
    query: str,
    hits: list,  # list[ImageryHit]
    album_order: dict[str, int] | None = None,
    artist: str = "",
) -> str:
    """Group traced imagery hits by album and render a vertical timeline.

    album_order maps album (lowercase) → position; unknown albums follow,
    alphabetically. Missing albums are grouped under 未知专辑.
    """
    query = (query or "").strip()
    if not query:
        return '<div class="chat-empty">输入一个意象（如：雨、scarf、童年），追踪它在整个曲库里的演变。</div>'
    scope = _esc(artist) if artist else "全部歌手"
    if not hits:
        return (f'<div class="chat-empty">在 {scope} 的语料库中'
                f'没有找到与「{_esc(query)}」相关的歌词。</div>')

    album_order = album_order or {}
    groups: dict[str, list] = {}
    for h in hits:
        groups.setdefault(h.album or "未知专辑", []).append(h)

    def order(album: str) -> tuple:
        return (album_order.get(album.lower(), 10**6), album.lower())

    blocks = []
    for album in sorted(groups, key=order):
        items = []
        for h in sorted(groups[album], key=lambda x: -x.similarity):
            tag = ('<span class="img-tag kw">原词</span>' if h.keyword
                   else f'<span class="img-tag">≈{h.similarity}</span>')
            items.append(
                '<div class="img-hit">'
                f'<div class="img-line">“{_esc(h.line)}”{tag}</div>'
                f'<div class="img-meta">《{_esc(h.song)}》'
                f'{" · " + _esc(h.artist) if not artist and h.artist else ""}'
                '</div></div>'
            )
        blocks.append(
            '<div class="img-album">'
            f'<div class="img-album-name">💿 {_esc(album)}</div>'
            + "".join(items) + '</div>'
        )
    head = (f'<div class="egg-summary">🔍 意象「{_esc(query)}」 · {scope} · '
            f'共 {len(hits)} 处（按专辑分组，「原词」为字面命中，'
            '「≈」为语义相近）</div>')
    return head + '<div class="img-timeline">' + "".join(blocks) + '</div>'


# ── Focus (star) view: one song and its echo partners ─────

_FOCUS_W, _FOCUS_H = 860, 430


def focus_choices(graph: EchoGraph) -> list[str]:
    """Songs offered in the 聚焦 dropdown, busiest first."""
    return [n.song for n in
            sorted(graph.nodes, key=lambda n: -n.echo_count)]


def render_focus_html(graph: EchoGraph, focus: str) -> str:
    """Simple star view: the focus song in the middle, partners around it,
    and every pair's lyric quotes laid out as cards — no hovering needed."""
    scope = _esc(graph.artist) if graph.artist else "跨歌手模式（全部歌手）"
    if graph.song_total < 2:
        return ('<div class="chat-empty">语料库中该范围的歌曲不足 2 首，'
                '无法构建彩蛋网络。</div>')
    if not graph.edges:
        return (f'<div class="chat-empty">在 {scope} 的 '
                f'{graph.song_total} 首歌曲之间未发现相似度 ≥ '
                f'{graph.threshold} 的彩蛋呼应。</div>')
    if not focus:
        return '<div class="chat-empty">请选择一首歌曲进行聚焦。</div>'

    # edges touching the focus song, partner first
    spokes: list[tuple[str, EchoEdge]] = []
    for e in graph.edges:
        if e.song_a == focus:
            spokes.append((e.song_b, e))
        elif e.song_b == focus:
            spokes.append((e.song_a, e))
    if not spokes:
        return (f'<div class="chat-empty">《{_esc(focus)}》'
                '在当前范围内没有检索到彩蛋呼应，换一首试试。</div>')
    spokes.sort(key=lambda s: -s[1].count)

    cx, cy = _FOCUS_W / 2, _FOCUS_H / 2
    ring = 150.0
    n = len(spokes)
    max_count = max(e.count for _, e in spokes)
    parts = []
    for k, (partner, e) in enumerate(spokes):
        angle = -math.pi / 2 + 2 * math.pi * k / n
        x = cx + ring * math.cos(angle)
        y = cy + ring * math.sin(angle)
        width = 1.5 + 3.5 * e.count / max_count
        parts.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'class="egg-edge" stroke-width="{width:.1f}"/>'
        )
        # count badge on the spoke
        bx, by = cx + (x - cx) * 0.55, cy + (y - cy) * 0.55
        parts.append(
            f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="11" class="egg-badge"/>'
            f'<text x="{bx:.1f}" y="{by + 4:.1f}" text-anchor="middle" '
            f'class="egg-badge-text">{e.count}</text>'
        )
        anchor = "start" if x >= cx else "end"
        lx = x + (14 if x >= cx else -14)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" '
            f'fill="{_album_color(partner)}" class="egg-spoke"/>'
            f'<text x="{lx:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
            f'class="egg-label">{_esc(_short(partner))}</text>'
        )
    # focus node on top
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="16" class="egg-focus"/>'
        f'<text x="{cx:.1f}" y="{cy - 26:.1f}" text-anchor="middle" '
        f'class="egg-label egg-focus-label">{_esc(_short(focus))}</text>'
    )

    total = sum(e.count for _, e in spokes)
    summary = (
        f'<div class="egg-summary">🥚 {scope} · 聚焦《{_esc(focus)}》：'
        f'与 {n} 首歌共 {total} 处彩蛋呼应 · 下方直接展示每对歌词</div>'
    )

    cards = []
    for partner, e in spokes:
        # quote order: focus song's line first
        la, lb = (e.example.line_a, e.example.line_b) \
            if e.song_a == focus else (e.example.line_b, e.example.line_a)
        cards.append(
            '<div class="egg-pair">'
            f'<div class="egg-pair-songs">↔ 《{_esc(partner)}》 · '
            f'{e.count} 处呼应</div>'
            f'<div class="egg-pair-quote">本歌：“{_esc(la)}”</div>'
            f'<div class="egg-pair-quote">对方：“{_esc(lb)}”'
            f'<span class="egg-pair-sim">{e.example.similarity}</span></div>'
            '</div>'
        )

    return (
        summary
        + f'<svg viewBox="0 0 {_FOCUS_W} {_FOCUS_H}" class="egg-svg" role="img">'
        + "".join(parts) + '</svg>'
        + '<div class="egg-pairs">' + "".join(cards) + '</div>'
    )
