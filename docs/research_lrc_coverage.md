# 调研：LRCLIB 搜不到 lonely / my shot 的 .lrc，而 iTunes 能搜到——原因与对策

日期：2026-10-31。相关代码：`src/lyric_agent/lrc_sources.py`（唯一的 LRCLIB 实现）。

## 结论先行

**不是覆盖缺口，两首歌 LRCLIB 都有同步歌词。** 实测两类真正原因：

1. **瞬时 503/429 被当成"没找到"**：`fetch_synced_lyrics` 用裸 `except Exception: return None`，LRCLIB 过载时返回 `503 ServerOverloaded`（本次实测多次命中），urllib 抛 HTTPError 被吞掉，上层只看到 None，与"真没歌词"不可区分，且无重试。本库落盘的正是占位 LRC（`data/songs/lonely/lyrics.lrc` 为"暂无歌词"占位）。
2. **`q=` 拼串搜索的排序不可控**：`q=Justin Bieber Lonely` 的前三条是 *One Less Lonely Girl*（都有 syncedLyrics），代码取"第一条有 syncedLyrics 的"会拿到**错歌**；`q=hamilton My Shot` 第一条是 `instrumental: true`（syncedLyrics 为 null）的脏记录。而 iTunes 之所以稳，是它的 search 本身按相关度排序主流曲库，且 `cover_art.py` 还做了 artist 子串校验兜底。

## 现状代码

`src/lyric_agent/lrc_sources.py:19-33`：拼 `q=<artist> <title>` 调 `https://lrclib.net/api/search`，取第一个带 `syncedLyrics` 的结果；任何异常（含 503/429/超时）统一 `return None`，仅 warning 日志。对比 `src/lyric_agent/cover_art.py:58-66`（iTunes）：结构化 `term` + `entity=song`，并优先挑 `artistName` 含目标 artist 的结果。

两首歌的实际检索串（`data/songs/*/metadata.json`）：

- lonely → `q=Justin Bieber Lonely`
- my_shot → `q=hamilton My Shot`（artist 存成了剧名 "hamilton"，不是真实 artist）

## LRCLIB API 要点（来源：https://lrclib.net/docs.md）

- `/api/search`：`q=` 在**所有字段**（标题/artist/专辑）做关键词匹配，优先级高于结构化参数；也可用 `track_name=` + `artist_name=` 结构化搜索。最多返回 20 条、无分页，**未承诺排序**。
- `/api/get`：`track_name` + `artist_name` 必填，`album_name`、`duration` 可选但强烈推荐；**duration 必须 ±2 秒内匹配**才返回，否则 404。本库 metadata 没有 duration，不适合直接用 /api/get。
- 限速：匿名/通用 UA 约 45 req/min/IP，带应用名 UA 约 90；超限返回 `429` + `Retry-After`（**必须遵守**）；极端过载时返回 `503 ServerOverloaded`。文档要求 UA 带项目链接或邮箱（现在是 `lyric-agent/0.1`，不合规，会按更低档限速）。

## 实测（2026-10-31，curl）

```bash
curl -s 'https://lrclib.net/api/search?q=Justin%20Bieber%20Lonely'
# 多次直接得到: {"message":"The server is busy, please retry in a moment",
#   "name":"ServerOverloaded","statusCode":503}
# 重试成功后 20 条，前 3 条均为:
#   "trackName":"Justin Bieber - One Less Lonely Girl"  syncedLyrics: 有  ← 错歌排最前
#   第 8 条才是 "Lonely" / "Justin Bieber"  syncedLyrics: 有

curl -s 'https://lrclib.net/api/search?track_name=Lonely&artist_name=Justin%20Bieber'
# 20 条，第 2 条起全是 "Lonely" / "Justin Bieber"，syncedLyrics: 有 ✓

curl -s 'https://lrclib.net/api/search?q=hamilton%20My%20Shot'
# 第 1 条: "My Shot" / "Hamilton Broadway Cast"  instrumental:true, syncedLyrics:null
# 第 2 条: '"My Shot" from HAMILTON' / "Original Broadway Cast of Hamilton"  syncedLyrics: 有 ✓

curl -s 'https://lrclib.net/api/search?track_name=My%20Shot&artist_name=hamilton'
# 20 条，第 3 条起多条 "My Shot" / "Hamilton Original Broadway Cast"，syncedLyrics: 有 ✓
```

即：**四种查询变体最终都能命中带 syncedLyrics 的正确记录**（现行"跳过无 synced 的第一条"逻辑对 my_shot 也能跳过 instrumental 脏记录），失败窗口来自 503 无重试；lonely 还叠加"第一条有 synced 但是错歌"的正确性隐患。

## 备选 / 兜底歌词源

| 源 | 可用性 | 备注 |
| --- | --- | --- |
| NetEase Cloud Music | 非官方 API（`music.163.com/api/song/lyric`），无 key | 中文曲库最全，欧美主流也有；接口非公开契约，随时可变；ToS 灰色 |
| QQ Music | 仅非官方逆向接口，需签名参数 | 维护成本高，不建议 |
| Musixmatch | 官方 API 需 key，免费档无 `subtitles`（同步歌词要付费 plan）；社区走的是逆向 token | 正规商用唯一选项，但同步歌词收费 |
| Megalobiz | 无 API，只能爬 HTML | syncedlyrics 包内置爬虫 |
| `syncedlyrics` Python 包（https://github.com/moehmeni/syncedlyrics，MIT） | pip 可装，聚合 Musixmatch(逆向)/LRCLIB/NetEase/Megalobiz/Genius 等 provider | 省自己写聚合，但多数 provider 走逆向/爬虫，ToS 风险自担，接口脆 |

许可提示：LRCLIB 本身开源开放（https://github.com/tranxuanthang/lrclib）、无 key；其余逆向源用于比赛 demo 可接受，不宜写进对外产品承诺。

## 建议（按工作量排序）

1. **（小，先做）查询与可靠性修复**，只动 `lrc_sources.py`：
   - 改用 `track_name=<title>&artist_name=<artist>` 结构化搜索，artist 为空时退回 `q=<title>`；结果里优先挑 `trackName` 与目标标题大小写无关相等、且非 `instrumental` 的记录（对齐 cover_art.py 的 artist 校验思路），解决"错歌排第一"。
   - 对 429/503/超时做 2~3 次退避重试（429 遵守 `Retry-After`），并把 HTTP 错误与"真 404/空结果"分开记日志。
   - UA 改为文档要求的 `lyric-agent/0.1 (+项目地址)` 拿更高限速档。
   - 查询串顺手清洗：去 `feat.` 后缀和括号备注后重试一次 title-only。
2. **（中）fallback 链**：LRCLIB 两轮都空时串接 `syncedlyrics` 包或直连 NetEase lyric 接口（遵守"长耗时调用走 background_task.py"铁律，不进请求 handler）。
3. **（零成本，已存在）手动兜底**：`PUT /api/songs/{id}/lyrics` 手动上传 LRC 已上线，UI 占位文案也已引导编辑 `lyrics.lrc`；对个别顽固缺失歌曲用这条路即可。

另：add-song 流程建议在拿到占位歌词时显式提示"LRCLIB 请求失败（503），稍后重试"而非静默落盘占位——与 CLAUDE.md"不许提交占位 LLM 输出"同类卫生问题。
