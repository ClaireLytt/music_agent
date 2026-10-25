# 前端重写基础方案(路线 A:FastAPI + 自建 SPA)

> 状态:草案,待评审。只定契约/架构/选型,不含代码与视觉设计。
> 原材料:webui 全部 7 个页签(5 顶层 + 互动 3 子页)的数据动作盘点(2026-10-09)。

## 0. 分层原则

```
前端 SPA(纯静态可独立部署)── 状态/路由/渲染,零业务逻辑
API 层(FastAPI,新写,薄)── 参数校验 → 调数据层 → 序列化
数据/引擎层(现有,零改动)── songdata / annotator / intertextuality / dict / games / fanlore
存储(现有,零改动)── data/songs/* + jsonl 语料 + npy 向量
```

铁律:API 层不搬业务逻辑,保证 MCP server、CLI、SPA 三入口共享同一行为。

## 1. 四种接口形状(全部端点只允许这四种)

| 形状 | 适用 | 约定 |
|---|---|---|
| **同步读** `GET` | 列表/详情/缓存命中的生成物 | 无副作用,可加 HTTP 缓存头 |
| **同步写** `POST/PUT/DELETE` | 收藏/笔记/单词本/绑定等毫秒级落盘 | 返回写后的最新资源 |
| **异步任务** | 一切长耗时 LLM 生成 | `POST /api/tasks/{kind}` → 202 `{task_id}`(缓存命中则 200 直接带结果);`GET /api/tasks/{id}` → `{status: running\|done\|error, progress?, result?}`。即 CLAUDE.md"长耗时交付铁律"的 API 化:后台线程 + 先落盘 + 轮询,结果永不押在长连接上 |
| **实时流** SSE/WS | 聊天流式输出、MCP 播放指令推送 | 仅限"断了也无损"的场景(聊天断流可重发;结果仍走落盘) |

异步任务 kind 清单:`annotation`(单行批注)、`intro`(导读)、`translation`(整歌翻译)、`fanlore`(歌迷考据)、`dict-ai`(AI 语境解释)、`rebuild-index`(语料重建,零 LLM 但 1-3 分钟)。
现状只有 fanlore 实现了铁律,其余五个全是同步阻塞/长连接流式——**重写时六个统一收编**,前端只实现一个轮询组件。

## 2. API 契约表

### 曲库与歌曲(读)
| 端点 | 对应现有动作 | 说明 |
|---|---|---|
| `GET /api/songs?q=&sort=` | 歌单筛选/排序 | q 匹配歌名/歌手/全文歌词(lyrics_blob) |
| `GET /api/songs/{id}` | 选歌(元数据部分) | meta + audio(type/src/offset_ms) + bvid |
| `GET /api/songs/{id}/lyrics` | 选歌(歌词部分) | timed_lines + 批注 map + 翻译(有缓存时) |
| `GET /api/songs/{id}/intro` | 导读(缓存命中) | 无缓存返回 404,前端引导走任务 |
| `GET /api/songs/{id}/fanlore` | 考据(缓存命中) | 同上 |
| `GET /api/songs/{id}/notes` | 笔记列表 | |
| `GET /api/songs/{id}/line/{idx}/context` | 点句 | 批注 + 互文 echoes + 母题 + 已存问答,一次请求聚合 |

### 检索与互文(读;即 MCP 7 工具的 REST 化,行为必须与 MCP 完全一致)
`GET /api/search?q=&semantic=` · `GET /api/echoes?text=&artist=&top_k=` · `GET /api/artists/{name}/motifs` · `GET /api/daily-quote` · `GET /api/dict/{word}`(ECDICT + ai_cache 命中)

### 用户数据(同步写;public 模式下全部 403)
| 端点 | 对应现有动作 |
|---|---|
| `POST/DELETE /api/favorites` `/{fav_id}` | 收藏歌词 / 删收藏 |
| `POST /api/songs/{id}/notes` · `DELETE .../notes/{ts}` | 添加/删除笔记 |
| `POST/PATCH/DELETE /api/wordbook/{word}` | 单词本 add/note/del |
| `POST /api/wordbook/import` · `DELETE /api/wordbook/groups/{g}` | 导入词表/删分组 |
| `GET /api/wordbook/export?format=json\|anki` | 两种导出,直接文件流 |

### 寻词练习(读+写)
`POST /api/drill/round?group=` 出题(卡片+TTS URL)· `POST /api/drill/result` 记录(word/mistakes/ms/blind/peeks)· `GET /api/drill/analysis` 热力图数据(**返回 JSON 数据而非 HTML**,渲染归前端)

### 游戏(纯本地)
`GET /api/games/quiz` · `GET /api/games/title-puzzle`(答案随 payload 下发,前端判题——单机学习产品无反作弊需求)

