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
- **Verification gates:** `python -m pytest tests/ -q` (unit) and
  `python scripts/ui_probe.py` (real-browser, all tabs) must both be green
  before claiming UI work done. Probe failures: read the screenshot in
  data/ui_probe/ before theorizing.
- **Adding one song:** never `lyric-agent pipeline` (re-annotates the whole
  library at full LLM cost); use the per-song commands in the add-song skill.
- **UI styling** is token-centric: edit `:root` variables and component rules
  in src/lyric_agent/ui_assets.py; SVG palettes live as Python constants in
  echo_map.py / universe.py and must match the theme's light/dark basis.
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
