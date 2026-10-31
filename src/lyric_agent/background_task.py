"""长耗时 LLM 任务的统一骨架（深模块）。

把「长耗时 LLM 调用铁律」（后台守护线程 + 结果落盘 + 状态轮询）从
文档规则变成代码结构：api.py 曾把同一形状手搓了四份互不相同的状态机
（intro / annotate / fanlore / rebuild），状态编码、错误截断、幂等起跳
各写各的。收口后每个任务点只剩三行。

接口（调用方需要知道的全部）：
  kick(key, run)      幂等起跳：同 key 运行中则忽略；run 在守护线程执行，
                      正常返回 → done（保留 update 过的附加字段），
                      抛异常 → error（msg=异常文本截断 160 字）。
  status(key)         {"status": "none"|"running"|"done"|"error",
                       "msg": str, ...update 过的附加字段}
  update(key, **extra) run 内部上报进度（如 fanlore 的 progress/chars）。

「完成」的真相始终在磁盘（缓存文件存在与否）——各端点先查文件再问
status，本模块只负责"在跑/出错/进度"这段中间态。

测试接缝：_spawn 可被替换成同步执行（见 tests/test_background_task.py），
端点级测试从此可确定性驱动。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_tasks: dict[str, dict] = {}


def _spawn(fn: Callable[[], None]) -> None:
    """默认执行器：守护线程。测试里换成直接调用即为同步。"""
    threading.Thread(target=fn, daemon=True).start()


def kick(key: str, run: Callable[[], None]) -> bool:
    """幂等起跳；返回是否真的启动了新任务。"""
    with _lock:
        if _tasks.get(key, {}).get("status") == "running":
            return False
        _tasks[key] = {"status": "running"}

    def _wrap() -> None:
        try:
            run()
        except Exception as exc:
            logger.exception("background task %s failed", key)
            with _lock:
                _tasks[key] = {"status": "error", "msg": str(exc)[:160]}
            return
        with _lock:
            _tasks[key] = {**_tasks.get(key, {}), "status": "done"}

    _spawn(_wrap)
    return True


def status(key: str) -> dict:
    with _lock:
        entry = _tasks.get(key)
        if entry is None:
            return {"status": "none", "msg": ""}
        return {"msg": "", **entry}


def update(key: str, **extra) -> None:
    """run 内部上报进度；只在任务仍在运行时生效。"""
    with _lock:
        entry = _tasks.get(key)
        if entry is not None and entry.get("status") == "running":
            entry.update(extra)