### 管理(admin;服务端强制鉴权)
`GET /api/catalog?q=` · `POST /api/songs/from-catalog`(批量)· `POST /api/songs`(手动,multipart:LRC/音频)· `DELETE /api/songs/{id}`(级联触发 rebuild-index 任务)· `POST /api/songs/{id}/audio` · `PUT /api/songs/{id}/bvid`(含 search 候选:`GET /api/bilibili/search?q=`)· `PUT /api/songs/{id}/offset`

### 聊天(SSE 流)
`POST /api/chat/line` 行级问答(song/line/question;结束时服务端落盘 chat_history)· `POST /api/chat/lore` 考据页问答(不落盘)

### 设置/鉴权/推送
`GET/PUT /api/settings`(public:前端只存 localStorage,每请求头带访客 key)· `GET /api/usage` · `POST /api/auth/login` → session cookie;`GET /api/me` → role · `WS /ws/player`:MCP play_song 推送(替代现在的命令文件 + 1s Timer 轮询)

## 3. 必须修的架构级缺陷(盘点新发现)

1. **鉴权只在 UI 层**:现在 viewer 角色只是 JS 隐藏 tab 按钮,后端 handler 零校验。API 层必须按 role 做服务端门禁(admin 端点 + 非 public 写操作)。
2. **隐藏 Textbox 通道**(ll-line-pick / ll-fav-act / ll-del-song 等十余个 JS→Python 暗道)全部显式化为上表端点,消灭无法测试的接线。
3. **public 模式**作为 API 层的统一中间件(禁写盘 + 访客 key 注入 + admin 端点 403),而非散落在各 handler 的 if。

## 4. Sitemap(信息架构重组)

```
/                  播放解读(全屏沉浸式播放页;右侧坞 → 可收起侧栏/底部抽屉)
/song/{id}?line=n  同上,可分享的深链(现在做不到的能力)
/words             词汇:寻词练习 + 单词本/词组本 + 数据分析(从播放页坞里独立出来)
/explore           互动:歌迷考据 + 歌词竞猜 + 歌名拼图
/library           曲库管理:内置曲库 + 手动添加 + 删除(admin)
/settings          API 密钥 / 用量 / Embedding 重建(admin)
```

变化:① 播放页的📒单词本/📝练习相关坞位归并到 /words,播放页只留与"正在听的这首歌"强相关的(批注/导读/收藏/笔记);② 真 URL 路由带来可分享深链与浏览器前进后退;③ viewer/public 看不到 /library 与 /settings(服务端 + 路由双重门禁)。

## 5. 技术选型

| 决策 | 选择 | 理由 |
|---|---|---|
| 框架 | **React 18 + TypeScript + Vite** | 生态最厚(组件库/动效库全覆盖),AI 辅助编码语料最多,招手即来的轮子最多;Svelte 更轻但本项目交互密度高,生态优先 |
| 样式 | **Tailwind + shadcn/ui** | token 化与现有 ui_assets.py 的 `:root` 变量思路同构,迁移心智成本低;shadcn 源码落在仓库里可随意改,不被组件库样式锁死(呼应"完全突破") |
| 服务端状态 | **TanStack Query** | 自带缓存/失效/轮询(refetchInterval),异步任务轮询与"切歌恢复 in-flight 状态"天然覆盖 |
| 客户端状态 | **zustand** | 全局播放器(当前歌/播放位置/高亮行)一个 store 搞定,跨页面常驻 |
| 动效 | Framer Motion(按需) | 歌词滚动/页面过渡;首版可无 |
| 构建产物 | Vite build → FastAPI StaticFiles 托管 | 单进程部署不变:`lyric-agent serve` 体验不变 |

## 6. 既有行为的保留承诺(回归底线)

- 所有 LLM 结果落盘永久缓存、命中零调用(annotations/intro/translation/fanlore/dict ai_cache/chat_history)——API 层不改变任何缓存文件格式
- public 模式三特征:不写服务器盘、key 来自访客浏览器、管理功能不可达
- MCP server / CLI 行为完全不变(共享数据层)
- 中文歌默认隐藏(LL_SHOW_CJK)、hackathon 歌单 public 排除等过滤规则原样保留

## 7. 里程碑

```
M1 契约冻结:本文档评审通过,接口表覆盖盘点清单全部动作   → 验证:逐行核对盘点表
M2 API 层:FastAPI 路由 + 服务端鉴权 + 六个异步任务收编   → 验证:pytest 新增 API 测试全绿,curl 冒烟
M3 前端骨架:路由 + token + 轮询组件 + 播放器 store       → 验证:空页面全路由可达,主题切换正常
M4 逐页实现:播放解读页最先(评委必看),其余按 sitemap     → 验证:screenshot + design-critic 循环
M5 巡检迁移:ui_probe 35 项逐项改写到新前端               → 验证:全绿后才允许删 Gradio
```

M1-M2 期间旧 UI 完全不动,随时可演示;到 M5 绿灯前 Gradio 一直是逃生舱。
