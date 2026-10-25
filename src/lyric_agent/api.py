"""FastAPI 薄 API 层（前端重写 M2 垂直切片：播放解读页所需端点）。

铁律（docs/frontend_rewrite_plan.md）：本层不搬业务逻辑——参数校验 →
调 songdata/dictionary 数据层 → 序列化。MCP/CLI/SPA 三入口共享同一行为。
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import dictionary, songdata
from .config import load_settings
from .songdata import _discover_songs, _load_song_data

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _songs() -> list[dict]:
    settings = load_settings()
    songdata.set_songs_root(settings.songs_dir)
    exclude_cjk = os.getenv("LL_SHOW_CJK", "") not in ("1", "true", "yes")
    return _discover_songs(settings.songs_dir, exclude_cjk=exclude_cjk)


def _find_song(song_id: str) -> dict:
    for s in _songs():
        if s["name"] == song_id:
            return s
    raise HTTPException(status_code=404, detail=f"song not found: {song_id}")


def _song_payload(s: dict) -> dict:
    return {
        "id": s["name"], "title": s["title"], "artist": s["artist"],
        "album": s["album"], "year": s["year"],
        "audio_type": s["audio_type"],
        "audio_offset_ms": s["audio_offset_ms"],
        "bvid": s["bvid"],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Lyric Lens API")

    @app.get("/api/songs")
    def list_songs() -> list[dict]:
        return [_song_payload(s) for s in _songs()]

    @app.get("/api/songs/{song_id}")
    def get_song(song_id: str) -> dict:
        return _song_payload(_find_song(song_id))

    @app.get("/api/songs/{song_id}/lyrics")
    def get_lyrics(song_id: str) -> dict:
        s = _find_song(song_id)
        data = _load_song_data(s["dir"])
        return {
            "timed_lines": [
                {"line_index": tl.line_index, "timestamp_ms": tl.timestamp_ms,
                 "text": tl.text}
                for tl in data["timed_lines"]
            ],
            "annotations": {
                str(idx): asdict(ann)
                for idx, ann in data["annotations"].items()
            },
        }

    @app.get("/api/songs/{song_id}/audio")
    def get_audio(song_id: str):
        s = _find_song(song_id)
        if s["audio_type"] == "url":
            return RedirectResponse(s["audio_src"])
        if s["audio_type"] == "local" and Path(s["audio_src"]).exists():
            return FileResponse(s["audio_src"])
        raise HTTPException(status_code=404, detail="no audio for this song")

    @app.get("/api/dict/{word}")
    def dict_lookup(word: str) -> dict:
        hit = dictionary.lookup(word)
        if not hit:
            raise HTTPException(status_code=404, detail=f"not found: {word}")
        return hit

    # 生产形态：Vite build 产物由同一进程托管（部署体验与 serve 一致）
    if _FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True),
                  name="spa")
    return app
