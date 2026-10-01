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
    is_cjk_text,
    normalize_rows,
    primary_artist,
)

# strongest edges drawn on the map; beyond this the circle becomes a hairball
MAX_EDGES = 60
MAX_EDGE_EXAMPLES = 10  # distinct pairs kept per edge

_NORM_LINE_RE = re.compile(r"[\W_]+", re.UNICODE)


def norm_line(text: str) -> str:
    """Casefolded, punctuation-free form for duplicate detection.

    Leading/trailing vocalization filler is stripped first, so
    "Oh, you're the one I want" and "Ah-ah, you're the one I want"
    normalize to the same core (covers() then absorbs remaining
    prefix/suffix variants by containment). CJK lines have no such
    filler tokens and keep the plain punctuation-free form."""
    lowered = (text or "").casefold()
    tokens = _WORD_RE.findall(lowered)
    while tokens and tokens[0].strip("'") in _FILLER_VOCAB:
        tokens.pop(0)
    while tokens and tokens[-1].strip("'") in _FILLER_VOCAB:
        tokens.pop()
    core = "".join(tokens)
    # _WORD_RE is latin-only: CJK (or all-filler) lines fall back to the
    # plain normalized form so they never collapse to ""
    return core or _NORM_LINE_RE.sub("", lowered)


def covers(a: str, b: str) -> bool:
    """True when two normalized lines are the same lyric for display
    purposes: equal, or one contains the other (ad-lib prefixes like
    "Oh, ..." / "Ah-ah, darling, ..." wrap the same hook line)."""
    return bool(a) and bool(b) and (a == b or a in b or b in a)
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


_CREDIT_RE = re.compile(
    r"^[\(（\[【\s]*(词|曲|作词|作曲|編曲|编曲|监制|監製|製作|制作|混音|和声|"
    r"詞|作詞|lyrics?\s+by|composed\s+by|produced\s+by)\s*[:：]",
    re.IGNORECASE)


