"""public 写闸门：public 模式下写类端点必须在 API 层被 403 拒绝。

PRODUCT.md 铁律"鉴权必须在 API 层做"——旧版只在 UI 层隐藏按钮是已知缺陷。

⚠️ 本文件所有测试都必须在 tmp 数据树里跑（isolated_data fixture）：
写端点是真实生效的，闸门未生效时（红灯阶段）对着仓库真实 data/ 跑
会删库（已发生过一次：DELETE /api/songs/cardigan rmtree 了整个歌曲目录）。
"""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

# 代表性写端点（method, path, body）——不求全列，但覆盖每类资源
WRITE_CALLS = [
    ("post", "/api/favorites", {"song_id": "x", "line_index": 0}),
    ("delete", "/api/favorites/xxx", None),
    ("post", "/api/wordbook", {"word": "test"}),
    ("delete", "/api/wordbook/test", None),
    ("put", "/api/wordbook/test/note", {"note": ""}),
    ("post", "/api/songs/demo/notes", {"ts_ms": 0, "text": "n"}),
    ("delete", "/api/songs/demo/notes/0", None),
    ("put", "/api/songs/demo/bvid", {"bvid": ""}),
    ("put", "/api/songs/demo/offset", {"offset_ms": 0}),
    ("post", "/api/drill/result", {"word": "x", "ok": True}),
    ("delete", "/api/wordbook/groups/g", None),
    ("put", "/api/settings", {}),
    ("post", "/api/rebuild-index", None),
    ("delete", "/api/songs/demo", None),
]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """最小 data/ 树 + chdir 隔离：测试绝不触碰仓库真实数据。"""
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
    (data / "user_settings.json").write_text(json.dumps(
        {"api_key": "sk-test-secret", "model_name": "m"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return data


def _client(monkeypatch, public: bool) -> TestClient:
    if public:
        monkeypatch.setenv("PUBLIC_MODE", "1")
    else:
        monkeypatch.delenv("PUBLIC_MODE", raising=False)
    from lyric_agent.api import create_app
    return TestClient(create_app())


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_public_mode_rejects_writes(isolated_data, monkeypatch,
                                    method, path, body):
    client = _client(monkeypatch, public=True)
    resp = getattr(client, method)(
        path, **({"json": body} if body is not None else {}))
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


def test_public_mode_reads_still_work(isolated_data, monkeypatch):
    client = _client(monkeypatch, public=True)
    assert client.get("/api/songs").status_code == 200


def test_local_mode_writes_not_blocked(isolated_data, monkeypatch):
    # 本地模式写端点不应被闸门拦下（403）；业务校验错误（4xx/2xx）皆可
    client = _client(monkeypatch, public=False)
    resp = client.post("/api/favorites",
                       json={"song_id": "x", "line_index": 0})
    assert resp.status_code != 403
