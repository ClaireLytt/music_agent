"""HTML/SVG rendering for the artist evolution map tab (PRD F-17).

Pure server-side SVG generation — no D3 or external JS libraries.
"""

from __future__ import annotations

import html

from .models import ArtistEvolution, EraProfile

_THEME_COLORS = {
    "love": "#f472b6",
    "nostalgia": "#fbbf24",
    "loss": "#60a5fa",
    "identity": "#a78bfa",
    "pain": "#f87171",
    "irony": "#34d399",
}

_THEME_LABELS_ZH = {
    "love": "爱情", "nostalgia": "怀旧", "loss": "失去",
    "identity": "自我", "pain": "伤痛", "irony": "反讽",
}


def _esc(s: str) -> str:
    return html.escape(s)


def _theme_label(key: str, lang: str) -> str:
    if lang == "zh":
        return _THEME_LABELS_ZH.get(key, key)
    return key


# ── Timeline ──────────────────────────────────────────────

def _render_timeline(evo: ArtistEvolution, current_era: str) -> str:
    nodes = []
    for e in evo.eras:
        has_songs = bool(e.songs)
        cls = "evo-node" + (" has-songs" if has_songs else "") + (
            " current" if e.era == current_era else "")
        marker = '<div class="evo-pin">📍</div>' if e.era == current_era else ""
        nodes.append(
            f'<div class="{cls}" data-era="{_esc(e.era)}">'
            f'{marker}'
            f'<div class="evo-emoji">{e.era_emoji}</div>'
            f'<div class="evo-era-name">{_esc(e.era)}</div>'
            f'<div class="evo-era-year">{_esc(e.years)}</div>'
            f'</div>'
        )
    return (
        '<div class="evo-timeline">'
        '<div class="evo-timeline-track"></div>'
        + "".join(nodes) +
        '</div>'
    )


# ── Genre flow ────────────────────────────────────────────

def _render_genre_flow(evo: ArtistEvolution) -> str:
    genres: list[str] = []
    for e in evo.eras:
        g = e.genre_tags[0] if e.genre_tags else ""
        if not genres or genres[-1] != g:
            genres.append(g)
    parts = []
    for i, g in enumerate(genres):
        if i:
            parts.append('<span class="evo-arrow">━►</span>')
        parts.append(f'<span class="evo-genre">{_esc(g)}</span>')
    return f'<div class="evo-genre-flow">{"".join(parts)}</div>'


# ── Theme streamgraph (stacked area SVG) ──────────────────

def _render_streamgraph(evo: ArtistEvolution, lang: str) -> str:
    themes = [t for t in _THEME_COLORS if t in evo.theme_timeline]
    n = len(evo.eras)
    if n < 2 or not themes:
        return ""

    width, height, pad = 860, 220, 30
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    xs = [pad + plot_w * i / (n - 1) for i in range(n)]

    totals = [
        sum(evo.theme_timeline[t][i] for t in themes) or 1.0
        for i in range(n)
    ]
    max_total = max(totals)

    baselines = [0.0] * n
    layers = []
    for t in themes:
        vals = evo.theme_timeline[t]
        tops = [baselines[i] + vals[i] for i in range(n)]
        top_pts = [
            f"{xs[i]:.1f},{height - pad - plot_h * tops[i] / max_total:.1f}"
            for i in range(n)
        ]
        bot_pts = [
            f"{xs[i]:.1f},{height - pad - plot_h * baselines[i] / max_total:.1f}"
            for i in reversed(range(n))
        ]
        color = _THEME_COLORS[t]
        layers.append(
            f'<polygon points="{" ".join(top_pts + bot_pts)}" '
            f'fill="{color}" fill-opacity="0.55" stroke="{color}" '
            f'stroke-opacity="0.8" stroke-width="1">'
            f'<title>{_esc(_theme_label(t, lang))}</title></polygon>'
        )
        baselines = tops

    axis_labels = "".join(
        f'<text x="{xs[i]:.0f}" y="{height - 8}" text-anchor="middle" '
        f'class="evo-svg-label">{e.era_emoji}</text>'
        for i, e in enumerate(evo.eras)
    )
    legend = "".join(
        f'<span class="evo-legend-item">'
        f'<span class="evo-legend-swatch" style="background:{_THEME_COLORS[t]}"></span>'
        f'{_esc(_theme_label(t, lang))}</span>'
        for t in themes
    )
    return (
        f'<div class="evo-legend">{legend}</div>'
        f'<svg viewBox="0 0 {width} {height}" class="evo-svg" role="img">'
        f'{"".join(layers)}{axis_labels}</svg>'
    )


# ── Rhetoric density trend ────────────────────────────────

