"""曲库数据卫生检查。

失败的 LLM 运行仍会落盘（annotations.json 里整片
"[Annotation generation failed]"），这种占位输出已经两次被提交进库。
这里把 CLAUDE.md 的"提交前 grep"规则变成一条会红的测试。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PLACEHOLDER = "[Annotation generation failed]"
ROOT = Path(__file__).resolve().parents[1]


def _tracked_annotation_files() -> list[Path]:
    # -z：NUL 分隔原始字节路径（中文歌目录名会被默认输出 C 转义）
    out = subprocess.run(
        ["git", "ls-files", "-z", "data/songs/*/annotations.json"],
        cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / p.decode("utf-8") for p in out.split(b"\0") if p]


def test_no_placeholder_llm_output_committed():
    """只查 git 已跟踪的文件：规则是"不许提交占位输出"；
    未提交的本地缓存重跑生成即可，不在此红。"""
    offenders = []
    for f in _tracked_annotation_files():
        text = f.read_text(encoding="utf-8")
        if PLACEHOLDER in text:
            offenders.append(f"{f.parent.name} ({text.count(PLACEHOLDER)} 处)")
    assert not offenders, (
        "git 跟踪的 data/songs/ 批注里有失败 LLM 运行的占位输出，"
        "重跑生成后再提交：" + ", ".join(offenders))
