# -*- coding: utf-8 -*-
"""Check if free try-listen (试听) segments are available for playlist songs."""
import json
import urllib.parse
import urllib.request

HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


songs = http_json(
    "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    "?type=1&json=1&utf8=1&onlysong=0&disstid=9778975366&format=json"
)["cdlist"][0]["songlist"]

# take 3 VIP-marked songs + 1 free song
samples = [s for s in songs if s["pay"]["payplay"] == 1][:3]
samples += [s for s in songs if s["pay"]["payplay"] == 0][:1]

for s in samples:
    mid, media = s["songmid"], s.get("strMediaMid") or s["songmid"]
    print(f"\n{s['songname']} (payplay={s['pay']['payplay']})")
    print("  preview field:", json.dumps(s.get("preview", {}), ensure_ascii=False))
    # try-listen segment: RS02 prefix on media mid
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
    try:
        info = http_json(url)["req_0"]["data"]["midurlinfo"][0]
        purl = info.get("purl", "")
        print("  try-segment purl:", (purl[:80] + "...") if purl else "(empty)")
    except Exception as exc:
        print("  vkey failed:", exc)
