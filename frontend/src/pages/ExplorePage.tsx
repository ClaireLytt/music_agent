import { useEffect, useState } from "react";
import {
  QuizQ, PuzzleQ, fetchPuzzle, fetchQuiz, useAdminActions, useFanlore,
  useSongs,
} from "../api";
import { usePlayer } from "../store";
import Scrollable from "../components/Scrollable";

const chip = (on: boolean) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[18.8px] font-medium transition-colors ${
    on
      ? "bg-accent font-semibold text-[#0e1016]"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

const CLUE_TYPE: Record<string, string> = {
  official: "官方信息",
  lyric_parallel: "歌词对照",
  fan_theory: "歌迷推测",
};

// ── 歌迷考据 ──────────────────────────────────────────────────

function Lore() {
  const { songId } = usePlayer();
  const { data: songs = [] } = useSongs();
  const song = songs.find((s) => s.id === songId);
  const lore = useFanlore(songId);
  const acts = useAdminActions();
  const [history, setHistory] = useState<{ speaker: string; text: string }[]>([]);
  const [q, setQ] = useState("");
  const [asking, setAsking] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setHistory([]); setErr(""); }, [songId]);

  const ask = async () => {
    const question = q.trim();
    if (!question || !songId || asking) return;
    setAsking(true);
    setHistory((h) => [...h, { speaker: "user", text: question }]);
    setQ("");
    try {
      const r = await acts.chatLore(songId, question, history);
      setHistory((h) => [...h, { speaker: "AI 助手", text: r.answer }]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提问失败");
    } finally {
      setAsking(false);
    }
  };

  const d = lore.data;
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[1fr_320px] gap-5">
      <Scrollable className="min-h-0">
        <h2 className="mb-3 text-center text-[24px] font-bold">
          {song ? `《${song.title}》· ${song.artist}` : "先在左侧选一首歌"}
        </h2>
        {d?.status === "done" && d.data ? (
          <div className="mx-auto flex max-w-2xl flex-col gap-3 text-center">
            {d.data.hook && (
              <p className="rounded-card border border-edge bg-panel p-4 text-[22.5px] font-semibold leading-7">
                {d.data.hook}
              </p>
            )}
            {d.data.clues.map((c, i) => (
              <div key={i} className="rounded-card border border-edge bg-panel p-4">
                <div className="mb-1.5 text-[16.5px] font-semibold tracking-[0.08em] text-accent">
                  {CLUE_TYPE[c.type] ?? c.type}
                </div>
                {c.title && <div className="mb-1 text-[21px] font-semibold">{c.title}</div>}
                <p className="text-[20.3px] leading-[1.8] text-ink2">{c.body}</p>
                {[c.quote_a, c.quote_b].filter(Boolean).map((qt, j) => (
                  <p key={j} className="mt-1.5 text-[18.8px] text-ink3">
                    「{qt![1]}」·《{qt![0]}》
                  </p>
                ))}
              </div>
            ))}
            {d.data.chain.length > 0 && (
              <div className="rounded-card border border-edge bg-panel p-4">
                <div className="mb-1.5 text-[16.5px] font-semibold tracking-[0.08em] text-ink3">
                  剧情推测链
                </div>
                <p className="text-[20.3px] leading-[1.8] text-ink2">
                  {d.data.chain.map(([s, b]) => `《${s}》（${b}）`).join(" → ")}
                </p>
              </div>
            )}
            {d.data.summary && (
              <p className="text-[20.3px] leading-[1.8] text-ink2">{d.data.summary}</p>
            )}
            {d.data.caveat && (
              <p className="text-[18px] text-ink3">{d.data.caveat}</p>
            )}
            <p className="pb-2 text-[16.5px] text-ink3">
              官方信息来自 AI 训练语料、可能有误，推测仅基于歌词 · 均非官方设定
            </p>
          </div>
        ) : d?.status === "running" ? (
          <p className="mt-10 text-center text-[20.3px] leading-7 text-ink3">
            AI 正在整理这首歌的官方信息、歌词呼应与推测——后台生成，
            切歌/刷新都不会中断。
            <br />
            {d.progress || "准备中…"}
            {d.chars ? `（已生成 ${d.chars} 字符）` : ""}
          </p>
        ) : (
          <div className="mt-10 flex flex-col items-center gap-3">
            {d?.status === "error" && (
              <p className="text-[18.8px] text-ink3">生成失败:{d.msg}</p>
            )}
            <button
              className={chip(true)}
              disabled={!songId}
              onClick={() =>
                songId &&
                acts.genFanlore(songId).catch((e) =>
                  setErr(e instanceof Error ? e.message : "启动失败"),
                )
              }
            >
              生成考据故事（调用 1 次 LLM，之后永久缓存）
            </button>
            {err && <p className="text-[18.8px] text-ink3">{err}</p>}
          </div>
        )}
      </Scrollable>

      <aside className="flex min-h-0 flex-col rounded-card border border-edge bg-panel p-4">
        <div className="mb-2 text-[18px] font-semibold text-ink2">AI 助手</div>
        <Scrollable className="min-h-0 flex-1">
          {history.length === 0 && (
            <p className="text-center text-[18.8px] leading-6 text-ink3">
              考据页哪里看不懂，随时在这里问——AI 会结合本页内容回答。
            </p>
          )}
          {history.map((m, i) => (
            <div
              key={i}
              className={`mb-2 rounded-lg px-3 py-2 text-[19.5px] leading-6 ${
                m.speaker === "user"
                  ? "bg-accent-soft text-ink"
                  : "bg-panel2 text-ink2"
              }`}
            >
              {m.text}
            </div>
          ))}
          {asking && <p className="text-[18px] text-ink3">思考中…</p>}
          {err && <p className="text-[18px] text-ink3">{err}</p>}
        </Scrollable>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <input
            name="lore-question"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="针对本页考据提问…"
            className="min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[19.5px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
          />
          <button type="submit" className={chip(true)} disabled={asking}>
            提问
          </button>
        </form>
      </aside>
    </div>
  );
}

