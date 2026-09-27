# -*- coding: utf-8 -*-
"""Build the built-in song catalog (data/catalog/catalog.json).

Fetches synced lyrics from LRCLIB for a curated multi-artist song list
(Taylor Swift + popular Chinese & western artists). Songs without synced
lyrics are skipped.

Usage: python scripts/build_catalog.py
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "catalog" / "catalog.json"

TS = "Taylor Swift"

# (artist, title, album, era)  — era 仅 Taylor Swift 用于艺术家图谱
SONGS: list[tuple[str, str, str, str]] = [
    # ══ Taylor Swift ══
    (TS, "Tim McGraw", "Taylor Swift", "debut"),
    (TS, "Teardrops on My Guitar", "Taylor Swift", "debut"),
    (TS, "Our Song", "Taylor Swift", "debut"),
    (TS, "Picture to Burn", "Taylor Swift", "debut"),
    (TS, "Love Story", "Fearless", "fearless"),
    (TS, "You Belong with Me", "Fearless", "fearless"),
    (TS, "Fifteen", "Fearless", "fearless"),
    (TS, "Fearless", "Fearless", "fearless"),
    (TS, "White Horse", "Fearless", "fearless"),
    (TS, "The Best Day", "Fearless", "fearless"),
    (TS, "Mine", "Speak Now", "speak now"),
    (TS, "Back to December", "Speak Now", "speak now"),
    (TS, "Sparks Fly", "Speak Now", "speak now"),
    (TS, "Dear John", "Speak Now", "speak now"),
    (TS, "Mean", "Speak Now", "speak now"),
    (TS, "Enchanted", "Speak Now", "speak now"),
    (TS, "Long Live", "Speak Now", "speak now"),
    (TS, "Speak Now", "Speak Now", "speak now"),
    (TS, "Red", "Red", "red"),
    (TS, "22", "Red", "red"),
    (TS, "I Knew You Were Trouble", "Red", "red"),
    (TS, "We Are Never Ever Getting Back Together", "Red", "red"),
    (TS, "Begin Again", "Red", "red"),
    (TS, "State of Grace", "Red", "red"),
    (TS, "Everything Has Changed", "Red", "red"),
    (TS, "Treacherous", "Red", "red"),
    (TS, "Shake It Off", "1989", "1989"),
    (TS, "Blank Space", "1989", "1989"),
    (TS, "Style", "1989", "1989"),
    (TS, "Bad Blood", "1989", "1989"),
    (TS, "Wildest Dreams", "1989", "1989"),
    (TS, "Out of the Woods", "1989", "1989"),
    (TS, "Clean", "1989", "1989"),
    (TS, "New Romantics", "1989", "1989"),
    (TS, "Look What You Made Me Do", "reputation", "reputation"),
    (TS, "Delicate", "reputation", "reputation"),
    (TS, "...Ready for It?", "reputation", "reputation"),
    (TS, "End Game", "reputation", "reputation"),
    (TS, "Gorgeous", "reputation", "reputation"),
    (TS, "Getaway Car", "reputation", "reputation"),
    (TS, "Call It What You Want", "reputation", "reputation"),
    (TS, "Dress", "reputation", "reputation"),
    (TS, "ME!", "Lover", "lover"),
    (TS, "You Need to Calm Down", "Lover", "lover"),
    (TS, "Lover", "Lover", "lover"),
    (TS, "The Archer", "Lover", "lover"),
    (TS, "Cruel Summer", "Lover", "lover"),
    (TS, "Paper Rings", "Lover", "lover"),
    (TS, "Cornelia Street", "Lover", "lover"),
    (TS, "Daylight", "Lover", "lover"),
    (TS, "the 1", "folklore", "folklore"),
    (TS, "betty", "folklore", "folklore"),
    (TS, "august", "folklore", "folklore"),
    (TS, "my tears ricochet", "folklore", "folklore"),
    (TS, "invisible string", "folklore", "folklore"),
    (TS, "illicit affairs", "folklore", "folklore"),
    (TS, "mirrorball", "folklore", "folklore"),
    (TS, "seven", "folklore", "folklore"),
    (TS, "peace", "folklore", "folklore"),
    (TS, "this is me trying", "folklore", "folklore"),
    (TS, "willow", "evermore", "evermore"),
    (TS, "no body, no crime", "evermore", "evermore"),
    (TS, "gold rush", "evermore", "evermore"),
    (TS, "'tis the damn season", "evermore", "evermore"),
    (TS, "tolerate it", "evermore", "evermore"),
    (TS, "happiness", "evermore", "evermore"),
    (TS, "ivy", "evermore", "evermore"),
    (TS, "cowboy like me", "evermore", "evermore"),
    (TS, "Lavender Haze", "Midnights", "midnights"),
    (TS, "Maroon", "Midnights", "midnights"),
    (TS, "Snow on the Beach", "Midnights", "midnights"),
    (TS, "You're on Your Own, Kid", "Midnights", "midnights"),
    (TS, "Midnight Rain", "Midnights", "midnights"),
    (TS, "Bejeweled", "Midnights", "midnights"),
    (TS, "Karma", "Midnights", "midnights"),
    (TS, "Mastermind", "Midnights", "midnights"),
    # ══ 周杰伦 ══
    ("周杰伦", "晴天", "叶惠美", ""),
    ("周杰伦", "七里香", "七里香", ""),
    ("周杰伦", "稻香", "魔杰座", ""),
    ("周杰伦", "告白气球", "周杰伦的床边故事", ""),
    ("周杰伦", "夜曲", "十一月的萧邦", ""),
    ("周杰伦", "青花瓷", "我很忙", ""),
    ("周杰伦", "简单爱", "范特西", ""),
    ("周杰伦", "搁浅", "七里香", ""),
    ("周杰伦", "安静", "范特西", ""),
    ("周杰伦", "不能说的秘密", "不能说的秘密电影原声带", ""),
    # ══ 林俊杰 ══
    ("林俊杰", "江南", "第二天堂", ""),
    ("林俊杰", "修炼爱情", "因你而在", ""),
    ("林俊杰", "不为谁而作的歌", "和自己对话", ""),
    ("林俊杰", "可惜没如果", "新地球", ""),
    ("林俊杰", "那些你很冒险的梦", "学不会", ""),
    # ══ 陈奕迅 ══
    ("陈奕迅", "十年", "黑白灰", ""),
    ("陈奕迅", "富士山下", "What's Going On", ""),
    ("陈奕迅", "浮夸", "U87", ""),
    ("陈奕迅", "好久不见", "认了吧", ""),
    ("陈奕迅", "孤勇者", "孤勇者", ""),
    # ══ 邓紫棋 ══
    ("邓紫棋", "光年之外", "光年之外", ""),
    ("邓紫棋", "泡沫", "Xposed", ""),
    ("邓紫棋", "倒数", "另一个童话", ""),
    # ══ 薛之谦 ══
    ("薛之谦", "演员", "初学者", ""),
    ("薛之谦", "丑八怪", "意外", ""),
    ("薛之谦", "认真的雪", "薛之谦", ""),
    # ══ 王菲 ══
    ("王菲", "红豆", "唱游", ""),
    ("王菲", "传奇", "传奇", ""),
    ("王菲", "匆匆那年", "匆匆那年", ""),
    # ══ 五月天 ══
    ("五月天", "突然好想你", "后青春期的诗", ""),
    ("五月天", "倔强", "神的孩子都在跳舞", ""),
    ("五月天", "温柔", "爱情万岁", ""),
    ("五月天", "后来的我们", "自传", ""),
    # ══ 朴树 / 赵雷 / 毛不易 / 李荣浩 ══
    ("朴树", "平凡之路", "猎户星座", ""),
    ("朴树", "那些花儿", "我去2000年", ""),
    ("赵雷", "成都", "无法长大", ""),
    ("毛不易", "消愁", "平凡的一天", ""),
    ("毛不易", "像我这样的人", "平凡的一天", ""),
    ("李荣浩", "年少有为", "耳朵", ""),
    ("李荣浩", "李白", "模特", ""),
    # ══ Ed Sheeran ══
    ("Ed Sheeran", "Shape of You", "÷ (Divide)", ""),
    ("Ed Sheeran", "Perfect", "÷ (Divide)", ""),
    ("Ed Sheeran", "Photograph", "x (Multiply)", ""),
    ("Ed Sheeran", "Thinking Out Loud", "x (Multiply)", ""),
    # ══ Adele ══
    ("Adele", "Hello", "25", ""),
    ("Adele", "Someone Like You", "21", ""),
    ("Adele", "Rolling in the Deep", "21", ""),
    ("Adele", "Easy On Me", "30", ""),
    # ══ Billie Eilish ══
    ("Billie Eilish", "bad guy", "When We All Fall Asleep, Where Do We Go?", ""),
    ("Billie Eilish", "lovely", "lovely", ""),
    ("Billie Eilish", "ocean eyes", "dont smile at me", ""),
    ("Billie Eilish", "What Was I Made For?", "Barbie The Album", ""),
    # ══ Coldplay ══
    ("Coldplay", "Yellow", "Parachutes", ""),
    ("Coldplay", "Fix You", "X&Y", ""),
    ("Coldplay", "Viva La Vida", "Viva la Vida or Death and All His Friends", ""),
    ("Coldplay", "The Scientist", "A Rush of Blood to the Head", ""),
    # ══ Bruno Mars ══
    ("Bruno Mars", "Just the Way You Are", "Doo-Wops & Hooligans", ""),
    ("Bruno Mars", "When I Was Your Man", "Unorthodox Jukebox", ""),
    ("Bruno Mars", "Grenade", "Doo-Wops & Hooligans", ""),
    # ══ The Weeknd ══
    ("The Weeknd", "Blinding Lights", "After Hours", ""),
    ("The Weeknd", "Save Your Tears", "After Hours", ""),
    # ══ Olivia Rodrigo ══
    ("Olivia Rodrigo", "drivers license", "SOUR", ""),
    ("Olivia Rodrigo", "good 4 u", "SOUR", ""),
    ("Olivia Rodrigo", "vampire", "GUTS", ""),
]


def _artist_match(want: str, got: str) -> bool:
    w, g = want.lower(), (got or "").lower()
    return w in g or g in w if g else False


def fetch_synced(artist: str, title: str, album: str) -> str | None:
    query = urllib.parse.quote(f"{artist} {title}".strip())
    req = urllib.request.Request(
        f"https://lrclib.net/api/search?q={query}",
        headers={"User-Agent": "lyric-agent/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        results = json.loads(resp.read().decode("utf-8"))
    synced = [e for e in results if e.get("syncedLyrics")]
    if not synced:
        return None
    album_l = album.lower()
    # 1. album + artist match  2. artist match  3. exact title  4. first
    for e in synced:
        if album_l and album_l in (e.get("albumName") or "").lower() \
                and _artist_match(artist, e.get("artistName", "")):
            return e["syncedLyrics"]
    for e in synced:
        if _artist_match(artist, e.get("artistName", "")):
            return e["syncedLyrics"]
    for e in synced:
        if (e.get("trackName") or "").lower() == title.lower():
            return e["syncedLyrics"]
    return synced[0]["syncedLyrics"]


def main() -> None:
    entries = []
    for i, (artist, title, album, era) in enumerate(SONGS, 1):
        lrc = None
        for attempt in range(2):  # one retry for transient 5xx
            try:
                lrc = fetch_synced(artist, title, album)
                break
            except Exception as exc:
                if attempt == 1:
                    print(f"[{i}/{len(SONGS)}] ERROR  {artist} - {title}: {exc}",
                          flush=True)
                else:
                    time.sleep(2)
        if lrc:
            entries.append({
                "title": title, "artist": artist,
                "album": album, "era": era, "lrc": lrc,
            })
            print(f"[{i}/{len(SONGS)}] OK     {artist} - {title}", flush=True)
        else:
            print(f"[{i}/{len(SONGS)}] SKIP   {artist} - {title}", flush=True)
        time.sleep(0.4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSaved {len(entries)} songs -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
