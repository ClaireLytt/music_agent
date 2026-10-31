# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project-specific notes (lyric_agent)

- **Staging area is not yours.** `git add .` may happen outside the session
  between turns. Before EVERY commit: check `git status --short` for staged
  (first-column) entries and `git diff --cached --stat`; re-add the files you
  mean to commit and verify the commit's file list afterwards. Stale staged
  snapshots have smuggled wrong content into commits twice.
- **Never commit placeholder output.** Failed LLM runs still write files
  (e.g. annotations.json full of "[Annotation generation failed]"). Grep for
  that marker before committing anything under data/songs/.
- **测试必须隔离真实 data/**（2026-10-30 已删过一次库）：API 写端点直接
  操作相对路径 `data/` 且真实生效（`DELETE /api/songs/{id}` 就是 rmtree）。
  任何涉及写端点的测试——尤其 TDD 红灯阶段"预期被拒"的请求——必须用
  tmp 数据树 + `monkeypatch.chdir` 隔离（样板：tests/test_public_gate.py
  的 isolated_data fixture）。untracked 的 mp3/笔记/LLM 缓存删了就是没了。
- **Verification gates:** `python -m pytest tests/ -q` (unit) and
  `python scripts/ui_probe.py` (real-browser, all tabs) must both be green
  before claiming UI work done. Probe failures: read the screenshot in
  data/ui_probe/ before theorizing.
- **Adding one song:** never `lyric-agent pipeline` (re-annotates the whole
  library at full LLM cost); use the per-song commands in the add-song skill.
- **UI styling** is token-centric: edit `:root` variables and component rules
  in src/lyric_agent/ui_assets.py; SVG palettes live as Python constants in
  echo_map.py / universe.py and must match the theme's light/dark basis.
- **生成文字内容一律居中**（用户的全局审美偏好，2026-10-05 定）：凡 AI
  生成的文字类内容页/卡片（歌迷考据、故事、总结等），容器 `margin: 0 auto`
  水平居中且 `text-align: center`。新功能渲染 HTML 时直接照此写；样板见
  ui_assets.py 的 `.lore-page`。
- **长耗时 LLM 调用的交付铁律**（同一坑已踩四次：查词弹卡、整歌翻译、
  彩蛋故事、歌迷考据）。症状：点了生成按钮，token 花了/调用挂着，页面却
  永远停在"生成中"；用户等不及刷新或重启 serve，同步阻塞的调用随之被杀，
  整次调用作废。根因：在 Gradio handler 里同步阻塞调 LLM，结果交付依赖
  长连接上的最后一个 yield——超过约 1 分钟 SSE 常已断。规范（新的
  LLM 生成功能一律照此，样板见 ui.py 的 on_gen_lore/_lore_generate_bg/
  on_lore_tick）：① 调用放后台 daemon 线程，先 save 落盘缓存；② ctx 记
  per-目标 in-flight 状态（running/done/error）；③ gr.Timer 轮询，状态
  翻转时刷一次 UI；④ 切歌/重进页面时读缓存 + in-flight 状态恢复 ⏳，
  绝不把"能否看到结果"押在那条长连接上。


  Git 提交规范
- 每次代码修改完成后，都必须立即提交 Git Commit(写英文)，不允许泄露带有电子邮件和api key的文件。
- 提交信息清晰，例如 feat: ...、fix: ...。
- 不允许留下未提交的修改。
- 不添加 AI 的署名或 Co-authored-by 信息。
- 不允许泄露带有电子邮件和 api key 的文件。
- 可以改代码 但不允许删除现有的代码文件
- 不允许运行任何rm -f的命令
- 不允许自动merge pr
- 不允许在运行chrome playwright的时候打开chrome界面 只允许使用mcp

 UI 设计规范
- 禁止使用紫色、蓝紫色及相关渐变。
- 保持整体视觉风格一致。
- 不允许使用emoji
- 禁止纯平背景色(必须有噪点或渐变)
- 禁止Hero+三卡片布局
- 禁止高深的专业名词和无意义的空话
- 禁止线性动画 ease-in-out
- 在可以用图形和按钮说明操作的情况下，不要添加多余的解释性文字——界面自解释优先于说明文案。

编码规范：
- 先思考，再编码：不要擅自假设需求；遇到歧义先说明假设、分析方案，必要时向用户确认。
- 保持简单：只实现用户要求的功能，不添加多余功能、抽象或复杂设计。
- 精准修改：只修改与需求直接相关的代码，不顺手重构其他模块；只清理自己此次修改产生的无用代码。
- 以结果为导向：先明确成功标准和执行计划，再通过测试、构建等方式验证结果，发现问题就继续修复。
- 优先复用现有代码；对于确实需要重复使用的逻辑，抽象为可复用函数，避免重复造轮子。
- 禁止直接在main分支修改代码 必须先判断main分支为最新代码后checkout到新分支再开始改代码
- 如果现在的分支不是main分支的话就直接开发 不允许切换到其他分支

犯错：
当我跟你强调修改或者添加某个功能，你已经修改了代码之后还是没有达到我要的效果，应该先仔细思考找出没有起效的原因和真正的解决方法写入到claude.md中，避免下次再次犯错

已归档的踩坑原因（改了没生效类）：
- Tailwind 只静态扫描源码里的字面类名：运行时拼接的类
  （`cls.replace("border-edge2","border-accent")`）不会被生成，样式
  静默失效。条件样式必须把每个状态写成完整字面量字符串。
- 浏览器断言要轮询等状态翻转（waitFor 式），不要固定 sleep 后采样：
  固定延时和真实 API 延迟赛跑，会产生"样式没生效"的假阴性。
  状态验证用 evaluate_script 断言；截图只留给视觉检查。

一次性脚本/日志放 tmp/（已 gitignore），不要写进 data/cache。

## 规则 ↔ 强制手段对照表

| 规则 | 强制手段 | 层级 |
|---|---|---|
| 测试不得动真实 data/songs/ | tests/conftest.py 会话级守卫：套件结束对比快照，动了即整体失败并列出文件 | 测试 |
| 浏览器实测/起服务验证必须隔离真实 data/ | `lyric-agent serve-web --sandbox`（临时副本数据树，与 ui_probe 同款） | 架构 |
| 不许提交占位 LLM 输出 | tests/test_data_hygiene.py 扫 git 跟踪的 annotations.json；pre-commit 钩子亚秒级兜底（装法见 scripts/git-hooks/pre-commit 头注释） | 测试 |
| heredoc 禁非 ASCII（Git Bash 吞字节） | ~/.claude/hooks/block_heredoc.py 直接拦截 Bash 调用 | 架构 |
| 长 LLM 调用必须后台线程+落盘+轮询 | 仅文档（样板 ui.py on_gen_lore；无自动检查） | 文档 |
| 提交前核查暂存区（外部 git add 污染） | 仅文档（流程规则，无法在仓库内强制） | 文档 |
| 条件 Tailwind 类写完整字面量 | 仅文档（见上方踩坑归档） | 文档 |
