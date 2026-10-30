# 调研：iPad 适配 与 导入导出补全

> 状态：调研笔记（2026-10-30），供排期决策。所有外部论断给出一手来源 URL，代码论断给出 file:line。
> 背景：React SPA（frontend/）+ FastAPI（src/lyric_agent/api.py），`<audio>` 驱动逐行歌词同步，
> 桌面三栏布局；公开体验版 `PUBLIC_MODE=1`（src/lyric_agent/config.py:92-104）。

---

## Plan A：跨平台到 iPad（让现有 Web SPA 在 iPad 上可用/好用）

### A1. iPadOS Safari 会咬到本应用的限制

**音频播放 / 自动播放策略。** WebKit 规则：带声音的媒体必须由用户手势启动播放；
事件回调里的 `play()` 只有在手势调用栈内才算数（click 回调算，`canplaythrough` 回调不算）
（https://webkit.org/blog/6784/new-video-policies-for-ios/ ；总览见
https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay ）。
对本应用的影响：播放由用户点击触发（frontend/src/components/PlayerBar.tsx:47-48
`if (a.paused) void a.play(); else a.pause();`），**天然合规**；一旦播放已由手势启动，
后续 JS 的 pause/play/seek 不再受限，歌词逐行同步（读 `currentTime`）不受影响。
需要避免的只有"切歌后自动续播"这类非手势 `play()` ——切歌若发生在点击回调里没问题，
若将来做"播完自动下一首"，`ended` 回调里的 `play()` 在 iOS 上被视为同一播放会话的延续，
通常允许，但要真机验证。

**`currentTime` 拖动进度条。** PlayerBar.tsx:55 直接赋值 `a.currentTime`。Safari 对
`<audio>` 的 seek 与时长读取依赖服务端支持 HTTP Range（206 分段响应）。本地音频走
Starlette `FileResponse`（src/lyric_agent/api.py:258-265），Starlette 自 0.33.0 起
`FileResponse` 支持 Range（https://github.com/encode/starlette/releases/tag/0.33.0 ），
本机已装 1.6.0，**无需改动**；但 `audio_type == "url"` 的 302 重定向源（api.py:261-262）
是否支持 Range 取决于外站。

**后台音频。** Safari 标签页切后台/锁屏后 `<audio>` 可继续播放，但 JS 定时器被节流，
歌词高亮依赖的 `timeupdate`/rAF 会停摆——回到前台需以 `currentTime` 重算当前行
（本应用本来就是每次按 `currentTime` 找行，影响小）。计时器节流见
https://developer.mozilla.org/en-US/docs/Web/API/Window/setTimeout#timeouts_in_inactive_tabs 。

**100vh 问题。** App.tsx:99 用 `h-screen`（= `100vh`）。移动 Safari 的 `100vh` 按工具栏
收起时的"大视口"计算，工具栏展开时页面底部（88px 播放条）会被遮住。Safari 15.4 起支持
`svh/dvh/lvh` 动态视口单位（https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/
"The new Viewport Units"）。修法：`h-screen` → `h-[100dvh]`（Tailwind 任意值即可，一行改动）。

**`:hover` 在触屏上。** MDN 明言 `:hover` 在触屏上有问题：可能完全不匹配，或在触摸后
"粘住"直到下一次触摸（https://developer.mozilla.org/en-US/docs/Web/CSS/:hover ）。
本项目 10+ 个组件用 `hover:`（Sidebar/Dock/LyricsView/Drill 等，`grep hover: frontend/src`）。
修法：把"信息只在 hover 出现"的交互（若有）改为点击可达；纯视觉的 hover 高亮用
`@media (hover: hover)` 包裹（Tailwind 默认 `hover:` 已按 `hover (hover: hover)` 编译，
需确认 tailwind.config.js 未关 `hoverOnlyWhenSupported`——当前 config 未设，Tailwind v3
需显式开 `future.hoverOnlyWhenSupported`，frontend/tailwind.config.js 里没有，**要加**）。

