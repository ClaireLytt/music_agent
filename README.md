# 歌词透镜 Lyric Lens — AI 歌词批注播放器

> 让每位听众都能成为歌词研究者。

播放歌曲时歌词逐句同步高亮（含逐字卡拉OK渐变），点击任意一句即可展开 AI 深度解读；
在整个曲库维度上，还能追踪歌与歌之间的互文「彩蛋」、意象演变与情绪版图。

## Quick Start

```bash
# 1. 克隆并安装（all = LLM + UI + embeddings + 全部扩展功能）
git clone https://github.com/ClaireLytt/music_agent.git
cd music_agent
pip install -e ".[all]"

# 2. 配置
cp .env.example .env
# 编辑 .env：填入 API_KEY、选择 LLM_PROVIDER（也可以稍后在界面「⚙️ 设置」页填）

# 3. 准备数据（仓库已带 8 首演示歌的歌词与批注，可直接跳到第 4 步）
python scripts/fetch_lrc.py          # 从 LRCLIB 抓取带时间戳歌词
lyric-agent generate-all             # 为歌曲生成 AI 批注
python scripts/build_corpus.py       # 构建互文语料库
lyric-agent embed                    # 生成语料库 embeddings（彩蛋/语义搜索需要）

# 4. 启动
lyric-agent serve
# 打开 http://127.0.0.1:7860
```

可选的系统依赖：

| 依赖 | 影响的功能 | 缺失时的行为 |
|---|---|---|
| **ffmpeg**（加入 PATH） | 🎙️ 听歌识曲对 mp3/m4a 曲目建索引 | 明确列出未入索引的歌曲并提示安装；wav 不受影响 |
| 网络（cdnjs） | 🌊 波形进度条（wavesurfer） | 波形区自动隐藏，播放器功能完整 |
| 网络（Microsoft TTS） | 📻 电台串场语音合成 | 生成时报错提示，其余电台功能可用 |

## 功能总览（8 个页签）

### 🎧 播放解读
- **同步歌词**：LRC 时间轴逐句高亮 + 自动滚动；**逐字卡拉OK渐变**（按行时间戳估算进度）；
  官方试听片段自动对齐（`audio_offset_ms`）
- **播放工具**：🌊 波形进度条（点击跳转）· ⏩ 一键跳副歌（重复行检测）·
  🅰🅱 A-B 区间循环跟唱 · 🎯 韵脚高亮（中文按韵辙、英文按 CMU 词典，同韵同色圆点）
- **📒 双击取词**：歌词里双击英文单词，离线词典（ECDICT 精简 5.8 万词）原地弹窗秒出音标与释义；可 ✨ 让 AI 结合本句语境解释，⭐ 收藏进单词本（公开版词典可用、单词本不提供）
- **⭐ 歌词收藏夹**：点选歌词一键收藏，收藏面板按「歌词——《歌》」展示，
  点击条目直接跳到那首歌（公开版不提供）
- **AI 助手**：点一句歌词提问（批注作为上下文、历史持久化）；
  🎭 **乐评人 vs 粉丝双视角辩论**（两个人格接连流式发言）
- **📖 歌曲导读**：AI 通读全词生成 120–180 字导读，缓存于歌曲目录
- **🥚 彩蛋 · 互文追踪**：点句检索同歌手其他作品的相似歌词 Top-K，可让 AI 解释，
  可生成两句对照的**彩蛋对照卡** PNG；全曲 🥚 标记 + 本歌彩蛋总览（点击跳行）
- **📝 听歌笔记**：带播放位置时间戳的感想，点笔记跳回该位置
- **📻 AI 电台**：播完自动切下一首；配合 edge-tts 生成的**串场语音**，进歌前先 DJ 播报
- **🖼️ 分享卡片**：歌词金句卡（歌词 + AI 解读排版成图）

### 🗺️ 艺术家图谱
时代时间轴、主题河流图、修辞密度趋势、时代雷达对比（纯服务端 SVG）。

### 🥚 彩蛋地图
- **⭐ 单曲聚焦**（默认）：一首歌为中心的星形图，辐条带呼应数徽章，
  下方直接铺开每对歌词（本歌 vs 对方 + 相似度）
