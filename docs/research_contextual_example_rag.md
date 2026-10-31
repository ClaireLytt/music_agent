# 调研：语境化例句 RAG（曲库真实例句注入查词 AI 解释）

日期：2026-10-31。前置调研 docs/research_word_rag.md 已定下检索层方案
（线性扫描 + 自家 lemma 归并，`dictionary._candidates()`，其 2.4 节给了
LLM 注入草案）。本篇只做两件事：把 2.4 节细化成可实施规格；回答答辩问题
「RAG 怎么帮助学英语」——给严格定义边界、学习科学依据、先例产品对比
和评价口径。检索层本身（扫描 vs 倒排、CJK、occurrences API）不再重复，
见前置调研 §2.1/2.2/2.5、§4。

## 1. 现状（本篇视角）

- `/api/dict-ai`（src/lyric_agent/api.py:1029-1069）：prompt 只含
  {word, line, song} 三个输入，严格三行模板、限 120 字；缓存 key =
  `md5("v3:" + word + "\x00" + line)`（api.py:1020-1023），落盘
  data/dict/ai_cache.json，命中零 LLM 调用。
- 对照组已存在：review.py:157-214 的 `word_examples()`——复习卡例句来源
  是有道 jsonapi / dictionaryapi.dev 的**通用词典例句**，第三优先级才退到
  曲库（`_examples_from_corpus`，正则 `\b word \b` 全等匹配、无 lemma
  归并、每首歌最多一句）。即：曲库例句已被当「兜底」，而非「首选语境」。
- PRODUCT.md:55 原则一「单词带语境：任何词汇功能都回链到它所在的歌词句，
  绝不脱离歌曲孤立展示」——本方案是该原则在 AI 解释上的落地：解释一个词
  时，证据来自用户真正听过的歌，而不是教科书例句。
- 语料规模（前置调研实测）：160 首 / 5257 行 / 3283 唯一词形 /
  30171 token。

## 2. 这算不算 RAG（答辩定性）

### 2.1 原论文的定义边界

Lewis et al. 2020《Retrieval-Augmented Generation for Knowledge-Intensive
NLP Tasks》（NeurIPS 2020，https://arxiv.org/abs/2005.11401 ）给出的 RAG
组成是两件：**parametric memory**（预训练 seq2seq 生成器，论文里是 BART）
+ **non-parametric memory**（外部语料索引 + retriever，论文里是 DPR 检索
Wikipedia 稠密向量）。即 RAG = retriever 选出与查询相关的文档片段，
generator 以「查询 + 检索结果」为条件生成。论文用的是稠密检索，但稠密
只是该论文的实现选择，不是定义的一部分。

### 2.2 检索方式不限于稠密向量

RAG survey（Gao et al. 2023，https://arxiv.org/abs/2312.10997 ）的
Naive RAG 范式明确为「索引 → 检索 → 生成」（Retrieve-Read），其
Retrieval 一章将 **sparse retriever（BM25 等词法检索）与 dense retriever
并列为检索器的两大类**。我们的「lemma 归并 + 全库扫描」是词法检索的
最简形态（等价于 lemma 字段上的布尔检索），完全落在 sparse retrieval
的定义内；注入 prompt 即 Retrieve-Read 中的 Read。

### 2.3 结论与一句话定性

**是 RAG，且是教科书形态的 Naive RAG**：外部非参数知识源（用户曲库
语料）+ 检索器（lemma 词法检索）+ 生成器（LLM 按模板生成解释），生成
严格以检索结果为条件。不是 RAG 的部分也要诚实：没有稠密向量、没有
rerank、没有迭代检索——那些是 Advanced/Modular RAG 的增强件，不是
RAG 的门槛。

答辩一句话：「RAG 的定义是检索器加生成器，检索器不限于向量检索——
我们用用户自己的曲库做知识源，lemma 级词法检索命中真实歌词行，注入
LLM 的释义 prompt，是标准的 Retrieve-Read 结构（Lewis et al. 2020；
Gao et al. 2023 survey 将 sparse retrieval 列为 RAG 检索器的一类）。」

## 3. 「语境化例句帮助词汇习得」的学习科学依据

答辩问题「RAG 怎么帮助学英语」的实质是：为什么把**真实语料中该词的
出现行**给学习者（并给 LLM 当解释素材）比裸词典释义好。依据三层：

1. **伴随性词汇习得（incidental vocabulary acquisition）**：
   Nagy, Herman & Anderson 1985《Learning Words from Context》
   （Reading Research Quarterly 20(2), 233-253，DOI:
   https://doi.org/10.2307/747758 ）：中学生在自然阅读中从上下文获得
   小而统计可靠的词义增益，且由于接触量巨大，语境习得解释了词汇增长的
   主要部分。后续 Nagy, Anderson & Herman 1987（AERJ 24(2)，DOI:
   https://doi.org/10.3102/00028312024002237 ）在正常阅读条件下复证。
   对应到本项目：用户反复听歌 = 高频自然接触；查词时把该词在曲库里的
   其他出现摆出来，是把「将来还会再遇到它」的语境提前聚合。
