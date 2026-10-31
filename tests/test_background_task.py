"""background_task 深模块：接口即测试面（kick/status/update）。"""
from __future__ import annotations

import pytest

from lyric_agent import background_task as bt


@pytest.fixture(autouse=True)
def sync_tasks(monkeypatch):
    """测试接缝：同步执行器 + 干净任务表，测试间无顺序依赖。"""
    monkeypatch.setattr(bt, "_spawn", lambda fn: fn())
    monkeypatch.setattr(bt, "_tasks", {})


def test_unknown_key_is_none():
    assert bt.status("nope") == {"status": "none", "msg": ""}


def test_success_becomes_done():
    ran = []
    assert bt.kick("k", lambda: ran.append(1)) is True
    assert ran == [1]
    assert bt.status("k")["status"] == "done"


def test_error_captured_and_truncated():
    def boom():
        raise RuntimeError("x" * 500)
    bt.kick("k", boom)
    st = bt.status("k")
    assert st["status"] == "error"
    assert len(st["msg"]) == 160


def test_idempotent_while_running(monkeypatch):
    # 异步模拟：spawn 不执行，任务停留在 running
    monkeypatch.setattr(bt, "_spawn", lambda fn: None)
    assert bt.kick("k", lambda: None) is True
    assert bt.status("k")["status"] == "running"
    assert bt.kick("k", lambda: None) is False  # 第二次被幂等忽略


def test_update_merges_progress_and_survives_done():
    def run():
        bt.update("k", progress="阶段 1", chars=42)
    bt.kick("k", run)
    st = bt.status("k")
    assert st["status"] == "done"
    assert st["progress"] == "阶段 1" and st["chars"] == 42


def test_update_ignored_when_not_running():
    bt.update("ghost", progress="x")
    assert bt.status("ghost")["status"] == "none"


def test_rerun_after_done_allowed():
    bt.kick("k", lambda: None)
    assert bt.kick("k", lambda: None) is True
