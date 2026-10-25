# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 18 + TypeScript + Vite，Tailwind CSS + shadcn/ui，TanStack Query（服务端状态/异步任务轮询），zustand（全局播放器状态），Recharts（学习统计图表），HTML5 Audio（播放与歌词同步高亮）。后端 FastAPI 薄 API 层包住现有 Python 数据/引擎层（songdata / annotator / intertextuality / dict / games / fanlore，零改动）。架构契约见 docs/frontend_rewrite_plan.md（四种接口形状、异步任务铁律、sitemap）。

## Users

喜欢听英文歌、想顺便把英语学好的中文听众。核心场景：边听歌边看逐句同步歌词，遇到不懂的句子/单词当场问懂、收藏、之后练会。**重点突出受众诉求：英语歌 → 学英语单词**（用户 2026-10-25 明确强调）。次要角色：admin（曲库管理/设置）、viewer/public 访客（只读学习功能）。

## Product Purpose

歌词透镜 Lyric Lens——"听英文歌，把英语学会"。不是背单词软件，也不是歌词翻译站：点一句歌词，AI 把这句讲懂，再把生词带走练会。学习闭环：听（逐句高亮/卡拉OK渐变）→ 问懂（点句问 AI / 逐句批注 / 整首翻译）→ 查词收藏（双击单词弹词义卡 + 真例句）→ 练会（盲打练习、分组训练、Anki/qwerty-learner 导出）。

## Positioning

单词永远活在它出生的那句歌词里：收藏跟随歌曲、练习卡片嵌在原句、释义带歌词语境 AI 解释。再加互文彩蛋引擎（同歌手跨歌呼应检索 + 彩蛋地图），是词典类和歌词站都抄不走的机制。

## Operating Context

- 桌面浏览器为主（`lyric-agent serve` 单进程本地部署；public 演示模式部署到公网）
- 腾讯音乐高校 AI Hackathon 参赛作品；播放解读页是评委必看页
- 音频来源：本地音频文件或官方试听片段（audio_offset_ms 对齐）；B 站 MV 官方嵌入播放器（不驱动歌词）
- MCP server / CLI 与 Web 三入口共享同一数据层，行为必须一致

## Capabilities and Constraints

- 功能全集：播放解读（同步歌词/批注/导读/翻译/点句问答/收藏/笔记/双击查词）、单词本与寻词练习（盲打、分组、导出、数据分析）、歌迷考据、彩蛋地图、歌词竞猜/歌名拼图、曲库管理、设置
- 所有长耗时 LLM 调用必须走异步任务模式（后台落盘 + 轮询），结果永不押在长连接上
- LLM 结果落盘永久缓存，命中零调用；API 层不改变缓存文件格式
- public 模式三特征：不写服务器盘、key 来自访客浏览器、管理功能不可达（服务端强制）
- 中文歌默认隐藏（LL_SHOW_CJK）；hackathon 歌单 public 排除
- 鉴权必须在 API 层做（旧版只在 UI 层隐藏按钮，是已知缺陷）

## Brand Commitments

- 产品名：歌词透镜 Lyric Lens；中文为主要界面语言
- 已定偏好：AI 生成的文字内容页/卡片一律水平居中 + text-align: center（用户全局审美偏好，2026-10-05）

## Evidence on Hand

- data/songs/ 下 8 首演示歌（含周杰伦中文互文组 + Taylor Swift 英文组），带真实 LRC 时间轴歌词、AI 批注、导读、翻译缓存
- docs/frontend_rewrite_plan.md：已评审的 API 契约与 sitemap
- 旧 Gradio UI（src/lyric_agent/webui/ + ui_assets.py）：功能行为的事实清单；重写中仅作反面参考
- 无真实用户 testimonial / 使用数据，不得虚构

## Product Principles

1. 单词带语境：任何词汇功能都回链到它所在的歌词句，绝不脱离歌曲孤立展示
2. 学习动线优先于功能堆叠：听 → 问懂 → 收藏 → 练会 的闭环必须在界面上显性
3. 结果永不丢：长 LLM 调用后台落盘 + 轮询恢复，刷新/切歌不作废
4. 三入口同行为：Web/MCP/CLI 共享数据层，API 不搬业务逻辑
5. 公开演示安全：public 模式下禁写、禁管理，服务端强制而非前端隐藏
