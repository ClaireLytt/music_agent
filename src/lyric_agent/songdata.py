"""歌曲数据发现/加载/持久化层：song discovery、per-song caches、
chat/notes/intro/favorites 等落盘读写。不 import 任何渲染/gradio 代码，
mcp_server 只依赖本层。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .annotator.models import Song
from .audio_provider import resolve as resolve_audio
from .lrc_parser import load_lrc_file

logger = logging.getLogger(__name__)

# 刻意最小的公开 API：仅这四个名字是稳定契约。其余 `_` 前缀符号均为
# 私有实现，ui_helpers 重导出它们只为旧导入路径兼容（兼容面由
# tests/test_features.py::test_ui_helpers_compat_surface 锁定）。
__all__ = [
    "discover_songs", "load_song_data", "load_translation", "song_is_cjk",
]


# 单一真相源：持有 Settings 的入口（webui Runtime / mcp_server）启动时
# 调 set_songs_root(settings.songs_dir)；未设置时才回退到环境变量口径
_SONGS_ROOT: Path | None = None


def set_songs_root(songs_dir: str | Path) -> None:
    global _SONGS_ROOT
    _SONGS_ROOT = Path(songs_dir).resolve()


def _songs_root() -> Path:
    if _SONGS_ROOT is not None:
        return _SONGS_ROOT
    import os
    return Path(os.getenv("SONGS_DIR", "data/songs")).resolve()


# ── Song loading ──────────────────────────────────────────

# keyed by (resolved dir, lyrics.lrc mtime) so equivalent paths share one
# entry and edited lyrics invalidate naturally
_SONG_CJK_CACHE: dict[tuple[str, float], bool] = {}


def song_is_cjk(song_dir: str | Path) -> bool:
    """这首歌是不是中文歌：取歌词前 30 行，过半数行 CJK 占比 >30% 判中文。
    产品定位是英文歌学英语，中文歌默认隐藏（LL_SHOW_CJK=1 可恢复）。"""
    lrc = Path(song_dir) / "lyrics.lrc"
    key = (str(Path(song_dir).resolve()),
           lrc.stat().st_mtime if lrc.exists() else 0.0)
    if key in _SONG_CJK_CACHE:
        return _SONG_CJK_CACHE[key]
    from .intertextuality.search import is_cjk_text
    from .lrc_parser import parse_lrc
    try:
        _, timed = parse_lrc((Path(song_dir) / "lyrics.lrc")
                             .read_text(encoding="utf-8"))
        lines = [ln.text for ln in timed[:30] if ln.text.strip()]
        result = bool(lines) and (
            sum(is_cjk_text(ln) for ln in lines) / len(lines) > 0.5)
    except Exception:
        result = False
    _SONG_CJK_CACHE[key] = result
    return result


def _discover_songs(songs_dir: str,
                    exclude_sources: set[str] | None = None,
                    exclude_cjk: bool = False) -> list[dict[str, Any]]:
    base = Path(songs_dir)
    if not base.exists():
        return []
    songs = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not (d / "lyrics.lrc").exists():
            continue
        meta = {}
        if (d / "metadata.json").exists():
            try:
                meta = json.loads(
                    (d / "metadata.json").read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    meta = {}
            except (OSError, ValueError):
                logger.exception("Malformed metadata.json in %s, skipping", d)
                meta = {}
        if exclude_sources and meta.get("source") in exclude_sources:
            continue
        if exclude_cjk and song_is_cjk(d):
            continue
        audio = resolve_audio(d)
        era = meta.get("era", "").lower()
        songs.append({
            "dir": str(d), "name": d.name,
            "title": meta.get("title", d.name.replace("_", " ").title()),
            "artist": meta.get("artist", "未知歌手"),
            "album": meta.get("album", ""), "year": meta.get("year", 0),
            "era": era,
            "audio_type": audio.type, "audio_src": audio.path_or_url or "",
            # preview clips start mid-song; shift lyric sync by this many ms
            "audio_offset_ms": int(meta.get("audio_offset_ms", 0) or 0),
            # bound bilibili video for the 📺 video playback mode
            "bvid": meta.get("bvid", ""),
            "bvid_no_auto": bool(meta.get("bvid_no_auto")),
            # Windows: st_ctime is directory creation time = when the song was added
            "added_ts": d.stat().st_ctime,
        })
    return songs


def _fetch_lrc_from_lrclib(title: str, artist: str) -> str | None:
    from .lrc_sources import fetch_synced_lyrics
    return fetch_synced_lyrics(title, artist)


_PLACEHOLDER_LRC = "[00:00.00] （暂无歌词 — 可编辑本目录下的 lyrics.lrc 补充）\n"

_CATALOG_PATH = Path("data/catalog/catalog.json")


def _load_catalog() -> list[dict]:
    """内置曲库（英文歌定位：默认滤掉中文条目，LL_SHOW_CJK=1 恢复）。"""
    import os
    import re as _re
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                if os.getenv("LL_SHOW_CJK", "") != "1":
                    cjk = _re.compile(r"[一-鿿]")
                    data = [c for c in data
                            if not cjk.search(str(c.get("title", ""))
                                              + str(c.get("artist", "")))]
                return data
    except Exception:
        logger.exception("Failed reading catalog %s", _CATALOG_PATH)
    return []


def _load_chat_history(song_dir: str | Path) -> dict:
    """Per-line saved chats: {"<line_index>": {"line": str, "turns": [...]}}"""
    path = Path(song_dir) / "chat_history.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        logger.exception("Failed reading chat history %s", path)
    return {}


def _save_chat_history(song_dir: str | Path, line_index: int,
                       lyric_line: str, turns: list[dict]) -> None:
    data = _load_chat_history(song_dir)
    data[str(line_index)] = {"line": lyric_line, "turns": turns}
    path = Path(song_dir) / "chat_history.json"
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        logger.exception("Failed to save chat history")


# per-song listening notes: [{"ts_ms": int, "text": str}]
_NOTES_FILENAME = "notes.json"


def _load_notes(song_dir: str | Path) -> list[dict]:
    path = Path(song_dir) / _NOTES_FILENAME
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        logger.exception("Failed reading notes for %s", song_dir)
    return []


def _save_notes(song_dir: str | Path, notes: list[dict]) -> None:
    (Path(song_dir) / _NOTES_FILENAME).write_text(
        json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")


# disk cache for whole-song echo scans (survives restarts; key-invalidated)
_ECHO_SCAN_CACHE_DIR = Path("data/cache/echo_scans")

# whole-song AI intro, generated once and cached in the song directory
_INTRO_FILENAME = "intro.txt"


def _load_intro(song_dir: str | Path) -> str:
    path = Path(song_dir) / _INTRO_FILENAME
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        logger.exception("Failed reading intro for %s", song_dir)
    return ""


# mtime-keyed cache: repeated song selections skip re-parsing lrc/annotations
_SONG_DATA_CACHE: dict[str, tuple[tuple[float, float], dict]] = {}


def _load_song_data(song_dir: str) -> dict[str, Any]:
    d = Path(song_dir)
    # 防路径穿越：本函数被 mcp_server 等以外部输入可达的路径调用，
    # 必须限定在配置的歌曲根目录之下
    if not d.resolve().is_relative_to(_songs_root()):
        raise ValueError(f"song_dir outside songs root: {song_dir}")
    lrc_path = d / "lyrics.lrc"
    ann_path = d / "annotations.json"
    stamp = (
        lrc_path.stat().st_mtime if lrc_path.exists() else 0.0,
        ann_path.stat().st_mtime if ann_path.exists() else 0.0,
    )
    cached = _SONG_DATA_CACHE.get(song_dir)
    if cached and cached[0] == stamp:
        return cached[1]

    _meta, timed_lines = load_lrc_file(str(lrc_path))
    annotations = {}
    if ann_path.exists():
        song = Song.load(ann_path)
        for ann in song.annotations:
            annotations[ann.line_index] = ann
    data = {
        "timed_lines": timed_lines,
        "annotations": annotations,
    }
    _SONG_DATA_CACHE[song_dir] = (stamp, data)
    return data


_FAVORITES_PATH = Path("data/favorites.json")


def _fav_id(line: str, title: str) -> str:
    """Stable identity for a favorite (favorites dedup on line+title), so
    delete/jump match by id and never drift with list position."""
    import hashlib
    return hashlib.md5(
        f"{line}\x00{title}".encode("utf-8")).hexdigest()[:12]


def _load_favorites() -> list[dict]:
    try:
        if _FAVORITES_PATH.exists():
            data = json.loads(_FAVORITES_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            # backfill ids for entries written before ids existed
            for f in data:
                if isinstance(f, dict) and not f.get("id"):
                    f["id"] = _fav_id(f.get("line", ""), f.get("title", ""))
            return data
    except (OSError, ValueError):
        logger.exception("Failed reading favorites")
    return []


def _save_favorites(favs: list[dict]) -> None:
    try:
        _FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FAVORITES_PATH.write_text(
            json.dumps(favs, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.exception("Failed saving favorites")


def load_translation(song_dir: str) -> dict[int, str]:
    """data/songs/<歌>/translation.json → {line_index: 中文}；无则 {}。"""
    p = Path(song_dir) / "translation.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("lines"), dict):
            return {}
        return {int(k): v for k, v in raw["lines"].items() if v}
    except (OSError, ValueError):
        return {}


# 跨模块共享 API（ui.py / mcp_server.py / cli.py 共用）——公开名
discover_songs = _discover_songs
load_song_data = _load_song_data
