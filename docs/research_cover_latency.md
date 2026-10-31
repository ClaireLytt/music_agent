# 调研：播放条专辑封面为什么要等几秒才出现

2026-10-30。问题：切到一首没有本地 cover.jpg 的歌，播放条封面要等约 5 秒
（有时更久）才出现。本文定位延迟构成并评估加速方案。测量在本机（Windows，
国内网络）repo 根目录用临时脚本直接调 `cover_art` 内部函数完成。

## 现有链路

1. 前端 `<img src=/api/songs/{id}/cover>`（PlayerBar.tsx:92-105）。
2. 后端命中本地文件即 FileResponse，否则 `cover_art.fetch_async(s)` 起后台
   daemon 线程并立刻 404（api.py:498-508）。
3. 后台 `_fetch` 依次试 iTunes → MusicBrainz/CAA → B 站 MV 图，命中落盘
   cover.jpg（cover_art.py:105-133）。
4. 前端 onError 后固定 5s 重试，最多 12 次 ≈ 60s（PlayerBar.tsx:97-100），
   成功后 500ms 淡入（PlayerBar.tsx:102 `duration-500`）。

## 实测耗时（Anti-Hero / Taylor Swift，3 次取样）

| 阶段 | 耗时 |
|---|---|
| iTunes search RTT | 339 / 347 / 407 ms |
| 600x600 下载（~69 KB） | 454 / 456 / 470 ms |
| 100x100 下载（~4.7 KB） | 336–377 ms |
| `_from_itunes` 端到端 | **889 ms** |
| `_from_caa` 端到端（MusicBrainz 查询 ~2.7s + 遍历 release 多次 404 后下载 45 KB） | **8451 ms** |

## 延迟拆解

用户感知延迟 = 后端抓取时间 + 前端重试量化误差：

- **常规路径（iTunes 命中）**：后端 ~0.9s 就已落盘，但前端第一次重试在
  404 后固定 5s 才发生 → 感知 ≈ **5s + 0.5s 淡入**。瓶颈不在网络，
  在前端 5s 平坦重试的量化延迟（PlayerBar.tsx:100 的 `5000`）。
- **坏路径（iTunes 未命中走 CAA）**：后端 ~9s → 感知落在第 2 个 5s tick，
  约 10s。CAA 每个 release 下载超时 20s（cover_art.py:83），理论最坏
  接近 60s，与前端 12 次重试上限对齐（PlayerBar.tsx:24-25 注释即此意）。

## 加速方案评估

### 1. 预热：/api/songs 时后台批量补缺封面 —— 推荐

模式现成：api.py:260-265 对 iTunes 试听已这么做（`fill_missing_async`，
限速 `_THROTTLE_S = 3`，itunes_audio.py:28；public 门禁同一处判断）。
cover_art 已有进程内去重 + 24h 负缓存（cover_art.py:136-146），批量预热只需
一个节流循环逐首调 `fetch_async` 或仿 fill 线程。打开曲库列表到点歌通常
有数秒间隔，每首 ~0.9s，预热几首后用户点到的歌大概率已有 cover.jpg →
首次 GET 直接 200，**感知 0s**。工作量小（~30 行 + 测试）。注意与
itunes_audio 填充线程共享 iTunes ~20 req/min/IP 限速，节流值应一致。

### 2. 端点 miss 时 hold 连接 ~N 秒轮询文件 —— 可选增强

GET /cover miss 后在线程池里 sleep-poll `find_local`，~3s 内文件出现就直接
200，消除量化延迟 → 感知 ≈ 0.9s + 淡入。CLAUDE.md 的长连接铁律针对的是
分钟级 LLM 调用 + Gradio SSE；这里是 3s 内的静态文件 HTTP 请求，断了前端
本来就会重试，**短 hold 不违反铁律**。代价：FastAPI 默认 def 端点占线程池
一个线程 3s，单用户场景无碍。工作量很小（~10 行）。

### 3. 前端更快首次重试（1s/2s/4s/8s… 退避）—— 推荐

把 PlayerBar.tsx:100 的平坦 5000 改为指数退避：iTunes 路径在第 1-2 次
重试（1-3s 内）即命中 → 感知 ~2s；CAA 路径 ~9s 时累计 1+2+4+8=15s 内
命中，不比现在差。保持总窗口 ≈ 60s 只需调次数上限。工作量最小（1-2 行）。

### 4. 复用 itunes_audio 缓存的搜索结果 —— 现状做不到，改造收益有限

itunes_previews.json 只存了 `{"url": previewUrl, "ts": ...}`
（itunes_audio.py:110），**没存 artworkUrl100**，当前无法直接复用。若在
fill 时顺手存 artworkUrl，可省一次 search RTT（~350ms），后端 0.9s → 0.55s。
但该缓存只覆盖"无音频无 MV"的歌，且省的 350ms 在 5s 量化面前不可见；
只有叠加方案 2/3 后才有感知意义。优先级低。

### 5. 先下 100x100 再换 600x600 —— 不建议

实测 100x100 下载 336–377ms，600x600 也只要 ~460ms，只差 ~100ms，却要双倍
请求、双份状态和一次图片闪换，52px 的播放条封面也看不出差别。overkill，
否。

## 建议组合

**方案 1（列表预热）+ 方案 3（前端指数退避）**，可再加方案 2 兜底：

- 用户正常浏览路径：预热已落盘 → 感知 **0s**。
- 冷启动直达某歌（预热没赶上）：退避 1s 首试 → iTunes 路径感知 **~2s**
  （现在 ~5.5s）；再加方案 2 的 3s hold 可压到 **~1s**。
- CAA 坏路径：~10s，与现状持平，有占位渐变兜底不恶化体验。

总工作量约半天含测试；全部改动都在现有"实验性可整体移除"边界内
（cover_art.py / api.py 封面小块 / PlayerBar img 分支）。
