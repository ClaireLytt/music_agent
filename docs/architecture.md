# lyric_agent 代码架构图（2026-10-09，前端拆分 + 三轮 review 加固后）

## 总览

```
                        ┌─────────────────────────────┐
  用户入口               │        cli.py  (click)       │
  ──────────            │ serve / generate / generate- │
  lyric-agent <cmd> ──▶ │ all / embed / doctor / mcp / │
                        │ users-add ...                │
                        └──────┬───────────┬──────────┘
                               │           │
              ┌────────────────▼─┐    ┌────▼─────────────┐
              │ ui.py (18 行转发壳)│    │  mcp_server.py    │ ◀── Claude Code /
              └────────┬─────────┘    │ MCP stdio 工具服务 │     Desktop 等
                       │              └────┬─────────────┘     外部 agent
          ┌────────────▼────────────┐      │ 只依赖 songdata
          │        webui/  包        │  mcp_channel.py（命令文件，
          │  app.py 组装 + 启动序列   │  channels.py Timer 轮询执行切歌）
          └─────────────────────────┘
```

## webui/ 包（本次拆分产物，原 ui.py 2785 行 → 10 个模块）

| 模块 | 行数级 | 职责 |
|---|---|---|
| `webui/app.py` | ~130 | `create_app` / `launch_kwargs`：头部 + user_llm/role_box + 依序调各 tab 的 build → wire → 启动序列（app.load 链） |
| `webui/context.py` | ~50 | `AppContext(dict)`：共享状态容器；缓存失效收敛成 4 个具名方法（invalidate_library_views / invalidate_echo_index / invalidate_echo_scans / invalidate_song），tab 模块只调方法、不裸 pop 键 |
| `webui/runtime.py` | ~420 | `Runtime` 类：曲库快照 refresh_library、后台线程（MV 自动绑定/语料重建/预热）、song_choices/find_song/label_of、request_settings（公开版访客 Key）、echo 索引与整歌彩蛋扫描、母题缓存、quote_verifier。`__init__` 调 `songdata.set_songs_root(settings.songs_dir)` 注入路径防护根目录 |
| `webui/tab_play.py` | ~750 | 🎧 播放解读：三栏布局 + 侧边图标坞 + 全部隐藏 JS 通道组件；handler：选歌/筛选排序/点句解读/生成批注/行级问答/导读/收藏/查词弹卡/单词本/笔记/引文跳转 |
| `webui/tab_play_tools.py` | ~250 | ⚙️ 歌曲工具子坞 handler：音频上传 / B 站视频绑定 / 整歌翻译 / 歌词偏移（组件在 tab_play 创建，这里只接线） |
| `webui/tab_review.py` | ~390 | 🔤 歌曲寻词：打字练习 / 分组导入删除 / JSON·Anki 导出 / 📊 数据分析 |
| `webui/tab_lore.py` | ~290 | 🕵️ 歌迷考据：LLM 长文生成（后台线程+落盘+Timer 轮询铁律样板）+ 页内 AI 助手 |
| `webui/tab_games.py` | ~165 | 🎯 歌词竞猜 + 🧩 歌名拼图 |
| `webui/tab_manage.py` | ~370 | ➕ 添加歌曲 / 内置曲库导入 / 刷新曲库 / 删除歌曲（跨 tab 经 ui 命名空间引用播放页的 song_radio / song_outputs / on_song_select） |
| `webui/tab_settings.py` | ~230 | ⚙️ 设置：📊 用量 / 🔑 API 密钥 / 🧠 Embedding 模型与索引重建 |
| `webui/channels.py` | ~55 | MCP 播放命令轮询（Timer 读命令文件 → 切歌 + JS 播放） |
| `webui/render.py` | ~795 | 渲染层：全部 `render_*`/`_render_*` HTML 函数与文案常量（原 ui_helpers 渲染半边） |

**拆分约定**：
- 每个 tab 模块 = `build(rt, ui)`（布局，组件挂到 ui 命名空间）+ `wire(rt, ui)`（handler 接线）；app.py 先全部 build 再全部 wire，跨 tab 组件引用因此总是存在；
- `rt: Runtime` 替代旧闭包变量 `ctx`/`settings`/`public`；`rt.settings` 可被 on_rebuild/on_save_settings 原地替换；
- 隐藏 Textbox JS 通道（ll-del-song / ll-offset-set / ll-bvid-act / ll-role 等）统一在 tab_play.build 创建（必须常驻播放页 DOM），与 ui_assets._HEAD_JS 的 JS 侧一一配对。

## 数据层与兼容壳

