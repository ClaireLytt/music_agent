# 调研：自动获取可播放音频的平台 API 候选

> 状态：调研笔记（2026-10-30），供排期决策。
> 背景：audio_provider.py 现有解析链是 本地 audio.mp3 → metadata.json 的
> `audio_url` → 无音频（纯歌词模式）。手动找 mp3 很痛苦，想接平台 API
> 自动拿可播流。调研口径：能否拿到可播 URL（全曲/试听）、鉴权、浏览器
> `<audio>` 能否直连（CORS/Referer）、URL 时效、合规性。

---

## 1. 网易云音乐

- **官方开放平台**：没有面向个人开发者的播放 API。可用的全是逆向接口。
- **Binaryify/NeteaseCloudMusicApi**（3 万 star 的事实标准）已于 2024-01
  以"保护版权"为由清空代码、2024-04 归档（https://github.com/Binaryify/NeteaseCloudMusicApi ，
  https://www.sohu.com/a/753958710_114760 ）。社区续命项目：
  xgxdmx/NeteaseMusic-API（基于 v4.28.0 自行维护，
  https://github.com/xgxdmx/NeteaseMusic-API ），另有 GitLab 备份镜像。
- **拿流的两条路**（文档：https://binaryify.github.io/NeteaseCloudMusicApi/ ）：
  - `/song/url`（eapi 加密接口）：免费歌（fee=0/8）给全曲 mp3；VIP 歌
    （fee=1）无 `MUSIC_U` 登录 cookie 时 URL 为空或 403；带 VIP 账号
    cookie 可拿全曲。URL 带 `expTime` 过期时间戳，过期 403
    （https://github.com/metowolf/NeteaseCloudMusicApi/wiki/网易云音乐API分析---weapi ）。
  - **官方外链** `https://music.163.com/song/media/outer/url?id=<id>.mp3`：
    302 到 CDN，免费歌直接可播、可做 `<audio>` src（官方 API 文档即推荐
    此法解 403）；VIP/版权受限歌则重定向到失败页或 30s 片段，不可靠
    （https://5ime.cn/481.html ）。流本身 CDN 不校验 Referer、支持 Range。
- **合规**：全部是未公开逆向接口，灰色；原作者删库即是版权压力的直接证据。
  本地自用可接受，公开部署不应启用（与 research_bilibili_sync.md 同一结论）。

## 2. QQ音乐 / 腾讯音乐

- **官方**：QQ音乐开发者平台（https://y.qq.com/music_developer/ ）提供
  登录授权 / OpenAPI / QPlay 三块能力，但面向**企业合作资质**（智能硬件、
  公播场景），需商务申请，不接受个人 hackathon 项目直接调播放 API。
  腾讯音乐高校 AI Hackathon 官方材料只给了歌单（9778975366）作素材，
  **没有发放任何音频 API 凭证**——参赛语境≠拿到 sanctioned 播放接口。
- **逆向**：jsososo/QQMusicApi 一脉已不活跃；现活跃的是 Python 封装
  luren-dc(L-1124)/QQMusicApi（https://github.com/L-1124/QQMusicApi ，
  PyPI `qqmusic-api-python`，自述"仅限技术研究，勿商用"）。拿播放 URL
  （vkey 签名、有时效）**必须传登录态 cookie**，VIP 歌还要 VIP 账号；
  Meting 系项目的 issue 也证实 QQ 源"需配置登录态 COOKIE 才能用"
  （https://github.com/metowolf/Meting-API/issues/16 ）。
- **合规**：主办方自家平台的逆向接口，hackathon 项目用它反而最敏感。不推荐。

## 3. Spotify Web API

- `preview_url`（30s 片段）已于 **2024-11-27 对新建应用停发**，永久返回
  null，官方声明不会恢复（https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api ；
  社区确认帖 https://community.spotify.com/t5/Spotify-for-Developers/Kind-request-regarding-the-Spotify-Web-API-preview-url/td-p/6909407 ）。
  同批还砍了 recommendations/audio-features 等。
- 全曲播放只能走 Web Playback SDK + 用户 Premium 登录，且音频在 SDK
  黑盒里，拿不到可塞进自家 `<audio>` 的 URL。另外 Spotify 中国大陆不可用。
- **结论：对本项目已无价值**（社区的替代方案恰恰是转投 iTunes API）。

## 4. iTunes Search API（Apple）

- `https://itunes.apple.com/search?term=..&media=music&entity=musicTrack&country=cn`
  （或 us/jp）：**免 key、免登录**，返回 `previewUrl`——30 秒 AAC(m4a)
  试听，官方文档明确该字段
  （https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/UnderstandingSearchResults.html ）。
- 曲库是主流商业曲库（Taylor Swift / 周杰伦等都有，取决于 country 分区）。
- CORS：预览音频 CDN（audio-ssl.itunes.apple.com）带 CORS 头，`<audio>`
  直连可播、`crossOrigin='anonymous'` 下 Web Audio 分析也合法
  （https://dev.to/bryanhamiltondev/building-a-real-audio-hover-preview-with-zero-dependencies-2mgp ）；
  但 **search 端点本身的 CORS 不稳定**（多个目录站报告不带 CORS 头，
  https://shipapis.dev/api/itunes-search ），所以搜索应由 FastAPI 后端代发，
  拿到 previewUrl 再交给前端直连播放。限速约 20 次搜索/分钟/IP。
