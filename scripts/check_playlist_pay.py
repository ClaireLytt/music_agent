# -*- coding: utf-8 -*-
"""Inspect pay flags for hackathon playlist songs."""
import json
import urllib.request

HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}

req = urllib.request.Request(
    "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    "?type=1&json=1&utf8=1&onlysong=0&disstid=9778975366&format=json",
    headers=HEADERS,
)
with urllib.request.urlopen(req, timeout=15) as r:
    songs = json.loads(r.read().decode("utf-8"))["cdlist"][0]["songlist"]

print("sample pay fields of first song:")
print(json.dumps(songs[0].get("pay", {}), ensure_ascii=False))
print("sample keys:", sorted(songs[0].keys()))

free_play, vip_play = [], []
for s in songs:
    pay = s.get("pay", {})
    singers = "/".join(x["name"] for x in s.get("singer", []))
    label = f"{s['songname']} — {singers}"
    if pay.get("payplay", 0) == 0:
        free_play.append((label, pay.get("paydownload", 0)))
    else:
        vip_play.append(label)

print(f"\nfree to PLAY (payplay=0): {len(free_play)}")
print(f"VIP needed to play (payplay=1): {len(vip_play)}")

with open("qq_playlist_downloadable.txt", "w", encoding="utf-8") as f:
    f.write("== 免费可听（客户端登录后即可播放，多数可免费下载标准音质）==\n")
    for label, pd in free_play:
        f.write(f"{label}\n")
    f.write(f"\n== 需要 VIP 才能完整播放（共 {len(vip_play)} 首）==\n")
    for label in vip_play:
        f.write(f"{label}\n")
print("saved -> qq_playlist_downloadable.txt")
