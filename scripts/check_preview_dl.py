# -*- coding: utf-8 -*-
"""Verify: (1) try-segment mp3 actually downloads; (2) QQ lyric API returns timestamped LRC."""
import base64
import json
import re
import urllib.parse
import urllib.request

HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}
STREAM_HOSTS = [
    "https://isure.stream.qqmusic.qq.com/",
    "https://ws.stream.qqmusic.qq.com/",
    "https://dl.stream.qqmusic.qq.com/",
]


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


songs = http_json(
    "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    "?type=1&json=1&utf8=1&onlysong=0&disstid=9778975366&format=json"
)["cdlist"][0]["songlist"]

# pick one VIP song: 北京昨夜下了雪
song = next(s for s in songs if s["songname"] == "北京昨夜下了雪")
mid, media = song["songmid"], song.get("strMediaMid") or song["songmid"]
print(f"song: {song['songname']}  mid={mid}")
print("preview:", json.dumps(song.get("preview", {}), ensure_ascii=False))

payload = {
    "req_0": {
        "module": "vkey.GetVkeyServer",
        "method": "CgiGetVkey",
        "param": {
            "guid": "358840384",
            "songmid": [mid],
            "songtype": [0],
            "filename": [f"RS02{media}.mp3"],
            "uin": "0",
            "loginflag": 1,
            "platform": "20",
        },
    },
    "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
}
url = ("https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data="
       + urllib.parse.quote(json.dumps(payload)))
purl = http_json(url)["req_0"]["data"]["midurlinfo"][0]["purl"]
print("purl ok:", bool(purl))

for host in STREAM_HOSTS:
    try:
        req = urllib.request.Request(host + purl, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        print(f"{host} -> {len(data)} bytes, starts with {data[:3]!r}")
        with open("preview_test.mp3", "wb") as f:
            f.write(data)
        print("saved preview_test.mp3")
        break
    except Exception as exc:
        print(f"{host} -> FAILED: {exc}")

# --- lyric API ---
lyr_url = (
    "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    f"?songmid={mid}&format=json&nobase64=0&g_tk=5381"
)
lyr = http_json(lyr_url)
raw = lyr.get("lyric", "")
if raw:
    lrc = base64.b64decode(raw).decode("utf-8", errors="replace")
    stamped = re.findall(r"\[\d{1,2}:\d{2}", lrc)
    print(f"\nlyric ok: {len(lrc)} chars, {len(stamped)} timestamped lines")
    print("first 300 chars:")
    print(lrc[:300])
else:
    print("\nlyric FAILED:", json.dumps(lyr)[:200])
