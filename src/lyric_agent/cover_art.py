"""【实验性，可整体移除】专辑封面自动抓取（docs/research_album_art.md）。

解析链：data/songs/<id>/cover.jpg 本地文件（可手动放图覆盖）
  → iTunes Search artworkUrl100（实测可升 600x600，CDN 可直连但仍落盘）
  → MusicBrainz + Cover Art Archive（官方免费；archive.org 国内不稳 → 落盘）
  → B 站绑定 MV 封面（view API 的 pic，仅 MV 图，末位兜底）
  → 全失败：前端保持现有占位渐变。

命中即下载保存为 cover.jpg（之后零网络）；未命中记入
data/cache/cover_art.json 负缓存（24h 后重试）。public 模式不写盘，禁用。

删除该功能 = 删本文件 + api.py 标记 "专辑封面" 的小块
+ PlayerBar 的 <img> 分支。stdlib only，请求风格同 bilibili.py。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_UA = "lyric-agent/1.0 (album art fetcher)"
_NEG_CACHE = Path("data/cache/cover_art.json")
_RETRY_AFTER_S = 24 * 3600
_COVER_EXTS = ("jpg", "jpeg", "png", "webp")

_lock = threading.Lock()
_inflight: set[str] = set()


def find_local(song_dir: str | Path) -> Path | None:
    for ext in _COVER_EXTS:
        p = Path(song_dir) / f"cover.{ext}"
        if p.exists():
            return p
    return None


def _get(url: str, timeout: int = 12, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


def _from_itunes(title: str, artist: str) -> bytes | None:
    q = urllib.parse.urlencode({
        "term": f"{title} {artist}".strip(), "media": "music",
        "entity": "song", "limit": 5})
    results = _get_json(f"https://itunes.apple.com/search?{q}").get("results") or []
    artist_lc = artist.lower()
    pick = next((r for r in results
                 if artist_lc and artist_lc in (r.get("artistName") or "").lower()),
                results[0] if results else None)
    art = (pick or {}).get("artworkUrl100") or ""
    if not art:
        return None
    # 600x600 是广泛可用的放大变体但非官方契约——失败回落原始 100x100
    for candidate in (art.replace("100x100bb", "600x600bb"), art):
        try:
            return _get(candidate)
        except Exception:
            continue
    return None


def _from_caa(title: str, artist: str, album: str) -> bytes | None:
    query = f'release:"{album or title}" AND artist:"{artist}"'
    q = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": "3"})
    data = _get_json(f"https://musicbrainz.org/ws/2/release/?{q}")
    for rel in data.get("releases") or []:
        try:
            return _get(f"https://coverartarchive.org/release/{rel['id']}/front-500",
                        timeout=20)
        except Exception:
            continue
    return None


def _from_bilibili(bvid: str) -> bytes | None:
    data = _get_json("https://api.bilibili.com/x/web-interface/view?bvid="
                     + urllib.parse.quote(bvid))
    pic = (data.get("data") or {}).get("pic") or ""
    if not pic:
        return None
    return _get(pic.replace("http://", "https://", 1))


def _neg() -> dict:
    try:
        return json.loads(_NEG_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fetch(song: dict) -> None:
    name = song["name"]
    try:
        img: bytes | None = None
        for src, fn in (
            ("itunes", lambda: _from_itunes(song["title"], song["artist"])),
            ("caa", lambda: _from_caa(song["title"], song["artist"],
                                      song.get("album", ""))),
            ("bilibili", lambda: _from_bilibili(song["bvid"])
                if song.get("bvid") else None),
        ):
            try:
                img = fn()
            except Exception as e:
                logger.info("cover source %s failed for %s: %s", src, name, e)
                img = None
            if img and len(img) > 2000:   # 过滤错误页/空图
                (Path(song["dir"]) / "cover.jpg").write_bytes(img)
                logger.info("cover saved for %s via %s (%d bytes)",
                            name, src, len(img))
                return
        with _lock:
            neg = _neg()
            neg[name] = time.time()
            _NEG_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _NEG_CACHE.write_text(json.dumps(neg, ensure_ascii=False),
                                  encoding="utf-8")
    finally:
        _inflight.discard(name)


_prewarm_started = False


def prewarm_async(songs: list[dict]) -> None:
    """列表加载时批量预热缺失封面：单线程串行 + 3s 节流（iTunes
    ~20 req/min），进程内只跑一次。命中过负缓存/已有本地图的跳过。
    调用方负责 public 门禁（public 不写服务器盘）。"""
    global _prewarm_started
    with _lock:
        if _prewarm_started:
            return
        _prewarm_started = True
    todo = [s for s in songs
            if not find_local(s["dir"])
            and time.time() - _neg().get(s["name"], 0) >= _RETRY_AFTER_S]
    if not todo:
        return

    def _run() -> None:
        logger.info("cover prewarm: %d songs missing covers", len(todo))
        for s in todo:
            with _lock:
                if s["name"] in _inflight:
                    continue
                _inflight.add(s["name"])
            _fetch(s)   # 自带 finally 释放 _inflight
            time.sleep(3)

    threading.Thread(target=_run, daemon=True,
                     name="cover-prewarm").start()


def fetch_async(song: dict) -> None:
    """后台补抓一首歌的封面；进程内去重 + 24h 负缓存。"""
    name = song["name"]
    with _lock:
        if name in _inflight:
            return
        if time.time() - _neg().get(name, 0) < _RETRY_AFTER_S:
            return
        _inflight.add(name)
    threading.Thread(target=_fetch, args=(song,), daemon=True,
                     name=f"cover-{name}").start()