2. **数据驱动学习（DDL）与 concordancer**：Tim Johns 1991《Should you
   be persuaded: Two samples of data-driven learning materials》
   （Johns & King (eds.), Classroom Concordancing, ELR Journal 4, 1-16，
   University of Birmingham；全文
   https://lexically.net/wordsmith/corpus_linguistics_links/Tim%20Johns%20and%20DDL.pdf ）
   首创 DDL 一词：学习者作为「研究者」直接面对语料证据（concordance
   行），自己归纳词的用法，concordancer 是该方法的核心工具。我们的
   「曲库里还有 N 处」折叠区就是一个个人化 concordancer。
3. **DDL 有效性的元分析**：Boulton & Cobb 2017《Corpus Use in Language
   Learning: A Meta-Analysis》（Language Learning 67(2), 348-393，DOI:
   https://doi.org/10.1111/lang.12224 ）：64 项研究 / 88 个样本，DDL
   对语言学习总体效应量大（组间 d = 0.95，前后测 d = 1.50）——
   「让学习者看真实语料例句」不是直觉，是有大效应量元分析背书的方法。

RAG 在其中的角色：传统 DDL 的痛点是 concordance 行对学习者太生（Johns
的方法需要教师引导归纳）；LLM 把「归纳」这步代劳了——检索给证据，
生成给解读，证据来自用户自己的歌所以可核查、可回跳播放。这就是
「RAG 帮助学英语」的完整链条：**检索保证例句真实且属于学习者自己的
输入史，生成保证例句被消化成可懂的解释**。

## 4. 先例产品与差异点

| 产品 | 例句来源 | 呈现方式 | 官方页 |
|---|---|---|---|
| SkELL | 千万句级通用网络语料，GDEX 算法按「好例句」打分排序 | 查词给 40 句最佳例句 + word sketch 搭配 | https://skell.sketchengine.eu/ ；方法论文 Baisa & Suchomel 2014，https://www.sketchengine.eu/wp-content/uploads/SkELL_2014.pdf |
| COCA | 10 亿词美国当代英语语料 | KWIC concordance 行 + 频率/体裁分布 | https://www.english-corpora.org/coca/ |
| Linggle | 网络 n-gram | 搭配模式查询（`v. ~ing` 式通配） | https://linggle.com/ |
| 有道/dictionaryapi.dev（本项目现状对照组） | 词典编纂例句 | 双语例句列表（review.py:157-193） | https://dict.youdao.com/ |

共同点：都信奉「真实语料例句 > 编造例句」，SkELL 甚至为此发明 GDEX
专门挑句。**我们的差异点**：语料不是匿名网络文本，而是**用户自己听过、
喜欢的歌**——(a) 例句自带情感联结与旋律记忆锚点；(b) 每句可回跳到歌内
原行继续播放（line_index 口径现成，前置调研 §1）；(c) 语料小（5k 行）
反而是特性：每一句用户都真见过，复现即复习。SkELL 们解决「例句够不够
好」，我们解决「例句是不是你的」。

## 5. prompt 注入规格（细化前置调研 §2.4）

### 5.1 模板：三行 → 四行

第④行为**条件行**：检索命中 ≥1 句他处出现才加，否则保持三行原样
（空列表时不许 LLM 编造「曲库里」内容）。system prompt 增补：

```
④曲库：<从「曲库例句」中挑 1-2 句，指出该词在那里的用法是否相同；
格式：在《歌名》里 "<原句>" 也是/却是 <义>>
仅当用户消息含「曲库例句」时输出第④行，且只许引用给出的句子，
不得自造歌词。
```

user_message 追加段（无命中则整段省略）：

```
曲库例句（该词在用户听过的其他歌里的出现）：
1. <line> ——《<song>》
2. ...
```

字数上限相应放宽到 160 字（原 120 字按三行标定，第四行约 +40 字）。

### 5.2 检索行数与 token 预算

- **上限 5 行**（去重后）：歌词行均长 ~15 词（30171 token / 5257 行
  ≈ 5.7 词/行，英文混中文歌名后保守按 15 词计），5 行 ≈ 75-100 词
  ≈ **120-200 prompt token**；加 system prompt 增补 ~80 token，单次
  查询增量 < 300 token——相对现有 prompt（~350 token）约 +60%，
  绝对成本可忽略（缓存命中仍零调用）。
- 行内截断：单行 > 120 字符时以命中词为中心截窗（歌词行一般不会，
  防御外语长行）。

### 5.3 排序信号（确定性，保证缓存 key 稳定）

1. 当前歌的其他行（`song` 参数已在 `/api/dict-ai` body 里）——
   「这首歌里他还唱过」最贴语境；
2. 有批注的行优先（data/songs/<slug>/annotations.json 覆盖该
   line_index 即算）——有批注说明该句本身被认为值得讲；
