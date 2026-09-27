# -*- coding: utf-8 -*-
"""Check which hackathon-playlist songs are freely downloadable (128k mp3)."""
import json
import time
import urllib.request

HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}
PLAYLIST_ID = "9778975366"


def http_json(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


playlist = http_json(
    "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    f"?type=1&json=1&utf8=1&onlysong=0&disstid={PLAYLIST_ID}&format=json"
)
songs = playlist["cdlist"][0]["songlist"]
print(f"playlist songs: {len(songs)}")

results = []
BATCH = 10
for i in range(0, len(songs), BATCH):
    chunk = songs[i:i + BATCH]
    mids = [s["songmid"] for s in chunk]
    payload = {
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": "358840384",
                "songmid": mids,
                "songtype": [0] * len(mids),
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        },
        "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
    }
    url = ("https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data="
           + urllib.request.quote(json.dumps(payload)))
    try:
        resp = http_json(url)
        infos = resp["req_0"]["data"]["midurlinfo"]
    except Exception as exc:
        print(f"batch {i}: FAILED {exc}")
        infos = [{"purl": ""} for _ in mids]
    for s, info in zip(chunk, infos):
        singers = "/".join(x["name"] for x in s.get("singer", []))
        free = bool(info.get("purl"))
        results.append({"title": s["songname"], "singer": singers,
                        "mid": s["songmid"], "free": free})
    time.sleep(0.5)

free_list = [r for r in results if r["free"]]
paid_list = [r for r in results if not r["free"]]
print(f"\nfree to fetch (128k): {len(free_list)}")
print(f"needs VIP/payment: {len(paid_list)}")

with open("qq_playlist_downloadable.txt", "w", encoding="utf-8") as f:
    f.write("== 可免费获取（128k mp3）==\n")
    for r in free_list:
        f.write(f"{r['title']} — {r['singer']}\n")
    f.write("\n== 需要 VIP / 付费 ==\n")
    for r in paid_list:
        f.write(f"{r['title']} — {r['singer']}\n")
print("saved -> qq_playlist_downloadable.txt")
