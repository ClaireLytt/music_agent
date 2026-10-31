"""FastAPI 薄层冒烟：行为须与数据层一致（不搬业务逻辑）。"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from lyric_agent.api import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_list_songs(client):
    songs = client.get("/api/songs").json()
    assert isinstance(songs, list) and songs
    s = songs[0]
    for key in ("id", "title", "artist", "audio_type", "audio_offset_ms", "bvid"):
        assert key in s


def test_song_detail_and_404(client):
    songs = client.get("/api/songs").json()
    sid = songs[0]["id"]
    assert client.get(f"/api/songs/{sid}").json()["id"] == sid
    assert client.get("/api/songs/__nope__").status_code == 404


def test_lyrics_shape(client):
    sid = client.get("/api/songs").json()[0]["id"]
    data = client.get(f"/api/songs/{sid}/lyrics").json()
    assert data["timed_lines"], "lyrics.lrc 应已解析出时间轴行"
    line = data["timed_lines"][0]
    assert {"line_index", "timestamp_ms", "text"} <= set(line)
    # annotations 键是行号字符串
    for k, ann in data["annotations"].items():
        assert k == str(ann["line_index"])
        break


def test_dict_lookup(client):
    hit = client.get("/api/dict/sequin").json()
    assert hit["word"] == "sequin" and hit["translation"]
    assert client.get("/api/dict/zzzznotaword").status_code == 404


def test_mv_candidates_sorted_by_play(client, monkeypatch):
    import lyric_agent.bilibili as bilibili

    fake = [
        {"bvid": "BV1", "title": "a", "author": "", "duration": "1:0", "play": 50},
        {"bvid": "BV2", "title": "b", "author": "", "duration": "1:0", "play": 900},
        {"bvid": "BV3", "title": "c", "author": "", "duration": "1:0", "play": 300},
    ]
    monkeypatch.setattr(bilibili, "search_mv", lambda *a, **k: list(fake))
    sid = client.get("/api/songs").json()[0]["id"]
    plays = [c["play"] for c in
             client.get(f"/api/songs/{sid}/mv-candidates").json()]
    assert plays == [900, 300, 50]
