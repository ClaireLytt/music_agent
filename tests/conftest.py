"""Session-wide guards for the whole test suite.

真实 data/ 保护（这个坑踩过三次：2026-10-30 红灯测试 rmtree 删真实歌曲、
ui_probe 污染统计、浏览器实测把 offset 写进真实 metadata）：
任何测试修改/删除/新增真实 data/songs/ 下的文件，整个测试会话直接失败，
并指名道姓列出被动的文件。写端点测试必须用 tmp 数据树 + monkeypatch.chdir
隔离（样板：tests/test_public_gate.py 的 isolated_data fixture）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SONGS = (Path(__file__).resolve().parents[1] / "data" / "songs").resolve()


def _snapshot() -> dict[str, tuple[int, int]]:
    if not _SONGS.is_dir():
        return {}
    return {
        str(p.relative_to(_SONGS)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in _SONGS.rglob("*") if p.is_file()
    }


@pytest.fixture(autouse=True, scope="session")
def protect_real_data():
    before = _snapshot()
    yield
    after = _snapshot()
    changed = sorted(
        set(k for k, v in before.items() if after.get(k) != v)
        | (set(after) - set(before)))
    if changed:
        pytest.fail(
            "真实 data/songs/ 在测试期间被修改（项目铁律：测试必须用 "
            "tmp 数据树 + monkeypatch.chdir 隔离，样板见 "
            "tests/test_public_gate.py 的 isolated_data）。被动的文件：\n  "
            + "\n  ".join(changed[:20]), pytrace=False)
