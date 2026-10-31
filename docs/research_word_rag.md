# 调研：查词弹卡「这个词在曲库里的所有出现」（word-lookup RAG）

日期：2026-10-31。问题：双击查词时，把该词在全曲库歌词中的所有出现列出来，
并（可选）喂给 AI 语境解释。符合 PRODUCT.md「单词带语境：任何词汇功能都
回链到它所在的歌词句」原则（PRODUCT.md:55）。

## 1. 现状

- **查词今天不搜曲库。** `/api/dict/{word}`（src/lyric_agent/api.py:1002）只调
  `dictionary.lookup()`（src/lyric_agent/dictionary.py:77），查离线 ECDICT 子集，
  返回 {word, phonetic, translation}；AI 语境解释 `/api/dict-ai` 只拿
  当前这一句 line 做 prompt（api.py:1029-1040）。
- **曲库语料已存在且形状合适。** `build_corpus()` 产出
  data/corpus/discography.jsonl（corpus.py:32），`load_corpus()` 展开为
  `CorpusLine(song, album, line_index, text, artist)`（corpus.py:13-19,118）。
  实测当前规模：**160 首歌 / 5257 行 / 3283 个唯一英文词形 / 30171 个
  词 token**（对 discography.jsonl 直接统计）。line_index 即歌内行号，
  前端跳行已有同口径（wordbook 条目带 label/line_index，dictionary.py:150）。
- **重建钩子现成。** 增删歌后 `_kick_corpus_rebuild()` 后台重建语料+
  embeddings（api.py:99-117）；手动 `/api/rebuild-index` 走 background_task
  （api.py:995）。词出现索引可挂同一钩子。
- **词形归并件现成。** dictionary 已加载 lemma.en.txt.gz 的
  inflected→lemma 映射 + 后缀启发（`_candidates()`，dictionary.py:58-74），
  这正是检索侧需要的 lemma 策略，零新依赖。
- **弹卡 UI。** frontend/src/components/DictPops.tsx：双击开卡，先 fetch
  `/api/dict/`，再 fetch AI 缓存（DictPops.tsx:56-67）；卡内已有释义区、
  AI 区、收藏按钮，出现列表可作第三区块（折叠式）。

## 2. 方案评估

### 2.1 线性扫描 + 词形匹配（最简）

每次查词时遍历 `load_corpus()` 的 5257 行做 token 匹配。规模下这就是
毫秒级（`trace_imagery` 已经在每次意象追踪时做同样的全库 substring 扫描，
search.py:279-285，无性能问题）。英文屈折：
- 朴素 lowercase 全等：run 查不到 running —— 不可接受。
- Porter/Snowball stemmer（nltk）：引入 nltk 依赖 + 数据下载，Windows 上
  又一个坑；且 stem 不可读（"runn"）。官方文档
  https://www.nltk.org/api/nltk.stem.porter.html 。
- spaCy/lemminflect：lemma 质量最好但 spaCy 模型 ~50MB+，为 3283 个词
  不值。lemminflect 官方 https://lemminflect.readthedocs.io/ 。
- **复用自家 lemma 表（推荐）**：对查询词和每个 corpus token 都走
  `_candidates()` 取 lemma，lemma 相等即命中。表已在内存
  （dictionary.py:46-52），覆盖 ECDICT lemma.en.txt 全量屈折。
  类似工具印证：qwerty-learner 等背词工具普遍只做 lowercase+词表匹配；
  有道取词靠自带 lemma 词典——与我们现有做法同构。

### 2.2 倒排索引（构建期）

重建语料时顺手建 `lemma -> [(song, line_index)]`，存
data/corpus/word_index.json。规模估算：30171 postings × ~40B ≈
**1-2 MB JSON，内存字典 < 5 MB**，构建 < 1 秒。查询 O(1)。
键选 **lemma-key**（查 run 命中 ran/running）；surface 词形保留在行文本里
自然可见，无需双索引。挂在 `_kick_corpus_rebuild()`（api.py:99）和
`_rebuild_index_bg`（api.py:173-185）即可。
结论：工程上干净，但在 5k 行规模下相对线性扫描**收益约等于零**，
还多一个要保持同步的落盘文件。曲库到数千首歌时再上。

