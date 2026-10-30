"""数据备份与恢复（.scratch/backup-restore/spec.md）。

全部用例跑在 tmp 数据树里（见 CLAUDE.md"测试必须隔离真实 data/"）。
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

SECRET = "sk-test-secret"


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
    (song / "audio.mp3").write_bytes(b"\xff\xfbfake-mp3-bytes")
    (data / "wordbook.json").write_text(
        json.dumps([{"word": "hello"}]), encoding="utf-8")
    (data / "favorites.json").write_text("[]", encoding="utf-8")
    (data / "user_settings.json").write_text(json.dumps(
        {"api_key": SECRET, "model_name": "m"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return data


def _client(monkeypatch, public: bool = False) -> TestClient:
    if public:
        monkeypatch.setenv("PUBLIC_MODE", "1")
    else:
        monkeypatch.delenv("PUBLIC_MODE", raising=False)
    from lyric_agent.api import create_app
    return TestClient(create_app())


def _export_zip(client) -> zipfile.ZipFile:
    resp = client.get("/api/backup/export")
    assert resp.status_code == 200
    return zipfile.ZipFile(io.BytesIO(resp.content))


# ── 导出 ──────────────────────────────────────────────────────

def test_export_zip_mirrors_data_tree(isolated_data, monkeypatch):
    zf = _export_zip(_client(monkeypatch))
    names = set(zf.namelist())
    assert {"songs/demo/lyrics.lrc", "songs/demo/metadata.json",
            "songs/demo/audio.mp3", "wordbook.json",
            "favorites.json", "user_settings.json"} <= names
    assert zf.read("songs/demo/audio.mp3") == b"\xff\xfbfake-mp3-bytes"


def test_export_strips_api_key_but_disk_keeps_it(isolated_data, monkeypatch):
    zf = _export_zip(_client(monkeypatch))
    packed = json.loads(zf.read("user_settings.json"))
    assert "api_key" not in packed
    assert packed["model_name"] == "m"
    on_disk = json.loads(
        (isolated_data / "user_settings.json").read_text(encoding="utf-8"))
    assert on_disk["api_key"] == SECRET


def test_export_filename_has_date(isolated_data, monkeypatch):
    resp = _client(monkeypatch).get("/api/backup/export")
    cd = resp.headers.get("content-disposition", "")
    assert "lyric_lens_backup_" in cd and ".zip" in cd


def test_export_403_in_public(isolated_data, monkeypatch):
    assert _client(monkeypatch, public=True).get(
        "/api/backup/export").status_code == 403


# ── 恢复 ──────────────────────────────────────────────────────

def _import_resp(client, blob: bytes):
    return client.post(
        "/api/backup/import",
        files={"file": ("backup.zip", blob, "application/zip")})


def test_restore_roundtrip_replaces_and_keeps_local_key(
        isolated_data, monkeypatch, tmp_path):
    client = _client(monkeypatch)
    blob = client.get("/api/backup/export").content
    # 改掉本机数据，模拟"另一台电脑"
    (isolated_data / "wordbook.json").write_text(
        json.dumps([{"word": "other"}]), encoding="utf-8")
    (isolated_data / "user_settings.json").write_text(json.dumps(
        {"api_key": "sk-local-key", "model_name": "local"}),
        encoding="utf-8")

    resp = _import_resp(client, blob)
    assert resp.status_code == 200
    # 数据来自备份包
    book = json.loads(
        (tmp_path / "data" / "wordbook.json").read_text(encoding="utf-8"))
    assert book == [{"word": "hello"}]
    # 本机 key 保留（包内无 key，不得清掉本机 key）
    settings = json.loads((tmp_path / "data" / "user_settings.json")
                          .read_text(encoding="utf-8"))
    assert settings["api_key"] == "sk-local-key"
    # 留底存在且含被替换前的数据
    baks = list(tmp_path.glob("data.bak_*"))
    assert len(baks) == 1
    old = json.loads((baks[0] / "wordbook.json").read_text(encoding="utf-8"))
    assert old == [{"word": "other"}]


def test_restore_rejects_non_backup_zip(isolated_data, monkeypatch, tmp_path):
    client = _client(monkeypatch)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.txt", "nope")
    resp = _import_resp(client, buf.getvalue())
    assert resp.status_code == 400
    # data/ 原样，无留底残留
    assert (tmp_path / "data" / "wordbook.json").exists()
    assert not list(tmp_path.glob("data.bak_*"))


def test_restore_rejects_not_a_zip(isolated_data, monkeypatch, tmp_path):
    resp = _import_resp(_client(monkeypatch), b"this is not a zip")
    assert resp.status_code == 400
    assert (tmp_path / "data" / "wordbook.json").exists()


def test_restore_rejects_zip_slip(isolated_data, monkeypatch, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("wordbook.json", "[]")
        zf.writestr("../evil.txt", "pwned")
    resp = _import_resp(_client(monkeypatch), buf.getvalue())
    assert resp.status_code == 400
    assert not (tmp_path / "evil.txt").exists()
    assert (tmp_path / "data" / "wordbook.json").exists()


def test_restore_403_in_public(isolated_data, monkeypatch):
    resp = _import_resp(_client(monkeypatch, public=True), b"x")
    assert resp.status_code == 403
