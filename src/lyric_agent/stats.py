"""每日学习活动计数——「数据分析」热力图的数据源。

借鉴 qwerty-learner 的 Analysis 页（useWordStats 按天聚合练习记录）：
data/stats.json 形如 {"2026-10-07": {"practice": 3, "collect": 2}}。
practice = 打词练习次数（review.record_result），collect = 收藏单词数
（dictionary.add_word 新增条目时）。
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from pathlib import Path

from .jsonio import read_json, write_json_atomic

STATS_PATH = Path("data/stats.json")
_LOCK = threading.Lock()   # bump 是读改写：练习与收藏并发时防丢计数


def load_stats() -> dict:
    data = read_json(STATS_PATH)
    return data if isinstance(data, dict) else {}


def save_stats(stats: dict) -> None:
    # 原子写：练习线程与收藏可能同时记账
    write_json_atomic(STATS_PATH, stats)


def bump(kind: str, n: int = 1, ts: float | None = None) -> None:
    """给今天（或 ts 所在日）的 practice/collect 计数 +n。"""
    day = date.fromtimestamp(ts if ts is not None else time.time()).isoformat()
    with _LOCK:
        stats = load_stats()
        rec = stats.setdefault(day, {})
        rec[kind] = rec.get(kind, 0) + n
        save_stats(stats)


def backfill_from_wordbook(book: list[dict]) -> dict:
    """stats.json 还不存在时做一次近似回填：每个词条的历史练习总次数
    记到它 last_ts 那天（逐日明细已不可考），让热力图首次打开不全空。"""
    if STATS_PATH.exists():
        return load_stats()
    stats: dict = {}
    for e in book:
        r = e.get("review") or {}
        ts = r.get("last_ts") or 0
        attempts = r.get("correct", 0) + r.get("wrong", 0)
        if ts and attempts:
            day = date.fromtimestamp(ts).isoformat()
            rec = stats.setdefault(day, {})
            rec["practice"] = rec.get("practice", 0) + attempts
    save_stats(stats)
    return stats


def year_series(stats: dict, kind: str, today: date | None = None
                ) -> list[tuple[str, int]]:
    """过去一年逐日 (iso-date, count)，从一年前最近的周日对齐到今天
    （GitHub 日历布局：列 = 周，行 = 周日..周六）。"""
    today = today or date.today()
    start = today - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)  # 回退到周日
    out = []
    d = start
    while d <= today:
        iso = d.isoformat()
        out.append((iso, int((stats.get(iso) or {}).get(kind, 0))))
        d += timedelta(days=1)
    return out
