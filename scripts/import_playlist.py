# -*- coding: utf-8 -*-
"""Import songs from the TME Hackathon reference playlist (QQ Music 9778975366).

For each selected song this fetches the official timestamped LRC and the free
try-listen mp3 segment (available to guests for every song), then creates a
song directory under data/songs/ with audio_offset_ms so lyric sync aligns.

Usage:
  python scripts/import_playlist.py --list          # show numbered songs
  python scripts/import_playlist.py 9 12            # import by number
  python scripts/import_playlist.py 北京昨夜下了雪    # import by title
"""
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PLAYLIST_ID = "9778975366"
HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}
STREAM_HOST = "https://isure.stream.qqmusic.qq.com/"
SONGS_DIR = Path("data/songs")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def http_json(url: str) -> dict:
    return json.loads(http_get(url).decode("utf-8"))


def fetch_playlist() -> list[dict]:
    data = http_json(
        "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
        f"?type=1&json=1&utf8=1&onlysong=0&disstid={PLAYLIST_ID}&format=json")
    return data["cdlist"][0]["songlist"]


def fetch_lyric(songmid: str) -> str | None:
    data = http_json(
        "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
        f"?songmid={songmid}&format=json&nobase64=0&g_tk=5381")
    raw = data.get("lyric", "")
    if not raw:
        return None
    return base64.b64decode(raw).decode("utf-8", errors="replace")


def fetch_preview(songmid: str, media_mid: str) -> bytes | None:
    payload = {
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": "358840384",
                "songmid": [songmid],
                "songtype": [0],
                "filename": [f"RS02{media_mid}.mp3"],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        },
        "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
    }
    url = ("https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data="
           + urllib.parse.quote(json.dumps(payload)))
    purl = http_json(url)["req_0"]["data"]["midurlinfo"][0].get("purl", "")
    if not purl:
        return None
    return http_get(STREAM_HOST + purl)


def slugify(title: str) -> str:
    slug = re.sub(r'[\\/:*?"<>|\s]+', "_", title.strip()).strip("_")
    return slug or "untitled"


def import_song(song: dict) -> bool:
    title = song["songname"]
    artist = "/".join(x["name"] for x in song.get("singer", []))
    album = song.get("albumname", "")
    mid = song["songmid"]
    media = song.get("strMediaMid") or mid
    preview_info = song.get("preview", {}) or {}
    trybegin = int(preview_info.get("trybegin", 0) or 0)

    dest = SONGS_DIR / slugify(title)
    if dest.exists():
        print(f"  跳过（目录已存在）: {dest}")
        return False

    lrc = fetch_lyric(mid)
    if not lrc or "[0" not in lrc:
        print(f"  ✗ 无带时间戳歌词，跳过: {title}")
        return False

    audio = fetch_preview(mid, media)

    dest.mkdir(parents=True)
    (dest / "lyrics.lrc").write_text(lrc, encoding="utf-8")
    meta = {
        "title": title,
        "artist": artist,
        "album": album,
        "source": "tme_hackathon_playlist",
    }
    if audio:
        (dest / "audio.mp3").write_bytes(audio)
        meta["audio_offset_ms"] = trybegin
    meta_path = dest / "metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    seg = f"，试听片段 {len(audio)//1024}KB（偏移 {trybegin}ms）" if audio else "，无音频"
    print(f"  ✓ {title} — {artist} → {dest}{seg}")
    return True


def main() -> None:
    args = sys.argv[1:]
    songs = fetch_playlist()
    if not args or args[0] == "--list":
        for i, s in enumerate(songs, 1):
            singers = "/".join(x["name"] for x in s.get("singer", []))
            print(f"{i:3d}. {s['songname']} — {singers}")
        return
    imported = 0
    for arg in args:
        if arg.isdigit() and 1 <= int(arg) <= len(songs):
            song = songs[int(arg) - 1]
        else:
            song = next((s for s in songs if s["songname"] == arg), None)
            if song is None:
                print(f"  ✗ 未找到: {arg}")
                continue
        if import_song(song):
            imported += 1
    print(f"\n共导入 {imported} 首。下一步可运行标注："
          "python scripts/generate_all.py")


if __name__ == "__main__":
    main()
