import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookStats, DrillEntry, DrillQueue, drillTtsUrl, useDrillActions,
  useDrillCard, useSongs,
} from "../api";
import { usePlayer } from "../store";
import { IconVolume } from "../icons";
import Scrollable from "./Scrollable";

/** 盲打偏好与旧版同款：localStorage 记忆，默认盲打 */
const BLIND_KEY = "ll-drill-blind";
/** 每轮词数档位（方案 A）：10/20/50/0=全部，localStorage 记忆 */
const LEN_KEY = "ll-drill-round-len";
export const ROUND_LENS = [10, 20, 50, 0] as const;

export function loadRoundLen(): number {
  try {
    const v = parseInt(localStorage.getItem(LEN_KEY) ?? "20", 10);
    return (ROUND_LENS as readonly number[]).includes(v) ? v : 20;
  } catch {
    return 20;
  }
}
export function saveRoundLen(n: number) {
  try { localStorage.setItem(LEN_KEY, String(n)); } catch { /* 忽略 */ }
}

interface RoundStats {
  words: number;
  perfect: number;
  chars: number;
  ms: number;
}

interface Missed {
  entry: DrillEntry;
  mistakes: number;
}

function statsLine(round: RoundStats, book: BookStats | undefined) {
  const parts: string[] = [];
  if (round.words) {
    const pct = Math.round((100 * round.perfect) / round.words);
    const wpm = round.ms
      ? Math.round(((round.chars / 5) / (round.ms / 60000)) * 10) / 10 : 0;
    parts.push(`本轮 ${round.words} 词 · 一遍过 ${round.perfect}（${pct}%） · WPM ${wpm}`);
  }
  if (book)
    parts.push(`单词本 ${book.practiced}/${book.total} 已练 · ${book.mastered} 熟练`);
  return parts.join(" ｜ ");
}