**双击查词（最大的交互冲突）。** 查词靠 document 级 `dblclick` 委托 + 选区
（frontend/src/components/DictPops.tsx:73-115）。两重问题：
1. WebKit 在"内容适配移动端"（viewport 含 `width=device-width`，本项目 index.html:5 满足）
   时**禁用双击缩放、启用 fast-tap**（https://webkit.org/blog/5610/more-responsive-tapping-on-ios/ ），
   300/350ms 单击延迟因此不存在——单击体验没问题；
2. 但 iPad 上双击一段文本的默认行为是**选中单词**（文本选择手势），`dblclick` 事件在触屏
   Safari 上的触发不可依赖（MDN 将 dblclick 列为鼠标事件，触屏兼容性需实测：
   https://developer.mozilla.org/en-US/docs/Web/API/Element/dblclick_event ）。
   好消息：现有 `lookup()` 本来就是"从 `window.getSelection()` 取词"（DictPops.tsx:76-88），
   iPad 双击恰好会产生单词选区。**修法**：加一个 `selectionchange`（或 `touchend` 后微延时）
   路径复用同一个 `lookup()`；词组照旧用长按拖选（iOS 原生选区手柄），`mouseup` 分支
   （DictPops.tsx:99-105）在 iPad 上对应 `touchend`/`pointerup`，改用 Pointer Events 统一。
   另外给歌词行加 `touch-action: manipulation` 保险（同 5610 博文 "Styling Fast-Tap Behavior"）。

**position:fixed 与软键盘。** iPad 弹出软键盘时 Safari 只缩小 visual viewport，layout
viewport 不变，fixed 元素可能停在键盘下面。需要时用 VisualViewport API 把输入区顶上来
（https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport ）。本应用主要输入点：
笔记输入、聊天框、设置页 key 输入——都在 Dock/页面流内而非 fixed 底栏，风险中低；
88px 播放条是 grid 行不是 fixed，不受此影响（App.tsx:99 `grid-rows-[1fr_88px]`）。

### A2. PWA（添加到主屏幕）值不值得做

- **Service Worker**：iOS 11.3 起支持（https://webkit.org/blog/8090/workers-at-your-service/ ），
  主屏 Web App 可用。但本应用强依赖后端 API 与 LLM，离线价值 ≈ 0。
- **存储逐出**：Safari ITP 会在"7 天使用 Safari 且未与站点交互"后删除全部脚本可写存储
  （LocalStorage/IndexedDB/SW 注册等）；**加到主屏幕的 Web App 不属于 Safari，按自身使用天数
  计数，首方数据实际不会被删**（https://webkit.org/blog/10218/full-third-party-cookie-blocking-and-more/
  "Script-Writeable Storage" 与 "A Note On Web Applications Added to the Home Screen"）。
  公开体验版把 API Key 存 localStorage（config.py:92 注释），这条对"访客 Key 会不会丢"直接相关：
  纯 Safari 标签页 7 天不访问就丢，主屏 PWA 不丢。
- **standalone 模式音频**：主屏 Web App 内 `<audio>` 行为同 Safari（同一手势规则）；iOS/iPadOS
  16.4 起主屏 Web App 还获得 Web Push（https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/ ），
  本应用用不上。
- **结论**：PWA 的增量 = 全屏无地址栏 + 图标 + 存储不被 7 天清理。成本 = 一个 manifest.json
  （`display: standalone`）+ 图标。**值得顺手做 manifest，但不做离线缓存**。

### A3. 布局策略：三栏在 iPad 上怎么摆

现状：App.tsx:99 `grid h-screen grid-cols-[420px_1fr_460px] grid-rows-[1fr_88px]`——
**固定 420px 侧栏 + 弹性主区 + 固定 460px Dock**，最小舒适宽度约 1280px。
（注意：DESIGN.md 写的是 232/320px，代码实际是 420/460，以代码为准。）

