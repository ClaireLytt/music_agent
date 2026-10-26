"""Lint: 新前端禁止裸原生滚动条。

教训（2026-10-26）：部分 Windows 环境（辅助功能强制经典滚动条）会无视
scrollbar-color / ::-webkit-scrollbar 配色，渲染白底原生条。主界面滚动区
必须用 components/Scrollable.tsx 自绘，不得直接写 overflow-y-auto 或
原生滚动条配色 CSS。

用法: python scripts/lint_scrollbars.py   (非法用法时退出码 1)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
# Scrollable 自身要隐藏原生条；index.css 保留全局兜底配色
ALLOWED = {"components/Scrollable.tsx", "index.css"}
PATTERNS = [
    (re.compile(r"overflow-y-auto|overflow-y:\s*auto"),
     "裸 overflow-y-auto（会出原生白底滚动条），请改用 <Scrollable>"),
    (re.compile(r"::-webkit-scrollbar|scrollbar-color"),
     "原生滚动条配色在部分系统被无视，请改用 <Scrollable>"),
]


def main() -> int:
    bad = []
    for f in SRC.rglob("*"):
        if f.suffix not in (".tsx", ".ts", ".css"):
            continue
        rel = f.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for pat, msg in PATTERNS:
                if pat.search(line):
                    bad.append(f"frontend/src/{rel}:{n}: {msg}")
    for b in bad:
        print(b)
    if bad:
        print(f"\n{len(bad)} 处违规。滚动区请用 components/Scrollable.tsx。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
