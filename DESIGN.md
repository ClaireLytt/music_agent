# DESIGN.md — 歌词透镜 新前端视觉系统

状态：已定（2026-10-25 决策轮：用户选定「品类标准·暗色沉浸播放页」常驻出口，
加 MV 视频位）。北极星原型：`prototypes/canon_mv_player.html`。
适用范围：React 新前端（当前仅播放解读页）；旧 Gradio UI 不适用、不回迁。

## 世界

品类标准暗色沉浸播放器（Spotify/网易云 的骨架语言），以最高工艺执行；
不撞竞品商标色。学习动线（讲解→生词→收藏→练）在右侧解读坞常驻，
是本产品区别于纯播放器的那一列。

## Tokens（与原型一致）

```css
--bg:#121212; --bg2:#181818; --panel:#1e1e22; --panel2:#24242a;
--ink:#f5f5f4; --ink2:#a8a8b3; --ink3:#6e6e78;
--accent:#7c9eff; --accent-soft:rgba(124,158,255,.16);
--bleed1/--bleed2: 随当前专辑色渗出的径向背景（默认 #2e4639/#1a2420）;
--radius:12px;
```

- 一色一职：`--accent` 只给「当前/正在学」（当前歌、当前句卡拉OK、主按钮、A-B 状态）。
- 侧栏/播放条底 `#0c0c0e`，比主底更深一级；面板边框 `#2a2a31`，分隔线 `#232329`。

## 字体

Inter + "Noto Sans SC"，system-ui 兜底。层级：
- 当前歌词句 26px/700；普通歌词行 19px/500（颜色层级 ink→ink2→ink3 做远近）
- 卡片标题(k) 12px/600；区块标题 12px/600 + letter-spacing .1em + ink3
- 正文/生成内容 13.5px，行高 1.8；时间码 11px tabular-nums

## 间距与组件

- 页面网格：`232px 侧栏 | 1fr 主区 | 320px 解读坞`，底部 88px 播放条
- 卡片：`--panel` 底 + 1px `#2a2a31` 边 + 12px 圆角 + 16px 内距；卡片间 14px
- 按钮：胶囊 chip（999px 圆角，1px 边框；主按钮 accent 实底配深色字）
- 阴影必须带偏移+柔和模糊（MV：`0 18px 40px -18px rgba(0,0,0,.65)`）；禁纯光晕
- 图标一律 SVG 线性（stroke 2），禁 emoji 充当图标；𝄆𝄇 作为音乐记号例外

## 布局与行为（播放解读页）

- 主区：MV 视频位（16:9，可收起，角标注明“视频不驱动歌词”）在上，
  同步歌词在下（居中、上下渐隐 mask、当前句 scrollIntoView 居中）
- 卡拉OK：当前句按行时间戳做文字渐变填充（background-clip:text）
- 解读坞：AI 讲解卡（**生成文字居中**，全局审美偏好）→ 生词卡 → 问 AI → 快捷操作
- 播放条：曲目信息 | 居中控制(上一首/播放/下一首/A-B/跳副歌)+进度 | 循环状态/韵脚/音量

## 技术栈约定

React 18 + TS + Vite；Tailwind（tokens 进 tailwind.config）+ 按需 shadcn/ui；
TanStack Query（服务端状态/任务轮询）；zustand（播放器全局 store）；
HTML5 Audio 驱动歌词同步；Recharts 留给 /words 统计页。