iPad 逻辑宽度（Apple HIG 布局尺寸，https://developer.apple.com/design/human-interface-guidelines/layout ）：
- 竖屏：768pt（iPad 9.7"）/ 810 / 820 / 834pt（11"）/ 1024pt（12.9" 竖）
- 横屏：1024 / 1080 / 1180 / 1194pt（11"）/ 1366pt（12.9"）
- Split View / Stage Manager 下窗口可窄到约 320-375pt（等同手机宽）。

结论：
- **12.9" 横屏（1366pt）**：三栏原样可活（420+460 后主区还剩 486px），不动。
- **11" 横屏（1194pt）**：主区只剩 314px，太挤——需要把侧栏收成图标栏或可抽出
  （组件：frontend/src/components/Sidebar.tsx），或把两侧栏压到 320/380。
- **竖屏（768-1024pt）**：三栏必死。Dock（frontend/src/components/Dock.tsx，批注/翻译/彩蛋等）
  改为底部抽屉或右滑覆盖层；Sidebar 改抽屉。
- Tailwind 默认断点 `md:768 / lg:1024 / xl:1280` 正好对上 iPad 竖/横/桌面三档，
  **不需要自定义断点**（frontend/tailwind.config.js 现在没定义 screens，用默认即可）；
  改法是把 App.tsx:99 的 grid-cols 写成 `lg:` / `xl:` 分层。
- 需要适配的具体组件：App.tsx（grid）、Sidebar.tsx（抽屉化）、Dock.tsx（抽屉化）、
  PlayerBar.tsx（窄屏下隐藏次要控件）、DictPops.tsx（弹卡定位按 visual viewport 夹紧）、
  Drill.tsx（打字练习需要物理键盘，iPad 外接键盘可用，软键盘场景可直接提示）。

### A4. iPad 怎么访问到这个应用

`lyric-agent serve-web` 硬编码 `host="127.0.0.1"`（src/lyric_agent/cli.py:54），iPad 根本
连不上。两条路：
1. **局域网直连**：加 `--host` 选项传给 `uvicorn.run`，`0.0.0.0` 后 iPad 用
   `http://<电脑局域网IP>:8765` 访问。代价：本机 API（含写接口、无鉴权）暴露到局域网——
   演示场景可接受，README 要写清楚；Windows 防火墙会弹一次放行。
   注意非 HTTPS 下部分 Web API 受限（如剪贴板），但本应用核心路径（audio/fetch）HTTP 可用。
2. **公开体验版**：已有 `PUBLIC_MODE` 部署（config.py:92-104），iPad 直接开公网 URL，
   零改动即可访问——**A 计划的演示路径建议直接走这条**，局域网 host 选项作为开发便利顺手加。

### A5. 触屏交互替换清单

| 桌面交互 | iPad 替换 | 依据 |
|---|---|---|
| 双击查单词（DictPops.tsx:109） | 双击→系统选词→走 selectionchange 复用 lookup；或单击词级 span | A1 双击节 |
| 拖选查词组（DictPops.tsx:100-105） | 长按出选区手柄后拖选，`pointerup` 触发 | 同上 |
| hover 高亮/提示 | `@media (hover:hover)` 守护 + 点击可达 | MDN :hover（A1） |
| 单击 300ms 延迟 | 已无此问题（viewport 含 device-width，index.html:5） | webkit.org/blog/5610 |
| 进度条点击 seek（PlayerBar.tsx:55） | 触点即 click，照常；加大热区到 ≥44pt | HIG 点击目标 44pt（上文 HIG layout） |

**选区干扰**：document 级 dblclick 查词会和 iPad 的"双击选词 + 弹出系统文本菜单
（拷贝/查询）"叠在一起——需要在歌词行上 `-webkit-touch-callout: none` 并在查词成功后
`sel.removeAllRanges()`，否则弹卡和系统菜单重叠。

