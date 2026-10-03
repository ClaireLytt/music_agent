---
name: lyric-lens
description: 通过 MCP 工具操作歌词透镜播放器——查歌/放歌/解读歌词/追彩蛋。用户说「放一首 XX」「用播放器放」「查歌词」「这句歌词什么意思」「找彩蛋」「挖母题」「lyric-lens」时使用。
---

# lyric-lens · MCP 工具使用剧本

歌词透镜（Lyric Lens）通过 MCP 暴露曲库查询与播放控制。本 skill 教你
把 8 个工具串成完整工作流，而不是逐个裸调。

## 前提

- MCP server 已注册：`claude mcp add lyric-lens -- lyric-agent mcp --root <仓库路径>`
  （Claude Desktop 配置见 README「MCP 集成」节）。
- **播放类操作**额外需要：`lyric-agent serve` 正在运行、页面已在浏览器打开、
  且用户在页面上点击过至少一次（浏览器自动播放策略）。
- 工具列表里没有 lyric-lens 时：把上面的注册命令告诉用户，**不要空转重试**。

## 工具速查

| 工具 | 用途 | 成本注记 |
|---|---|---|
| `list_songs()` | 全曲库清单（标题/歌手/专辑/年份/有无音频） | 毫秒 |
| `search_lyrics(query, semantic=False, limit=10)` | 搜歌词。模糊描述（"关于雨的歌"）用 `semantic=True` | 关键词毫秒级；semantic **首调约 10-20s**（加载模型），先告知用户再调 |
| `get_lyrics(title)` | 整首歌词，带行号 `i` 与时间戳 | 毫秒 |
| `get_annotation(title, line_index)` | 某一行的 AI 批注（修辞/意象/情感/用典） | 毫秒；无批注的歌会明确报错 |
| `find_echoes(lyric_text, artist=None, top_k=4)` | 一句歌词的「彩蛋」呼应（语义相似的其他歌词） | 首调加载 embeddings，之后快 |
| `artist_motifs(artist, top_n=6)` | 歌手反复埋的母题意象 + 例句 | 纯统计，快 |
| `daily_quote()` | 今日推荐歌词 + 解读 | 毫秒 |
| `play_song(title, line_index=None)` | 浏览器播放器切歌播放，可定位到行 | 写命令文件，1-2 秒生效 |

## 标准剧本

### ① 放歌：「放一首周杰伦关于雨的歌」
1. `search_lyrics("雨", semantic=True)`（或先 `list_songs()` 按歌手筛再搜）；
2. 从命中里挑目标，记下**准确 title** 和命中的 `line_index`；
3. `play_song(title, line_index=命中行)`——会切歌、定位并高亮那一行；
4. 回复用户已切到哪首、定位到哪句；若无声，提醒"在页面上点一下即可"。

### ② 解读：「这句歌词什么意思」/「帮我解读 XX」
1. `get_lyrics(title)` 拿到行号；
2. `get_annotation(title, i)` 取该行批注，组织成回答；
3. 返回"没有批注"时如实说明（这首歌尚未生成 AI 批注），**不要编造解读**。

### ③ 互文：「这句在他别的歌里出现过吗」/「挖挖 XX 的母题」
- 单句溯源：`find_echoes("歌词原句", artist="歌手名")`；
- 歌手级：`artist_motifs("周杰伦")` → 按母题讲"反复埋藏的意象"故事。

## 纠错约定

- 工具返回 `{"error": …, "available_titles": […]}` 时：先用 available_titles
  自纠歌名**重试一次**，仍失败就把 error 原样转告用户，不再重试。
- `play_song` 返回 ok 只代表命令已下发——播放器端生效依赖 serve 在跑。

## 边界

- 公开部署（PUBLIC_MODE）下 `play_song` 会拒绝：转为只读查询，向用户说明
  "公开版不提供远程播放控制"。
- 比赛歌单素材在公开模式下自动从查询结果排除，这是版权守卫，不要绕过。