### 2.3 复用 embedding 检索

embeddings.npy 是**行级语义向量**（embeddings.py:33-36），MiniLM 类模型
对"某个词是否出现"没有保证——"run" 的查询向量会召回 escape/chase 等
语义邻居而漏掉字面出现，precision/recall 都不对口。诚实结论：**不适合做
occurrence 检索**；可作可选的二次排序信号（命中行按与当前歌词句的相似度
排，"相似用法在前"），但 v1 不必。

### 2.4 LLM-RAG：出现列表喂给 AI 语境解释

把命中行拼进 `/api/dict-ai` 的 prompt（api.py:1029 起）。当前模板是严格
三行、限 120 字（api.py:1043-1050），塞多了会稀释语境义。建议：最多取
**5 行**（每行 ~15 词 ≈ 总增量 <200 token），排序：当前歌优先 → 有批注的
行优先（annotations.json 存在性可查）→ 其余按歌名稳定序。模板加第四行
"④曲库里：他还在《X》里唱过 …"为可选行，缓存 key 的 v3 前缀需升 v4
（api.py:1022，key 含模板版本）。此项独立于出现列表 UI，可后做。

### 2.5 CJK

corpus 里有中文歌（search.py 专门有 CJK 阈值，search.py:29-34）。中文"词"
需要 jieba 分词才能对齐双击取词，但 DictPops 的取词正则本身只匹配
`[A-Za-z]`（DictPops.tsx:26-27），**中文根本触发不了查词弹卡**。
结论：v1 明确 skip CJK，与现有取词口径一致；若将来做，用子串匹配
（`q in text`，同 trace_imagery）比 jieba 更符合"字面出现"语义。

## 3. 对比表

| 方案 | 准确性 | 新依赖 | 构建成本 | 查询成本 | 工作量 |
|---|---|---|---|---|---|
| 线性扫描+自家 lemma | 高（屈折全覆盖） | 无 | 无 | ~5k 行遍历，毫秒级 | ~0.5 天 |
| 倒排索引（lemma-key） | 同上 | 无 | 重建 +1s，+1 落盘文件 | O(1) | ~1 天 |
| embedding 复用 | 低（语义≠出现） | 无 | 已有 | 已有 | 不采用 |
| LLM-RAG 注入解释 | 取决于上两者 | 无 | 无 | +~200 prompt token | ~0.5 天（后做） |

## 4. 推荐

**v1 = 线性扫描 + 自家 lemma 归并，不建倒排、不动 embedding。**

- **数据结构**：无新落盘；进程内可 `functools.lru_cache` 一份
  `{lemma: [(song, line_index, text)]}`，以 discography.jsonl 的 mtime 为
  缓存失效键（重建后自动换新，无需挂构建钩子——这就把 2.2 的同步问题
  消掉了）。
- **构建钩子**：不需要；若将来改倒排，挂 `_kick_corpus_rebuild`（api.py:99）。
- **API**：`GET /api/dict/{word}/occurrences` →
  `{word, lemma, total, items: [{song, line_index, line}]}`，`limit` 默认 20，
  当前歌置顶（传 `song` 查询参数）。不改动现有 `/api/dict/{word}` 响应，
  前端并行第三个 fetch，404/空结果不影响弹卡主体。
- **UI**：DictPops 卡内 AI 区下方加折叠区"曲库里还有 N 处"，每行
  歌名+歌词行，点击行走既有 `pickLine` 跳行（DictPops.tsx:38）；仅当前歌
  的命中可直接跳，他歌命中点击切歌后跳（或 v1 只展示不跳他歌）。
  文案遵守 CLAUDE.md：不用 emoji，自解释优先。
- **lemma 策略**：查询词与 corpus token 都经 `dictionary._candidates()`
  取首个 lemma 命中即匹配；CJK 行直接跳过（`is_cjk_text`，search.py:41）。
- **工作量**：后端 ~0.5 天（含测试：隔离 data 树）、前端 ~0.5 天；
  LLM-RAG 注入（2.4）另 ~0.5 天作为二期。