def _render_density_trend(evo: ArtistEvolution) -> str:
    pts = [(i, e.avg_rhetoric_density) for i, e in enumerate(evo.eras)]
    active = [(i, v) for i, v in pts if v > 0]
    if len(active) < 2:
        return ""

    width, height, pad = 860, 140, 30
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    n = len(evo.eras)
    max_v = max(v for _, v in active)

    def xy(i: int, v: float) -> tuple[float, float]:
        return (pad + plot_w * i / (n - 1), height - pad - plot_h * v / max_v)

    path = " ".join(
        f"{'M' if k == 0 else 'L'}{xy(i, v)[0]:.1f},{xy(i, v)[1]:.1f}"
        for k, (i, v) in enumerate(active)
    )
    dots = "".join(
        f'<circle cx="{xy(i, v)[0]:.1f}" cy="{xy(i, v)[1]:.1f}" r="4" fill="#58a6ff">'
        f'<title>{_esc(evo.eras[i].era)}: {v:.2f}</title></circle>'
        for i, v in active
    )
    labels = "".join(
        f'<text x="{pad + plot_w * i / (n - 1):.0f}" y="{height - 8}" '
        f'text-anchor="middle" class="evo-svg-label">{e.era_emoji}</text>'
        for i, e in enumerate(evo.eras)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" class="evo-svg" role="img">'
        f'<path d="{path}" fill="none" stroke="#58a6ff" stroke-width="2"/>'
        f'{dots}{labels}</svg>'
    )


# ── Radar chart ───────────────────────────────────────────

def _radar_polygon(era: EraProfile, themes: list[str], cx: float, cy: float, r: float) -> str:
    import math
    pts = []
    for k, t in enumerate(themes):
        angle = -math.pi / 2 + 2 * math.pi * k / len(themes)
        v = era.theme_weights.get(t, 0.0)
        pts.append(f"{cx + r * v * math.cos(angle):.1f},{cy + r * v * math.sin(angle):.1f}")
    return " ".join(pts)


def _render_radar_compare(era_a: EraProfile, era_b: EraProfile, lang: str) -> str:
    import math
    themes = list(_THEME_COLORS.keys())
    size, cx, cy, r = 340, 170, 175, 110

    grid = ""
    for frac in (0.33, 0.66, 1.0):
        pts = []
        for k in range(len(themes)):
            angle = -math.pi / 2 + 2 * math.pi * k / len(themes)
            pts.append(f"{cx + r * frac * math.cos(angle):.1f},{cy + r * frac * math.sin(angle):.1f}")
        grid += (
            f'<polygon points="{" ".join(pts)}" fill="none" '
            f'stroke="#30363d" stroke-width="1"/>'
        )

    axis_labels = ""
    for k, t in enumerate(themes):
        angle = -math.pi / 2 + 2 * math.pi * k / len(themes)
        lx = cx + (r + 22) * math.cos(angle)
        ly = cy + (r + 18) * math.sin(angle) + 4
        axis_labels += (
            f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" '
            f'class="evo-svg-label">{_esc(_theme_label(t, lang))}</text>'
        )

    poly_a = _radar_polygon(era_a, themes, cx, cy, r)
    poly_b = _radar_polygon(era_b, themes, cx, cy, r)

    return (
        f'<div class="evo-radar-block">'
        f'<div class="evo-radar-title">{era_a.era_emoji} {_esc(era_a.era)}'
        f' <span class="evo-vs">vs</span> {era_b.era_emoji} {_esc(era_b.era)}</div>'
        f'<svg viewBox="0 0 {size} {size + 10}" class="evo-radar-svg" role="img">'
        f'{grid}'
        f'<polygon points="{poly_a}" fill="#f8717155" stroke="#f87171" stroke-width="2"/>'
        f'<polygon points="{poly_b}" fill="#34d39944" stroke="#34d399" stroke-width="2"/>'
        f'{axis_labels}</svg></div>'
    )


# ── Era detail panels ─────────────────────────────────────

def _render_era_details(evo: ArtistEvolution, current_era: str, lang: str) -> str:
    blocks = []
    for e in evo.eras:
        if not e.songs and not e.ai_summary:
            continue
        songs_html = " | ".join(f"{_esc(s)} ★" for s in e.songs) or "—"
        open_attr = " open" if e.era == current_era else ""
        summary_txt = e.ai_summary or ("（暂无 AI 解读）" if lang == "zh" else "(no AI summary yet)")
        emo = e.avg_emotion or {}
        emo_html = ""
        if emo.get("valence"):
            emo_html = (
                f'<div class="evo-era-emo">valence {emo["valence"]:.2f} · '
                f'arousal {emo["arousal"]:.2f} · '
                f'rhetoric {e.avg_rhetoric_density:.2f}</div>'
            )
        blocks.append(
            f'<details class="evo-era-detail"{open_attr}>'
            f'<summary>{e.era_emoji} <b>{_esc(e.era)}</b> ({_esc(e.years)}) — '
            f'{_esc(", ".join(e.genre_tags))}</summary>'
            f'<p class="evo-era-summary">{_esc(summary_txt)}</p>'
            f'{emo_html}'
            f'<div class="evo-era-songs">{"歌曲" if lang == "zh" else "Songs"}: {songs_html}</div>'
            f'</details>'
        )
    return "".join(blocks)


# ── Main entry ────────────────────────────────────────────

