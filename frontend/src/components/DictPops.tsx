import { useCallback, useEffect, useRef, useState } from "react";
import { DictHit, Occurrences, OccurrenceItem, fetchOccurrences, useActions, useSongs } from "../api";
import { usePlayer } from "../store";
import { Song } from "../api";
import Scrollable from "./Scrollable";

/** 旧版 ll-dict-pop 的 React 移植：
 *  - 双击查单词、拖选 2-16 词查词组（正则与旧 JS 一致）
 *  - 弹卡锚定在选区旁、可拖动、最多同屏 4 张、Esc 全关
 *  - 有道 dictvoice 自动发音 + 🔊 重播
 *  - ✨ AI 语境解释（v3 三行模板，服务端落盘缓存）、⭐ 收藏单词/词组 */

interface Pop {
  id: number;
  word: string;
  line: string;
  x: number;
  y: number;
  hit: DictHit | null;
  loading: boolean;
  ai: string;
  aiLoading: boolean;
  faved: boolean;
  lineIndex: number;
  occ: Occurrences | null;
  occDone: boolean;
  occOpen: boolean;
}

const WORD_RE =
  /^[A-Za-z][A-Za-z'’-]{1,31}(?: [A-Za-z][A-Za-z'’,.-]{0,31}){0,15}/;

const voiceUrl = (w: string) =>
  `https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(w)}&type=2`;
const say = (w: string) => {
  new Audio(voiceUrl(w)).play().catch(() => undefined);
};