---

## Plan B：导入导出补全（学习数据可带走/可恢复）

### B1. 现状盘点（已有什么）

**已有导出**（都只覆盖单词本）：
- `GET /api/wordbook/export?format=anki|json`（api.py:541-557）→ `export_anki` TSV /
  `export_qwerty` JSON（src/lyric_agent/review.py:110-149）；前端按钮在
  frontend/src/pages/WordsPage.tsx:156-160（exportUrl 定义 frontend/src/api.ts:217）。

**已有导入**（仅外部词表 → 单词本）：
- `POST /api/wordbook/import`（api.py:523-539）→ `dictionary.parse_wordlist_file`
  （src/lyric_agent/dictionary.py:175-233，支持 csv/tsv/txt/xlsx，表头按
  word/单词、translation/释义、phonetic/音标识别，无表头按列位置）→
  `import_words`（dictionary.py:236-261，按小写词形去重，缺释义查本地词典补全，带分组）。

**全部学习数据的落盘位置与 schema**（实测读取）：
| 文件 | 形状 | 出处 |
|---|---|---|
| data/wordbook.json | `[{word, phonetic, translation, line, song, review:{correct,wrong,last_ts,b_correct,b_wrong,b_peek,b_clean}, group?, ai?}]` | dictionary.py:23,112-121；review 字段见 review.py:48-77 |
| data/favorites.json | `[{id, line, title, artist, label}]`（id 为 line+title 稳定哈希） | songdata.py:248-281 |
| data/stats.json | `{"YYYY-MM-DD": {practice/collect 计数}}` 热力图 | review.py:70-71（stats.bump） |
| data/user_settings.json | 用户设置（public 模式下不读，config.py:106） | config.py |
| data/songs/&lt;id&gt;/notes.json | `[{ts_ms, text}]` 听歌笔记 | songdata.py:176-194 |
| data/songs/&lt;id&gt;/chat_history.json | `{"<line_index>": {line, turns:[...]}}` 逐行追问 | songdata.py:151-175 |

练习（drill）记录没有独立文件——就是 wordbook 每个词条里的 `review` 子对象
（review.py:48-72 `record_result` 原地改 entry）。

### B2. Anki 导入格式核对

官方规范（https://docs.ankiweb.net/importing/text-files.html ）：纯文本 UTF-8；
分隔符逗号/分号/Tab；2.1.54+ 支持文件头 `#separator:(Comma|Semicolon|Tab|Space|Pipe|Colon)`、
`#html:true|false`、`#tags:`、`#columns:`、`#notetype:`、`#deck:`、`#guid column:` 等；
HTML 换行（`<br>`）需 Allow HTML；媒体引用 `[sound:...]` 同样需 Allow HTML。

现有 `export_anki`（review.py:131-149）输出 `#separator:tab` + `#html:true` 头、字段内
Tab/换行折叠、HTML `<br>` 分段——**与规范一致，Anki 2.1.54+ 可直接导入**。差距：
1. **无 `#deck:` / `#notetype:` / `#tags:` 头**——导入落到当前选中牌组、Basic 模板；
   加一行 `#deck:Lyric Lens` 和 `#tags:lyric-lens` 成本极低、体验明显（来源同上，头部清单）。
2. **无 guid 列**——二次导出再导入会重复建卡；加 `#guid column:` + 稳定 guid（词形哈希）
   可实现"重复导入即更新"（同上，GUID Column 节）。
3. **无媒体**——TTS 的 mp3（review.py:261-291 有缓存）可以 `[sound:word.mp3]` 引用，但
   文本导入不会搬运媒体文件，需用户手动放入 collection.media，**不建议做**（官方文档
   Importing Media 的约束）。

### B3. qwerty-learner 格式核对

