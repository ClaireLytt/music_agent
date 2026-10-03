# AGENTS.md — AI 贡献者须知

歌词透镜（Lyric Lens）：AI 歌词批注播放器。Python + Gradio 单体应用，
本地 sentence-transformers embedding 做互文检索，LLM 仅用于批注/解读生成。

## 起步

```bash
pip install -e ".[all]"       # llm + ui + embeddings + features + mcp
lyric-agent serve             # http://127.0.0.1:7860
```

## 验证门（UI 改动双绿才算完成）

```bash
python -m pytest tests/ -q    # 单元测试
python scripts/ui_probe.py    # 真实浏览器逐页签走查（~3-4 分钟）
```

probe 失败：先看 `data/ui_probe/` 里的失败截图，再推理。

## 硬规则

- **单曲禁用 `lyric-agent pipeline`**——它会对全库重新跑 LLM 批注（整库重付费）。
  加歌/补批注走 `.claude/skills/add-song` 的分步命令。
- **提交前核对暂存区**：`git status --short` + `git diff --cached --stat`——
  暂存区可能被会话外的 `git add .` 污染过，重新 add 你要提交的文件。
- **占位符不入库**：提交 `data/songs/` 下任何文件前
  `grep -rl "Annotation generation failed"` 必须无命中。
- **UI 样式 token 化**：只改 `src/lyric_agent/ui_assets.py` 的 `:root` 变量与
  组件规则；SVG 配色是 echo_map.py / universe.py 里的 Python 常量。
- 事件接线用 `.change`，不要用 `.input`（本 Gradio 构建会丢事件）。

## MCP

`lyric-agent mcp --root <仓库路径>` 启动 stdio MCP server（8 个工具：
查歌/歌词/批注/语义搜索/彩蛋/母题/每日一句/播放控制）。
接入方式见 README「MCP 集成」节；AI 侧使用剧本见
`.claude/skills/lyric-lens/SKILL.md`。

## 更多

详细行为准则与项目注意事项见 `CLAUDE.md`；功能全景与测试体系见 `README.md`。
