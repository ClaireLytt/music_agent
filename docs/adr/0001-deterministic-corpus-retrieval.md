# 查词例句检索必须确定性，缓存 key 含 ctx_digest

查词的曲库例句（occurrences 与 /api/dict-ai 第④行注入）共用同一 lemma 词法检索，
排序为固定三级（当前歌 → 有批注 → (song, line_index) 字典序），刻意不用现成的
embeddings.npy 做相似度 rerank：行级语义向量对"某词是否出现"无保证
（docs/research_word_rag.md §2.3），且非确定性排序会让同一 (word, line) 的
ctx_digest 抖动，击穿 ai_cache 的缓存命中。dict-ai 缓存 key 自 v4 起带
ctx_digest（检索结果规范化 md5 前 8 位），曲库增删后解释自动跟随语料失效，
不会引用已删的歌。想给检索加排序信号的人：先保证信号确定且进 digest。
