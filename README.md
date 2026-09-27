# Lyric Lens — AI 歌词批注播放器

> 让每位听众都能成为歌词研究者。

播放歌曲时歌词逐句同步高亮，点击任意一句即可展开 AI 生成的深度解读：隐喻分析、典故引用、双关解读、情感基调、跨歌曲意象互文追踪。

## Quick Start

```bash
# 1. Clone & install
git clone https://github.com/ClaireLytt/lyric_agent.git
cd lyric_agent
pip install -e ".[all]"

# 2. Configure
cp .env.example .env
# Edit .env: fill in API_KEY, choose LLM_PROVIDER

# 3. Fetch lyrics & generate annotations
python scripts/fetch_lrc.py          # download LRC files from LRCLIB
# Add audio.mp3 files to data/songs/*/
lyric-agent generate-all             # generate AI annotations

# 4. Launch
lyric-agent serve
# Open http://localhost:7860
```

## Features

- **Synced Lyrics**: LRC-based real-time lyric highlighting synced to audio playback
  - Active line highlighted with accent glow and scale
  - Played/unplayed lines visually distinguished
  - Auto-scroll follows playback (pauses on user scroll for 5s)
- **AI Annotations**: Click any line to expand multi-dimensional analysis:
  - 📖 Metaphor analysis / 📚 Allusions & references / 🔤 Wordplay
  - 💫 Emotional tone / 🌍 Cultural context / 🎤 Taylor Swift biographical context
  - 🎵 Related lines from other songs (intertextuality)
  - Accordion-style: opening one closes others
  - Blue annotation indicator dots on annotated lines
- **彩蛋 · Intertextuality**: cross-song echo tracking within one artist's discography
  - 🥚 互文追踪：点击歌词行，检索同歌手其他作品中最相似的歌词 Top-K，可让 AI 解释呼应
  - 🥚 全曲标记：切歌后自动扫描整首歌，有强呼应的行尾显示 🥚（悬停给出目标歌曲与相似度）
  - 🗺️ 本歌彩蛋总览：一次列出全部呼应行与目标，点击跳转到对应歌词
  - 🥚 彩蛋地图页签：歌手级互文网络图（节点=歌曲、连线=呼应，纯服务端 SVG）
  - 中文歌词使用更严格的 CJK 阈值 + 共享短语锚定，避免英文向 embedding 模型的假呼应；
    阈值均可通过环境变量调整（见 `.env.example` 的 ECHO_* 配置）
- **Interactive Review**: Rich-based CLI tool for human annotation quality review
- **Docker Ready**: One-command deployment with docker-compose

## Demo Songs

| Song | Album | Era | Why |
|------|-------|-----|-----|
| cardigan | folklore (2020) | folklore | Extended metaphor, cardigan trilogy |
| champagne problems | evermore (2020) | evermore | Narrative complexity, class metaphors |
| All Too Well (10 Min) | Red TV (2021) | Red | Most analyzed TS song, dense imagery |
| exile ft. Bon Iver | folklore (2020) | folklore | Dual perspective, communication breakdown |
| Anti-Hero | Midnights (2022) | Midnights | Self-referential, ironic tone |

## CLI Commands

```bash
lyric-agent generate <song_dir>    # Generate annotations for one song
lyric-agent generate-all           # Generate annotations for all songs
lyric-agent serve [--port 7860]    # Launch the player UI
lyric-agent review <song_dir>      # Interactively review annotations for one song
lyric-agent review-all             # Review annotations for all songs
lyric-agent embed                  # Generate sentence embeddings for corpus
```

## Pipeline Scripts

```bash
python scripts/fetch_lrc.py        # Fetch LRC files from LRCLIB API
python scripts/build_corpus.py     # Build lyrics corpus for intertextuality
python scripts/generate_all.py     # Run full pipeline end-to-end
python scripts/import_playlist.py --list   # List TME Hackathon reference playlist
python scripts/import_playlist.py 9 12     # Import songs (timestamped lyrics +
                                           # official 60s preview clip, auto-aligned)
```

## 公开部署（Public Mode）

设置环境变量 `PUBLIC_MODE=1` 后启动，即切换为可公开访问的多用户模式：

- **API Key 按访客隔离**：每位访客在「⚙️ 设置」页填入自己的 Key，只存于其浏览器
  localStorage（`gr.BrowserState`），不上传、不落盘，访客之间互不可见；
  服务器 `.env` 中的 Key 不会被访客使用
- **只读曲库**：隐藏「添加歌曲」页签与音频上传入口，访客不能改动服务器文件
- **问答不落盘**：AI 问答历史不写入服务器磁盘，访客之间互不可见
- **版权守卫**：`source: tme_hackathon_playlist` 的歌曲自动从歌单中排除
  （比赛素材仅限赛内演示，不得公开上线）

```bash
# Docker 部署（推荐腾讯云轻量应用服务器，IP:端口 访问无需 ICP 备案）
# 在 .env 中加一行 PUBLIC_MODE=1，然后：
docker compose up -d
# 或魔搭创空间（ModelScope，免费、国内可访问）：上传仓库，
# 空间环境变量里设 PUBLIC_MODE=1，SDK 选 Gradio
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Web UI | Gradio 4.0+ with custom HTML/JS |
| LLM | Anthropic Claude / OpenAI-compatible (DeepSeek, etc.) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Audio Sync | HTML5 Audio + requestAnimationFrame JS |

## Project Structure

```
lyric_agent/
├── src/lyric_agent/
│   ├── config.py           # Settings from .env
│   ├── llm.py              # Dual-provider LLM client
│   ├── lrc_parser.py       # LRC file parser
│   ├── cli.py              # CLI entry point
│   ├── ui.py               # Gradio player UI
│   ├── annotator/          # Annotation engine
│   │   ├── models.py       # Data models
│   │   ├── engine.py       # Batch LLM annotation
│   │   ├── prompts.py      # System prompts
│   │   └── reviewer.py     # Human review tool
│   └── intertextuality/    # Cross-song search
│       ├── corpus.py       # Lyrics corpus loader
│       ├── embeddings.py   # Sentence embeddings
│       └── search.py       # Similarity search
├── data/
│   ├── songs/*/            # Per-song: audio.mp3, lyrics.lrc, metadata.json, annotations.json
│   └── corpus/             # discography.jsonl, embeddings.npy
├── scripts/                # Pipeline scripts
└── tests/                  # Unit tests
```

## License

MIT