def render_evolution_html(
    evo: ArtistEvolution,
    current_song_title: str = "",
    current_era: str = "",
    lang: str = "zh",
) -> str:
    zh = lang == "zh"
    t_timeline = "创作演化时间线" if zh else "Career Timeline"
    t_genre = "风格演变" if zh else "Genre Evolution"
    t_stream = "主题强度河流图" if zh else "Theme Streamgraph"
    t_density = "修辞密度趋势" if zh else "Rhetoric Density Trend"
    t_detail = "Era 详情" if zh else "Era Details"
    t_radar = "Era 对比雷达" if zh else "Era Comparison Radar"

    current_html = ""
    if current_song_title:
        loc = "当前歌曲" if zh else "Now viewing"
        current_html = (
            f'<div class="evo-current">📍 {loc}: <b>{_esc(current_song_title)}</b>'
            f' ({_esc(current_era)})</div>'
        )

    demo_eras = [e for e in evo.eras if e.songs]
    radar_html = ""
    if len(demo_eras) >= 2:
        radar_html = _render_radar_compare(demo_eras[0], demo_eras[1], lang)
        if len(demo_eras) >= 4:
            radar_html += _render_radar_compare(demo_eras[2], demo_eras[3], lang)

    return f"""\
<div class="evo-wrap">
  <h2 class="evo-title">🗺️ {_esc(evo.artist)} — {"创作演化图谱" if zh else "Artist Evolution Map"}</h2>
  {current_html}
  <h3 class="evo-section">── {t_timeline} ──</h3>
  {_render_timeline(evo, current_era)}
  <h3 class="evo-section">── {t_genre} ──</h3>
  {_render_genre_flow(evo)}
  <h3 class="evo-section">── {t_stream} ──</h3>
  {_render_streamgraph(evo, lang)}
  <h3 class="evo-section">── {t_density} ──</h3>
  {_render_density_trend(evo)}
  <h3 class="evo-section">── {t_detail} ──</h3>
  <div class="evo-details-wrap">{_render_era_details(evo, current_era, lang)}</div>
  <h3 class="evo-section">── {t_radar} ──</h3>
  <div class="evo-radar-row">{radar_html}</div>
</div>"""


EVOLUTION_CSS = """\
.evo-wrap { padding: 12px 20px 40px; max-width: 960px; margin: 0 auto; }
.evo-title { color: var(--text-primary); font-size: 22px; }
.evo-section {
  color: var(--text-secondary); font-size: 13px; letter-spacing: 1px;
  margin: 26px 0 12px; font-weight: 600;
}
.evo-current {
  display: inline-block; padding: 6px 14px; border-radius: 8px;
  background: var(--accent-soft); color: var(--accent);
  border: 1px solid rgba(88,166,255,0.25); font-size: 13px;
}
.evo-timeline {
  position: relative; display: flex; justify-content: space-between;
  padding: 24px 6px 4px;
}
.evo-timeline-track {
  position: absolute; left: 2%; right: 2%; top: 58px; height: 2px;
  background: var(--border);
}
.evo-node {
  position: relative; text-align: center; flex: 1; opacity: 0.45;
  padding-top: 8px;
}
.evo-node.has-songs { opacity: 1; }
.evo-node.current .evo-emoji { transform: scale(1.3); }
.evo-pin { position: absolute; top: -16px; left: 0; right: 0; font-size: 14px; }
.evo-emoji { font-size: 26px; transition: transform .2s; position: relative; z-index: 1; }
.evo-era-name { font-size: 11px; color: var(--text-primary); margin-top: 6px; }
.evo-era-year { font-size: 10px; color: var(--text-secondary); }
.evo-genre-flow {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  font-size: 13px;
}
.evo-genre {
  padding: 3px 12px; border-radius: 12px; background: var(--bg-card);
  border: 1px solid var(--border); color: var(--text-primary);
}
.evo-arrow { color: var(--accent); font-size: 12px; }
.evo-svg { width: 100%; height: auto; background: var(--bg-secondary); border-radius: 10px; }
.evo-svg-label { fill: #8b949e; font-size: 13px; }
.evo-legend { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }
.evo-legend-item {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; color: var(--text-secondary);
}
.evo-legend-swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.evo-details-wrap { display: flex; flex-direction: column; gap: 8px; }
.evo-era-detail {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 16px; color: var(--text-primary);
}
.evo-era-detail summary { cursor: pointer; font-size: 14px; }
.evo-era-summary {
  color: var(--text-secondary); font-size: 13px; line-height: 1.8;
  margin: 10px 0 6px;
}
.evo-era-emo { color: var(--accent); font-size: 11px; margin-bottom: 6px; }
.evo-era-songs { color: var(--text-secondary); font-size: 12px; }
.evo-radar-row { display: flex; gap: 24px; flex-wrap: wrap; }
.evo-radar-block {
  background: var(--bg-secondary); border-radius: 12px;
  padding: 14px; flex: 1; min-width: 300px; max-width: 420px;
}
.evo-radar-title {
  text-align: center; color: var(--text-primary); font-size: 14px;
  margin-bottom: 6px;
}
.evo-vs { color: var(--text-secondary); font-size: 12px; }
.evo-radar-svg { width: 100%; height: auto; }
"""
