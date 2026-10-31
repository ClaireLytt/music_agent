"""dict-ai 曲库例句注入 + v4 缓存 key（隔离 tmp 数据树，LLM 一律 mock）。"""

import hashlib
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from lyric_agent.llm import LLMResponse  # noqa: E402

CURRENT_LINE = "I run every night"


class FakeLLM:
    calls: list[dict] = []
    reply = "mocked explanation"

    def __init__(self, settings):
        pass

    def generate(self, system_prompt, user_message, **kwargs):
        FakeLLM.calls.append({"system": system_prompt, "user": user_message})
        return LLMResponse(reply_text=FakeLLM.reply)


def _write_corpus(data, entries):
    corpus = data / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "discography.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8")


def _entries():
    return [
        {"title": "Alpha", "artist": "tester", "album": "", "lyrics_lines": [
            CURRENT_LINE,
            "She ran away",
            "Running home now",
            "Run run run",
        ]},
        {"title": "Beta", "artist": "tester", "album": "", "lyrics_lines": [
            "Running wild tonight",
            "They ran fast",
            "Run to me",
        ]},
        {"title": "Gamma", "artist": "tester", "album": "", "lyrics_lines": [
            "Dreams of gold",
            "They ran together",
        ]},
    ]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    song = data / "songs" / "alpha"
    song.mkdir(parents=True)
    (song / "metadata.json").write_text(json.dumps({
        "title": "Alpha", "artist": "tester", "album": "", "year": 0,
        "era": "", "themes": [],
    }), encoding="utf-8")
    (data / "wordbook.json").write_text("[]", encoding="utf-8")
    (data / "favorites.json").write_text("[]", encoding="utf-8")
    (data / "user_settings.json").write_text(json.dumps(
        {"api_key": "sk-test-secret", "model_name": "m"}), encoding="utf-8")
    _write_corpus(data, _entries())
    monkeypatch.chdir(tmp_path)
    return data


@pytest.fixture
def client(isolated_data, monkeypatch):
    import lyric_agent.llm as llm_mod
    monkeypatch.setattr(llm_mod, "LLMClient", FakeLLM)
    FakeLLM.calls = []
    from lyric_agent.api import create_app
    return TestClient(create_app())


def _post(client, word="run", line=CURRENT_LINE, song="Alpha"):
    return client.post("/api/dict-ai",
                       json={"word": word, "line": line, "song": song})


def test_injects_corpus_examples_capped(client):
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.json()["ai"] == "mocked explanation"
    assert len(FakeLLM.calls) == 1
    user = FakeLLM.calls[0]["user"]
    assert "曲库例句（该词在用户听过的其他歌里的出现）：" in user
    section = user.split("曲库例句")[1]
    assert CURRENT_LINE not in section
    numbered = [ln for ln in section.splitlines()
                if ln[:2] in {f"{i}." for i in range(1, 10)}]
    assert len(numbered) == 5
    assert sum("《Alpha》" in ln for ln in numbered) == 2
    assert sum("《Beta》" in ln for ln in numbered) == 2
    assert sum("《Gamma》" in ln for ln in numbered) == 1
    assert numbered[0] == "1. She ran away ——《Alpha》"
    assert numbered[1] == "2. Running home now ——《Alpha》"
    assert "Run to me" not in section


def test_system_prompt_has_conditional_fourth_line_rule(client):
    _post(client)
    system = FakeLLM.calls[0]["system"]
    assert "④曲库" in system
    assert "不得自造歌词" in system
    assert "160" in system
    assert "120 字" not in system


def test_no_hits_omits_section(client):
    _post(client, word="quasar", line="quasar glow", song="Alpha")
    user = FakeLLM.calls[0]["user"]
    assert "曲库例句" not in user


def test_cache_hit_zero_llm_calls(client):
    _post(client)
    assert len(FakeLLM.calls) == 1
    resp = _post(client)
    assert resp.json()["ai"] == "mocked explanation"
    assert len(FakeLLM.calls) == 1


def test_get_path_uses_v4_key(client):
    _post(client)
    resp = client.get("/api/dict-ai",
                      params={"word": "run", "line": CURRENT_LINE,
                              "song": "Alpha"})
    assert resp.json()["ai"] == "mocked explanation"


def test_corpus_change_invalidates_key(client, isolated_data):
    _post(client)
    assert len(FakeLLM.calls) == 1
    entries = _entries()
    entries[2]["lyrics_lines"].remove("They ran together")
    _write_corpus(isolated_data, entries)
    import os
    corpus_file = isolated_data / "corpus" / "discography.jsonl"
    st = corpus_file.stat()
    os.utime(corpus_file, (st.st_atime, st.st_mtime + 10))
    _post(client)
    assert len(FakeLLM.calls) == 2


def test_v4_key_format_and_v3_entries_kept(client, isolated_data):
    cache_path = isolated_data / "dict" / "ai_cache.json"
    cache_path.parent.mkdir(parents=True)
    v3_key = hashlib.md5(f"v3:run\x00{CURRENT_LINE}".encode()).hexdigest()
    cache_path.write_text(json.dumps({v3_key: "old v3 text"}),
                          encoding="utf-8")
    _post(client)
    assert len(FakeLLM.calls) == 1
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache[v3_key] == "old v3 text"
    v4_keys = [k for k in cache if k != v3_key]
    assert len(v4_keys) == 1
    assert cache[v4_keys[0]] == "mocked explanation"


def test_empty_hits_ctx_digest_is_empty_string(client):
    _post(client, word="quasar", line="quasar glow", song="Alpha")
    cache_path = client.get("/api/dict-ai", params={
        "word": "quasar", "line": "quasar glow", "song": "Alpha"})
    assert cache_path.json()["ai"] == "mocked explanation"
    expected = hashlib.md5(
        "v4:quasar\x00quasar glow\x00".encode()).hexdigest()
    from pathlib import Path
    cache = json.loads(Path("data/dict/ai_cache.json")
                       .read_text(encoding="utf-8"))
    assert expected in cache