官方词典格式（https://github.com/RealKai42/qwerty-learner/blob/master/docs/toBuildDict.md ）：
`[{"name": "...", "trans": ["...", ...]}]`，文件放 `public/dicts/`，在
`resources/dictionary.ts` 建索引。运行时 Word 类型为
`{name: string, trans: string[], usphone: string, ukphone: string, notation?}`
（https://github.com/RealKai42/qwerty-learner/blob/master/src/typings/index.ts 的 `export type Word`）。

现有 `export_qwerty`（review.py:110-122）输出 `{name, trans[]}`，释义按 ECDICT 的字面
`\n` 拆成数组——**最小必需字段符合**（toBuildDict.md 示例即只有 name/trans）。
差距：缺 `usphone/ukphone`；wordbook 每条有 `phonetic`（单一音标，B1 表），可同时填进
usphone 和 ukphone 两个字段，qwerty-learner 音标显示即可用。一行改动（review.py:121）。

### B4. 全量备份/恢复设计

**覆盖范围**：B1 表中属于"用户学习数据"的四类——wordbook.json、favorites.json、
stats.json、每首歌的 notes.json（chat_history.json 可选，属对话缓存；user_settings.json
含 API Key 等敏感项，**不入包**）。

**包格式建议：单 JSON**（不是 zip）。理由：总量 KB 级（当前 wordbook 70 词、favorites
10 条）；单 JSON 前端 `<a download>` / `<input type=file>` 即可收发，无需引 zip 库；
内嵌版本号便于迁移：

```json
{"app": "lyric-lens", "schema": 1, "exported_at": "...",
 "wordbook": [...], "favorites": [...], "stats": {...},
 "notes": {"<song_id>": [{"ts_ms":..., "text":...}]}}
```

**导入合并策略**（不是整体覆盖）：
- wordbook：按 `word.lower()` 对齐（与 import_words 同口径，dictionary.py:243-247）；
  已存在的词条合并 review 计数（逐字段取 max 或相加？**取相加会重复计数，取 max 丢数据；
  建议按 last_ts 新者胜整个 review 对象**——简单且语义清楚）。
- favorites：按现有 `id`（line+title 哈希，songdata.py:252-257）去重，天然幂等。
- stats：按日期键逐日取 max（同一天两边都练过，取大者，避免相加虚高）。
- notes：按 (song_id, ts_ms) 去重追加；song_id 在本库不存在的条目跳过并报告。
- 返回 `{added, merged, skipped}` 给前端展示。

**公开模式必须拒写**。现状注意：**FastAPI 层（api.py）完全没有 public_mode 检查**
（`grep public_mode src/lyric_agent/api.py` 零命中）——公开部署目前跑的是旧 Gradio UI，
其只读约束在 webui 层（src/lyric_agent/webui/runtime.py:49 `self.public`、app.py:86,102
`if not public:` 不注册写回调）。若 SPA 版要公开部署，所有写端点（favorites/notes/wordbook/
import/upload_audio/restore）需要统一闸门——建议一个 FastAPI dependency：
`load_settings().public_mode` 为真时对写方法抛 403（settings 读取见 config.py:104
`PUBLIC_MODE` 环境变量）。恢复（restore）端点同受此闸。

### B5. 外部 CSV 词表导入的数据模型张力

解析与列识别已存在（B1；dictionary.py:175-233，最小列就是 word 一列，translation/
phonetic 可选）。张力在于：本应用的词条原则是"词活在它的歌词行里"——wordbook 条目带
`line`（出处歌词）和 `song`（B1 表），练习卡和 Anki 导出都展示出处（review.py:142-144）。
外部导入的词没有出处行。现有模型已经给出答案：**`group` 字段**——导入词挂
`group: <词表名>`（api.py:534-537），而歌词收藏的词 `group` 缺省为空（api.py:443-444
`📖 歌词收藏` = `not e.get("group")`）。即"有 group = 外来词，无 group = 歌词词"已是
事实约定，UI 按分组筛选也已存在（WordsPage 分组 chip）。需要补的只是：
1. 练习卡/导出对无 `line` 词条的降级展示（export_anki 已处理：`if e.get("line")`，
   review.py:142——**无需改**）；
