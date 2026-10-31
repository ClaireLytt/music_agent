# 调研：歌词跟随 B 站 MV 播放进度（embed iframe 同步问题）

> 状态：调研笔记（2026-10-30），供排期决策。
> 背景：MV 播放用官方外链播放器 `//player.bilibili.com/player.html?bvid=...`（iframe），
> 跨域取不到 `currentTime`；现状是本地时钟硬跟（手动同点开始、漂移、暂停即废，
> frontend/src/components/MvPanel.tsx 的 follow/startFollow/stopFollow）。
> 本次外部论断尽量回溯一手来源；GitHub/raw/jsdelivr 在本机网络不可达（curl exit 35，
> 连接被重置），因此 playurl 相关结论**直接对 api.bilibili.com 实测验证**（2026-10-30，
> 测试视频 BV1GJ411x7h7 / cid 137649199），比转述文档更硬。

---

## 方案 1：embed 播放器的 postMessage API —— 不存在

- 官方外链播放器使用说明（https://player.bilibili.com/ ）只给 iframe 嵌入参数
  （bvid/aid/cid/page/autoplay/danmaku/t 等），**没有任何运行时消息接口**，
  没有 play/pause/timeupdate 事件，也没有 seek 控制。
- 有 postMessage API 的是**直播**播放器：`live.bilibili.com` 的嵌入文档
  （https://live.bilibili.com/p/html/bilibili-live-player/docs/api.html ）定义了
  `playerOperation-` 前缀事件（playing/paused/volumeChange）和 `setPlayer-` 控制——
  但那是直播域，且连 seek/进度都没有，对点播 `player.html` 不适用。
- 社区绕法印证了"原生没有"：roam-research-bilibili-timestamp
  （https://github.com/LudwigWS/roam-research-bilibili-timestamp ）要做 iframe 内跳时间戳，
  只能靠 Tampermonkey + Requestly 把播放器的 `liteplayer.min.js` 重定向成改过的版本；
  站内脚本则用同源的 `window.player.seek()/getManifest()`（Bilibili-Evolved 讨论
  https://github.com/the1812/Bilibili-Evolved/discussions/4341 ）——都要求用户装扩展，
  不是产品可用的路径。

**结论：不可行**。无官方 API，逆向 hack 依赖用户侧扩展，不能作为功能基础。

## 方案 2：playurl API 取流，放进自家 `<video>`/`<audio>` —— 技术上完全可行

接口文档：bilibili-API-collect `docs/video/videostream_url.md`
（https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/video/videostream_url.md ，
本机网络不可达，以下为**直接实测**）：

- `GET https://api.bilibili.com/x/player/playurl?bvid=..&cid=..&fnval=16`（DASH）
  **无 cookie、无 WBI 签名即可调通**（code 0），cid 由
  `x/web-interface/view?bvid=..` 得到。
- 免登录可得：DASH 视频最高 **qn 32（480P）**；音频流三档全给
  （30216/30232/30280 ≈ 64K/132K/192K）。`fnval=1` 可拿**单文件 mp4**（免登录
  quality 16=360P，登录后可到 720P），`<video>` 直接可播，省去 MSE 合流。
- 流 URL 实测：无 Referer → **403**；带 `Referer: https://www.bilibili.com` + 浏览器
  UA → **206**（支持 Range，可 seek）；有 Referer 但无 UA → 403。
  浏览器 `<video>` 无法自定义 Referer，所以**必须走本地后端代理**：FastAPI 加一个
  `/api/mv/{song_id}/stream`，服务端带 Referer+UA 转发（透传 Range），完全可行。
- URL 带 `deadline` 参数，实测约 **2 小时过期**——代理应每次播放现取 playurl，
  不缓存流 URL。
- 风险：这是未公开接口，**绕过了 B 站播放器/广告/防盗链**，属于灰色地带
  （yt-dlp/BBDown 等即此路线）。接口形态、风控（近年已加 buvid/WBI 梯度）随时可变。
  仅限本地自用尚可接受；**公开部署（PUBLIC_MODE）不应启用**。

**结论：可行，M 档工作量**（后端代理 + 前端把 iframe 换成自家 `<video>`，
currentTime 原生可读，歌词同步逻辑与本地 `<audio>` 完全复用）。
鲁棒性中等：依赖非公开接口，免登录画质 360/480P。

## 方案 3：其他角度

- **MediaSession API**：只能为*本页自己的*媒体设置元数据/接收硬件键，读不到
  跨域 iframe 的播放位置（https://developer.mozilla.org/en-US/docs/Web/API/Media_Session_API ）。不可行。
- **getDisplayMedia 抓标签页音频 + 指纹对齐本地 mp3**：Chrome 系才支持 tab audio、
  每次都要弹系统选择器、用户必须手选"当前标签页"
  （https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia ），
  再加在线对齐算法。L 档工作量、体验极差。不可行（工程上不值得）。
- **反转主从：本地 mp3 驱动歌词，MV 只做装饰**——即现状 follow 模式的本质，
  只是把"本地时钟"换成"本地 `<audio>` 时钟"。同步精度没变好（iframe 仍是
  黑盒，暂停/卡顿即错位），但这提示了一个**零成本的产品化收口**：MV 面板
  明确定位为"看 MV"或"听本地音频+歌词"二选一，不承诺两者同步。
- **第三方嵌入器**（player.js / embedly 等协议，https://github.com/embedly/player.js/ ）：
  需要宿主播放器实现协议，B 站未实现。不可行。

## 汇总

| 方案 | 可行性 | 工作量 | 鲁棒性 | 主要风险 |
|---|---|---|---|---|
| 1 postMessage | 否（API 不存在） | — | — | — |
| 2 playurl+代理+自家 video | 是 | M | 中 | 非公开接口/ToS、画质限 360-480P、URL 2h 过期 |
| 3a MediaSession | 否 | — | — | — |
| 3b 抓音频+指纹对齐 | 理论可、工程否 | L | 低 | 浏览器限制、每次手动授权 |
| 3c 本地音频驱动+MV 装饰 | 是（但不解决同步） | S | — | 同步承诺要撤掉 |

## 建议

**删掉现有的"跟随"硬跟功能**（startFollow 本地时钟那套）：它承诺了做不到的事，
漂移和暂停即废是结构性的，没有补救空间。

MV 功能本身两条路二选一：

1. **最小方案（推荐）**：保留 iframe 纯观看，移除 follow 按钮及相关 store 状态——
   歌词同步始终由本地 `<audio>` 驱动，MV 是独立的观看入口。改动小、无新风险。
2. **若"MV 画面 + 精准歌词"是 demo 刚需**：做方案 2（本地后端代理 playurl mp4 流，
   自家 `<video>` 播放），仅在非 PUBLIC_MODE 下启用。能拿到原生 currentTime，
   同步质量与本地 mp3 等同，代价是 M 档工作量和对非公开接口的依赖。

不建议在两者之间再留"半同步"状态。
