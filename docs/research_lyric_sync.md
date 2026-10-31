# 调研：逐字（卡拉OK）歌词同步的数据来源与生成方案

> 状态：调研笔记（2026-10-30），供排期决策。
> 背景：播放器目前用行级 LRC（data/songs/<id>/lyrics.lrc，lrc_parser.py 解析，
> lrc_sources.py 只查 lrclib.net 的 /api/search）。卡拉OK 填充 = 当前行到
> 下一行时间戳之间的线性插值（前端 LyricsView 的 karaokeP）。
> 痛点：(a) 每首歌都要手调 audio_offset_ms；(b) 行内填充匀速，真实演唱
> 语速差异极大。本文按"数据来源 / 格式 / 自己生成 / 低技术改良"四路调研。

---

## 1. 大厂怎么做逐字歌词

### Apple Music：TTML + itunes 扩展（行业标杆）

- 官方格式是 **TTML 1.0 的受限方言 + Apple 私有扩展**（命名空间
  `http://itunes.apple.com/lyric-ttml-extensions`），经 Transporter 提交
  （官方资产指南：https://help.apple.com/itc/videoaudioassetguide/en.lproj/static.html ，
  提交流程：https://itunespartner.apple.com/music/support/5218-submit-lyrics ）。
- 行级计时写在 `<p begin end>`，**逐字/逐音节计时写在行内 `<span begin end>`**；
  根节点 `itunes:timing` 只有 None/Line/Word 三值，音节级也声明为 Word，
  靠 span 间空格区分词/音节（社区逆向整理：
  https://github.com/hakimifr/ttml-lyrics-sync ）。
- 社区镜像规范（AMLL TTML DB）完整文档化了该格式，并维护了一个
  **开放的 Apple 式 TTML 逐字歌词库**，可直接借鉴甚至取数：
  https://github.com/amll-dev/amll-ttml-db/blob/main/instructions/ttml-specification-en.md 。
- 数据生产方包括 Musixmatch（也给 Apple 供逐字歌词，
  https://en.wikipedia.org/wiki/Musixmatch ）。

### Spotify：Musixmatch 行级

- Spotify 歌词由 Musixmatch 独家授权与同步，**对用户展示只有行级**
  （官方：https://support.spotify.com/us/artists/article/lyrics/ ）。
- Musixmatch 贡献工具里有逐字（word-by-word）同步模式（仅 App 可用），
  但逐字展示落地在 Apple Music 等平台而非 Spotify
  （https://www.unchainedmusic.io/blog-posts/unchained-guides-how-to-get-your-music-lyrics-to-spotify-genius-and-musixmatch/ ）。
- 结论：Spotify 路线对我们没有增量；Apple 的 TTML span 模型是逐字格式的
  事实标准。

## 2. 可消费的逐字歌词格式与数据源

- **Enhanced LRC（A2 扩展）**：在行级 `[mm:ss.xx]` 基础上加行内
  `<mm:ss.xx>` 词标签，de-facto 标准、无正式规范，KuGou/QQ/网易云/AIMP
  等播放器都认（https://en.wikipedia.org/wiki/LRC_(file_format) ，
  语法细则：https://easylrc.com/blog/lrc-format-complete-guide ）。
  对我们最友好：仍是 .lrc，解析器增量升级即可。
- **lrclib.net（现有唯一源）**：`/api/get` 返回 `plainLyrics` +
  `syncedLyrics`，后者**行级 LRC**（无鉴权、免费，文档 https://lrclib.net/docs ）。
  社区 issue（2026-09）称 lrclib 新增了 `lyricsfile` YAML 字段承载逐字
  时间戳，规范在 https://lrclib.net/lyricsfile ，旧 `syncedLyrics` 保持行级
  （https://github.com/MetrolistGroup/Metrolist/issues/4408 ）。
  **未实测**（本机网络策略挡了 lrclib 直连），接入前需先打一发 API 验证
  字段存在性与覆盖率；覆盖率大概率远低于行级。
- **QQ音乐 QRC**：加密 XML，`[行起始ms,时长]字(字起始ms,时长)` 逐字结构
  （https://baike.baidu.com/item/qrc/2737625 ）；社区有解密+下载工具链
  （qrckit：https://github.com/proify/qrckit ，LDDC 可直接把 QRC/YRC 下成
  逐字 lrc/增强 lrc：https://github.com/hellolio/LDDC ）。
- **网易云 YRC**：`[start,duration](start,duration,0)Word` 明文逐字格式，
  走逆向接口取（解析样例：https://github.com/FPSMasterTeam/Cadence ；
  多格式互转库 Lyricify-Lyrics-Helper 支持 LRC/QRC/KRC/YRC/TTML：
  https://github.com/WXRIW/Lyricify-Lyrics-Helper ）。
  合规：QRC/YRC 均为逆向私有接口 + 解密，**不可进对外产品**，比赛演示
  本地使用灰色但风险可控（中文歌覆盖率最高的一路）。
- **Musixmatch richsync API**：逐字数据在 `track.richsync.get`，免费
  developer key（~2000 调用/天）只给 30% 歌词预览，**richsync/全文属
  商业授权，价格不公开**（https://freeapihub.com/apis/musixmatch ，
  richsync 端点形态：https://github.com/sydlexius/canticle/issues/613 ）。
  对本项目基本不可行。

