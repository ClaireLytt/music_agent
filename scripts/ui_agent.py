#!/usr/bin/env python3
"""UI test-and-fix agent: the closed loop over scripts/ui_probe.py.

    probe the real UI  ->  feed failures to a coding agent  ->  re-probe
    until everything is green (or --max-iters is hit).

The fixing half runs `claude -p` (Claude Code headless). Each iteration:
1. run ui_probe.py (spawns its own server on a free port);
2. if checks failed, hand the agent the report + failure screenshots and
   let it fix the APP code (probe timing issues must be justified);
3. repeat. The loop also insists the unit suite stays green.

Usage:
    python scripts/ui_agent.py                 # up to 3 fix iterations
    python scripts/ui_agent.py --max-iters 5
    python scripts/ui_agent.py --dry-run       # probe + report only, no agent

Requires the `claude` CLI on PATH for the fix phase (https://claude.com/code).
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "data" / "ui_probe" / "report.json"

# what the fix agent is allowed to do, and nothing else
_AGENT_TOOLS = (
    "Read,Grep,Glob,Edit,Write,"
    "Bash(python -m pytest*),Bash(python -c*),Bash(python scripts/ui_probe.py*)"
)

_PROMPT_TEMPLATE = """\
你是本仓库的 UI 修复 agent。刚刚运行了 `python scripts/ui_probe.py`（真实浏览器
UI 巡检），以下检查失败了：

{failures}

完整报告在 data/ui_probe/report.json，失败截图在 data/ui_probe/<check_id>.png。

要求：
1. 逐项诊断根因并修复。优先修**应用代码**（src/lyric_agent/）；只有当失败明显是
   探针自身的时序/选择器问题时才修 scripts/ui_probe.py，并在改动处注释说明理由。
2. 修完运行 `python -m pytest -q` 确保 {n_tests} 项单元测试仍全绿。
3. 不要提交 git，不要改动与失败无关的代码。
4. 最后用一个简短列表总结：每个失败项的根因与修复方式。
"""


def run_probe() -> int:
    print("── probing UI ─────────────────────────────────")
    proc = subprocess.run(
        [sys.executable, "scripts/ui_probe.py"], cwd=str(ROOT))
    return proc.returncode


def load_failures() -> list[dict]:
    if not REPORT.exists():
        return []
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    return [c for c in data.get("checks", []) if not c.get("ok")]


def count_unit_tests() -> int:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        for line in reversed(out.stdout.splitlines()):
            if "test" in line and ("collected" in line or "tests" in line):
                digits = [int(t) for t in line.split() if t.isdigit()]
                if digits:
                    return digits[0]
    except Exception:
        pass
    return 0


def run_fix_agent(failures: list[dict], n_tests: int) -> bool:
    claude = shutil.which("claude")
    if claude is None:
        print("⚠️ 未找到 `claude` CLI —— 无法自动修复。")
        print("   请安装 Claude Code，或把 data/ui_probe/report.json "
              "交给任意编码 agent 处理。")
        return False
    lines = [
        f"- [{f['id']}] {f['name']}\n  详情: {f['detail'][:400]}"
        for f in failures
    ]
    prompt = _PROMPT_TEMPLATE.format(
        failures="\n".join(lines), n_tests=n_tests or "全部")
    print(f"── fixing via claude -p ({len(failures)} failure(s)) ──")
    proc = subprocess.run(
        [claude, "-p", prompt,
         "--permission-mode", "acceptEdits",
         "--allowedTools", _AGENT_TOOLS],
        cwd=str(ROOT))
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-iters", type=int, default=3,
                    help="max probe->fix iterations (default 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="probe and report only; skip the fix phase")
    args = ap.parse_args()

    n_tests = count_unit_tests()
    for i in range(1, args.max_iters + 1):
        print(f"\n══ iteration {i}/{args.max_iters} ══")
        failed = run_probe()
        if failed == 0:
            print("✅ UI 巡检全绿，闭环结束。")
            return 0
        failures = load_failures()
        print(f"❌ {len(failures)} 项失败。")
        if args.dry_run:
            print("(dry-run：跳过修复阶段)")
            return failed
        if not run_fix_agent(failures, n_tests):
            print("修复阶段未完成，停止循环。")
            return failed
    print(f"\n⚠️ 达到最大迭代次数（{args.max_iters}），仍有失败项 —— "
          "请人工查看 data/ui_probe/report.json。")
    return load_failures() and len(load_failures()) or 1


if __name__ == "__main__":
    raise SystemExit(main())
