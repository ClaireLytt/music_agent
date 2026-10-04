"""MCP server (stdio) — lets AI agents query the library and drive playback.

`lyric-agent mcp` runs this over stdio for Claude Code / Claude Desktop.
Module top stays import-light so startup is instant; heavy pieces
(settings, songs, searcher, embeddings) load lazily on first use.

stdout is the MCP protocol: never print here — logging goes to stderr.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

server = MCPServer(
    name="lyric-lens",
    instructions=(
        "歌词透镜（Lyric Lens）曲库查询与播放控制。"
        "找歌先用 search_lyrics 或 list_songs 确认准确歌名，"
        "再用 get_lyrics / get_annotation 深入，或用 play_song 让"
        "浏览器里的播放器切歌播放。"
    ),
)

_ctx: dict[str, Any] = {}


# ── lazy data layer ──────────────────────────────────────────────────────

def _settings():
    if "settings" not in _ctx:
        from .config import load_settings
        _ctx["settings"] = load_settings()
    return _ctx["settings"]


def _songs() -> list[dict]:
    if "songs" not in _ctx:
        from .config import HACKATHON_PLAYLIST_SOURCE
        from .ui_helpers import _discover_songs
        s = _settings()
        exclude = {HACKATHON_PLAYLIST_SOURCE} if s.public_mode else None
        _ctx["songs"] = _discover_songs(s.songs_dir, exclude_sources=exclude)
    return _ctx["songs"]


def _searcher():
    if "searcher" not in _ctx:
        from .search import LyricsSearcher
        s = _settings()
        _ctx["searcher"] = LyricsSearcher(
            _songs(), model_name=s.embedding_model, corpus_dir=s.corpus_dir)
    return _ctx["searcher"]


def _embeddings():
    if "embeddings" not in _ctx:
        from .intertextuality.embeddings import load_embeddings
        s = _settings()
        _ctx["embeddings"] = load_embeddings(s.corpus_dir, s.embedding_model)
    return _ctx["embeddings"]


def _match_song(title: str) -> dict | None:
    """Exact title → 「title — artist」 label → casefold → unique substring."""
    want = (title or "").strip()
    if not want:
        return None
    songs = _songs()
    for s in songs:
        if s["title"] == want:
            return s
    for s in songs:
        if f"{s['title']} — {s['artist']}" == want:
            return s
    folded = want.casefold()
    for s in songs:
        if s["title"].casefold() == folded:
            return s
    subs = [s for s in songs if folded in s["title"].casefold()]
    return subs[0] if len(subs) == 1 else None


def _err(msg: str) -> dict:
    return {"error": msg,
            "available_titles": [s["title"] for s in _songs()[:30]]}


# ── tools ────────────────────────────────────────────────────────────────

@server.tool()
def list_songs() -> list[dict]:
    """列出曲库全部歌曲（标题、歌手、专辑、年份、是否有音频）。"""
    return [{"title": s["title"], "artist": s["artist"], "album": s["album"],
             "year": s.get("year") or None,
             "has_audio": bool(s.get("audio_src"))}
            for s in _songs()]


@server.tool()
def get_lyrics(title: str) -> dict:
    """取一首歌的完整歌词（逐行，带行号与时间戳毫秒）。title 需准确，
    不确定时先用 search_lyrics 或 list_songs。"""
    song = _match_song(title)
    if song is None:
        return _err(f"未找到歌曲：{title}")
    from pathlib import Path

    from .lrc_parser import load_lrc_file
    _, lines = load_lrc_file(Path(song["dir"]) / "lyrics.lrc")
    return {"title": song["title"], "artist": song["artist"],
            "lines": [{"i": ln.line_index, "ts_ms": ln.timestamp_ms,
                       "text": ln.text} for ln in lines]}


@server.tool()
def get_annotation(title: str, line_index: int) -> dict:
    """取某首歌某一行的 AI 批注（修辞、意象、情感、用典）。行号来自
    get_lyrics 的 i 字段。没有批注的歌返回提示。"""
    song = _match_song(title)
    if song is None:
        return _err(f"未找到歌曲：{title}")
    from .ui_helpers import _load_song_data
    data = _load_song_data(song["dir"])
    ann = (data.get("annotations") or {}).get(line_index)
    if ann is None:
        return {"error": f"《{song['title']}》第 {line_index} 行没有批注"
                         "（这首歌可能尚未生成 AI 批注）"}
    fields = dataclasses.asdict(ann) if dataclasses.is_dataclass(ann) \
        else dict(ann)
    return {"title": song["title"], "line_index": line_index,
            **{k: v for k, v in fields.items() if v not in (None, "", [])}}


@server.tool()
def search_lyrics(query: str, semantic: bool = False, limit: int = 10) -> dict:
    """按关键词搜索歌词（毫秒级）。semantic=True 走语义搜索——
    「关于雨的歌」这类模糊描述用它，但首次调用需加载模型（约 10-20 秒）。"""
    limit = max(1, min(int(limit), 30))
    if semantic:
        hits, mode = _searcher().semantic(query, limit=limit)
    else:
        hits, mode = _searcher().keyword(query, limit=limit), "keyword"
    return {"mode": mode,
            "hits": [{"title": h.song_title, "album": h.album,
                      "line_index": h.line_index, "text": h.text,
                      "score": round(h.score, 3)} for h in hits]}


@server.tool()
def find_echoes(lyric_text: str, artist: str | None = None,
                top_k: int = 4) -> dict:
    """找一句歌词在曲库中的「彩蛋」呼应（语义相似的其他歌词）。
    artist 填歌手名则只看同歌手作品。"""
    top_k = max(1, min(int(top_k), 10))
    s = _settings()
    try:
        emb, corpus = _embeddings()
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}  # message carries the fix command
    from .intertextuality.search import search_similar
    results = search_similar(
        lyric_text, emb, corpus, model_name=s.embedding_model,
        top_k=top_k, artist=artist,
        min_similarity=s.echo_search_min_similarity,
        min_similarity_cjk=s.echo_search_min_similarity_cjk)
    return {"echoes": [{"title": r.song, "album": r.album, "line": r.line,
                        "similarity": round(r.similarity, 3)}
                       for r in results]}


@server.tool()
def artist_motifs(artist: str, top_n: int = 6) -> dict:
    """挖掘一位歌手反复出现的母题意象（零 LLM，纯语料统计）。
    每个母题附出现歌数与最多 3 条例句。"""
    from .archaeology import mine_motifs
    from .intertextuality.corpus import load_corpus
    corpus = load_corpus(_settings().corpus_dir)
    motifs = mine_motifs(corpus, artist, top_n=max(1, min(int(top_n), 10)))
    if not motifs:
        return {"error": f"{artist} 没有挖到母题"
                         "（需要同一意象出现在至少 3 首歌里）"}
    return {"artist": artist,
            "motifs": [{"word": m["word"], "n_songs": m["n_songs"],
                        "total": m["total"],
                        "examples": [{"title": h["song"], "text": h["text"]}
                                     for h in m["hits"][:3]]}
                       for m in motifs]}


@server.tool()
def daily_quote() -> dict:
    """今日推荐：每天确定性地推一句带 AI 解读的歌词。"""
    from .insights import daily_quote as _daily
    quote = _daily(_songs())
    return quote or {"error": "暂无可推荐的批注歌词（曲库里还没有带批注的歌）"}


@server.tool()
def play_song(title: str, line_index: int | None = None) -> dict:
    """让浏览器里打开的歌词透镜播放器切到这首歌并播放；line_index
    可选，定位并高亮到那一行。需要 `lyric-agent serve` 正在运行、
    页面已在浏览器打开。"""
    if _settings().public_mode:
        return {"error": "公开部署模式下不支持远程播放控制"}
    song = _match_song(title)
    if song is None:
        return _err(f"未找到歌曲：{title}")
    from .mcp_channel import write_mcp_command
    write_mcp_command("play", title=song["title"], line_index=line_index)
    return {"status": "ok", "title": song["title"],
            "has_audio": bool(song.get("audio_src")),
            "note": "浏览器中打开的播放器将在 1-2 秒内切歌并播放"
                    "（需 lyric-agent serve 正在运行且页面已打开）"}


def create_server() -> MCPServer:
    return server
