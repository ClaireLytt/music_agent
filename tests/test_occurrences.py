"""occurrences API：lemma 归并检索曲库出现（隔离 tmp 数据树）。"""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _song_dir(data, slug, title, annotated_indices=None):
    d = data / "songs" / slug
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({
        "title": title, "artist": "tester", "album": "", "year": 0,
        "era": "", "themes": [],
    }), encoding="utf-8")
    if annotated_indices:
        (d / "annotations.json").write_text(json.dumps({
            "song": {"title": title, "artist": "tester", "album": "",
                     "year": 0, "era": ""},
            "annotations": [{"line_index": i, "annotation": "x"}
                            for i in annotated_indices],
        }), encoding="utf-8")
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    entries = [
        {"title": "Alpha", "artist": "tester", "album": "", "lyrics_lines": [
            "I run every night",
            "She ran away",
            "Shine bright",
            "Shine bright",
            "快跑快跑 run 快跑快跑",
        ]},
        {"title": "Beta", "artist": "tester", "album": "", "lyrics_lines": [
            "Running wild tonight",
            "A quiet storm",
        ]},
        {"title": "Gamma", "artist": "tester", "album": "", "lyrics_lines": [
            "Dreams of gold",
            "They ran together",
        ]},
    ]
    (corpus / "discography.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8")
    _song_dir(data, "alpha", "Alpha")
    _song_dir(data, "beta", "Beta")
    _song_dir(data, "gamma", "Gamma", annotated_indices=[1])
    (data / "wordbook.json").write_text("[]", encoding="utf-8")
    (data / "favorites.json").write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from lyric_agent.api import create_app
    return TestClient(create_app())


def test_lemma_merge_hits_inflections(client):
    data = client.get("/api/dict/run/occurrences").json()
    assert data["word"] == "run" and data["lemma"] == "run"
    texts = [it["line"] for it in data["items"]]
    assert "She ran away" in texts
    assert "Running wild tonight" in texts
    assert "They ran together" in texts
    assert "I run every night" in texts
    assert data["total"] == 4


def test_inflected_query_merges_to_lemma(client):
    data = client.get("/api/dict/ran/occurrences").json()
    assert data["lemma"] == "run"
    assert data["total"] == 4


def test_excludes_current_line(client):
    data = client.get(
        "/api/dict/run/occurrences",
        params={"song": "Alpha", "line": "I run every night"}).json()
    texts = [it["line"] for it in data["items"]]
    assert "I run every night" not in texts
    assert data["total"] == 3


def test_same_song_same_text_dedup_keeps_earliest(client):
    data = client.get("/api/dict/shine/occurrences").json()
    assert data["total"] == 1
    assert data["items"][0]["line_index"] == 2


def test_cjk_lines_skipped(client):
    data = client.get("/api/dict/run/occurrences").json()
    assert all("快跑" not in it["line"] for it in data["items"])


def test_limit_caps_items_not_total(client):
    data = client.get("/api/dict/run/occurrences",
                      params={"limit": 1}).json()
    assert len(data["items"]) == 1
    assert data["total"] == 4


def test_song_param_pins_current_song_first(client):
    data = client.get("/api/dict/run/occurrences",
                      params={"song": "Beta"}).json()
    assert data["items"][0]["song"] == "Beta"


def test_annotated_lines_rank_before_plain(client):
    data = client.get("/api/dict/run/occurrences").json()
    first = data["items"][0]
    assert first["song"] == "Gamma" and first["line_index"] == 1


def test_unknown_word_returns_empty(client):
    data = client.get("/api/dict/zzzznotaword/occurrences").json()
    assert data["total"] == 0 and data["items"] == []


def test_item_shape(client):
    data = client.get("/api/dict/run/occurrences").json()
    assert set(data) == {"word", "lemma", "total", "items"}
    for it in data["items"]:
        assert set(it) == {"song", "line_index", "line"}