3. 其余按 (song, line_index) 字典序稳定排。
同一首歌最多取 2 行，避免 5 个名额被一首歌占满。
不用 embedding 相似度 rerank（前置调研 §2.3 已论证不对口，且会引入
非确定性，破坏缓存）。

### 5.4 缓存 key v3 → v4 的影响面

- key 改为 `md5("v4:" + word + "\x00" + line + "\x00" + ctx_digest)`，
  `ctx_digest` = 注入例句列表（规范化拼接）的 md5 前 8 位；无命中时
  为空串。这样曲库增删歌后同一 (word, line) 的检索结果变化会自然
  产生新 key，解释跟着语料走，不会引用已删的歌。
- **影响面**：现有 v3 缓存条目全部失效（key 不同，旧条目成为死数据但
  无害，可留存文件里不清理）；上线后首轮查询全部回源 LLM——按
  ai_cache.json 现有条目数预估一次性成本，demo 前用 demo-prep 的
  预热流程把高频词焐热。GET `/api/dict-ai` 的查询路径同步换 v4 key，
  前端零改动（接口形状不变）。
- 回滚安全：v3 条目仍在文件中，代码退回 v3 key 即恢复。

### 5.5 实施边界

- 检索函数复用前置调研 §4 定下的
  `{lemma: [(song, line_index, text)]}` lru_cache（以 discography.jsonl
  mtime 失效），`/api/dict-ai` 与 `/api/dict/{word}/occurrences` 共用
  同一份，不另造轮子。
- `/api/dict-ai` 是同步 handler 且本就同步调 LLM——本次不改这个结构
  （弹卡场景单次生成 ~2s 可接受，且 GET 缓存路径兜底），但若将来模板
  变长导致超时，按 CLAUDE.md 铁律迁入 background_task。
- review.py 的 `word_examples()` 不动：它是复习卡场景、零 LLM，与
  本方案（查词卡、LLM 解释）正交；仅在文档里记一笔「曲库例句逻辑
  将来可收敛到共用检索函数」。

## 6. 评价口径（demo/答辩怎么证明有效）

1. **A/B 展示（定性，最有说服力）**：同一个词并排两张卡——左：有道
   通用例句（review.py 对照组现成）；右：曲库例句 + 第④行解释。
   讲解点：右边每句观众刚在 demo 里听过，点击即回跳播放。
2. **检索命中率（定量）**：注意口径——查词入口是双击歌词，被查词
   **必然**出现在当前行，所以「≥1 次出现」命中率恒为 100%，无信息量。
   有效指标是**跨歌命中率**：被查词在 ≥2 首歌出现的比例（对 3283
   唯一词形离线跑一遍 lemma 检索即得，一次性脚本放 tmp/）。预期高频
   功能词近 100%、实义词是关键区间；答辩给这个数 +「命中失败时静默
   退回三行模板，无害降级」。
3. **成本口径**：单次查询 prompt 增量 < 300 token（§5.2），缓存命中
   零调用——「RAG 没有把查词变贵」。
4. **学理口径**：§3 的三条文献（尤其 Boulton & Cobb 2017 的
   d = 0.95）——「真实语料例句有效」不靠我们自证。

## 7. 对比表与推荐

| 方案 | 例句真实性 | 个人相关性 | 新依赖 | 工作量 |
|---|---|---|---|---|
| 现状：不注入（只有 word+line） | — | 仅当前句 | — | — |
| 通用词典例句注入（有道/dictionaryapi） | 编纂例句 | 无 | 已有 | ~0.2 天 |
| **曲库例句注入（本方案）** | 真实歌词行 | 用户自己的歌，可回跳 | 无 | ~0.5 天（检索函数已含在前置 v1 的 0.5 天里） |
| 曲库例句 + embedding rerank | 同上 | 同上 | 无（已有向量） | 不采用：非确定性破坏缓存，前置 §2.3 已否 |

**推荐**：按 §5 规格实施，作为前置调研 v1（occurrences API + 弹卡
折叠区）之后的二期，两者共用同一检索函数。先做 occurrences UI 再做
注入——UI 先让用户看见证据，注入让 LLM 消化证据，顺序即叙事。

## 8. 答辩一段话（30 秒）

「RAG 是检索器加生成器：检索器从外部知识源找证据，生成器以证据为条件
作答（Lewis et al. 2020）。在我们这里，知识源不是 Wikipedia，而是用户
自己听过的曲库；查一个词时，lemma 级检索找出它在你听过的歌里的真实
出现行，一部分直接展示——这就是语言教学里有大效应量元分析支持的
数据驱动学习（Boulton & Cobb 2017, d≈0.95）——另一部分注入 LLM 的
释义 prompt，让 AI 用你唱过的句子给你讲这个词。词典给的是别人的例句，
我们给的是你自己听过、能一键回跳播放的例句：RAG 在这里不是减少幻觉的
工程技巧，而是把『从真实语境学词』这件教育学上被验证过的事自动化了。」