export default function DictPops({ song }: { song: Song | undefined }) {
  const [pops, setPops] = useState<Pop[]>([]);
  const nextId = useRef(1);
  const { pickLine, setSong } = usePlayer();
  const acts = useActions(song?.id ?? null, song?.title ?? "");
  const { data: allSongs = [] } = useSongs("");
  const songTitle = song?.title ?? "";

  const jumpOcc = (it: OccurrenceItem) => {
    if (it.song === songTitle) {
      pickLine(it.line_index);
      return;
    }
    const hit = allSongs.find((sg) => sg.title === it.song);
    if (!hit) return;
    setSong(hit.id);
    pickLine(it.line_index);
  };

  const open = useCallback(
    async (word: string, line: string, lineIndex: number, x: number, y: number) => {
      const id = nextId.current++;
      say(word); // 自动发音（与旧版 lastSpoken 行为一致：每次查询读一遍）
      setPops((ps) => {
        const kept = ps.length >= 4 ? ps.slice(1) : ps; // 最多 4 张,顶掉最旧
        return [...kept, {
          id, word, line, lineIndex,
          x: Math.min(x, window.innerWidth - 300),
          y: Math.min(y + 6, window.innerHeight - 300),
          hit: null, loading: true, ai: "", aiLoading: false, faved: false,
          occ: null, occDone: false, occOpen: false,
        }];
      });
      const patch = (p: Partial<Pop>) =>
        setPops((ps) => ps.map((q) => (q.id === id ? { ...q, ...p } : q)));
      void fetchOccurrences(word, songTitle, line)
        .then((d) => patch({ occ: d.total > 0 ? d : null, occDone: true }))
        .catch(() => patch({ occDone: true }));
      try {
        const res = await fetch(`/api/dict/${encodeURIComponent(word)}`);
        patch({ hit: res.ok ? await res.json() : null, loading: false });
      } catch {
        patch({ loading: false });
      }
      try {
        const res = await fetch(
          `/api/dict-ai?word=${encodeURIComponent(word)}&line=${encodeURIComponent(line)}`,
        );
        const d = await res.json();
        if (d.ai) patch({ ai: d.ai }); // 生成过的解释直接带出
      } catch { /* 缓存未命中即忽略 */ }
    },
    [songTitle],
  );

  // 事件委托：歌词行上的 dblclick（单词）与 mouseup（含空格的拖选=词组）
  useEffect(() => {
    const lookup = (e: Event) => {
      const sel = window.getSelection();
      let anchor: Element | null = null;
      const node = sel?.anchorNode;
      if (node)
        anchor = node.nodeType === 3 ? node.parentElement : (node as Element);
      const lineEl =
        anchor?.closest?.(".lyric-line") ??
        (e.target as Element | null)?.closest?.(".lyric-line");
      if (!lineEl) return;
      const raw = (sel?.toString() ?? "").trim().replace(/\s+/g, " ");
      const m = raw.match(WORD_RE);
      if (!m) return;
      const word = m[0].replace(/[,.-]+$/, "");
      const line = lineEl.textContent?.trim() ?? "";
      const lineIndex = Number((lineEl as HTMLElement).dataset.line ?? -1);
      let rect = lineEl.getBoundingClientRect();
      try {
        const r = sel!.getRangeAt(0).getBoundingClientRect();
        if (r && r.width) rect = r;
      } catch { /* 无选区矩形则用整行 */ }
      void open(word, line, lineIndex, rect.left, rect.bottom);
    };
    const onDbl = (e: Event) => lookup(e);
    const onUp = (e: Event) => {
      // 稍等一拍让浏览器敲定选区；选区含空格才按词组查
      setTimeout(() => {
        const s = (window.getSelection()?.toString() ?? "").trim();
        if (s.includes(" ")) lookup(e);
      }, 10);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPops([]);
    };
    document.addEventListener("dblclick", onDbl);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("dblclick", onDbl);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = (id: number) => setPops((ps) => ps.filter((p) => p.id !== id));
  const patchPop = (id: number, p: Partial<Pop>) =>
    setPops((ps) => ps.map((q) => (q.id === id ? { ...q, ...p } : q)));

  const genAi = async (p: Pop) => {
    patchPop(p.id, { aiLoading: true });
    try {
      const res = await fetch("/api/dict-ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ word: p.word, line: p.line, song: song?.title ?? "" }),
      });
      const d = await res.json().catch(() => null);
      patchPop(p.id, {
        ai: res.ok ? d.ai : `⚠️ ${d?.detail ?? "LLM 调用失败"}`,
        aiLoading: false,
      });
    } catch {
      patchPop(p.id, { ai: "⚠️ LLM 调用失败", aiLoading: false });
    }
  };

  // 拖动：按住卡片空白处移动
  const drag = (e: React.PointerEvent, p: Pop) => {
    if ((e.target as Element).closest("button")) return;
    const sx = e.clientX, sy = e.clientY, px = p.x, py = p.y;
    const onMove = (ev: PointerEvent) =>
      patchPop(p.id, {
        x: Math.max(0, px + ev.clientX - sx),
        y: Math.max(0, py + ev.clientY - sy),
      });
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <>
      {pops.map((p) => {
        const isPhrase = p.word.includes(" ");
        return (
          <div
            key={p.id}
            onPointerDown={(e) => drag(e, p)}
            className="fixed z-50 w-[290px] cursor-grab rounded-card border border-edge bg-panel2 p-3.5 shadow-mv"
            style={{ left: p.x, top: p.y }}
            role="dialog"
            aria-label={`词典卡 ${p.word}`}
            data-occ-state={p.occDone ? (p.occ ? "some" : "none") : "loading"}
          >
            <div className="flex items-center gap-2">
              <b className="text-[15px]">{p.hit?.word ?? p.word}</b>
              {p.hit?.phonetic && (
                <span className="text-[11.5px] text-ink3">/{p.hit.phonetic}/</span>
              )}
              <button
                className="text-ink2 hover:text-ink"
                title="重播发音"
                onClick={() => say(p.word)}
              >
                🔊
              </button>
              <button
                className="ml-auto text-ink3 hover:text-ink"
                aria-label="关闭"
                onClick={() => close(p.id)}
              >
                ✕
              </button>
            </div>
            <div className="mt-1.5 whitespace-pre-line text-[12.5px] leading-6 text-ink2">
              {p.loading
                ? "⏳ 查询中…"
                : p.hit
                  ? p.hit.translation.replace(/\\n/g, "\n")
                  : "本地词典没有这个词，试试 ✨ AI 解释。"}
            </div>
            {p.ai && (
              <div className="mt-2 whitespace-pre-line rounded-lg bg-accent-soft px-2.5 py-2 text-[12.5px] leading-6 text-ink">
                ✨ {p.ai}
              </div>
            )}
            {p.occDone && p.occ && (
              <div className="mt-2" data-occ-fold>
                <button
                  className="w-full text-left text-[12px] text-ink3 transition-colors hover:text-accent"
                  onClick={() => patchPop(p.id, { occOpen: !p.occOpen })}
                >
                  <span className="inline-flex items-center gap-1">
                    曲库里还有 {p.occ.total} 处
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 16 16"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className={p.occOpen ? "rotate-180" : ""}
                    >
                      <path d="M4 6l4 4 4-4" />
                    </svg>
                  </span>
                </button>
                {p.occOpen && (
                  <Scrollable className="mt-1.5 max-h-44">
                    <ul className="flex flex-col gap-0.5" data-occ-list>
                      {p.occ.items.map((it) => (
                        <li key={`${it.song}:${it.line_index}`}>
                          <button
                            className="w-full rounded-md px-2 py-1 text-left text-[12px] leading-5 text-ink2 transition-colors hover:bg-white/5 hover:text-ink"
                            data-occ-item
                            data-occ-song={it.song}
                            data-occ-line={it.line_index}
                            onClick={() => jumpOcc(it)}
                          >
                            {it.line}
                            <span className="ml-1 text-ink3">《{it.song}》</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </Scrollable>
                )}
              </div>
            )}
            <div className="mt-2.5 flex gap-2">
              <button
                className="rounded-full border border-[#33333c] px-3 py-1 text-[12px] text-ink2 transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
                disabled={p.faved}
                onClick={() => {
                  pickLine(p.lineIndex >= 0 ? p.lineIndex : null);
                  void acts
                    .collectWord(p.word, p.line, p.lineIndex)
                    .then(() => patchPop(p.id, { faved: true }));
                }}
              >
                {p.faved ? "已收藏" : isPhrase ? "⭐ 收藏词组" : "⭐ 收藏单词"}
              </button>
              {!p.ai && (
                <button
                  className="rounded-full border border-[#33333c] px-3 py-1 text-[12px] text-ink2 transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
                  disabled={p.aiLoading}
                  onClick={() => void genAi(p)}
                >
                  {p.aiLoading ? "✨ 生成中…" : "✨ AI 语境解释"}
                </button>
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}