def is_filler(text: str) -> bool:
    """True for vocalization filler ("Oh, oh, oh-oh") and credit lines."""
    if _CREDIT_RE.match((text or "").strip()):
        return True  # "词：徐若瑄" etc. — embedded credits, not lyrics
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
    # strongest examples (leading one prefers distinct wording), max 3 —
    # the detective's evidence dossier reads these
    examples: list[EchoPair] = field(default_factory=list)


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
    edge_example_distinct: dict[tuple, EchoPair] = {}
    edge_pairs: dict[tuple, list[EchoPair]] = {}
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
        # NOTE: the old cjk_pair_anchored guard (verbatim shared phrase)
        # is gone: it existed because the English-only MiniLM made CJK
        # similarities meaningless, and it killed legitimate paraphrase
        # echoes (plus every traditional/simplified pair). With the
        # multilingual model the stricter *_CJK threshold is the only
        # CJK-specific gate.
        edge_count[key] = edge_count.get(key, 0) + 1
        if la.text == lb.text:
            edge_identical[key] = edge_identical.get(key, 0) + 1
        if key[0] == ka:
            pair = EchoPair(la.text, lb.text, round(sim, 3))
        else:
            pair = EchoPair(lb.text, la.text, round(sim, 3))
        edge_pairs.setdefault(key, []).append(pair)
        best = edge_example.get(key)
        if best is None or sim > best.similarity:
            edge_example[key] = pair
        # "the same line sung twice" makes a boring showcase; prefer the
        # strongest pair with *different* wording when the edge has one
        if la.text.strip().casefold() != lb.text.strip().casefold():
            best = edge_example_distinct.get(key)
            if best is None or sim > best.similarity:
                edge_example_distinct[key] = pair

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

    def top_examples(key: tuple) -> list[EchoPair]:
        """Strongest pairs with NO repeated lyric on either side: a line
        that already appears (or is an ad-lib variant of one that does)
        is skipped, so the expandable list shows variety, not the same
        hook sung eight ways."""
        lead = edge_example_distinct.get(key) or edge_example[key]
        seen_a = [norm_line(lead.line_a)]
        seen_b = [norm_line(lead.line_b)]
        out = [lead]
        for p in sorted(edge_pairs[key], key=lambda p: p.similarity,
                        reverse=True):
            na, nb = norm_line(p.line_a), norm_line(p.line_b)
            if any(covers(na, s) for s in seen_a) \
                    or any(covers(nb, s) for s in seen_b):
                continue
            seen_a.append(na)
            seen_b.append(nb)
            out.append(p)
            if len(out) == MAX_EDGE_EXAMPLES:
                break
        return out

    edges = [
        EchoEdge(label(ka), label(kb), n,
                 edge_example_distinct.get((ka, kb)) or edge_example[(ka, kb)],
                 top_examples((ka, kb)))
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
_LABEL_MAX_UNITS = 26  # label width budget; CJK glyphs count double
# strongest pairs drawn in the accent color; the rest recede to grey
_TOP_EDGES_HIGHLIGHT = 3

# visually distinct hues only — album colors are assigned sequentially per
# graph (see _album_colors), so near-duplicate shades would defeat the legend
_NODE_PALETTE = [
    "#0969da", "#bc4c00", "#1a7f37", "#cf222e", "#8250df",
    "#bf3989", "#1b7c8c", "#9a6700", "#57606a", "#6e5494",
]


def _esc(s: str) -> str:
    return html.escape(str(s))


def _short(title: str) -> str:
    """Truncate for SVG labels; CJK glyphs are twice as wide as latin."""
    units = 0
    for i, ch in enumerate(title):
        units += 2 if ord(ch) > 0x2E7F else 1
        if units > _LABEL_MAX_UNITS:
            return title[:i] + "…"
    return title


def _album_colors(nodes: list[EchoNode]) -> dict[str, str]:
    """Album → color for one graph, in node order (nodes sort by album).

    Sequential assignment instead of hashing: within one map no two albums
    share a color until the palette runs out, and the on-page legend
    (_album_legend) makes the mapping explicit.
    """
    colors: dict[str, str] = {}
    for node in nodes:
        album = node.album or "未知专辑"
        if album not in colors:
            colors[album] = _NODE_PALETTE[len(colors) % len(_NODE_PALETTE)]
    return colors


def _album_legend(colors: dict[str, str]) -> str:
    """Color legend chips shown under the SVG (the「颜色 = 专辑」key)."""
    chips = "".join(
        f'<span class="egg-chip"><i style="background:{c}"></i>{_esc(a)}</span>'
        for a, c in colors.items())
    return ('<div class="egg-legend"><span class="egg-legend-title">'
            '节点颜色 = 专辑：</span>' + chips + '</div>')


def _sim_tag(pair: EchoPair) -> str:
    """Similarity rendered as words; the raw number lives in the tooltip."""
    if pair.line_a.strip().casefold() == pair.line_b.strip().casefold():
        label = "两首歌唱了同一句"
    elif pair.similarity >= 0.8:
        label = "用词高度相似"
    else:
        label = "语义相近"
    return (f'<span class="egg-pair-sim" title="歌词语义相似度 '
            f'{pair.similarity}（0~1，1 为完全相同）">{label}</span>')


def render_echo_map_html(graph: EchoGraph) -> str:
    """Network view: conclusion first, then the ring map, then examples."""
    scope = _esc(graph.artist) if graph.artist else "跨歌手模式（全部歌手）"
    if graph.song_total < 2:
        return ('<div class="chat-empty">语料库中该范围的歌曲不足 2 首，'
                '无法构建彩蛋网络。</div>')
    if not graph.edges:
        return (f'<div class="chat-empty">在 {scope} 的 '
                f'{graph.song_total} 首歌曲之间未发现相似度 ≥ '
                f'{graph.threshold} 的彩蛋呼应。</div>')

    colors = _album_colors(graph.nodes)
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
    for idx, e in enumerate(graph.edges):  # sorted by count, strongest first
        (x1, y1), (x2, y2) = pos[e.song_a], pos[e.song_b]
        # bezier control point pulled toward the center keeps chords readable
        qx = cx + ((x1 + x2) / 2 - cx) * 0.35
        qy = cy + ((y1 + y2) / 2 - cy) * 0.35
        width = 1.0 + 3.0 * e.count / max_count
        # foreground/background split: only the strongest pairs keep the
        # accent color, everything else fades to grey — no more hairball
        top = idx < _TOP_EDGES_HIGHLIGHT and e.count > 1
        cls = "egg-edge egg-edge-top" if top else "egg-edge"
        if top:
            opacity = 0.75
        elif e.count <= 1:
            # single-pair edges are the hairball: near-invisible at rest,
            # they revive on hover and on node-highlight
            opacity = 0.05
        else:
            opacity = 0.12 + 0.28 * e.count / max_count
        tip = (f'《{e.song_a}》↔《{e.song_b}》共 {e.count} 处呼应\n'
               f'例：“{e.example.line_a}” ↔ “{e.example.line_b}”\n'
               '点击两端的圆点可逐对细看')
        edge_parts.append(
            f'<path d="M{x1:.1f},{y1:.1f} Q{qx:.1f},{qy:.1f} {x2:.1f},{y2:.1f}" '
            f'class="{cls}" stroke-width="{width:.1f}" '
            f'stroke-opacity="{opacity:.2f}" '
            f'data-ega="{_esc(e.song_a)}" data-egb="{_esc(e.song_b)}">'
            f'<title>{_esc(tip)}</title></path>'
        )

    node_parts = []
    for node in graph.nodes:
        x, y = pos[node.song]
        r = 6 + 2.2 * math.sqrt(node.echo_count)
        anchor = "start" if x >= cx else "end"
        lx = x + (r + 6 if x >= cx else -(r + 6))
        cls = "egg-node in-library" if node.in_library else "egg-node"
        artist_part = f' · {node.artist}' if graph.cross_artist and node.artist else ""
        tip = (f'《{node.song}》{artist_part} · {node.album or "未知专辑"}'
               f' · {node.echo_count} 处呼应')
        if node.in_library:
            tip += "（在你的歌曲列表中）"
        tip += "。点击聚焦这首歌"
        node_parts.append(
            f'<g class="{cls}" data-focus-pick="{_esc(node.song)}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{colors[node.album or "未知专辑"]}">'
            f'<title>{_esc(tip)}</title></circle>'
            f'<text x="{lx:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
            f'class="egg-label">{_esc(_short(node.song))}'
            f'<title>{_esc(tip)}</title></text></g>'
        )

    total_pairs = sum(e.count for e in graph.edges)
    busiest = max(graph.nodes, key=lambda nd: nd.echo_count)
    top_edge = graph.edges[0]
    summary = (
        f'<div class="egg-headline">🥚 {scope} 的彩蛋网络'
        f'<span class="egg-headline-sub">{n} 首歌 · {total_pairs} 处呼应 · '
        f'相似度阈值 ≥ {graph.threshold}</span></div>'
        f'<div class="egg-conclusion">一句话总结：这 {n} 首歌之间共有 '
        f'<b>{total_pairs}</b> 处歌词呼应；《{_esc(busiest.song)}》与其他歌'
        f'互文最多（{busiest.echo_count} 处）；呼应最密的一对是'
        f'《{_esc(top_edge.song_a)}》↔《{_esc(top_edge.song_b)}》'
        f'（{top_edge.count} 处，图中最粗的彩色线）。</div>'
        '<div class="egg-howto">怎么看这张图：一个圆点 = 一首歌，'
        '点越大它的呼应越多，颜色 = 所属专辑（图例在图下方）；'
        '两点之间的连线 = 这两首歌的歌词互相呼应，线越粗呼应越多，'
        '彩色线是呼应最强的几对，灰色线较弱。悬停圆点只看这首歌的连线，'
        '悬停连线看具体歌词，<b>点击圆点进入聚焦视图逐对阅读</b>。</div>'
    )

    top_items = []
    for e in graph.edges[:TOP_PAIRS_SHOWN]:
        top_items.append(
            '<div class="egg-pair egg-clickable" '
            f'data-focus-pick="{_esc(e.song_a)}" '
            f'title="点击聚焦《{_esc(e.song_a)}》，逐对查看这两首歌的呼应">'
            f'<div class="egg-pair-songs">《{_esc(e.song_a)}》↔'
            f'《{_esc(e.song_b)}》 · {e.count} 处呼应'
            '<span class="egg-pair-go">聚焦 ›</span></div>'
            f'<div class="egg-pair-lines">“{_esc(e.example.line_a)}” ↔ '
            f'“{_esc(e.example.line_b)}”{_sim_tag(e.example)}</div>'
            '</div>'
        )
    top_html = ('<div class="egg-pairs"><div class="egg-pairs-title">'
                '🔗 呼应最强的歌曲对（点击任意一对细看）</div>'
                + "".join(top_items) + '</div>')

    return (
        summary
        + f'<svg viewBox="0 0 {_SVG_W} {svg_h}" class="egg-svg" role="img">'
        + "".join(edge_parts) + "".join(node_parts) + '</svg>'
        + _album_legend(colors)
        + top_html
    )


ECHO_MAP_CSS = """
.egg-summary {
  font-size: 13px; color: var(--text-secondary); padding: 8px 12px;
  background: var(--bg-card); border-radius: 8px; margin-bottom: 8px;
}
.egg-svg { width: 100%; height: auto; display: block; }
.egg-edge {
  fill: none; stroke: #8b949e;
  transition: stroke-opacity 0.15s ease, opacity 0.15s ease;
}
.egg-edge-top { stroke: var(--accent); }
.egg-edge:hover { stroke-opacity: 0.95; }
.egg-edge.egg-dim { stroke-opacity: 0.04; }
.egg-edge.egg-lit { stroke: var(--accent); stroke-opacity: 0.7; }
.egg-node.egg-dim, g.egg-clickable.egg-dim { opacity: 0.2; }
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

.egg-headline {
  font-size: 18px; font-weight: 700; color: var(--text-primary);
  padding: 4px 2px 2px;
}
.egg-headline-sub {
  font-size: 13px; font-weight: 400; color: var(--text-secondary);
  margin-left: 10px;
}
.egg-clickable { cursor: pointer; }
.egg-clickable:hover .egg-label { fill: var(--accent); font-weight: 700; }
.egg-pair.egg-clickable:hover { border-color: var(--accent); }
.egg-more { margin-top: 6px; }
.egg-more summary {
  cursor: pointer; font-size: 12px; color: var(--accent);
  user-select: none; list-style-position: inside;
}
.egg-more summary:hover { text-decoration: underline; }
.egg-more-pair {
  margin: 6px 0 0; padding: 6px 8px; border-left: 2px solid var(--border);
}
.egg-more-note {
  margin-top: 6px; font-size: 11.5px; color: var(--text-secondary);
}
.egg-pair-go {
  float: right; font-size: 11px; color: var(--accent); opacity: 0;
  transition: opacity 0.15s ease;
}
.egg-pair.egg-clickable:hover .egg-pair-go { opacity: 1; }
.egg-node { cursor: pointer; }
.egg-node:hover circle { stroke: var(--accent); }

.egg-conclusion {
  font-size: 13.5px; line-height: 1.7; color: var(--text-primary);
  background: var(--accent-soft); border-radius: 10px; padding: 9px 13px;
  margin: 8px 0 4px;
}
.egg-howto {
  font-size: 12.5px; line-height: 1.7; color: var(--text-secondary);
  margin: 4px 0 6px;
}
.egg-legend {
  display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center;
  font-size: 12px; color: var(--text-secondary); margin: 6px 0 2px;
}
.egg-legend-title { font-weight: 600; }
.egg-chip { display: inline-flex; align-items: center; gap: 5px; }
.egg-chip i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.egg-pair-sim { cursor: help; border-bottom: 1px dotted var(--accent); }

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
    """Star view: the focus song in the middle, partners around it, and
    every pair's lyric quotes laid out as cards — no hovering needed."""
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

    colors = _album_colors(graph.nodes)
    album_of = {nd.song: (nd.album or "未知专辑") for nd in graph.nodes}

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
            f'class="egg-edge" stroke-opacity="0.45" '
            f'stroke-width="{width:.1f}"/>'
        )
        # count badge on the spoke (= number of echoing line pairs)
        bx, by = cx + (x - cx) * 0.55, cy + (y - cy) * 0.55
        parts.append(
            f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="11" class="egg-badge"/>'
            f'<text x="{bx:.1f}" y="{by + 4:.1f}" text-anchor="middle" '
            f'class="egg-badge-text">{e.count}</text>'
        )
        anchor = "start" if x >= cx else "end"
        lx = x + (14 if x >= cx else -14)
        tip = f"《{partner}》与《{focus}》有 {e.count} 处呼应 · 点击聚焦这首歌"
        parts.append(
            f'<g class="egg-clickable" data-focus-pick="{_esc(partner)}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" '
            f'fill="{colors.get(album_of.get(partner, "未知专辑"), "#57606a")}" '
            'class="egg-spoke">'
            f'<title>{_esc(tip)}</title></circle>'
            f'<text x="{lx:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
            f'class="egg-label">{_esc(_short(partner))}'
            f'<title>{_esc(tip)}</title></text></g>'
        )
    # focus node on top
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="16" class="egg-focus"/>'
        f'<text x="{cx:.1f}" y="{cy - 26:.1f}" text-anchor="middle" '
        f'class="egg-label egg-focus-label">{_esc(_short(focus))}</text>'
    )

    total = sum(e.count for _, e in spokes)
    best_partner, best_edge = spokes[0]
    summary = (
        f'<div class="egg-headline">🥚 《{_esc(focus)}》的彩蛋网络'
        f'<span class="egg-headline-sub">{scope}</span></div>'
        f'<div class="egg-conclusion">一句话总结：《{_esc(focus)}》的歌词与 '
        f'<b>{n}</b> 首歌互相呼应，共 <b>{total}</b> 处；和它呼应最多的是'
        f'《{_esc(best_partner)}》（{best_edge.count} 处）。</div>'
        '<div class="egg-howto">怎么看：中间金色的点是当前聚焦的歌，四周是'
        '与它有歌词呼应的歌（颜色 = 专辑，图例在图下方）；'
        '<b>连线上的数字 = 两首歌呼应的次数</b>。具体歌词不用悬停，'
        '下方卡片已逐对列出；点击图上或卡片里的任意歌曲即可聚焦它。</div>'
    )

    # legend limited to albums actually on screen (focus + partners)
    shown = {album_of.get(focus, "未知专辑")}
    shown.update(album_of.get(p, "未知专辑") for p, _ in spokes)
    legend = _album_legend({al: c for al, c in colors.items() if al in shown})

    def _oriented(e: EchoEdge, p: EchoPair) -> tuple[str, str]:
        # quote order: focus song's line first
        return (p.line_a, p.line_b) if e.song_a == focus \
            else (p.line_b, p.line_a)

    cards = []
    for partner, e in spokes:
        la, lb = _oriented(e, e.example)
        extras = e.examples[1:]
        if extras:
            rows = "".join(
                f'<div class="egg-more-pair">'
                f'<div class="egg-pair-quote">“{_esc(ea)}”</div>'
                f'<div class="egg-pair-quote">“{_esc(eb)}”{_sim_tag(p)}</div>'
                '</div>'
                for p in extras for ea, eb in [_oriented(e, p)])
            note = ""
            if e.count > len(e.examples):
                note = (f'<div class="egg-more-note">共 {e.count} 处呼应，'
                        f'此处保留最强的 {len(e.examples)} 对。</div>')
            more = (
                f'<details class="egg-more"><summary>展开其余 '
                f'{len(extras)} 对呼应</summary>{rows}{note}</details>')
        elif e.count > 1:
            more = (f'<div class="egg-more-note">共 {e.count} 处呼应，'
                    '其余各对与上面措辞重复，已合并展示。</div>')
        else:
            more = ""
        cards.append(
            f'<div class="egg-pair egg-clickable" '
            f'data-focus-pick="{_esc(partner)}" title="点击聚焦《{_esc(partner)}》">'
            f'<div class="egg-pair-songs">↔ 《{_esc(partner)}》 · '
            f'{e.count} 处呼应<span class="egg-pair-go">聚焦 ›</span></div>'
            f'<div class="egg-pair-quote">《{_esc(focus)}》唱道：“{_esc(la)}”</div>'
            f'<div class="egg-pair-quote">《{_esc(partner)}》唱道：“{_esc(lb)}”'
            f'{_sim_tag(e.example)}</div>'
            f'{more}'
            '</div>'
        )

    return (
        summary
        + f'<svg viewBox="0 0 {_FOCUS_W} {_FOCUS_H}" class="egg-svg" role="img">'
        + "".join(parts) + '</svg>'
        + legend
        + '<div class="egg-pairs">' + "".join(cards) + '</div>'
    )
