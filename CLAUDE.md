# CLAUDE.md

编码规范：
- 先思考，再编码：不擅自假设需求；有歧义先说明假设与方案，必要时向用户确认。
- 保持简单：只实现用户要求的功能，不加多余功能、抽象或"预留灵活性"。
- 精准修改：只动与需求直接相关的代码，不顺手重构别的模块；只清理本次修改产生的无用代码（import/变量/函数），既有死代码提一句但不删。
- 以结果为导向：先定成功标准（能测试/构建验证的那种），做完验证，发现问题继续修。
- 优先复用现有代码；确实重复的逻辑才抽成可复用函数。
- 禁止直接在 main 分支改代码：先确认 main 最新再 checkout 新分支；当前已在非 main 分支时直接开发，不许切换分支。
- 不要写任何注释。

Git 提交规范：
- 每次代码修改完成后立即提交（英文 commit，feat:/fix: 等清晰前缀），不留未提交的修改。
- 不添加 AI 署名或 Co-authored-by。
- 不允许泄露含电子邮件、API key 的文件。
- 可以改代码，但不允许删除现有代码文件；不允许运行任何 rm -f。
- 不允许自动 merge PR。
- 跑 Chrome/Playwright 只允许无头 MCP，不许弹出浏览器界面。
- 不允许使用用户在项目中配置的 LLM API key；只有用户亲自操作才可触发 LLM 调用。

UI 设计规范：
- 禁止紫色、蓝紫色及相关渐变；整体视觉风格保持一致。
- 不允许使用 emoji。
- 禁止纯平背景色（必须有噪点或渐变）；禁止 Hero+三卡片布局。
- 禁止高深专业名词和无意义空话；图形和按钮能说明的操作不加解释性文字。
- 禁止线性动画 ease-in-out。
- AI 生成的文字内容页/卡片一律水平居中 + text-align: center（全局审美偏好，样板 ui_assets.py 的 .lore-page）。

## 项目须知（lyric_agent）

- **暂存区不属于你**：会话间可能有外部 `git add .`。每次提交前查 `git status --short` 和 `git diff --cached --stat`，重新 add 目标文件，提交后核对文件清单（脏快照混入过两次）。
- **测试/起服务必须隔离真实 data/**（2026-10-30 删过一次库）：写端点对相对路径 `data/` 真实生效。测试用 tmp 数据树 + `monkeypatch.chdir`（样板 tests/test_public_gate.py 的 isolated_data）；浏览器实测用 `serve-web --sandbox`。
- **不许提交占位 LLM 输出**：失败的生成也会落盘（"[Annotation generation failed]"），提交 data/songs/ 前先 grep。
- **验证门禁**：`python -m pytest tests/ -q` 和 `python scripts/ui_probe.py` 都绿才算 UI 工作完成；探针失败先看 data/ui_probe/ 截图再推理。
- **加一首歌**：禁用 `lyric-agent pipeline`（全库重批注烧钱），用 add-song 技能的逐歌命令。
- **长耗时 LLM 调用铁律**（踩过四次）：禁止在请求 handler 里同步阻塞调 LLM——结果绝不押在长连接上。统一走 `src/lyric_agent/background_task.py`（kick 幂等起跳 / status 轮询 / update 进度；done 的真相在磁盘缓存文件），前端 2s 轮询恢复。
- **UI 样式**走 token：新前端在 tailwind.config/DESIGN.md；旧 Gradio UI 在 ui_assets.py 的 `:root` 变量；SVG 配色常量在 echo_map.py / universe.py，须匹配主题明暗基调。
- **一次性脚本/日志放 tmp/**（已 gitignore），不要写进 data/cache。

犯错：
当用户强调修改某功能、你改了代码却没达到效果时，先找出没生效的真正原因，写入本文件归档，避免重犯。

已归档的踩坑原因（改了没生效类）：
- Tailwind 只静态扫描字面类名：运行时拼接的类（`cls.replace(...)`）不会被生成，样式静默失效。条件样式每个状态写完整字面量。
- 浏览器断言要轮询等状态翻转（waitFor 式），不要固定 sleep 后采样——和真实延迟赛跑会产生假阴性。状态验证用 evaluate_script 断言，截图只留给视觉检查。

## 规则 ↔ 强制手段对照表

| 规则 | 强制手段 | 层级 |
|---|---|---|
| 测试不得动真实 data/songs/ | tests/conftest.py 会话级快照守卫（并设 LL_CORPUS_REBUILD=0、LL_COVER_FETCH=0 关掉副作用线程） | 测试 |
| 浏览器实测/起服务验证隔离真实 data/ | `lyric-agent serve-web --sandbox` | 架构 |
| 不许提交占位 LLM 输出 | tests/test_data_hygiene.py；pre-commit 钩子兜底（装法见 scripts/git-hooks/pre-commit） | 测试 |
| heredoc 禁非 ASCII/反斜杠 | ~/.claude/hooks/block_heredoc.py 拦截 | 架构 |
| 长 LLM 调用后台化 | src/lyric_agent/background_task.py 深模块（新功能一律坐进该接缝） | 架构 |
| 提交前核查暂存区 | 仅文档（流程规则） | 文档 |
| 条件 Tailwind 类写完整字面量 | 仅文档（见踩坑归档） | 文档 |