| 模块 | 职责 |
|---|---|
| `songdata.py`（~290 行，新） | 歌曲数据发现/加载/持久化：discover_songs、load_song_data(+缓存)、catalog、翻译、LRCLIB 抓词、聊天史/笔记/简介/收藏 读写。**不 import 任何渲染/gradio 代码；mcp_server 只依赖这层**。review 加固（2026-10-09）：① `load_song_data` 路径穿越防护——song_dir resolve 后必须在歌曲根目录下，根目录由持有 Settings 的入口（Runtime / mcp_server）经 `set_songs_root()` 注入（单一真相源，env 仅兜底）；② metadata.json / translation.json 坏文件容错，不再崩整个发现流程；③ CJK 判定缓存键 = resolve 路径 + lyrics.lrc mtime（等价路径共享、改词自动失效）；④ `__all__` 刻意只含 4 个稳定公开名，`_` 前缀为私有 |
| `ui_helpers.py`（76 行转发壳） | re-export songdata 24 符号 + webui/render 37 符号，旧消费方（tests/cli/mcp_server/各 tab）import 路径不变；兼容面由 `tests/test_features.py::test_ui_helpers_compat_surface` 锁定 |
| `ui.py`（18 行转发壳） | re-export create_app / launch_kwargs / _discover_songs 供 cli.py 与旧脚本 |

## 领域功能层（本次未动）

```
LLM 生成类（都走 llm.py，单次 prompt→回复，无工具调用循环）
├─ annotator/        逐行批注流水线 engine→prompts→models，reviewer 人工复核
├─ fanlore.py        歌迷考据长文（schema/prompt/持久化/渲染）
├─ debate.py         AI 问答（DebateSession）
├─ dictionary.py     查词 + 生词本（data/wordbook）
├─ insights.py       整歌解读
└─ artist_profile.py 歌手画像

纯统计/算法类（零 LLM）
├─ intertextuality/  corpus 语料 → embeddings 向量 → search 语义搜 → echo_map 彩蛋星图
│                    （build_corpus 过滤「暂无歌词」占位行，不入语料/向量）
├─ archaeology.py    母题挖掘（mine_motifs，MCP 也在用）
├─ fingerprint.py    歌手风格指纹
├─ rhyme.py          押韵分析
├─ universe.py       歌手宇宙 SVG（调色板常量须跟主题走）
├─ evolution/        风格演化（engine+models+自带 ui 片段）
├─ search.py         关键词搜索
└─ stats.py          统计

数据/基础设施
├─ config.py   .env + Settings
├─ jsonio.py   原子读写 JSON
├─ llm.py      多 provider LLM 客户端（含用量记账——待拆，见"后续"）
├─ auth.py     可选登录（data/users.json）
├─ lrc_parser.py / lrc_sources.py   LRC 解析 / 外部歌词源
├─ audio_provider.py / bilibili.py  音频解析（B 站风控处理在 bilibili.py）
└─ doctor.py   曲库健康检查
```

## 对外接口（MCP）

`mcp_server.py` 暴露 8 个工具（list_songs / search_lyrics / get_lyrics /
get_annotation / find_echoes / artist_motifs / play_song / daily_quote）；
`play_song` 经 `mcp_channel.py` 写命令文件、`webui/channels.py` 的 Timer
轮询执行。**项目自身目前没有 agentic loop**——所有 LLM 功能都是单次生成调用。

## scripts/（开发与数据流水线）

- `ui_probe.py` 真实浏览器全 Tab 巡检（35 项检查）——重构安全网，依赖页面元素 id
- `ui_agent.py` probe→`claude -p` 修复→re-probe 闭环（开发工具）
- `screenshot.py` 单 Tab 截图（design-critic 评审循环用）；输出目录 `data/design_loop/` 已 gitignore（截图/日志属生成产物，日志可能含敏感请求信息）
- `build_catalog / build_corpus / build_dict / build_evolution / fetch_lrc / import_playlist / generate_all / warm_cache`：数据流水线
- `self_test.py` / `make_demo_annotations.py`：测试与演示数据

## 重构时不能破坏的契约（持续有效）

1. `ui_helpers.py` / `ui.py` 转发壳的符号集（tests、cli、mcp_server、旧脚本在用；由 test_ui_helpers_compat_surface 强制）
2. `ui_probe.py` 依赖的 DOM 元素 id（`ll-side-dock`、`ll-quiz-wrap` 等）
3. 长耗时 LLM 调用四件套（CLAUDE.md 铁律）：后台 daemon 线程 + 落盘缓存 + in-flight 状态 + gr.Timer 轮询（样板现在在 `webui/tab_lore.py`）
4. `mcp_channel.py` 命令文件协议（MCP ↔ UI 的唯一通道）
5. `data/` 下各缓存文件格式（annotations.json、wordbook、fanlore 缓存、TTS 缓存）
6. 生成文字内容一律居中（`.lore-page` 样板）

## 后续可做（本次未做，原第 4 步）

- `llm.py` 用量记账 → `usage.py`；`review.py` 拆 TTS/例句；`universe.py`/`fanlore.py` 渲染段并入 webui/render.py；`cli.py` 业务下沉；`_HEAD_JS` 按模块拆字符串；`ui_probe.run_probe` 检查项注册化
- 移动端适配：各 tab 模块已就位，`@media` 断点按模块补即可

## 已知局限（review 发现，留待前端重写时解决）

- **角色门禁只在 UI 级**：viewer/admin 区分靠 `_HEAD_JS` 前端隐藏 tab 按钮，
  后端 handler 不做角色校验（黑客松威胁模型）。重写为 FastAPI 时必须服务端
  强制（见 docs/frontend_rewrite_plan.md §3）
- 十余个隐藏 Textbox JS→Python 通道无法单测，重写时应显式化为 API 端点
