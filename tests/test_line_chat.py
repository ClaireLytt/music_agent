"""行级 AI 助手（旧 Gradio 播放页「💬 AI 助手」迁移到 React 前端）。

隔离 tmp 数据树（见 CLAUDE.md"测试必须隔离真实 data/"）。
"""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    song = data / "songs" / "demo"
    song.mkdir(parents=True)
    (song / "lyrics.lrc").write_text(
        "[00:01.00]hello world\n[00:02.00]second line\n", encoding="utf-8")
    (song / "metadata.json").write_text(json.dumps({
        "title": "demo", "artist": "tester", "album": "", "year": 0,
        "era": "", "themes": [],
    }), encoding="utf-8")
    (song / "chat_history.json").write_text(json.dumps({
        "0": {"line": "hello world",
              "turns": [{"speaker": "user", "text": "什么意思？"},
                        {"speaker": "🤖 AI 助手", "text": "问好。"}]},
    }), encoding="utf-8")
    (data / "user_settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return data


def _client(monkeypatch, public: bool = False) -> TestClient:
    if public:
        monkeypatch.setenv("PUBLIC_MODE", "1")
    else:
        monkeypatch.delenv("PUBLIC_MODE", raising=False)
    from lyric_agent.api import create_app
    return TestClient(create_app())


def test_history_roundtrip(isolated_data, monkeypatch):
    resp = _client(monkeypatch).get("/api/songs/demo/chat/0")
    assert resp.status_code == 200
    turns = resp.json()["history"]
    assert len(turns) == 2 and turns[0]["text"] == "什么意思？"


def test_history_empty_line(isolated_data, monkeypatch):
    resp = _client(monkeypatch).get("/api/songs/demo/chat/1")
    assert resp.status_code == 200 and resp.json()["history"] == []


def test_history_hidden_in_public(isolated_data, monkeypatch):
    # public 模式访客不能看到彼此留下的问答
    resp = _client(monkeypatch, public=True).get("/api/songs/demo/chat/0")
    assert resp.status_code == 200 and resp.json()["history"] == []


def test_ask_requires_api_key(isolated_data, monkeypatch):
    resp = _client(monkeypatch).post(
        "/api/songs/demo/chat",
        json={"line_index": 0, "question": "why?"})
    assert resp.status_code == 400


def test_ask_rejects_blank_question(isolated_data, monkeypatch):
    resp = _client(monkeypatch).post(
        "/api/songs/demo/chat", json={"line_index": 0, "question": "  "})
    assert resp.status_code == 422


def test_ask_404_on_bad_line(isolated_data, monkeypatch):
    resp = _client(monkeypatch).post(
        "/api/songs/demo/chat", json={"line_index": 99, "question": "hi"})
    assert resp.status_code == 404
