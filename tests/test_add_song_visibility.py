"""新加入的歌必须出现在左侧曲库列表（isolated_data 隔离真实 data/）。"""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

CJK_LRC = "\n".join(
    f"[00:{i:02d}.00]" + line for i, line in enumerate([
        "月亮代表我的心",
        "轻轻的一个吻",
        "你问我爱你有多深",
        "我爱你有几分",
    ]))


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    song = data / "songs" / "demo"
    song.mkdir(parents=True)
    (song / "lyrics.lrc").write_text(
        "[00:01.00]hello world\n", encoding="utf-8")
    (song / "metadata.json").write_text(json.dumps({
        "title": "demo", "artist": "tester", "album": "", "year": 0,
        "era": "", "themes": [],
    }), encoding="utf-8")
    (data / "wordbook.json").write_text("[]", encoding="utf-8")
    (data / "favorites.json").write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LL_SHOW_CJK", raising=False)
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    return data


@pytest.fixture
def client(isolated_data):
    from lyric_agent.api import create_app
    return TestClient(create_app())


def test_added_cjk_song_visible_in_list(client):
    r = client.post("/api/songs", json={
        "title": "yueliang", "artist": "teresa", "lrc_text": CJK_LRC})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    ids = [s["id"] for s in client.get("/api/songs").json()]
    assert sid in ids


def test_song_without_lrc_accepts_upload_later(client, monkeypatch):
    from lyric_agent import songdata
    monkeypatch.setattr(songdata, "_fetch_lrc_from_lrclib",
                        lambda *a, **k: None)
    r = client.post("/api/songs", json={"title": "no lrc yet"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    ids = [s["id"] for s in client.get("/api/songs").json()]
    assert sid in ids

    r = client.put(f"/api/songs/{sid}/lyrics",
                   json={"lrc_text": "[00:01.00]hello again\n"})
    assert r.status_code == 200, r.text
    lines = client.get(f"/api/songs/{sid}/lyrics").json()["timed_lines"]
    assert any("hello again" in ln["text"] for ln in lines)


def test_same_title_different_artist_both_addable(client, monkeypatch):
    from lyric_agent import songdata
    monkeypatch.setattr(songdata, "_fetch_lrc_from_lrclib",
                        lambda *a, **k: None)
    r1 = client.post("/api/songs",
                     json={"title": "Lonely", "artist": "Justin Bieber"})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/songs",
                     json={"title": "Lonely", "artist": "Akon"})
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] != r2.json()["id"]
    songs = client.get("/api/songs").json()
    ids = [s["id"] for s in songs]
    assert r1.json()["id"] in ids and r2.json()["id"] in ids

    r3 = client.post("/api/songs",
                     json={"title": "Lonely", "artist": "Akon"})
    assert r3.status_code == 409


def test_upload_lyrics_rejects_unparseable(client, monkeypatch):
    from lyric_agent import songdata
    monkeypatch.setattr(songdata, "_fetch_lrc_from_lrclib",
                        lambda *a, **k: None)
    sid = client.post("/api/songs",
                      json={"title": "bad lrc"}).json()["id"]
    r = client.put(f"/api/songs/{sid}/lyrics",
                   json={"lrc_text": "no timestamps here"})
    assert r.status_code == 422
