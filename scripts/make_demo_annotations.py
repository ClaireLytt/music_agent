#!/usr/bin/env python3
"""Generate curated demo annotations (no LLM required).

Produces annotations.json for each demo song with:
- Hand-curated annotations for the most analyzed lines (with cross-song links)
- A lexicon-based per-line emotion arc (valence / arousal / category)

Run:  python scripts/make_demo_annotations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lyric_agent.annotator.models import Annotation, RelatedLine, Song, SongMetadata  # noqa: E402
from lyric_agent.lrc_parser import load_lrc_file  # noqa: E402

SONGS_DIR = ROOT / "data" / "songs"

# ── Emotion lexicon (keyword → valence delta, arousal delta, category) ──

_LEXICON: list[tuple[tuple[str, ...], float, float, str]] = [
    (("love", "lover", "favorite", "kiss", "adore"), 0.30, 0.15, "love"),
    (("young", "dancing", "alive", "shine", "golden", "smile"), 0.25, 0.20, "joy"),
    (("hope", "peace", "healed", "marvelous", "best"), 0.25, 0.05, "hope"),
    (("remember", "memory", "old", "vintage", "autumn", "photograph"), -0.05, -0.10, "nostalgia"),
    (("lost", "losing", "goodbye", "leave", "leaving", "left", "gone"), -0.25, 0.05, "loss"),
    (("cry", "crying", "tears", "weep", "broke", "broken", "shattered"), -0.30, 0.20, "sadness"),
    (("alone", "lonely", "exile", "empty", "cold", "december"), -0.30, -0.05, "loneliness"),
    (("hate", "curse", "fight", "screaming", "rage", "fury"), -0.30, 0.35, "anger"),
    (("death", "die", "dead", "ghost", "grave", "kill"), -0.35, 0.15, "despair"),
    (("problem", "exhausting", "monster", "nightmare", "depression"), -0.25, 0.15, "self-doubt"),
    (("secret", "midnight", "haze", "shadow"), -0.10, 0.05, "mystery"),
    (("home", "warm", "cardigan", "bed", "porch"), 0.10, -0.15, "tenderness"),
    (("dream", "wish", "stars", "sky"), 0.15, 0.00, "longing"),
    (("never", "can't", "wouldn't", "shouldn't"), -0.10, 0.05, "regret"),
]


def estimate_emotion(text: str) -> tuple[float, float, str]:
    t = text.lower()
    valence, arousal = 0.5, 0.4
    category = "neutral"
    best_hit = 0
    for keywords, dv, da, cat in _LEXICON:
        hits = sum(1 for k in keywords if k in t)
        if hits:
            valence += dv * min(hits, 2) * 0.6
            arousal += da * min(hits, 2) * 0.6
            if hits > best_hit:
                best_hit = hits
                category = cat
    return max(0.0, min(1.0, valence)), max(0.0, min(1.0, arousal)), category


# ── Hand-curated annotations ─────────────────────────────
# Keyed by song dir; each entry matched to the FIRST lyric line containing `match`.

CURATED: dict[str, list[dict]] = {
    "cardigan": [
        {
            "match": "vintage tee, brand new phone",
            "summary": "开篇用两个物件并置——复古T恤与崭新手机——瞬间定格「青春期的时间错位感」：既怀旧又崭新。",
            "metaphor_analysis": "vintage（旧）与 brand new（新）的对撞是整首歌「记忆 vs 当下」主题的微缩模型。",
            "wordplay": None,
            "cultural_context": "High heels on cobblestones 暗示纽约西村的鹅卵石街道，为 folklore 的都市怀旧定调。",
            "taylor_swift_context": "folklore 开创了 Taylor 的虚构叙事时期，cardigan 是 Betty-James-Augustine 三角故事中 Betty 的视角。",
            "emotion": (0.55, 0.35, "nostalgia"),
        },
        {
            "match": "when you are young, they assume you know nothing",
            "summary": "副歌前的核心命题：成人世界对年轻人的傲慢假设。整首歌是对这句话的反驳——「但我知道」(But I knew you)。",
            "metaphor_analysis": None,
            "allusions": ["呼应彼得潘式的「永恒少年」主题（后文 Peter losing Wendy）"],
            "taylor_swift_context": "Taylor 在 folklore 纪录片中说，这句是整个三部曲的情感锚点：年轻人的感情被低估，但他们记得所有细节。",
            "emotion": (0.4, 0.45, "regret"),
        },
        {
            "match": "felt like i was an old cardigan",
            "summary": "全曲核心意象：被遗忘在床下的旧开衫——不再被穿上、被选择的自我价值感的隐喻。",
            "metaphor_analysis": "本体：被忽视的自我；喻体：床下的旧开衫。「床下」意味着不可见、被搁置——不是被丢弃，而是被遗忘，这比丢弃更刺痛。",
            "wordplay": "「put me on」双关：字面是「穿上我」，引申是「重视我/给我位置」。",
            "cultural_context": "开衫 (cardigan) 是温暖、居家、被包裹的象征物，Taylor 发行时同步售卖同款开衫周边，将隐喻实体化。",
            "taylor_swift_context": "Betty 视角：回忆 James 曾让她感到被珍视。与 betty、august 构成 folklore 三部曲。",
            "related_lines": [
                {"song": "All Too Well (10 Minute Version)", "album": "Red (Taylor's Version)", "line": "But you keep my old scarf from that very first week", "similarity": 0.78},
                {"song": "champagne problems", "album": "evermore", "line": "Your mom's ring in your pocket", "similarity": 0.62},
            ],
            "emotion": (0.45, 0.3, "tenderness"),
        },
        {
            "match": "you put me on and said i was your favorite",
            "summary": "隐喻的温柔顶点：被「穿上」即被选择、被贴近身体——亲密与依赖的具象化。",
            "metaphor_analysis": "延续衣物隐喻体系：从「床下」到「穿上」，是从被遗忘到被珍视的情感位移。",
            "wordplay": "favorite 既指「最喜欢的衣物」也指「最爱的人」。",
            "emotion": (0.75, 0.45, "love"),
        },
        {
            "match": "peter losing wendy",
            "summary": "用彼得潘与温蒂的分离，隐喻「拒绝长大的人终将失去愿意等待的人」。",
            "allusions": ["J.M. Barrie《彼得·潘》：Peter 永远年轻，Wendy 选择长大离开梦幻岛"],
            "metaphor_analysis": "James 是 Peter（逃避、漂泊），Betty 是 Wendy（清醒、等待后离开）。",
            "taylor_swift_context": "Taylor 后来在 TTPD 中写了一首《Peter》，正面回应这个意象——跨越 4 年的自我互文。",
            "related_lines": [
                {"song": "exile", "album": "folklore", "line": "I think I've seen this film before, and I didn't like the ending", "similarity": 0.58},
            ],
            "emotion": (0.3, 0.4, "loss"),
        },
        {
            "match": "i knew you'd come back to me",
            "summary": "结尾的确信宣言：整首歌从「被遗忘」走向「被证明」——Betty 早就知道 James 会回来。",
            "metaphor_analysis": None,
            "taylor_swift_context": "与 betty 中 James 道歉的场景呼应，三部曲叙事在此闭环。",
            "emotion": (0.65, 0.5, "hope"),
        },
    ],
    "all_too_well_10min": [
        {
            "match": "left my scarf there at your sister's house",
            "summary": "整首歌最著名的物件：留在对方姐姐家的围巾——被留下的不只是围巾，是一部分自我。",
            "metaphor_analysis": "围巾=纯真与亲密的信物。它被「留下」又被「保留」，成为一段关系的物证。",
            "cultural_context": "十年来粉丝反复追问「围巾在哪」，使它成为流行文化中最著名的失物之一。",
            "taylor_swift_context": "普遍认为写给 Jake Gyllenhaal，Maggie Gyllenhaal 曾在访谈中被问及围巾下落。",
            "related_lines": [
                {"song": "cardigan", "album": "folklore", "line": "And when I felt like I was an old cardigan under someone's bed", "similarity": 0.78},
            ],
            "emotion": (0.4, 0.35, "nostalgia"),
        },
        {
            "match": "autumn leaves falling down like pieces into place",
            "summary": "秋叶落定如拼图归位——用季节意象把「回忆的必然性」写成风景。",
            "metaphor_analysis": "本体：记忆的碎片；喻体：落叶。falling into place 双重含义：物理落下 + 真相拼合。",
            "wordplay": "pieces into place 既是叶子落地，也是回忆拼图完成。",
            "emotion": (0.45, 0.3, "nostalgia"),
        },
        {
            "match": "i was there, i remember it",
            "summary": "全曲的证词式宣言：「我在场，我记得」——用记忆对抗被抹除的叙事权。",
            "metaphor_analysis": None,
            "taylor_swift_context": "10 分钟版本是 Taylor's Version 重录计划的核心宣言：夺回自己故事的所有权。",
            "emotion": (0.35, 0.55, "nostalgia"),
        },
        {
            "match": "crumpled up piece of paper",
            "summary": "「你把我像一张揉皱的纸扔掉」——被弃感最物化、最锋利的表达。",
            "metaphor_analysis": "本体：被轻易结束的感情；喻体：揉皱的纸。纸曾承载文字（承诺），揉皱即背弃。",
            "emotion": (0.15, 0.6, "sadness"),
        },
        {
            "match": "keep my old scarf from that very first week",
            "summary": "结尾回到围巾：对方留着它，「因为它闻起来像我，因为你无法摆脱回忆」——记忆是双向的囚笼。",
            "metaphor_analysis": "围巾从「我的失物」变成「你的收藏」，权力关系翻转：遗忘失败的是你。",
            "related_lines": [
                {"song": "cardigan", "album": "folklore", "line": "You put me on and said I was your favorite", "similarity": 0.66},
            ],
            "emotion": (0.3, 0.5, "loss"),
        },
    ],
    "exile": [
        {
            "match": "i can see you standing, honey",
            "summary": "开场即是「旁观」：男声视角看着旧爱牵起别人的手——exile 的核心是沟通的错位与迟到的明白。",
            "taylor_swift_context": "与 Bon Iver (Justin Vernon) 的男女双视角对唱，folklore 最戏剧化的编排。",
            "emotion": (0.3, 0.35, "loneliness"),
        },
        {
            "match": "i think i've seen this film before",
            "summary": "把感情的结局比作看过的电影——「我知道结局是坏的，却还是看完了」。宿命感与无力感并置。",
            "metaphor_analysis": "本体：重复失败的感情模式；喻体：重映的老电影。观影是被动的——暗示两人都未曾真正行动。",
            "wordplay": "film 同时暗示「隔着一层膜观看」：亲历者变成了旁观者。",
            "related_lines": [
                {"song": "cardigan", "album": "folklore", "line": "Peter losing Wendy", "similarity": 0.58},
                {"song": "champagne problems", "album": "evermore", "line": "Sometimes you just don't know the answer", "similarity": 0.55},
            ],
            "emotion": (0.25, 0.4, "despair"),
        },
        {
            "match": "leaving out the side door",
            "summary": "从侧门离开——不告而别的具象化：不是戏剧性的摔门，是安静的、不被注意的退场。",
            "metaphor_analysis": "正门=正式的告别仪式；侧门=逃避与体面的双重含义。",
            "emotion": (0.25, 0.3, "loss"),
        },
        {
            "match": "you never gave a warning sign",
            "summary": "双声部争论的核心：男声「你从没给过警告」vs 女声「我给了太多警告」——同一段感情，两套记忆。",
            "metaphor_analysis": "warning sign 延伸出「界碑/信号」意象群 (side door / holding out / breaking branches)。",
            "taylor_swift_context": "合唱段两人歌词交叠对抗，是编曲层面对「沟通失败」主题的直接演绎。",
            "emotion": (0.2, 0.55, "anger"),
        },
    ],
    "champagne_problems": [
        {
            "match": "your mom's ring in your pocket",
            "summary": "口袋里的婚戒——一场没有发生的求婚。整首歌是对「拒绝的那一刻」的回放与自责。",
            "metaphor_analysis": "戒指=承诺的实体。它停留在口袋（未送出），如同这段关系停在未完成时。",
            "taylor_swift_context": "evermore 时期 Taylor 转向纯虚构叙事，本曲与 Joe Alwyn 合写（化名 William Bowery）。",
            "related_lines": [
                {"song": "cardigan", "album": "folklore", "line": "And when I felt like I was an old cardigan under someone's bed", "similarity": 0.62},
            ],
            "emotion": (0.3, 0.4, "regret"),
        },
        {
            "match": "champagne problems",
            "summary": "标题双关：字面是「香槟级的烦恼」（富人的小事），实际指拒婚这件被旁人轻描淡写、却摧毁两个人的大事。",
            "wordplay": "champagne problems 是英语习语「无关痛痒的烦恼」；歌中反讽——对局外人是谈资，对当事人是余生。",
            "cultural_context": "香槟本该在订婚时开启庆祝，此处成为「庆祝落空」的反讽物。",
            "emotion": (0.3, 0.35, "regret"),
        },
        {
            "match": "she would've made such a lovely bride",
            "summary": "借旁人之口的闲言碎语：「她本该是多美的新娘，可惜她脑子不正常」——污名化拒绝者的社会目光。",
            "cultural_context": "「what a shame she's fucked in the head」直录流言的残忍原声，是 Taylor 词作中罕见的粗粝笔触。",
            "emotion": (0.2, 0.5, "sadness"),
        },
        {
            "match": "you won't remember all my",
            "summary": "结尾的自我安慰或诅咒：你会遇到更好的人，忘掉我这些「香槟问题」——温柔表面下是深不见底的自贬。",
            "emotion": (0.35, 0.3, "loss"),
        },
    ],
    "anti_hero": [
        {
            "match": "get older but just never wiser",
            "summary": "开篇自嘲：年岁渐长智慧不增。Midnights 的「深夜自省」母题第一句就点题。",
            "taylor_swift_context": "Taylor 称 Anti-Hero 是她「最诚实的歌之一」：把最讨厌自己的部分写成了热单。",
            "emotion": (0.35, 0.4, "self-doubt"),
        },
        {
            "match": "midnights become my afternoons",
            "summary": "昼夜颠倒的失眠意象：午夜成了下午——抑郁与自我审视把时间结构溶解了。",
            "metaphor_analysis": "时间错乱=心理秩序崩塌。同时点出专辑名 Midnights 的概念：13 个不眠之夜。",
            "emotion": (0.3, 0.35, "mystery"),
        },
        {
            "match": "i'm the problem, it's me",
            "summary": "病毒式传播的核心句：「问题在我」。用会议出席的口吻（Hi!）自我点名，反讽中带着真诚的自我指认。",
            "wordplay": "「It's me, hi」模拟点名/自我介绍场景，把内心审判庭具象成一场尴尬的会议。",
            "cultural_context": "发行后成为 TikTok 现象级 meme，「自我问题化」的表达进入日常语言。",
            "related_lines": [
                {"song": "exile", "album": "folklore", "line": "So step right out, there is no amount of crying I can do for you", "similarity": 0.52},
            ],
            "emotion": (0.3, 0.55, "self-doubt"),
        },
        {
            "match": "sometimes i feel like everybody is a sexy baby",
            "summary": "最受争议的一句：「人人都是性感宝贝，而我是山丘上的怪物」——身材焦虑与年龄焦虑的超现实表达。",
            "metaphor_analysis": "sexy baby 指婴儿化的女性审美标准；monster on the hill 是被排除在标准外的自我——巨大、笨拙、被围观。",
            "allusions": ["「sexy baby」可能引用《30 Rock》中对婴儿化女性形象的讽刺"],
            "emotion": (0.25, 0.5, "self-doubt"),
        },
        {
            "match": "exhausting, always rooting for the anti-hero",
            "summary": "副歌点题：「一直为反英雄加油，一定很累吧」——替爱自己的人说出疲惫，是更深一层的自责。",
            "wordplay": "anti-hero（反英雄）：文学中有缺陷的主角。Taylor 把自己从「美国甜心」重新定位为「反英雄」。",
            "emotion": (0.3, 0.5, "self-doubt"),
        },
    ],
}


def build_song(song_dir: Path) -> None:
    meta_raw = json.loads((song_dir / "metadata.json").read_text(encoding="utf-8"))
    meta = SongMetadata(
        title=meta_raw.get("title", song_dir.name),
        artist=meta_raw.get("artist", "Taylor Swift"),
        album=meta_raw.get("album", ""),
        year=meta_raw.get("year", 0),
        era=meta_raw.get("era", ""),
        genre=meta_raw.get("genre", ""),
        themes=meta_raw.get("themes", []),
    )
    _, lines = load_lrc_file(str(song_dir / "lyrics.lrc"))

    curated = CURATED.get(song_dir.name, [])
    used_indices: set[int] = set()
    annotations: list[Annotation] = []

    for spec in curated:
        match = spec["match"].lower()
        line = next(
            (ln for ln in lines
             if match in ln.text.lower() and ln.line_index not in used_indices),
            None,
        )
        if line is None:
            print(f"  WARN [{song_dir.name}]: no line matches '{spec['match']}'")
            continue
        used_indices.add(line.line_index)
        v, a, cat = spec.get("emotion", estimate_emotion(line.text))
        annotations.append(Annotation(
            line_index=line.line_index,
            lyric_text=line.text,
            summary=spec.get("summary", ""),
            metaphor_analysis=spec.get("metaphor_analysis"),
            allusions=spec.get("allusions", []),
            wordplay=spec.get("wordplay"),
            emotional_tone=cat,
            cultural_context=spec.get("cultural_context"),
            taylor_swift_context=spec.get("taylor_swift_context"),
            related_lines=[RelatedLine(**r) for r in spec.get("related_lines", [])],
            emotion_valence=v,
            emotion_arousal=a,
            emotion_category=cat,
        ))

    curated_emotion = {a.line_index: a for a in annotations}
    emotion_arc = []
    for ln in lines:
        if ln.line_index in curated_emotion:
            a = curated_emotion[ln.line_index]
            v, ar, cat = a.emotion_valence, a.emotion_arousal, a.emotion_category
        else:
            v, ar, cat = estimate_emotion(ln.text)
        emotion_arc.append({
            "line_index": ln.line_index,
            "t_ms": ln.timestamp_ms,
            "valence": round(v, 3),
            "arousal": round(ar, 3),
            "category": cat,
        })

    annotations.sort(key=lambda a: a.line_index)
    song = Song(metadata=meta, annotations=annotations, emotion_arc=emotion_arc)
    out = song_dir / "annotations.json"
    song.save(out)
    print(f"  {song_dir.name}: {len(annotations)} annotations, {len(emotion_arc)} emotion points -> {out.name}")


def main() -> None:
    for d in sorted(SONGS_DIR.iterdir()):
        if d.is_dir() and (d / "lyrics.lrc").exists():
            build_song(d)


if __name__ == "__main__":
    main()
