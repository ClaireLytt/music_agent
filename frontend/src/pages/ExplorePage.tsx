import { useEffect, useState } from "react";
import {
  QuizQ, PuzzleQ, fetchPuzzle, fetchQuiz, useAdminActions, useFanlore,
  useSongs,
} from "../api";
import { usePlayer } from "../store";
import Scrollable from "../components/Scrollable";

const chip = (on: boolean) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors ${
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
        <h2 className="mb-3 text-center text-base font-bold">
          {song ? `《${song.title}》· ${song.artist}` : "先在左侧选一首歌"}
        </h2>
        {d?.status === "done" && d.data ? (
          <div className="mx-auto flex max-w-2xl flex-col gap-3 text-center">
            {d.data.hook && (
              <p className="rounded-card border border-edge bg-panel p-4 text-[15px] font-semibold leading-7">
                {d.data.hook}
              </p>
            )}
            {d.data.clues.map((c, i) => (
              <div key={i} className="rounded-card border border-edge bg-panel p-4">
                <div className="mb-1.5 text-[11px] font-semibold tracking-[0.08em] text-accent">
                  {CLUE_TYPE[c.type] ?? c.type}
                </div>
                {c.title && <div className="mb-1 text-[14px] font-semibold">{c.title}</div>}
                <p className="text-[13.5px] leading-[1.8] text-ink2">{c.body}</p>
                {[c.quote_a, c.quote_b].filter(Boolean).map((qt, j) => (
                  <p key={j} className="mt-1.5 text-[12.5px] text-ink3">
                    「{qt![1]}」·《{qt![0]}》
                  </p>
                ))}
              </div>
            ))}
            {d.data.chain.length > 0 && (
              <div className="rounded-card border border-edge bg-panel p-4">
                <div className="mb-1.5 text-[11px] font-semibold tracking-[0.08em] text-ink3">
                  剧情推测链
                </div>
                <p className="text-[13.5px] leading-[1.8] text-ink2">
                  {d.data.chain.map(([s, b]) => `《${s}》（${b}）`).join(" → ")}
                </p>
              </div>
            )}
            {d.data.summary && (
              <p className="text-[13.5px] leading-[1.8] text-ink2">{d.data.summary}</p>
            )}
            {d.data.caveat && (
              <p className="text-[12px] text-ink3">{d.data.caveat}</p>
            )}
            <p className="pb-2 text-[11px] text-ink3">
              官方信息来自 AI 训练语料、可能有误，推测仅基于歌词 · 均非官方设定
            </p>
          </div>
        ) : d?.status === "running" ? (
          <p className="mt-10 text-center text-[13.5px] leading-7 text-ink3">
            AI 正在整理这首歌的官方信息、歌词呼应与推测——后台生成，
            切歌/刷新都不会中断。
            <br />
            {d.progress || "准备中…"}
            {d.chars ? `（已生成 ${d.chars} 字符）` : ""}
          </p>
        ) : (
          <div className="mt-10 flex flex-col items-center gap-3">
            {d?.status === "error" && (
              <p className="text-[12.5px] text-ink3">生成失败:{d.msg}</p>
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
            {err && <p className="text-[12.5px] text-ink3">{err}</p>}
          </div>
        )}
      </Scrollable>

      <aside className="flex min-h-0 flex-col rounded-card border border-edge bg-panel p-4">
        <div className="mb-2 text-xs font-semibold text-ink2">AI 助手</div>
        <Scrollable className="min-h-0 flex-1">
          {history.length === 0 && (
            <p className="text-center text-[12.5px] leading-6 text-ink3">
              考据页哪里看不懂，随时在这里问——AI 会结合本页内容回答。
            </p>
          )}
          {history.map((m, i) => (
            <div
              key={i}
              className={`mb-2 rounded-lg px-3 py-2 text-[13px] leading-6 ${
                m.speaker === "user"
                  ? "bg-accent-soft text-ink"
                  : "bg-panel2 text-ink2"
              }`}
            >
              {m.text}
            </div>
          ))}
          {asking && <p className="text-[12px] text-ink3">思考中…</p>}
          {err && <p className="text-[12px] text-ink3">{err}</p>}
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
            className="min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[13px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
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

function Game({ kind }: { kind: "quiz" | "puzzle" }) {
  const [q, setQ] = useState<QuizQ | PuzzleQ | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [verdict, setVerdict] = useState("");
  const [score, setScore] = useState({ ok: 0, total: 0 });
  const [hint, setHint] = useState("");

  const draw = async () => {
    setVerdict("");
    setPicked(null);
    try {
      setQ(kind === "quiz" ? await fetchQuiz() : await fetchPuzzle());
      setHint("");
    } catch (e) {
      setQ(null);
      setHint(e instanceof Error ? e.message : "出题失败");
    }
  };

  const submit = () => {
    if (!q || verdict) return;
    if (!picked) {
      setHint("请先选择一个选项");
      return;
    }
    const ok = picked === q.answer;
    setScore((s) => ({ ok: s.ok + (ok ? 1 : 0), total: s.total + 1 }));
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

  // 键盘:1-4 选项、Enter 提交/下一题（与旧版一致）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Enter") {
        if (verdict) void draw();
        else submit();
      } else if (/^[1-4]$/.test(e.key) && q) {
        const opt = q.options[Number(e.key) - 1];
        if (opt) setPicked(opt);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-5">
      {q ? (
        <>
          <p className="text-center text-[19px] font-semibold leading-8">
            {kind === "quiz" ? `“${(q as QuizQ).line}”` : `《${(q as PuzzleQ).masked}》`}
          </p>
          <p className="text-[12.5px] text-ink3">歌手:{q.artist}</p>
          <div className="flex w-full flex-col gap-2" role="radiogroup"
            aria-label={kind === "quiz" ? "它出自哪首歌？" : "被挖掉的是哪一块？"}>
            {q.options.map((opt, i) => (
              <button
                key={opt}
                role="radio"
                aria-checked={picked === opt}
                onClick={() => setPicked(opt)}
                className={`rounded-card border px-4 py-2.5 text-left text-[14px] transition-colors ${
                  picked === opt
                    ? "border-accent bg-accent-soft text-ink"
                    : "border-edge bg-panel text-ink2 hover:border-[#44444f]"
                }`}
              >
                <span className="mr-2 text-[11px] text-ink3">{i + 1}</span>
                {opt}
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="text-[13.5px] text-ink3">
          {hint || (kind === "quiz" ? "点「开始 / 下一题」抽一句歌词。" : "点「来一题」抽一个缺了一块的歌名。")}
        </p>
      )}
      <div className="flex gap-2">
        <button className={chip(true)} onClick={() => void draw()}>
          {kind === "quiz" ? "开始 / 下一题" : "来一题"}
        </button>
        <button className={chip(false)} onClick={submit}>
          {kind === "quiz" ? "提交答案" : "拼好了"}
        </button>
      </div>
      {hint && q && <p className="text-[12.5px] text-ink3">{hint}</p>}
      {verdict && (
        <p className="text-center text-[14px] leading-7">
          {verdict}　当前战绩 <b>{score.ok} / {score.total}</b>
        </p>
      )}
      <p className="text-[11px] text-ink3">
        按 1-4 选选项、Enter 提交，看完答案再按一次 Enter 下一题
      </p>
    </div>
  );
}

export default function ExplorePage() {
  const [tab, setTab] = useState<"lore" | "quiz" | "puzzle">("lore");
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden bg-bg2 px-10 py-6">
      <header className="flex items-center gap-2">
        <h1 className="mr-2 text-sm font-bold tracking-wide">互动探索</h1>
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
