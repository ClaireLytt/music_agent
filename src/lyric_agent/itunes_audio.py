"""【实验性，可整体移除】iTunes 30 秒试听兜底 —— 没音频也没 MV 的歌自动搜试听。

调研依据 docs/research_audio_sources.md：iTunes Search API 官方公开、
免 key，返回主流曲库的 30s AAC previewUrl；音频 CDN 对浏览器 <audio>
可直连（media 元素本就不要求 CORS），search 端点由后端调用。

设计与 bilibili_audio.py 同构：不改 audio_provider/songdata/metadata，
只在 API 层兜底。结果持久化在 data/cache/itunes_previews.json
（含 24h 负缓存，避免反复打接口；~20 req/min/IP 限速 → 填充线程节流）。

删除该功能 = 删掉本文件 + api.py 中标记 "iTunes 试听" 的小块
+ 前端 PlayerBar 的试听角标 + api.ts 类型里的 "preview" 一词。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"
_CACHE_PATH = Path("data/cache/itunes_previews.json")
_RETRY_AFTER_S = 24 * 3600   # 负缓存：没搜到/出错 24h 后才重试
_THROTTLE_S = 3              # 填充线程限速（官方 ~20 req/min/IP）

_lock = threading.Lock()
_fill_started = False


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def preview_url(song_name: str) -> str:
    """缓存里的试听 URL；无缓存/负缓存返回 ""（不打网络）。"""
    return _load_cache().get(song_name, {}).get("url", "")


def _search(title: str, artist: str) -> str:
    """iTunes Search → previewUrl；优先歌手匹配的结果，搜不到返回 ""。"""
    from .jsonio import http_get_json
    q = urllib.parse.urlencode({
        "term": f"{title} {artist}".strip(), "media": "music",
        "entity": "song", "limit": 5})
    data = http_get_json(f"{_SEARCH_URL}?{q}", {"User-Agent": "lyric-agent"})
    results = data.get("results") or []
    artist_lc = artist.lower()
    for r in results:
        if artist_lc and artist_lc in (r.get("artistName") or "").lower():
            return r.get("previewUrl") or ""
    return (results[0].get("previewUrl") or "") if results else ""


def _needs_fill(cache: dict, s: dict) -> bool:
    entry = cache.get(s["name"])
    if entry is None:
        return True
    return not entry.get("url") and \
        time.time() - entry.get("ts", 0) > _RETRY_AFTER_S


def fill_missing_async(songs: list[dict]) -> None:
    """后台线程为候选歌（API 层已筛好）补试听缓存；进程内只跑一次。"""
    global _fill_started
    with _lock:
        if _fill_started:
            return
        _fill_started = True
    todo = [s for s in songs if _needs_fill(_load_cache(), s)]
    if not todo:
        return

    def _run() -> None:
        hits = 0
        for s in todo:
            try:
                url = _search(s["title"], s["artist"])
            except Exception as e:
                logger.info("itunes search failed for %s: %s", s["name"], e)
                url = ""
            hits += bool(url)
            with _lock:
                cache = _load_cache()
                cache[s["name"]] = {"url": url, "ts": time.time()}
                _save_cache(cache)
            time.sleep(_THROTTLE_S)
        logger.info("itunes preview fill done: %d/%d hit", hits, len(todo))

    threading.Thread(target=_run, daemon=True,
                     name="itunes-preview-fill").start()