## 3. 自己生成：强制对齐（同时解决痛点 a）

- **WhisperX**：Whisper 转写 + wav2vec2 强制对齐出词级时间戳，精度约
  ±50ms（vs 原生 Whisper ±500ms），GPU 上 60–70x 实时；faster-whisper
  后端 large-v2 <8GB 显存、对齐模型 +0.5GB，CPU 可跑小模型 + int8
  （https://github.com/m-bain/whisperX ）。已知歌声（lyrics.lrc 已有文本）
  时可只用 `whisperx.align()` 做纯对齐，4 分钟歌在无 GPU 笔记本上也在
  分钟量级。需按语言换 wav2vec2 对齐模型（英文最好；中文有官方对齐模型
  但歌声效果未证）。
- **歌声的坑**：Whisper 系对齐在重复段/半说唱段会"跟丢"，KaraokeFuture
  的做法是先试 torchaudio 的 MMS 强制对齐（仅拉丁字母）再回落 stable-ts
  （https://github.com/abels-lab/KaraokeFuture/pull/5 ）。伴奏干扰大时
  先过人声分离（demucs）再对齐是通行做法。
- **SOFA（Singing-Oriented Forced Aligner）**：专为歌声设计，自称比 MFA
  更易装、更准、更快，默认中文歌唱词典（opencpop-extension），输入
  wav+文本（https://github.com/qiuqiao/SOFA ）——中文歌的最优解。
- **MFA**：有 Windows conda 包和 mandarin 声学模型/词典，但按语音训练，
  对歌声只宜粗对齐 + 人工校正（GTSinger 语料的做法，
  https://arxiv.org/pdf/2409.13832 ；中文流程参考
  https://github.com/lars76/forced-alignment-chinese ）。
- **对痛点 a**：对齐出的第一行真实起唱时间 − LRC 第一行时间戳 ≈
  audio_offset_ms，可全库批量自动校准，哪怕不上逐字渲染也值得做。

## 4. 低技术改良：行内音节加权插值（零依赖）

- 先例不少：TermiLyrics 的 `estimate_syllables()` 按音节数（CJK 单字=1、
  英文按元音组）加权分配行内时长，避免 "a" 和 "beautiful" 等宽
  （https://github.com/mr1charles/TermiLyrics/pull/1 ）；nusamusic 对
  仅行级的 LRC/TTML 在原区间内做估计并保留 CJK/Unicode 簇
  （https://github.com/yohandeku32/nusamusic/pull/144 ）；YTFast 进一步
  用"最快 30% 行的语速"定上限、末词延长（拖音），实测词起点平均误差
  0.366s、57% 在 0.25s 内（https://github.com/Likheet/YTFast/pull/37 ）。
- 工程含义：把 karaokeP 从线性换成"按词音节数的分段线性"，纯前端
  十几行代码，无新数据；只缓解痛点 b 的观感，不解决痛点 a。

---

## 5. 对比与建议

| 方案 | 数据来源/工具 | 词级? | 获取难度 | 合规 | 痛点a偏移 | 痛点b匀速 |
|---|---|---|---|---|---|---|
| 音节加权插值 | 无（纯前端估计） | 伪词级 | 零 | 无风险 | 无改善 | 明显缓解 |
| Enhanced LRC + lrclib lyricsfile | lrclib 开放 API | 词级 | 低（需实测字段+覆盖率） | 好 | 间接（词戳更准） | 根治（有数据时） |
| QRC/YRC 抓取 | QQ/网易逆向接口（LDDC 等） | 词级 | 中（解密/逆向） | 灰（仅本地演示） | 间接 | 根治，中文覆盖最好 |
| Musixmatch richsync | 商业 API | 词级 | 高（商业授权） | 需付费合同 | 间接 | 根治但不可行 |
| Apple TTML / amll-ttml-db | 社区 TTML 库 | 词/音节级 | 中（格式新、覆盖看运气） | 好（社区库） | 间接 | 根治（命中时） |
| WhisperX/SOFA 强制对齐 | 本地音频+已有歌词 | 词级 | 中（装环境；CPU 慢但可用） | 好（自产） | **根治（自动校准offset）** | 根治 |

**建议路径（按性价比排序）：**
1. **先上音节加权插值**：零依赖立刻改善观感（样板 TermiLyrics/YTFast）。
2. **lrc_parser 支持 Enhanced LRC `<mm:ss.xx>`**，作为统一的内部词级表示；
   QRC/YRC/TTML/对齐结果都转成它落在 lyrics.lrc 旁（LDDC、
   Lyricify-Lyrics-Helper 已证明互转可行）。实测 lrclib `lyricsfile`
   字段后决定是否在 lrc_sources.py 顺带抓词级。
3. **自立路线：WhisperX（英文）/SOFA（中文）离线对齐**生成词级时间戳并
   自动推导 audio_offset_ms——唯一同时根治 a、b 且不依赖外部数据覆盖率
   的方案，适合做成 add-song 流程里的可选步骤。
