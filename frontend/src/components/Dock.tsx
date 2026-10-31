import { useEffect, useRef, useState } from "react";
import {
  ChatTurn, Lyrics, Song, askLine, useActions, useFavorites, useIntro,
  useLineChat, useNotes, useWordbook,
} from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";

function Chip({
  children, primary, onClick, disabled, title, type = "button",
}: {
  children: React.ReactNode;
  primary?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-[15px] font-medium transition-colors ${
        primary
          ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
          : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
      } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[#33333c] disabled:hover:text-ink2`}
    >
      {children}
    </button>
  );
}

function Card({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-edge bg-panel p-4">
      <div className="mb-2.5 flex items-center gap-2 text-[14.4px] font-semibold text-ink2">
        {k}
      </div>
      {children}
    </div>
  );
}

function Fold({
  k, id, children,
}: { k: string; id?: string; children: React.ReactNode }) {
  return (
    <details id={id} className="group rounded-card border border-edge bg-panel">
      <summary className="cursor-pointer select-none list-none p-4 text-[14.4px] font-semibold text-ink2 transition-colors hover:text-ink">
        <span className="mr-1 inline-block transition-transform group-open:rotate-90">
          ▸
        </span>
        {k}
      </summary>
      <div className="px-4 pb-4">{children}</div>
    </details>
  );
}

function fmt(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const inputCls =
  "min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-[9px] text-[15.6px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";

function AskAiCard({
  songId, line, lineText,
}: { songId: string | null; line: number | null; lineText: string }) {
  const saved = useLineChat(songId, line);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // 切句/切歌时载入该句已保存的问答
  useEffect(() => {
    setTurns(saved.data?.history ?? []);
    setErr("");
  }, [songId, line, saved.data]);

  const send = () => {
    const text = q.trim();
    if (!text || busy || !songId || line === null || line < 0) return;
    setBusy(true);
    setErr("");
    setTurns((t) => [...t, { speaker: "user", text }]);
    setQ("");
    askLine(songId, line, text, turns)
      .then((r) => {
        // 失败路径的回答以 ⚠️ 开头且不入历史——作为错误显示而非静默丢弃
        if (r.answer.startsWith("⚠️")) setErr(r.answer.replace(/^⚠️\s*/, ""));
        setTurns(r.history);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "提问失败"))
      .finally(() => setBusy(false));
  };

  const picked = line !== null && line >= 0;
  return (
    <Card k={picked ? `💬 AI 助手 · 第 ${(line ?? 0) + 1} 句` : "💬 AI 助手"}>
      {picked ? (
        <p className="mb-2 truncate text-center text-[14.4px] italic text-ink3"
           title={lineText}>
          「{lineText}」
        </p>
      ) : (
        <p className="mb-2 text-center text-[15.6px] text-ink3">
          点一句歌词，针对这句提问
        </p>
      )}
      {turns.length > 0 && (
        <Scrollable className="mb-2.5 max-h-72" contentClassName="flex flex-col gap-2">
          {turns.map((t, i) => (
            <div
              key={i}
              className={`max-w-[85%] whitespace-pre-line rounded-lg px-3 py-2 text-[15px] leading-relaxed ${
                t.speaker === "user"
                  ? "self-end bg-accent-soft text-ink"
                  : "self-start bg-panel2 text-ink2"
              }`}
            >
              {t.text}
            </div>
          ))}
          {busy && (
            <div className="self-start rounded-lg bg-panel2 px-3 py-2 text-[15px] text-ink3">
              思考中…
            </div>
          )}
        </Scrollable>
      )}
      {err && (
        <p className="mb-2 text-center text-[14.4px] text-ink3">⚠️ {err}</p>
      )}
      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="针对这句歌词提问 ..."
          disabled={!picked || busy}
          className={inputCls}
        />
        <Chip primary onClick={send} disabled={!picked || busy || !q.trim()}>
          提问
        </Chip>
      </div>
    </Card>
  );
}

export default function Dock({
  lyrics,
  song,
}: {
  lyrics: Lyrics | undefined;
  song: Song | undefined;
}) {
  const { pickedLine, timeMs, requestSeek, setSong, pickLine } =
    usePlayer();
  // 批注/AI 助手只跟手动点选的句子，不随播放自动切换（2026-10-30 用户定）
  const line = pickedLine ?? -1;
  const ann = lyrics?.annotations[String(line)];
  const songId = song?.id ?? null;

  useEffect(() => {
    const open = () => {
      const d = document.getElementById("song-tools") as
        HTMLDetailsElement | null;
      if (!d) return;
      d.open = true;
      d.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    window.addEventListener("ll-open-song-tools", open);
    return () => window.removeEventListener("ll-open-song-tools", open);
  }, []);
  const songTitle = song?.title ?? "";
  const acts = useActions(songId, songTitle);
  const intro = useIntro(songId);
  const notes = useNotes(songId);
  const wordbook = useWordbook(songTitle || null);
  const favorites = useFavorites();
  // 只显示本首歌收藏的歌词（旧数据没有 song_id，用 title 匹配兜底）
  const songFavs = (favorites.data ?? []).filter(
    (f) => (f.song_id ? f.song_id === songId : f.title === songTitle));
  const [noteText, setNoteText] = useState("");
  const [offset, setOffset] = useState<string>("");
  // 切歌/打开时带出已保存的校准值，避免每次都要重填
  useEffect(() => {
    setOffset(song ? String(song.audio_offset_ms ?? 0) : "");
  }, [songId, song?.audio_offset_ms]);
  const [toast, setToast] = useState("");
  // 偏移保存反馈（方案 C：字段确认）——反馈就在按钮/输入框上，
  // 不再依赖面板顶部那条看不见的 toast
  const [offsetPhase, setOffsetPhase] =
    useState<"idle" | "saving" | "saved">("idle");
  const offsetTimer = useRef<number>();
  useEffect(() => () => window.clearTimeout(offsetTimer.current), []);
  const saveOffsetNow = async () => {
    if (offsetPhase !== "idle") return;
    setOffsetPhase("saving");
    try {
      await acts.saveOffset(parseInt(offset || "0", 10) || 0);
      setOffsetPhase("saved");
      offsetTimer.current = window.setTimeout(
        () => setOffsetPhase("idle"), 1500);
    } catch (e) {
      setOffsetPhase("idle");
      setToast(e instanceof Error ? e.message : "保存失败");
    }
  };
  const fileRef = useRef<HTMLInputElement>(null);

  const run = (p: Promise<unknown>, ok: string) =>
    p.then(() => setToast(ok)).catch((e) =>
      setToast(e instanceof Error ? e.message : "操作失败"),
    );

  const words = (wordbook.data ?? []).filter((e) => !e.word?.includes(" "));
  const phrases = (wordbook.data ?? []).filter((e) => e.word?.includes(" "));

  return (
    <Scrollable
      ariaLabel="解读面板"
      className="h-full min-h-0 border-l border-line bg-bg2"
      contentClassName="flex flex-col gap-3.5 px-[18px] py-5"
    >
      <h2 className="flex items-center text-[14.4px] font-semibold tracking-[0.1em] text-ink3">
        本句解读
        {toast && (
          <span className="ml-auto font-normal normal-case tracking-normal text-ink3">
            {toast}
          </span>
        )}
      </h2>

      <Card k={ann ? `✏️ AI 批注 · 第 ${line + 1} 句` : "✏️ AI 批注"}>
        {ann ? (
          <div className="mx-auto text-center text-[16.2px] leading-[1.8] text-ink2">
            <p>{ann.summary}</p>
            {ann.metaphor_analysis && (
              <p className="mt-1 text-ink">{ann.metaphor_analysis}</p>
            )}
            {ann.wordplay && <p className="mt-1">{ann.wordplay}</p>}
            {ann.emotional_tone && (
              <p className="mt-1.5 text-[14.4px] text-ink3">
                情绪基调 · {ann.emotional_tone}
              </p>
            )}
          </div>
        ) : (
          <p className="mx-auto text-center text-[16.2px] leading-[1.8] text-ink3">
            点一句歌词，看这句的 AI 批注
          </p>
        )}
      </Card>

      <AskAiCard
        songId={songId}
        line={line ?? null}
        lineText={lyrics?.timed_lines?.find((l) => l.line_index === line)?.text ?? ""}
      />

      <Card k="📖 歌曲导读">
        {intro.data?.status === "done" ? (
          <p className="mx-auto whitespace-pre-line text-center text-[16.2px] leading-[1.8] text-ink2">
            {intro.data.text}
          </p>
        ) : intro.data?.status === "running" ? (
          <p className="text-center text-[15.6px] text-ink3">
            AI 正在通读整首歌词，生成导读…（可随意切歌，回来还在）
          </p>
        ) : (
          <>
            {intro.data?.status === "error" && (
              <p className="mb-2 text-center text-[15px] text-ink3">
                生成失败：{intro.data.text}
              </p>
            )}
            <div className="flex justify-center">
              <Chip primary onClick={() => run(acts.genIntro(), "导读生成中…")}>
                生成导读
              </Chip>
            </div>
          </>
        )}
      </Card>

      <Fold k={`📝 听歌笔记（${notes.data?.length ?? 0}）`}>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!noteText.trim()) return;
            run(acts.addNote(Math.floor(timeMs), noteText.trim()), "笔记已存");
            setNoteText("");
          }}
        >
          <input
            name="note-text"
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder={`在 ${fmt(timeMs)} 记一条感想…`}
            className={inputCls}
          />
          <Chip primary type="submit">
            记下
          </Chip>
        </form>
        <ul className="mt-2.5 flex flex-col gap-1.5">
          {(notes.data ?? []).map((n) => (
            <li
              key={n.ts_ms}
              className="group flex items-start gap-2 rounded-lg bg-panel2 px-3 py-2"
            >
              <button
                className="font-semibold tabular-nums text-accent hover:underline"
                title="跳到这个位置"
                onClick={() => requestSeek(n.ts_ms)}
              >
                {fmt(n.ts_ms)}
              </button>
              <span className="min-w-0 flex-1 text-ink2">{n.text}</span>
              <button
                className="invisible text-ink3 hover:text-ink group-hover:visible"
                aria-label="删除笔记"
                onClick={() => run(acts.delNote(n.ts_ms), "已删除")}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </Fold>

      <Fold k={`⭐ 歌词收藏夹 ${songFavs.length}`}>
        <div className="mb-2">
          <Chip
            disabled={line < 0 || !songId}
            title={line < 0 ? "先在歌词区点选一句歌词" : undefined}
            onClick={() => {
              // 旧版口径：按 timed_lines 的 line_index 收藏，而非数组下标
              const tl = lyrics?.timed_lines[line];
              if (tl) run(acts.addFav(tl.line_index), "已收藏这句歌词");
            }}
          >
            ⭐ 收藏当前选中的歌词
          </Chip>
        </div>
        {songFavs.length ? (
          <ul className="flex flex-col gap-1.5">
            {songFavs.map((f) => (
              <li
                key={f.id}
                className="group flex items-start gap-2 rounded-lg bg-panel2 px-3 py-2"
              >
                <button
                  className="min-w-0 flex-1 text-left transition-colors hover:text-accent"
                  title="跳到这首歌的这句"
                  onClick={() => {
                    if (f.song_id && f.song_id !== songId) setSong(f.song_id);
                    pickLine(f.line_index);
                  }}
                >
                  <span className="text-[16.2px] font-medium text-ink2">{f.line}</span>
                  <span className="mt-0.5 block text-[13.8px] text-ink3">
                    {f.title}{f.artist ? ` · ${f.artist}` : ""}
                  </span>
                </button>
                <button
                  className="invisible text-ink3 hover:text-ink group-hover:visible"
                  aria-label="删除收藏"
                  onClick={() => run(acts.delFav(f.id), "已删除收藏")}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[15px] text-ink3">这首歌还没有收藏的歌词。</p>
        )}
      </Fold>

      <Fold k={`📒 单词本 ${words.length} · 词组本 ${phrases.length}`}>
        {[
          ["单词", words] as const,
          ["词组", phrases] as const,
        ].map(([label, list]) =>
          list.length ? (
            <div key={label} className="mb-2">
              <div className="mb-1 text-[12.6px] text-ink3">{label}</div>
              <ul className="flex flex-col gap-1.5">
                {list.map((e) => (
                  <li
                    key={e.word}
                    className="group rounded-lg bg-panel2 px-3 py-2 text-[15px]"
                  >
                    <div className="flex items-center gap-2">
                      <b className="text-ink">{e.word}</b>
                      {e.phonetic && (
                        <span className="text-[15.4px] text-ink3">
                          /{e.phonetic}/
                        </span>
                      )}
                      <button
                        className="invisible ml-auto text-ink3 hover:text-ink group-hover:visible"
                        aria-label={`编辑 ${e.word} 的笔记`}
                        title="编辑笔记"
                        onClick={() => {
                          const v = window.prompt(
                            `「${e.word}」的笔记：`, e.note ?? "");
                          if (v !== null)
                            run(acts.setWordNote(e.word, v), "笔记已保存");
                        }}
                      >
                        📝
                      </button>
                      <button
                        className="invisible text-ink3 hover:text-ink group-hover:visible"
                        aria-label={`移除 ${e.word}`}
                        onClick={() => run(acts.removeWord(e.word), "已移除")}
                      >
                        ✕
                      </button>
                    </div>
                    {e.translation && (
                      <p className="mt-0.5 whitespace-pre-line text-[15.4px] text-ink2">
                        {e.translation.replace(/\\n/g, "\n")}
                      </p>
                    )}
                    {e.line && (
                      <p className="mt-0.5 truncate text-[15.4px] text-ink3">
                        「{e.line}」
                      </p>
                    )}
                    {e.note && (
                      <p className="mt-0.5 whitespace-pre-line text-[15.4px] text-accent">
                        📝 {e.note}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
        {!words.length && !phrases.length && (
          <p className="text-[14.4px] text-ink3">
            双击歌词里的单词 → 生词卡 → 收藏，单词会跟随这首歌
          </p>
        )}
      </Fold>

      <Fold k="⚙️ 歌曲工具" id="song-tools">
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-[12.6px] text-ink3">
              歌词时间校准（毫秒，正=歌词提前）
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void saveOffsetNow();
              }}
            >
              <input
                name="offset-ms"
                inputMode="numeric"
                value={offset}
                onChange={(e) => setOffset(e.target.value)}
                placeholder={String(song?.audio_offset_ms ?? 0)}
                className={`min-w-0 flex-1 rounded-full border bg-panel2 px-3.5 py-[9px] text-[15.6px] text-ink placeholder:text-ink3 transition-[border-color,box-shadow] duration-300 focus:border-accent focus:outline-none ${
                  offsetPhase === "saved"
                    ? "border-accent shadow-[0_2px_18px_-6px_rgba(124,158,255,.5)]"
                    : "border-edge2"
                }`}
              />
              <Chip primary type="submit" disabled={offsetPhase === "saving"}>
                <span className="grid min-w-[30px] place-items-center">
                {offsetPhase === "idle" && "保存"}
                {offsetPhase === "saving" && (
                  <svg
                    className="animate-spin"
                    width="14" height="14" viewBox="0 0 16 16" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                  >
                    <path d="M8 1.5a6.5 6.5 0 1 1-6.5 6.5" />
                  </svg>
                )}
                {offsetPhase === "saved" && (
                  <svg
                    className="animate-popin"
                    width="14" height="14" viewBox="0 0 16 16" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M2.5 8.5l3.5 3.5 7-8" />
                  </svg>
                )}
                </span>
              </Chip>
            </form>
          </div>
          <div>
            <div className="mb-1 text-[12.6px] text-ink3">
              为当前歌曲上传音频（mp3/wav/flac/ogg/m4a）
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".mp3,.wav,.flac,.ogg,.m4a"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) run(acts.uploadAudio(f), "音频已上传，现在可以播放了");
                e.target.value = "";
              }}
            />
            <Chip onClick={() => fileRef.current?.click()}>选择音频文件…</Chip>
          </div>
        </div>
      </Fold>
    </Scrollable>
  );
}
