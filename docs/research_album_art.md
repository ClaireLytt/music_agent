# 调研：播放条封面位自动抓取专辑图

> 状态：调研笔记（2026-10-30），供排期决策。
> 背景：PlayerBar 左下角封面位目前是占位渐变方块。歌在 data/songs/<id>/，
> metadata.json 有 title/artist/album/year，可选 bvid。后端已接 iTunes
> Search（试听，见 research_audio_sources.md）和 bilibili playurl/pagelist
> （本地 Referer 代理，见 research_bilibili_sync.md）。调研口径：可行性 /
> 鉴权 / 浏览器 `<img>` 能否直连 / 匹配准确率 / 合规性。
> 标注【实测】的结论来自 2026-10-30 当天的真实请求。

---

## 1. iTunes Search API（首选）

- **可行性**：search 结果（entity=song）自带 `artworkUrl30/60/100` 三档
  （官方文档：https://performance-partners.apple.com/search-api ）。
  【实测】搜 "Anti-Hero Taylor Swift" 第一条即正确曲目，带
  previewUrl + artworkUrl100。
- **高清变体**：把 URL 末段 `100x100bb.jpg` 改成 `600x600bb.jpg` 等任意
  尺寸是社区惯用法，**官方文档只承诺到 100**，属"广泛可用但无契约"
  （Apple 官方论坛也只建议此法：https://developer.apple.com/forums/thread/680550 ）。
  【实测】`600x600bb.jpg` 返回 200 / image/jpeg / 69KB。做法：请求 600，
  失败回落 100。
- **鉴权 / 限速**：免 key；约 20 req/min/IP（同上官方文档），项目里
  itunes_audio.py 已按 3s 节流。
- **`<img>` 直连**：【实测】mzstatic CDN 响应带
  `Access-Control-Allow-Origin: *`，无 Referer 校验，`<img>` 热链无障碍
  （其实 `<img>` 本就不要求 CORS）。
- **准确率**：主流欧美/日流行歌极高；查询串可加 album 提升消歧。现有
  itunes_audio 缓存**只存了 previewUrl 没存 artwork**，需补一个字段。
- **合规**：Search API 面向联盟推广展示，非商用展示封面是行业普遍实践；
  条款要求不得暗示 Apple 背书（https://performance-partners.apple.com/search-api ）。
  本项目本地/比赛演示场景风险低。

## 2. MusicBrainz + Cover Art Archive（免费官方，次选）

- **流程**：MB 搜索 release-group（`ws/2/release-group/?query=...&fmt=json`）
  拿 mbid → `https://coverartarchive.org/release-group/<mbid>/front-500`
  307 跳转到 archive.org 图片（API 文档：
  https://musicbrainz.org/doc/Cover_Art_Archive/API ）。
  【实测】搜 "Midnights + Taylor Swift" score=100 命中，front-500 返回
  307 → archive.org JPEG，响应带 `Access-Control-Allow-Origin: *`。
- **鉴权 / 限速**：免 key，但 MB 要求有意义的 User-Agent 且 **1 req/s**
  （https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting ）；CAA 图片
  本身不限速。图片托管在 archive.org，国内直连时慢时断——**后端下载落盘
  比前端热链可靠**。
- **准确率/覆盖**：主流专辑覆盖好，但搜索打分偏松，需校验 artist 命中；
  部分 release 无封面（404）。
- **合规**：CAA 就是为第三方展示封面而建（MetaBrainz + Internet Archive
  合办，https://coverartarchive.org/ ），合规性五个来源里最干净。

## 3. bilibili 视频封面（有 bvid 的歌）

- **可行性**：view API（`api.bilibili.com/x/web-interface/view?bvid=...`）
  免登录返回 `pic` 字段（字段文档：
  https://socialsisteryi.github.io/bilibili-API-collect/docs/video/info.html ）。
  【实测】无 cookie 请求返回 code=0，pic 为 i2.hdslb.com JPEG。
- **`<img>` 直连**：【实测】hdslb.com 图片 CDN **不校验 Referer**（与
  playurl 流不同），且 `Access-Control-Allow-Origin: *`，可直接热链，
  不需要走现有 Referer 代理。注意 `pic` 返回的是 http://，前端要改 https。
- **准确率**：是 MV 封面不是专辑封面，构图常带标题字幕，只适合兜底或
  "MV 模式"下替代。合规同 research_bilibili_sync.md 结论：view 是公开
  web 接口，灰度低，但热链他人图床公开部署仍不妥。

## 4. Spotify Web API

- 需注册 app + OAuth client-credentials 才能调 `/v1/search`，album 对象
  带 640/300/64 三档 images（https://developer.spotify.com/documentation/web-api/reference/search ）。
  CDN（i.scdn.co）可热链，但**开发者设计条款要求展示封面时保持原样并
  附带 Spotify 归因/可跳转**（https://developer.spotify.com/documentation/design ），
  且 2025 起新 app 配额审核收紧。对一个只要封面图的需求是最重的方案，
  不建议。

## 5. Deezer / Last.fm

- **Deezer**：`api.deezer.com/search` 传统上免 key，track 带
  `album.cover_xl`（1000px）（https://developers.deezer.com/api ）。
  【实测】本机直连 api.deezer.com 与 dzcdn.net 均无响应（疑地域/网络
  受限），国内不可靠，不采用。
- **Last.fm**：`album.getInfo` 需注册 API key（https://www.last.fm/api/show/album.getInfo ），
  且其封面图近年大量缺失/占位，社区普遍转投 iTunes/CAA，不值得接。

---

## 对比与建议

| 来源 | 鉴权 | 图质量 | `<img>`直连 | 准确率 | 合规 |
|---|---|---|---|---|---|
| iTunes Search | 免 key（~20/min） | 600px（非契约） | 可（ACAO:*，实测） | 高 | 可接受 |
| MB+CAA | 免 key（1/s+UA） | 500/1200px | 可但 archive.org 国内不稳 | 中高 | 最干净 |
| bilibili pic | 免登录 | MV 封面非专辑图 | 可（实测不校验 Referer） | 低（非专辑） | 灰度低 |
| Spotify | OAuth+审核 | 640px | 可 | 高 | 条款最重 |
| Deezer/Last.fm | 免key/需key | 1000px/缺失多 | — | — | 国内不可达/图缺 |

**建议**：后端解析 + 落盘缓存，一次抓取终身可用，顺序：

1. `data/songs/<id>/cover.jpg` 已存在 → 直接由现有静态路由供图（最优先，
   也允许用户手动放图覆盖）。
2. **iTunes Search**：复用 itunes_audio.py 的搜索/节流/负缓存骨架（它
   已经在打同一个端点拿 previewUrl，同一次响应里就有 artworkUrl100——
   只需在缓存里多存一个 `artwork` 字段，600 失败回落 100），后端下载
   落盘为 cover.jpg。
3. **CAA 兜底**：iTunes 未命中时按 artist+album 查 MB → front-500 落盘
   （1 req/s 节流，UA 带项目名）。
4. **bilibili pic 最后兜底**（仅有 bvid 的歌），落盘同路径。

集成形态：一个 `GET /api/songs/{id}/cover` 端点（或在现有 song detail
里带 cover 字段），命中落盘文件直接返回，未命中触发后台补抓（遵循
CLAUDE.md 的后台线程 + 轮询交付铁律，不阻塞请求）；前端 `<img>` 只认
本站 URL，失败显示现有占位渐变。落盘到歌目录意味着备份/导出自然携带，
且不依赖外链存活。