2. 可选的"例句回填"：导入词可用 `_examples_from_corpus`（review.py:196-214）在曲库歌词里
   搜真实出现，搜到即可把该词"认领"到某句歌词——这是差异化亮点，但属 nice-to-have。

---

## 对比与排期建议

| 维度 | Plan A（iPad 适配） | Plan B（导入导出补全） |
|---|---|---|
| 难度 | 中高：触屏交互重写（查词）、三档响应式布局、真机才能验证 | 低：纯 JSON 读写 + 两个端点 + 两个按钮 |
| 工作量 | 布局 1-2 天 + 交互 1 天 + 真机调试不可控 | 0.5-1 天（含合并策略测试） |
| 风险 | 高：无 iPad 真机/远程调试则盲改；dblclick/选区行为必须实测；回归面大（所有页面） | 低：不碰现有路径，新增端点；最大坑是合并语义，可用单测锁死 |
| 验证 | 需真机 Safari（或 macOS + 模拟器），现有 ui_probe 不覆盖触屏 | `python -m pytest tests/ -q` 可全覆盖 |
| 演示价值 | 高（现场拿 iPad 演示很抓眼） | 中（"数据可带走"是加分项，评委感知弱于前者） |

### Plan A 任务拆解（有序）

1. `h-screen` → `h-[100dvh]`，加 manifest.json + 图标 → frontend/src/App.tsx:99、frontend/index.html
2. tailwind.config.js 加 `future: { hoverOnlyWhenSupported: true }` → frontend/tailwind.config.js
3. `serve-web` 加 `--host` 选项透传 uvicorn → src/lyric_agent/cli.py:37-54
4. 响应式布局：`<lg` 侧栏/Dock 抽屉化，`lg~xl` 压缩栏宽 → App.tsx、Sidebar.tsx、Dock.tsx、PlayerBar.tsx
5. 触屏查词：selectionchange/pointerup 路径复用 lookup + touch-action + removeAllRanges → frontend/src/components/DictPops.tsx:73-115
6. 真机巡检：竖/横/Split View 三形态过一遍五个页面（ui_probe 不可替代）

### Plan B 任务拆解（有序）

1. `export_qwerty` 补 usphone/ukphone（填 `phonetic`）→ src/lyric_agent/review.py:110-122
2. `export_anki` 加 `#deck:`/`#tags:`/guid 列 → src/lyric_agent/review.py:131-149
3. `GET /api/backup` 导出全量 JSON 包（wordbook/favorites/stats/notes，schema 带版本）→ src/lyric_agent/api.py（新端点，挨着 541）
4. `POST /api/backup/restore` 按 B4 合并策略导入 + 单测锁合并语义 → api.py + tests/
5. 写端点统一 public_mode 403 闸（dependency）→ api.py（现状零检查，见 B4）
6. 前端设置页加"备份/恢复"按钮 → frontend/src（设置页）+ frontend/src/api.ts

### 先做哪个

**黑客松截止前先做 Plan B，再做 Plan A 的 1-3 步。**理由：B 全程可被现有单测验证、
半天到一天收口、零回归风险，且第 5 步（public_mode 闸）是 SPA 公开部署的**前置安全项**，
无论如何都得做；A 的核心难点（触屏查词、真机调试）时间不可控，而 A 的 1-3 步
（dvh、hover 守护、--host）是三行级改动，顺手做完就能让 iPad "能用"——"好用"（抽屉布局、
触屏查词）留给赛后或 demo 前确认有真机再投入。演示上，公开体验版 URL 在 iPad Safari
打开即是 A 的最低可行形态（A4 路径 2，零改动）。