- **🕸️ 整体网络**：全曲库歌曲互文网络（节点=歌曲、连线粗细=呼应数、悬停看歌词）
- **🌐 跨歌手引用**模式：只看不同歌手之间的呼应（引用/致敬）
- **✨ AI 解读网络**：把最强歌曲对喂给 LLM，区分真呼应与字面撞车
- **🔍 意象追踪**：输入意象（雨 / scarf / 童年），原词命中 + 语义近邻按专辑时间线分组
- 默认多语言 embedding 模型（`paraphrase-multilingual-MiniLM-L12-v2`），
  中文呼应真实可用；CJK 行使用更严格阈值（`ECHO_*` 环境变量可调，见 `.env.example`）
- **🎬 MV 彩蛋**：选一首歌，AI 整理官方 MV 的导演、隐藏细节与歌词呼应
  （不了解的 MV 如实说明而非编造；结果按歌缓存，附 B 站/YouTube 搜索直达）

### 🕵️ 歌词宇宙
- **开始破案**：把一位歌手的彩蛋呼应网络当「证据链」（每条边最多 3 对呼应句），
  LLM 推理出人物、关系与故事时间线，输出人物关系图（SVG）+ 带引文的故事板；
  结果按「证据+模型」磁盘缓存，语料或模型变更自动失效
- **💌 隔空回信**：选一对呼应的歌，AI 以 A 歌叙事者口吻给 B 歌写信，
  呼应歌词金色高亮，信纸样式呈现

### 📊 曲库洞察
- **📅 每日一句**：每天确定性地推一句带 AI 解读的歌词
- **☁️ 高频意象词云**：按歌手统计（中文 jieba 分词 + 双语停用词），点词直接溯源到具体歌词
- **🎭 情绪地图**：以批注的逐行 valence/arousal 均值把歌曲散点在情绪平面上，点击即播放
  （歌名防碰撞布局：放不下的标签悬停圆点显示，重合点自动错开）
- **📖 歌单故事线**：勾选几首歌，AI 按情绪弧线排序并讲出歌单的故事

### 🎮 互动
- **🎯 歌词竞猜**：随机抽句猜出处（防剧透过滤、同歌手干扰项、战绩累计）
- **🧩 歌名拼图**：歌名被挖掉一块（英文挖单词、中文挖字），四选一拼回
  完整歌名（纯曲库零成本）
- **🥚 彩蛋猜猜乐**：抽一句有回声的歌词，猜它在同歌手哪首歌里被呼应，
  答完揭晓两句如何互文（彩蛋图现成边，零 LLM）
- **🎙️ 听歌识曲**：录音/上传片段，本地 Shazam 式声纹（STFT 峰值星座哈希）
  识别曲库歌曲与片段位置

### ➕ 添加歌曲
内置约 140 首中外热门曲库一键添加；手动添加仅歌名必填（歌词自动从 LRCLIB 补全）；
🗂️ 管理列表（删除歌曲 / 刷新曲库）。

### ⚙️ 设置
界面内填 API Key 即时生效；可切换 embedding 模型（中文曲库建议
`paraphrase-multilingual-MiniLM-L12-v2`）并一键重建语料库索引。

## Demo Songs

| Song | Album | 亮点 |
|------|-------|------|
| cardigan | folklore (2020) | 隐喻密集、cardigan 三部曲互文 |
| champagne problems | evermore (2020) | 叙事复杂度、阶级隐喻 |
| All Too Well (10 Min) | Red TV (2021) | 意象密度最高的 TS 曲目 |
| exile ft. Bon Iver | folklore (2020) | 双视角对话（ft. 歌手模糊匹配演示） |
| Anti-Hero | Midnights (2022) | 自我指涉与反讽 |
| Save Your Tears | After Hours (2020) | 跨歌手引用演示 |
| 北京昨夜下了雪 / 今晚月色真美 | — | 中文歌词、试听片段对齐、CJK 彩蛋阈值演示 |

## CLI Commands

```bash
lyric-agent serve [--port 7860]    # 启动播放器 UI
lyric-agent generate <song_dir>    # 为一首歌生成 AI 批注
lyric-agent generate-all           # 为全部歌曲生成批注
lyric-agent embed                  # 生成语料库 embeddings
lyric-agent users-add <名字> [--role admin|viewer]  # 建登录账号（建号后 serve 要求登录）
lyric-agent users-list             # 列账号；无账号 = 不要求登录
lyric-agent doctor                 # 曲库/语料库健康检查（重复收录、过期索引等）
lyric-agent search <query> [-s]    # 命令行歌词搜索（-s 语义模式）
lyric-agent review <song_dir>      # 交互式人工复核批注
lyric-agent build-evolution        # 聚合艺术家演化数据
```

