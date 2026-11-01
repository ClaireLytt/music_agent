"""fetch_synced_lyrics：结构化检索、择优选曲、429/503 重试。"""

import urllib.error

import pytest

from lyric_agent import lrc_sources


def _entry(track, synced="[00:01.00]x", instrumental=False):
    return {"trackName": track, "syncedLyrics": synced,
            "instrumental": instrumental}


def test_prefers_exact_title_over_first_result(monkeypatch):
    seen = {}

    def fake(url, timeout):
        seen["url"] = url
        return [_entry("One Less Lonely Girl", "[00:01.00]wrong"),
                _entry("Lonely", "[00:01.00]right")]

    monkeypatch.setattr(lrc_sources, "_get_json", fake)
    out = lrc_sources.fetch_synced_lyrics("Lonely", "Justin Bieber")
    assert out == "[00:01.00]right"
    assert "track_name=Lonely" in seen["url"]
    assert "artist_name=Justin+Bieber" in seen["url"]


def test_skips_instrumental_and_unsynced(monkeypatch):
    monkeypatch.setattr(lrc_sources, "_get_json", lambda u, t: [
        _entry("My Shot", synced=None, instrumental=True),
        _entry("My Shot (Remix)", "[00:01.00]remix"),
    ])
    assert lrc_sources.fetch_synced_lyrics("My Shot", "hamilton") \
        == "[00:01.00]remix"


def test_returns_none_when_nothing_usable(monkeypatch):
    monkeypatch.setattr(lrc_sources, "_get_json", lambda u, t: [
        _entry("My Shot", synced=None, instrumental=True)])
    assert lrc_sources.fetch_synced_lyrics("My Shot") is None


def test_returns_none_on_persistent_error(monkeypatch):
    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 503, "ServerOverloaded", {}, None)

    monkeypatch.setattr(lrc_sources, "_get_json", boom)
    assert lrc_sources.fetch_synced_lyrics("Lonely", "Justin Bieber") is None


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(script, calls):
    class Opener:
        def open(self, req, timeout=None):
            calls.append(req.full_url)
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return _Resp(step)

    return Opener()


def _http_error(code, headers=None):
    import email.message
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("u", code, "err", msg, None)


def test_get_json_retries_on_503(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(lrc_sources.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        lrc_sources.urllib.request, "build_opener",
        lambda *a: _opener(
            [_http_error(503), _http_error(429, {"Retry-After": "3"}),
             b'[{"ok": 1}]'],
            calls))
    assert lrc_sources._get_json("http://x", 5) == [{"ok": 1}]
    assert len(calls) == 3
    assert sleeps[1] == 3.0


def test_get_json_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(lrc_sources.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        lrc_sources.urllib.request, "build_opener",
        lambda *a: _opener([_http_error(503)] * 5, []))
    with pytest.raises(urllib.error.HTTPError):
        lrc_sources._get_json("http://x", 5)


def test_get_json_no_retry_on_404(monkeypatch):
    calls = []
    monkeypatch.setattr(
        lrc_sources.urllib.request, "build_opener",
        lambda *a: _opener([_http_error(404)] * 2, calls))
    with pytest.raises(urllib.error.HTTPError):
        lrc_sources._get_json("http://x", 5)
    assert len(calls) == 1