- 合规：公开 API，但条款要求预览用于"推广商店内容"；教育/个人 demo 的
  30s 试听属于最接近白色的选项。**硬伤：只有 30 秒**，对整首歌词跟随
  只能覆盖片段（现有 `audio_is_preview` 字段正好可标记）。

## 5. YouTube / yt-dlp

- 曲库最全、几乎必有 MV/Topic 音频；yt-dlp 工具本身合法开源，但用它下载
  **违反 YouTube ToS**（ToS 禁止官方功能以外的下载），属平台合同违约，
  后果是限流/封号而非违法（https://audioutils.com/blog/is-yt-dlp-legal ，
  https://www.tbd.yt/blog/is-it-legal-to-download-youtube-videos/ ）；RIAA 曾
  以"rolling cipher 规避"推动 GitHub 下架。技术上近年 PO token/SABR 风控
  频繁 break，需要常更 yt-dlp；且国内网络不可直达。
- 形态上是"下载成本地 audio.mp3"而非在线流，等于给解析链第 1 层做
  自动化填充。**本地自用可作兜底脚本，不进在线解析链。**

## 6. Jamendo / Free Music Archive 等正版免费库

- Jamendo API（https://developer.jamendo.com/v3.0 ）：官方、client_id 即用、
  免费档 3.5 万请求/月，直接返回可流式播放的音频 URL，非商用免费。
- 但曲库是 **独立音乐人 CC 授权作品，没有主流商业歌曲**
  （https://help-licensing.jamendo.com/hc/en-us/articles/20699346005661-Jamendo-API ）。
  本项目曲库是主流流行歌，命中率≈0。合规满分但不解决问题，不接。

## 7. 酷狗 / 酷我 / B 站音频

- 酷狗免登录接口（wwwapi.kugou.com `play/getdata`）已被限制为 1 分钟试听
  且拿不到 VIP 歌（https://www.daimadog.com/9745.html ）；酷我源在 Meting
  系项目中报"已失效待修复"（https://github.com/metowolf/Meting-API/issues/16 ）。
  现存方案（MakcRe/KuGouMusicApi、live-ling/Meting-API）普遍要求登录
  cookie + 自动续期监测，维护成本高、同样灰色。不值得单独接。
- **B 站 playurl 音频流**：research_bilibili_sync.md 已实测——免登录可拿
  192K AAC 音频流，流 URL 需 `Referer: https://www.bilibili.com`+浏览器 UA
  （403 否则），约 2 小时过期，必须走 FastAPI 代理转发（透传 Range）。
  很多歌已有 bvid（MV 功能在用），**这是免登录拿"整首"音频的最现实路径**，
  但同为非公开接口，仅限本地模式。

---

## 对比与推荐

| 来源 | 音频长度 | 鉴权 | 浏览器可直连? | 合规性 | 推荐度 |
|---|---|---|---|---|---|
| iTunes Search API | 30s 试听 (m4a) | 无 | 音频可直连；搜索走后端 | 公开 API，较白 | ★★★★ |
| B 站 playurl 音频流 | 整首（MV 音轨） | 免登录 | 否，需后端代理带 Referer | 灰色，仅本地 | ★★★★（已有调研/bvid 基础） |
| 网易云 outer 外链 / song/url | 免费歌整首；VIP 歌不可 | 免登录（VIP 需 cookie） | 外链可直连 | 灰色，原库已删 | ★★★ |
| yt-dlp 下载 | 整首（落盘 mp3） | 无 | —（变本地文件） | 违 YouTube ToS | ★★（离线兜底脚本） |
| QQ音乐逆向 | 整首 | 必须登录 cookie | 否 | 灰色且是主办方平台 | ★ |
| 酷狗/酷我 | 1 分钟/失效 | cookie | 否 | 灰色 | ★ |
| Spotify | 无（preview 已停发） | — | — | — | ✕ |
| Jamendo/FMA | 整首 | client_id | 可 | 白 | ✕（无主流曲库） |

**建议的接入形态**（都不改变"metadata 可手工覆盖"的现状）：

1. **第一步接 iTunes 试听**：audio_provider 解析链加第 2.5 层——本地无
   文件且无 `audio_url` 时，后端按 `title+artist` 查 iTunes Search（结果
   缓存进 metadata.json：`audio_url`+`audio_is_preview: true`，现有字段
   零改动），前端 `<audio>` 直连 previewUrl。成本最低、最白，立刻消灭
   "完全没声音"的歌。
2. **第二步接 B 站音频代理**（本地模式限定）：对已有 bvid 的歌加
   `GET /api/audio/{song_id}/stream`，复用 bilibili 调研的 playurl+Referer
   代理方案取 DASH 音频流，整首可播。优先级高于 30s 试听。
3. 最终解析顺序：本地文件 → metadata `audio_url` → B 站音频代理（本地
   模式且有 bvid）→ iTunes 30s 试听 → 纯歌词。网易云 outer 外链可作为
   手工填 `audio_url` 时的推荐来源写进 add-song skill，不做自动化依赖。
4. PUBLIC_MODE 下只保留本地文件与 iTunes 试听，灰色源一律关闭。