// ── 歌词竞猜 / 歌名拼图（共用一套四选一流程） ─────────────────

const ROUND_SIZE = 10;

interface GameResult {
  prompt: string;
  answer: string;
  picked: string;
  ok: boolean;
}

function Game({ kind }: { kind: "quiz" | "puzzle" }) {
  const [q, setQ] = useState<QuizQ | PuzzleQ | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [verdict, setVerdict] = useState("");
  const [results, setResults] = useState<GameResult[]>([]);
  const [phase, setPhase] = useState<"idle" | "playing" | "review">("idle");
  const [hint, setHint] = useState("");

  const draw = async (seen: string[]) => {
    setVerdict("");
    setPicked(null);
    setQ(null);
    try {
      let next: QuizQ | PuzzleQ | null = null;
      for (let tries = 0; tries < 6; tries++) {
        const cand = kind === "quiz" ? await fetchQuiz() : await fetchPuzzle();
        const key = kind === "quiz" ? (cand as QuizQ).line : (cand as PuzzleQ).masked;
        if (!seen.includes(key)) {
          next = cand;
          break;
        }
        next = cand;
      }
      setQ(next);
      setHint("");
    } catch (e) {
      setQ(null);
      setHint(e instanceof Error ? e.message : "出题失败");
    }
  };
  const seenKeys = () =>
    results.map((r) => r.prompt.replace(/^[“《]|[”》]$/g, ""));

  const startRound = () => {
    setResults([]);
    setPhase("playing");
    void draw([]);
  };

  const advance = () => {
    if (results.length >= ROUND_SIZE) {
      setQ(null);
      setPhase("review");
    } else {
      void draw(seenKeys());
    }
  };

  const submit = () => {
    if (!q || verdict) return;
    if (!picked) {
      setHint("请先选择一个选项");
      return;
    }
    const ok = picked === q.answer;
    setResults((r) => [...r, {
      prompt: kind === "quiz"
        ? `“${(q as QuizQ).line}”`
        : `《${(q as PuzzleQ).masked}》`,
      answer: kind === "quiz" ? `《${q.answer}》`
        : `「${q.answer}」（《${(q as PuzzleQ).title}》）`,
      picked: picked ?? "",
      ok,
    }]);
    if (kind === "quiz")
      setVerdict(ok ? `答对了！正是《${q.answer}》` : `不对，这句出自《${q.answer}》`);
    else {
      const p = q as PuzzleQ;
      setVerdict(
        (ok ? "拼对了！" : `不对，缺的是「${p.answer}」。`) +
          `　完整歌名:《${p.title}》· ${p.artist}`,
      );
    }
    setHint("");
  };

  // 键盘:1-4 选项、Enter 提交/下一题/回顾页开下一轮（与打单词一致）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Enter") {
        if (phase === "review" || phase === "idle") startRound();
        else if (verdict) advance();
        else submit();
      } else if (/^[1-4]$/.test(e.key) && q) {
        const opt = q.options[Number(e.key) - 1];
        if (opt) setPicked(opt);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── 回顾页（与打单词的轮回顾同构：本轮成绩 + 错题清单） ──
  if (phase === "review") {
    const wrong = results.filter((r) => !r.ok);
    return (
      <div className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-5">
        <p className="text-[24px] font-bold">
          {wrong.length ? `本轮完成 · ${wrong.length} 题答错` : "本轮完成 · 全对"}
        </p>
        <p className="text-[18.8px] text-ink3">
          本轮 {results.length} 题 · 答对 {results.length - wrong.length}
          （{Math.round(((results.length - wrong.length) / results.length) * 100)}%）
        </p>
        {wrong.length ? (
          <div className="w-full rounded-card border border-edge bg-panel">
            <div className="px-4 pb-1 pt-3 text-[16.5px] font-semibold tracking-[.08em] text-ink3">
              错题
            </div>
            {wrong.map((r, i) => (
              <div key={i} className="border-t border-edge px-4 py-2.5">
                <p className="text-[19.5px] text-ink">{r.prompt}</p>
                <p className="text-[18px] text-ink3">
                  你选「{r.picked}」 · 正确答案 {r.answer}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[18.8px] text-ink2">没有错题——这轮漂亮。</p>
        )}
        <button className={chip(true)} onClick={startRound}>
          下一轮（Enter）
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-5">
      {q ? (
        <>
          <p className="text-center text-[28.5px] font-semibold leading-8">
            {kind === "quiz" ? `“${(q as QuizQ).line}”` : `《${(q as PuzzleQ).masked}》`}
          </p>
          <p className="text-[18.8px] text-ink3">歌手:{q.artist}</p>
          <div className="flex w-full flex-col gap-2" role="radiogroup"
            aria-label={kind === "quiz" ? "它出自哪首歌？" : "被挖掉的是哪一块？"}>
            {q.options.map((opt, i) => (
              <button
                key={opt}
                role="radio"
                aria-checked={picked === opt}
                onClick={() => setPicked(opt)}
                className={`rounded-card border px-4 py-2.5 text-left text-[21px] transition-colors ${
                  picked === opt
                    ? "border-accent bg-accent-soft text-ink"
                    : "border-edge bg-panel text-ink2 hover:border-[#44444f]"
                }`}
              >
                <span className="mr-2 text-[16.5px] text-ink3">{i + 1}</span>
                {opt}
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="text-[20.3px] text-ink3">
          {hint ||
            (kind === "quiz"
              ? `按 Enter 或点「开始一轮」：${ROUND_SIZE} 句歌词连猜，最后看错题。`
              : `按 Enter 或点「开始一轮」：${ROUND_SIZE} 个歌名连拼，最后看错题。`)}
        </p>
      )}
      <div className="flex gap-2">
        {phase === "playing" && q ? (
          verdict ? (
            <button className={chip(true)} onClick={advance}>
              {results.length >= ROUND_SIZE ? "看本轮回顾" : "下一题"}
            </button>
          ) : (
            <button className={chip(true)} onClick={submit}>
              {kind === "quiz" ? "提交答案" : "拼好了"}
            </button>
          )
        ) : (
          <button className={chip(true)} onClick={startRound}>
            开始一轮
          </button>
        )}
      </div>
      {hint && q && <p className="text-[18.8px] text-ink3">{hint}</p>}
      {q && (
        <p className="text-[18.8px] text-ink3">
          第 <b className="text-ink2">{Math.min(results.length + (verdict ? 0 : 1), ROUND_SIZE)}</b> / {ROUND_SIZE} 题
          {results.length > 0 && ` · 已对 ${results.filter((r) => r.ok).length}`}
        </p>
      )}
      {verdict && (
        <p className="text-center text-[21px] leading-7">{verdict}</p>
      )}
      <p className="text-[16.5px] text-ink3">
        按 1-4 选选项、Enter 提交，看完答案再按一次 Enter 继续
      </p>
    </div>
  );
}

export default function ExplorePage() {
  const [tab, setTab] = useState<"lore" | "quiz" | "puzzle">("lore");
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden bg-bg2 px-10 py-6">
      <header className="flex items-center gap-2">
        <h1 className="mr-2 text-[21px] font-bold tracking-wide">互动探索</h1>
        {([["lore", "歌迷考据"], ["quiz", "歌词竞猜"], ["puzzle", "歌名拼图"]] as const).map(
          ([k, label]) => (
            <button key={k} className={chip(tab === k)} onClick={() => setTab(k)}>
              {label}
            </button>
          ),
        )}
      </header>
      {tab === "lore" ? <Lore /> : <Game key={tab} kind={tab} />}
    </div>
  );
}