export default function Drill({
  group,
  roundLen,
  queue,
  loading,
  onNewQueue,
}: {
  group: string;
  roundLen: number;
  queue: DrillQueue | undefined;
  loading: boolean;
  onNewQueue: () => void;
}) {
  const acts = useDrillActions();
  const navigate = useNavigate();
  const { setSong, pickLine } = usePlayer();
  const { data: allSongs = [] } = useSongs("");
  // 词条只存歌名：跳转前按 title 兜底解析成 song id（同收藏夹口径）
  const jumpToSong = (title: string, lineIndex?: number) => {
    const hit = allSongs.find((sg) => sg.title === title);
    if (!hit) return;
    setSong(hit.id);
    if (lineIndex !== undefined && lineIndex >= 0) pickLine(lineIndex);
    navigate("/");
  };
  // 本轮词表：优先级队列切片，或「重打错词」的自定义列表
  const [roundWords, setRoundWords] = useState<DrillEntry[]>([]);
  const [offset, setOffset] = useState(0);
  const [phase, setPhase] = useState<"typing" | "review">("typing");
  const [qi, setQi] = useState(0);
  const [typed, setTyped] = useState(0);
  const [mistakes, setMistakes] = useState(0);
  const [peeks, setPeeks] = useState(0);
  const [peeking, setPeeking] = useState(false);
  const [done, setDone] = useState(false);
  const [blind, setBlind] = useState(() => {
    try { return localStorage.getItem(BLIND_KEY) !== "0"; } catch { return true; }
  });
  const [round, setRound] = useState<RoundStats>({ words: 0, perfect: 0, chars: 0, ms: 0 });
  const [missed, setMissed] = useState<Missed[]>([]);
  const [bookStats, setBookStats] = useState<BookStats | undefined>();
  const startRef = useRef<number | null>(null);
  const ttsRef = useRef<HTMLAudioElement>(null);

  const entry = phase === "typing" ? roundWords[qi] : undefined;
  const word = entry?.word ?? "";
  const card = useDrillCard(word || null);

  const resetWord = () => {
    setTyped(0); setMistakes(0); setPeeks(0); setDone(false);
    startRef.current = null;
  };
  const beginRound = useCallback((words: DrillEntry[]) => {
    setRoundWords(words);
    setQi(0);
    setRound({ words: 0, perfect: 0, chars: 0, ms: 0 });
    setMissed([]);
    setPhase("typing");
    setTyped(0); setMistakes(0); setPeeks(0); setDone(false);
    startRef.current = null;
  }, []);

  // 范围/档位/队列变化 → 从头开一轮（切片前 N 个）
  useEffect(() => {
    const all = queue?.entries ?? [];
    setOffset(0);
    beginRound(roundLen > 0 ? all.slice(0, roundLen) : all);
  }, [group, roundLen, queue, beginRound]);

  useEffect(() => { setBookStats(queue?.stats); }, [queue]);

  // 卡片就绪自动读音
  useEffect(() => {
    if (card.data?.tts && ttsRef.current && word) {
      ttsRef.current.src = drillTtsUrl(word);
      void ttsRef.current.play().catch(() => undefined);
    }
  }, [card.data, word]);

  const nextRound = useCallback(() => {
    const all = queue?.entries ?? [];
    if (roundLen <= 0 || offset + roundLen >= all.length) {
      onNewQueue(); // 范围内打完一遍：重排队列（useEffect 会重开一轮）
      return;
    }
    const next = offset + roundLen;
    setOffset(next);
    beginRound(all.slice(next, next + roundLen));
  }, [queue, roundLen, offset, onNewQueue, beginRound]);

  // 跳过：不计成绩、不进错词表——队列前排老是同几个词时的出口
  const skipWord = useCallback(() => {
    if (qi + 1 >= roundWords.length) setPhase("review");
    else { setQi((i) => i + 1); resetWord(); }
  }, [qi, roundWords.length]);

  // 键击循环：打错整词重来；Tab 偷看；Enter 换词/回顾页开下一轮
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (phase === "review") {
        if (e.key === "Enter") nextRound();
        return;
      }
      if (!word) return;
      if (e.key === "Tab") {
        e.preventDefault();
        if (blind && !done) {
          setPeeks((p) => p + 1);
          setPeeking(true);
          setTimeout(() => setPeeking(false), 1500);
        }
        return;
      }
      if (e.key === "Enter") {
        if (!done) return;
        if (qi + 1 >= roundWords.length) setPhase("review");
        else { setQi((i) => i + 1); resetWord(); }
        return;
      }
      if (done || e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) return;
      e.preventDefault();
      if (startRef.current === null) startRef.current = performance.now();
      if (e.key.toLowerCase() === word[typed]?.toLowerCase()) {
        const n = typed + 1;
        setTyped(n);
        if (n >= word.length) {
          setDone(true);
          const ms = startRef.current ? performance.now() - startRef.current : 0;
          const clean = mistakes === 0;
          setRound((r) => ({
            words: r.words + 1,
            perfect: r.perfect + (clean ? 1 : 0),
            chars: r.chars + word.length,
            ms: r.ms + ms,
          }));
          if (!clean && entry)
            setMissed((m) => [...m, { entry, mistakes }]);
          acts.reportResult(word, clean, blind, peeks)
            .then(setBookStats).catch(() => undefined);
        }
      } else {
        setTyped(0); // 整词重来
        setMistakes((m) => m + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, word, typed, done, mistakes, blind, peeks, qi, roundWords,
      entry, acts, nextRound]);

  if (loading)
    return <p className="flex flex-1 items-center justify-center text-sm text-ink3">加载单词本…</p>;
  if (!queue?.entries.length)
    return (
      <p className="mx-auto flex max-w-md flex-1 items-center text-center text-sm leading-7 text-ink3">
        {group === "全部"
          ? "单词本是空的——去「播放解读」双击歌词里的英文单词收藏几个，或在下方导入单词表。"
          : "这个分组没有单词。"}
      </p>
    );

  // ── 回顾页 ──
  if (phase === "review") {
    const pct = round.words ? Math.round((100 * round.perfect) / round.words) : 0;
    return (
      <Scrollable
        ariaLabel="本轮回顾"
        className="min-h-0 flex-1"
        contentClassName="flex flex-col items-center gap-[18px] pt-6"
      >
        <h2 className="text-xl font-bold">
          {missed.length ? `本轮完成 · ${missed.length} 个错词` : "本轮完成 · 全部一遍过"}
        </h2>
        <p className="text-[13.5px] tabular-nums text-ink2">
          本轮 {round.words} 词 · 一遍过 {round.perfect}（{pct}%）
          {bookStats && `　｜　单词本 ${bookStats.practiced}/${bookStats.total} 已练 · ${bookStats.mastered} 熟练`}
        </p>
        <div className="flex w-[min(560px,100%)] flex-col gap-2">
          {missed.length ? (
            <>
              <div className="text-[11px] font-semibold tracking-[0.1em] text-ink3">
                错词（本轮整词重来 ≥1 次）
              </div>
              {missed.map((m) => (
                <div key={m.entry.word} className="flex items-baseline gap-2.5 rounded-card border border-edge bg-panel px-4 py-3 text-[13.5px]">
                  <b className="text-[15px]">{m.entry.word}</b>
                  {m.entry.phonetic && (
                    <span className="text-[11.5px] text-ink3">/{m.entry.phonetic}/</span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-ink2">
                    {(m.entry.translation ?? "").replace(/\\n/g, "；")}
                  </span>
                  <span className="flex-none font-semibold tabular-nums text-accent">
                    重来 ×{m.mistakes}
                  </span>
                </div>
              ))}
            </>
          ) : (
            <p className="py-4 text-center text-sm text-ink2">没有错词——这轮漂亮。</p>
          )}
        </div>
        <div className="flex gap-2.5">
          {missed.length > 0 && (
            <button
              className="rounded-full bg-accent px-3.5 py-1.5 text-[12.5px] font-semibold text-[#0e1016] hover:brightness-110"
              onClick={() => beginRound(missed.map((m) => m.entry))}
            >
              重打错词
            </button>
          )}
          <button
            className="rounded-full border border-[#33333c] px-3.5 py-1.5 text-[12.5px] font-medium text-ink2 hover:border-accent hover:text-accent"
            onClick={nextRound}
          >
            下一轮
          </button>
        </div>
        <p className="text-[11px] text-ink3">按 Enter 直接开下一轮</p>
      </Scrollable>
    );
  }

  // ── 练习态 ──
  if (!entry) return null; // 切片 effect 尚未写入 roundWords 的首帧
  const e2 = card.data?.entry ?? entry;
  const reveal = !blind || peeking || done;
  const masked = (line: string) =>
    reveal
      ? line
      : line.replace(
          new RegExp(word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"),
          "●".repeat(word.length),
        );

  return (
    <section aria-label="打字练习" className="flex flex-1 flex-col items-center justify-center gap-6">
      <audio ref={ttsRef} preload="none" />
      {/* 进度条：本轮 n/N */}
      <div className="flex w-[min(560px,100%)] items-center gap-2.5">
        <div className="h-[5px] flex-1 overflow-hidden rounded-[3px] bg-edge2">
          <div
            className="h-full rounded-[3px] bg-accent transition-[width] duration-200"
            style={{ width: `${(qi / roundWords.length) * 100}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-ink3">
          {qi}/{roundWords.length}
        </span>
      </div>

      <p className="max-w-xl text-center text-[19.5px] leading-7 text-ink">
        {(e2.translation ?? "").replace(/\\n/g, "；")}
      </p>

      <div className="flex items-center gap-3">
        <div className="flex gap-[3px] text-[34px] font-bold tracking-wide" aria-label={done ? word : "待输入的单词"}>
          {word.split("").map((c, i) => (
            <span key={i} className={i < typed ? "text-accent" : "text-ink3"}>
              {c === " " ? " " : i < typed || reveal ? c : "●"}
            </span>
          ))}
        </div>
        {e2.phonetic && <span className="text-sm text-ink3">/{e2.phonetic}/</span>}
        {card.data?.tts && (
          <button
            className="text-ink2 transition-colors hover:text-ink"
            aria-label="重播发音"
            onClick={() => void ttsRef.current?.play()}
          >
            <IconVolume />
          </button>
        )}
        <button
          className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
            blind ? "border-accent text-accent" : "border-[#33333c] text-ink2"
          }`}
          title="切换 盲打 / 显示单词"
          onClick={() => {
            setBlind((b) => {
              try { localStorage.setItem(BLIND_KEY, b ? "0" : "1"); } catch { /* 忽略 */ }
              return !b;
            });
          }}
        >
          盲打
        </button>
      </div>

      {e2.line && (
        <p className="max-w-xl text-center text-[23.8px] leading-[1.7] text-ink3">
          「{masked(e2.line)}」
          {e2.song && (
            <button
              className="text-ink3 underline-offset-4 transition-colors hover:text-accent hover:underline"
              title={`打开《${e2.song}》并定位到这句`}
              onClick={() => jumpToSong(e2.song!, e2.line_index)}
            >
              {` ·《${e2.song}》`}
            </button>
          )}
        </p>
      )}
      {!!card.data?.examples?.length && (
        <ul className="max-w-xl text-center text-[21.3px] leading-[1.6] text-ink3">
          {card.data.examples.slice(0, 2).map((ex) => (
            <li key={ex}>{masked(ex)}</li>
          ))}
        </ul>
      )}
      {e2.ai && (
        <p className="max-w-xl text-center text-[21.3px] leading-[1.6] text-ink3">{e2.ai}</p>
      )}

      <div className="flex gap-2.5">
        <button
          className="rounded-full border border-[#33333c] px-3.5 py-1.5 text-[12.5px] font-medium text-ink2 transition-colors hover:border-accent hover:text-accent"
          title="这个词不想打：不计成绩，直接看下一个"
          onClick={skipWord}
        >
          跳过这个词
        </button>
        <button
          className="rounded-full border border-[#33333c] px-3.5 py-1.5 text-[12.5px] font-medium text-ink2 transition-colors hover:border-accent hover:text-accent"
          title="这一轮的词都不想打：直接换下一批"
          onClick={nextRound}
        >
          跳过这一轮
        </button>
      </div>

      {done && (
        <p className="text-xs text-ink3" aria-live="polite">
          完成（{mistakes === 0 ? "一遍过" : `${mistakes} 次重来`}）· 按 Enter 下一个
        </p>
      )}
      <p className="text-xs tabular-nums text-ink3">{statsLine(round, bookStats)}</p>
    </section>
  );
}