> ⚠️ **模型迁移**：embedding 默认模型已切换为多语言版。`embeddings.npy`
> 带模型指纹（`embeddings.meta.json`），模型不匹配会明确报错——
> pull 新代码后跑一次 `lyric-agent embed` 即可。

## 登录与角色（可选）

默认无需登录。`lyric-agent users-add` 创建首个账号后，`serve` 自动要求登录
（密码 PBKDF2 加盐哈希存 `data/users.json`，已 gitignore）。
`admin` 见全部页签；`viewer` 隐藏「➕ 添加歌曲 / ⚙️ 设置」。

## Pipeline Scripts

```bash
python scripts/fetch_lrc.py        # LRCLIB 抓取带时间戳歌词
python scripts/build_corpus.py     # 构建互文语料库（曲库歌曲 + 内置曲库）
python scripts/generate_all.py     # 端到端跑完整管线
python scripts/import_playlist.py --list   # 列出 TME Hackathon 官方参考歌单
python scripts/import_playlist.py 9 12     # 按序号导入（歌词 + 60s 官方试听自动对齐）
```

## 测试

三层测试，见 `TESTING.html`（46+ 条功能验收单，标注自动/手动与验证方式）：

```bash
# 1. 单元测试（50 项：LRC 解析、彩蛋检索、图构建、韵脚、竞猜、声纹指纹、登录、MV 彩蛋等）
pytest

# 2. 端到端自测（50 项：对着运行中的服务器打真实 HTTP API）
lyric-agent serve            # 先在一个终端启动【新】服务器
python scripts/self_test.py  # 另一终端运行；UI_PORT 环境变量可改端口

# 3. UI 巡检（42 项：真实浏览器逐页签走查交互与守卫路径、抓 JS 报错与服务端异常）
python scripts/ui_probe.py           # 自起独立服务器；--port 7860 可附加现有服务器
python scripts/ui_agent.py           # 闭环模式：巡检 → claude 自动修复 → 复测
python scripts/ui_agent.py --dry-run # 只巡检出报告，不修复
```

注意：`self_test.py` 需对**新启动**的服务器运行（它的加歌测试会清理磁盘目录，
旧服务器内存中的曲库不会同步）。UI 巡检报告与失败截图在 `data/ui_probe/`；
在 Claude Code 会话内可直接用 `/ui-fixloop` 跑同样的闭环（修复质量更高）。

## 公开部署（Public Mode）

设置环境变量 `PUBLIC_MODE=1` 后启动，即切换为可公开访问的多用户模式：

- **API Key 按访客隔离**：每位访客在「⚙️ 设置」页填入自己的 Key，只存于其浏览器
  localStorage（`gr.BrowserState`），不上传、不落盘，访客之间互不可见
- **只读曲库**：隐藏添加/删除歌曲、音频上传、索引重建、串场语音生成等写入口
- **不落盘**：AI 问答历史与听歌笔记不写服务器磁盘
- **版权守卫**：`source: tme_hackathon_playlist` 的比赛素材自动从歌单排除

## 项目结构

```
src/lyric_agent/
├── ui.py                  # Gradio 界面（7 页签 + 全部前端 JS/CSS）
├── cli.py                 # 命令行入口
├── config.py              # 全部可调参数（env 可覆盖）与共享常量
├── llm.py / debate.py     # LLM 客户端 / 多人格对话（助手、乐评人、粉丝）
├── annotator/             # 批注生成引擎 + 数据模型 + 人工复核
├── intertextuality/       # 彩蛋检索：语料库、embeddings、相似检索、网络图
├── evolution/             # 艺术家演化图谱
├── insights.py            # 词云 / 情绪地图 / 每日一句 / 副歌检测
├── rhyme.py               # 中英文韵脚分组
├── quiz.py                # 歌词竞猜出题
├── fingerprint.py         # 听歌识曲（声纹指纹）
├── radio.py               # 电台串场语音（edge-tts）
├── doctor.py              # 曲库健康检查
├── share_card.py          # 金句卡 / 彩蛋对照卡渲染
└── search.py / lrc_parser.py / audio_provider.py
```

## Docker

```bash
docker compose up --build   # 见 docker-compose.yml / Dockerfile
```
