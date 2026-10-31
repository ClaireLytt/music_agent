"""【实验性，可整体移除】B 站 MV 音轨代理 —— 无本地 mp3 的歌直接播 MV 音轨。

调研依据 docs/research_bilibili_sync.md / research_audio_sources.md：
playurl 免登录可取整首 DASH 音轨（~192K AAC），但流 URL 必须带
Referer: bilibili.com（浏览器设不了）→ 本模块做本地转发代理。
非公开接口灰色地带：public 模式一律禁用。

删除该功能 = 删掉本文件 + api.py 中两处标记 "B站音轨代理" 的小块
+ frontend/src/api.ts 类型里的 "bilibili" 一词。

stdlib only（urllib），请求风格与 bilibili.py 一致。
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Iterator

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_API_HEADERS = {"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}
_PAGELIST_URL = "https://api.bilibili.com/x/player/pagelist"
_PLAYURL_URL = "https://api.bilibili.com/x/player/playurl"

_CHUNK = 64 * 1024
# bvid -> (stream_url, mime, expire_ts)；playurl 地址约 2h 过期，
# URL 自带 deadline= 时间戳，取不到就按 1h 保守估计
_stream_cache: dict[str, tuple[str, str, float]] = {}
_DEADLINE_RE = re.compile(r"[?&]deadline=(\d+)")


def enabled(settings) -> bool:
    """public 演示模式禁用（非公开接口不对外提供）。"""
    return not settings.public_mode


def _get_json(url: str, params: dict) -> dict:
    from .jsonio import http_get_json
    full = url + "?" + urllib.parse.urlencode(params)
    return http_get_json(full, _API_HEADERS)


def _fetch_stream_url(bvid: str) -> tuple[str, str]:
    """playurl → (音轨流 URL, mime)。取 DASH 音轨里码率最高的一条。"""
    pages = _get_json(_PAGELIST_URL, {"bvid": bvid})
    cid = pages["data"][0]["cid"]
    play = _get_json(_PLAYURL_URL, {"bvid": bvid, "cid": cid, "fnval": 16})
    audios = (play.get("data", {}).get("dash", {}) or {}).get("audio") or []
    if not audios:
        raise LookupError(f"no dash audio for {bvid}")
    best = max(audios, key=lambda a: a.get("bandwidth", 0))
    return best["baseUrl"], best.get("mimeType") or "audio/mp4"


def _stream_url(bvid: str, fresh: bool = False) -> tuple[str, str]:
    cached = None if fresh else _stream_cache.get(bvid)
    if cached and cached[2] > time.time():
        return cached[0], cached[1]
    url, mime = _fetch_stream_url(bvid)
    m = _DEADLINE_RE.search(url)
    expire = (int(m.group(1)) if m else time.time() + 3600) - 300
    _stream_cache[bvid] = (url, mime, expire)
    return url, mime


def _open_stream(bvid: str, range_header: str | None):
    """打开上游流（带 Referer），URL 过期 403 时强刷一次重试。"""
    stream_headers = {"User-Agent": _UA,
                      "Referer": "https://www.bilibili.com/"}
    if range_header:
        stream_headers["Range"] = range_header
    for fresh in (False, True):
        url, mime = _stream_url(bvid, fresh=fresh)
        req = urllib.request.Request(url, headers=stream_headers)
        try:
            return urllib.request.urlopen(req, timeout=15), mime
        except urllib.error.HTTPError as e:
            if e.code in (403, 404) and not fresh:
                logger.info("bilibili stream URL stale for %s, refreshing",
                            bvid)
                continue
            raise
    raise RuntimeError("unreachable")


def proxy_response(bvid: str, range_header: str | None):
    """FastAPI StreamingResponse：把 B 站音轨转发给浏览器 <audio>，
    透传 Range/206 以支持拖进度条。"""
    from fastapi.responses import StreamingResponse

    upstream, mime = _open_stream(bvid, range_header)

    def _body() -> Iterator[bytes]:
        try:
            while chunk := upstream.read(_CHUNK):
                yield chunk
        finally:
            upstream.close()

    headers = {"Accept-Ranges": "bytes"}
    for h in ("Content-Range", "Content-Length"):
        v = upstream.headers.get(h)
        if v:
            headers[h] = v
    # 上游常报 application/octet-stream，<audio> 不认 → 用 playurl 的 mime
    upstream_type = upstream.headers.get("Content-Type") or ""
    if not upstream_type.startswith("audio/"):
        upstream_type = mime
    return StreamingResponse(
        _body(), status_code=upstream.status, media_type=upstream_type,
        headers=headers)
