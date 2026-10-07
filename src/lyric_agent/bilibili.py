"""Bilibili integration for the 📺 video playback mode.

Playback itself uses the OFFICIAL embed player (player.bilibili.com) — a
public capability. `search_mv` is a convenience helper hitting bilibili's
web search endpoint (NOT a public API): best-effort ladder — bare request →
WBI-signed + session-cookie retry → [] — so losing it only loses
convenience, never playback. Stream extraction/downloading is out of scope.

stdlib only (urllib/hashlib), mirroring lrc_sources.py's request style.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}
_SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

_BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")

# the documented reorder table for deriving the wbi mixin key (stable
# since 2023; see bilibili-API-collect docs/misc/sign/wbi.md)
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# day-stamped caches: wbi keys rotate daily, buvid3 is long-lived
_cache: dict = {}


def extract_bvid(text: str) -> str:
    """BV id from a bare id or any bilibili URL; "" when absent."""
    m = _BVID_RE.search(text or "")
    return m.group(0) if m else ""


_TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")


def ts_to_seconds(ts: str) -> int | None:
    """「1:32」/「01:02:03」(可带前后缀文字) → 秒；解析不出返回 None。"""
    m = _TS_RE.search(ts or "")
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h or 0) * 3600 + int(mm) * 60 + int(ss)


def embed_url(bvid: str) -> str:
    """Official embed player URL (no autoplay, danmaku off)."""
    return ("https://player.bilibili.com/player.html"
            f"?bvid={urllib.parse.quote(bvid)}&autoplay=0&danmaku=0")


def _get_json(url: str, headers: dict) -> dict:
    from .jsonio import http_get_json
    return http_get_json(url, headers)


def _mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def _wbi_sign(params: dict, mixin_key: str) -> dict:
    """Add wts + w_rid per the documented scheme (sorted, %-encoded, md5)."""
    signed = dict(params, wts=str(int(time.time())))
    query = urllib.parse.urlencode(
        sorted(signed.items()), quote_via=urllib.parse.quote, safe="")
    signed["w_rid"] = hashlib.md5(
        (query + mixin_key).encode("utf-8")).hexdigest()
    return signed


def _wbi_keys() -> str:
    """Today's mixin key, cached per day."""
    day = time.strftime("%Y-%m-%d")
    if _cache.get("wbi_day") != day:
        nav = _get_json(_NAV_URL, _HEADERS)
        img = nav["data"]["wbi_img"]["img_url"].rsplit("/", 1)[-1]
        sub = nav["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[-1]
        _cache["mixin"] = _mixin_key(img.split(".")[0], sub.split(".")[0])
        _cache["wbi_day"] = day
    return _cache["mixin"]


def _session_cookie() -> str:
    """Browser-like cookie set (buvid3/b_nut + bili_ticket + _uuid +
    b_lsid), cached per day. buvid3 alone now trips gaia risk control
    (code=0 with only v_voucher in data); this full set passes."""
    day = time.strftime("%Y-%m-%d")
    if _cache.get("cookie_day") != day:
        import hmac
        import http.cookiejar
        import random
        import uuid
        from .jsonio import http_get_json
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        with opener.open(urllib.request.Request(
                "https://www.bilibili.com/", headers=_HEADERS),
                timeout=10) as resp:
            resp.read(0)   # cookies land in the jar; body unwanted
        ck = {c.name: c.value for c in jar}
        ts = int(time.time())
        hexsign = hmac.new(b"XgwSnGZ1p", f"ts{ts}".encode(),
                           hashlib.sha256).hexdigest()
        ticket_url = (
            "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/"
            f"GenWebTicket?key_id=ec02&hexsign={hexsign}"
            f"&context[ts]={ts}&csrf=")
        tk = http_get_json(ticket_url, _HEADERS, method="POST")
        # 风控日接口会回 {"data": null} —— or {} 兜底,别让 None 炸链路
        ck["bili_ticket"] = (tk.get("data") or {}).get("ticket", "")
        ck["_uuid"] = str(uuid.uuid4()).upper() + "infoc"
        ck["b_lsid"] = (f"{random.getrandbits(32):08X}_"
                        f"{int(time.time() * 1000):X}")
        _cache["cookie"] = "; ".join(f"{k}={v}" for k, v in ck.items())
        _cache["cookie_day"] = day
    return _cache["cookie"]


def _strip_em(title: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", title or ""))


def _parse_results(data: dict, limit: int) -> list[dict]:
    items = (data.get("data") or {}).get("result") or []
    out = []
    for it in items:
        if it.get("type") not in (None, "video") or not it.get("bvid"):
            continue
        out.append({"bvid": it["bvid"], "title": _strip_em(it.get("title")),
                    "author": it.get("author", ""),
                    "duration": it.get("duration", ""),
                    "play": int(it.get("play", 0) or 0)})
        if len(out) >= limit:
            break
    return out


def pick_best(cands: list[dict], title: str) -> dict | None:
    """自动绑定的选片规则：标题必须含歌名，其中取播放量最高（用户决定：
    播放量优先于"标题含歌手名"）。全被淘汰时退回搜索相关性第一条。"""
    if not cands:
        return None
    t = title.casefold()
    pool = [c for c in cands if t in c["title"].casefold()]
    if not pool:
        return cands[0]
    return max(pool, key=lambda c: c.get("play", 0))


def search_mv(title: str, artist: str, limit: int = 20) -> list[dict]:
    """Top MV candidates for a song; [] on any failure (manual fallback)."""
    keyword = f"{title} {artist} MV".strip()
    params = {"search_type": "video", "keyword": keyword, "page": "1"}
    def _ok(data: dict) -> bool:
        # gaia risk control answers code=0 with only v_voucher in data —
        # treat "no result field" as failure so we fall through to retry
        return (data.get("code") == 0
                and "result" in (data.get("data") or {}))

    try:
        url = _SEARCH_URL + "?" + urllib.parse.urlencode(params)
        data = _get_json(url, _HEADERS)
        if _ok(data):
            return _parse_results(data, limit)
        logger.info("bare bilibili search got code=%s; retrying signed",
                    data.get("code"))
        signed = _wbi_sign(params, _wbi_keys())
        url = _SEARCH_URL + "?" + urllib.parse.urlencode(signed)
        headers = dict(_HEADERS, Cookie=_session_cookie())
        data = _get_json(url, headers)
        if _ok(data):
            return _parse_results(data, limit)
        logger.warning("bilibili search failed: code=%s", data.get("code"))
    except Exception as exc:  # network/parse — degrade to manual input
        logger.warning("bilibili search unavailable: %s", exc)
    return []


_AUTOBIND_FAIL_PATH = "data/cache/bvid_autobind.json"
_RETRY_AFTER_S = 24 * 3600
_THROTTLE_S = 3


def auto_bind_missing(songs: list[dict], is_enabled) -> int:
    """Background bulk binder: search + pick_best for every song without a
    bvid, writing metadata in place. Throttled; failures remembered for 24h
    so restarts don't re-hammer the search endpoint. Never raises.

    is_enabled: zero-arg callable checked before each song (kill switch).
    Returns the number of songs bound."""
    import json as _json
    import pathlib
    from .jsonio import read_json, write_json_atomic
    fail_path = pathlib.Path(_AUTOBIND_FAIL_PATH)
    fails = read_json(fail_path, {})
    if not isinstance(fails, dict):
        fails = {}
    bound = 0
    for s in songs:
        if not is_enabled():
            break
        if (s.get("bvid") or s.get("bvid_no_auto")
                or not s.get("title") or not s.get("dir")):
            continue
        if time.time() - fails.get(s["dir"], 0) < _RETRY_AFTER_S:
            continue
        try:
            best = pick_best(search_mv(s["title"], s.get("artist", "")),
                             s["title"])
            if best is None:
                raise LookupError("no candidates")
            meta_path = pathlib.Path(s["dir"]) / "metadata.json"
            meta = (_json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta_path.exists() else {})
            if not meta.get("bvid"):  # never overwrite a manual binding
                meta["bvid"] = best["bvid"]
                meta["bvid_source"] = "auto"
                meta_path.write_text(
                    _json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                bound += 1
                logger.info("auto-bound %s -> %s (%s)", s["title"],
                            best["bvid"], best["title"])
        except Exception as exc:
            fails[s["dir"]] = time.time()
            logger.info("auto-bind skipped %s: %s", s.get("title"), exc)
            try:
                write_json_atomic(fail_path, fails, indent=None)
            except OSError:
                pass
        time.sleep(_THROTTLE_S)
    return bound
