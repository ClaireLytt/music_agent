"""曲库搜索相关性：标题命中 > 歌手命中 > 歌词全文命中（isolated_data 隔离）。"""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _mk_song(root, slug, title, artist, lines, album=""):
    d = root / "songs" / slug
    d.mkdir(parents=True)
    d_lrc = "\n".join(f"[00:{i:02d}.00]{t}" for i, t in enumerate(lines, 1))
    (d / "lyrics.lrc").write_text(d_lrc + "\n", encoding="utf-8")
    (d / "metadata.json").write_text(json.dumps({
        "title": title, "artist": artist, "album": album, "year": 0,
        "era": "", "themes": [],
    }), encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _mk_song(data, "a_my_shot", "My Shot", "hamilton",
             ["the blood we shed begin an endless"])
    _mk_song(data, "b_vampire", "vampire", "Olivia Rodrigo",
             ["bloodsucker, fame fucker"])
    _mk_song(data, "z_bad_blood", "Bad Blood", "Taylor Swift",
             ["now we got bad blood"])
    _mk_song(data, "c_blood_artist", "Six Feet Under", "Bloodhound Gang",
             ["something else entirely"])
    _mk_song(data, "e_blood_album", "Let's Fall in Love for the Night",
             "FINNEAS", ["nothing matching here"], album="Blood Harmony")
    (data / "wordbook.json").write_text("[]", encoding="utf-8")
    (data / "favorites.json").write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    from lyric_agent.api import create_app
    return TestClient(create_app())


def test_title_match_ranks_first(client):
    ids = [s["id"] for s in client.get("/api/songs?q=blood").json()]
    assert ids[0] == "z_bad_blood", ids
    assert ids[1] == "c_blood_artist", ids
    assert ids[2] == "e_blood_album", ids
    assert set(ids[3:]) == {"a_my_shot", "b_vampire"}


def test_album_query_finds_song(client):
    ids = [s["id"] for s in client.get("/api/songs?q=harmony").json()]
    assert ids == ["e_blood_album"]


def test_no_query_keeps_full_list(client):
    assert len(client.get("/api/songs").json()) == 5
