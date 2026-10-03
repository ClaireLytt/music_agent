"""Tests for the MCP command channel and server tool helpers."""

from __future__ import annotations

import json

import pytest

# the whole file exercises the MCP feature — skip gracefully in minimal
# environments installed without the `mcp` extra
pytest.importorskip("mcp")

from lyric_agent.mcp_channel import read_mcp_command, write_mcp_command  # noqa: E402


def test_command_roundtrip_and_dedupe(tmp_path):
    path = tmp_path / "cmd.json"
    payload = write_mcp_command("play", title="晴天", line_index=3, path=path)
    assert payload["cmd"] == "play" and payload["title"] == "晴天"
    assert payload["line_index"] == 3 and payload["nonce"]

    mtime, got = read_mcp_command(0.0, path=path)
    assert got == payload and mtime > 0

    # same mtime again -> consumed, nothing new
    mtime2, got2 = read_mcp_command(mtime, path=path)
    assert got2 is None and mtime2 == mtime

    # missing file -> never raises
    assert read_mcp_command(0.0, path=tmp_path / "nope.json") == (0.0, None)


def test_command_corrupt_json_ignored(tmp_path):
    path = tmp_path / "cmd.json"
    path.write_text("{not json", encoding="utf-8")
    mtime, got = read_mcp_command(0.0, path=path)
    assert got is None and mtime > 0


def _song(title, artist, album="AL", source=None):
    d = {"dir": f"/x/{title}", "name": title, "title": title,
         "artist": artist, "album": album, "year": 0, "audio_src": ""}
    if source:
        d["source"] = source
    return d


@pytest.fixture
def mcp_ctx(monkeypatch):
    from lyric_agent import mcp_server
    monkeypatch.setitem(mcp_server._ctx, "songs", [
        _song("晴天", "周杰伦"), _song("夜曲", "周杰伦"),
        _song("富士山下", "陈奕迅"),
    ])
    yield mcp_server
    mcp_server._ctx.clear()


def test_match_song(mcp_ctx):
    m = mcp_ctx._match_song
    assert m("晴天")["artist"] == "周杰伦"                 # exact
    assert m("晴天 — 周杰伦")["title"] == "晴天"            # label form
    assert m("富士山")["title"] == "富士山下"               # unique substring
    assert m("山")["title"] == "富士山下"                   # still unique
    assert m("不存在的歌") is None
    assert m("") is None


def test_list_songs_serializable(mcp_ctx):
    out = mcp_ctx.list_songs()
    assert json.dumps(out, ensure_ascii=False)
    assert {"title": "晴天", "artist": "周杰伦", "album": "AL",
            "year": None, "has_audio": False} in out


def test_play_song_writes_command(mcp_ctx, monkeypatch, tmp_path):
    from lyric_agent import mcp_channel
    monkeypatch.setattr(mcp_channel, "MCP_COMMAND_PATH",
                        tmp_path / "cmd.json")
    monkeypatch.setitem(
        mcp_ctx._ctx, "settings",
        type("S", (), {"public_mode": False})())
    out = mcp_ctx.play_song("晴天", line_index=5)
    assert out["status"] == "ok" and out["title"] == "晴天"
    _, cmd = read_mcp_command(0.0, path=tmp_path / "cmd.json")
    assert cmd["cmd"] == "play" and cmd["title"] == "晴天"
    assert cmd["line_index"] == 5


def test_play_song_refused_in_public_mode(mcp_ctx, monkeypatch):
    monkeypatch.setitem(
        mcp_ctx._ctx, "settings",
        type("S", (), {"public_mode": True})())
    out = mcp_ctx.play_song("晴天")
    assert "error" in out and "公开" in out["error"]


def test_play_song_unknown_title(mcp_ctx, monkeypatch):
    monkeypatch.setitem(
        mcp_ctx._ctx, "settings",
        type("S", (), {"public_mode": False})())
    out = mcp_ctx.play_song("没有这首")
    assert "error" in out and "晴天" in out["available_titles"]


def test_songs_exclude_hackathon_in_public_mode(tmp_path, monkeypatch):
    from lyric_agent import mcp_server
    mcp_server._ctx.clear()
    for title, source in (("普通歌", None), ("赛内歌", "tme_hackathon_playlist")):
        d = tmp_path / title
        d.mkdir()
        (d / "lyrics.lrc").write_text("[00:01.00] 一句\n", encoding="utf-8")
        meta = {"title": title, "artist": "A", "album": "AL"}
        if source:
            meta["source"] = source
        (d / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(
        mcp_server._ctx, "settings",
        type("S", (), {"public_mode": True, "songs_dir": str(tmp_path)})())
    titles = [s["title"] for s in mcp_server._songs()]
    mcp_server._ctx.clear()
    assert titles == ["普通歌"]
