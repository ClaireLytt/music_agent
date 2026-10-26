import { useRef, useState } from "react";
import {
  Lyrics, Song, useActions, useIntro, useNotes, useWordbook,
} from "../api";
import { usePlayer } from "../store";

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
      className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors ${
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
      <div className="mb-2.5 flex items-center gap-2 text-xs font-semibold text-ink2">
        {k}
      </div>
      {children}
    </div>
  );
}

function Fold({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-card border border-edge bg-panel">
      <summary className="cursor-pointer select-none list-none p-4 text-xs font-semibold text-ink2 transition-colors hover:text-ink">
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
  "min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-[9px] text-[13px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";

export default function Dock({
  lyrics,
  song,
}: {
  lyrics: Lyrics | undefined;
  song: Song | undefined;
}) {
  const { currentLine, pickedLine, timeMs, requestSeek } = usePlayer();
  const line = pickedLine ?? currentLine;
  const ann = lyrics?.annotations[String(line)];
  const songId = song?.id ?? null;
  const songTitle = song?.title ?? "";
  const acts = useActions(songId, songTitle);
  const intro = useIntro(songId);
  const notes = useNotes(songId);
  const wordbook = useWordbook(songTitle || null);
  const [noteText, setNoteText] = useState("");
  const [offset, setOffset] = useState<string>("");
  const [toast, setToast] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const run = (p: Promise<unknown>, ok: string) =>
    p.then(() => setToast(ok)).catch((e) =>
      setToast(e instanceof Error ? e.message : "操作失败"),
    );

  const words = (wordbook.data ?? []).filter((e) => !e.word?.includes(" "));
  const phrases = (wordbook.data ?? []).filter((e) => e.word?.includes(" "));

  return (
    <aside
      aria-label="解读面板"
      className="flex flex-col gap-3.5 overflow-y-auto border-l border-line bg-bg2 px-[18px] py-5"
    >
      <h2 className="flex items-center text-xs font-semibold tracking-[0.1em] text-ink3">
        本句解读
        {toast && (
          <span className="ml-auto font-normal normal-case tracking-normal text-ink3">
            {toast}
          </span>
        )}
      </h2>

      <Card k={ann ? `✏️ AI 批注 · 第 ${line + 1} 句` : "✏️ AI 批注"}>
        {ann ? (
          <div className="mx-auto text-center text-[13.5px] leading-[1.8] text-ink2">
            <p>{ann.summary}</p>
            {ann.metaphor_analysis && (
              <p className="mt-1 text-ink">{ann.metaphor_analysis}</p>
            )}
            {ann.wordplay && <p className="mt-1">{ann.wordplay}</p>}
            {ann.emotional_tone && (
              <p className="mt-1.5 text-xs text-ink3">
                情绪基调 · {ann.emotional_tone}
              </p>
            )}
          </div>
        ) : (
          <p className="mx-auto text-center text-[13.5px] leading-[1.8] text-ink3">
            点一句歌词，看这句的 AI 批注
          </p>
        )}
      </Card>

      <Card k="📖 歌曲导读">
        {intro.data?.status === "done" ? (
          <p className="mx-auto whitespace-pre-line text-center text-[13.5px] leading-[1.8] text-ink2">
            {intro.data.text}
          </p>
        ) : intro.data?.status === "running" ? (
          <p className="text-center text-[13px] text-ink3">
            AI 正在通读整首歌词，生成导读…（可随意切歌，回来还在）
          </p>
        ) : (
          <>
            {intro.data?.status === "error" && (
              <p className="mb-2 text-center text-[12.5px] text-ink3">
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
              className="group flex items-start gap-2 rounded-lg bg-panel2 px-3 py-2 text-[13px]"
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

      <Fold k={`📒 单词本 ${words.length} · 词组本 ${phrases.length}`}>
        {[
          ["单词", words] as const,
          ["词组", phrases] as const,
        ].map(([label, list]) =>
          list.length ? (
            <div key={label} className="mb-2">
              <div className="mb-1 text-[11px] text-ink3">{label}</div>
              <ul className="flex flex-col gap-1.5">
                {list.map((e) => (
                  <li
                    key={e.word}
                    className="group rounded-lg bg-panel2 px-3 py-2 text-[13px]"
                  >
                    <div className="flex items-center gap-2">
                      <b className="text-ink">{e.word}</b>
                      {e.phonetic && (
                        <span className="text-[11px] text-ink3">
                          /{e.phonetic}/
                        </span>
                      )}
                      <button
                        className="invisible ml-auto text-ink3 hover:text-ink group-hover:visible"
                        aria-label={`移除 ${e.word}`}
                        onClick={() => run(acts.removeWord(e.word), "已移除")}
                      >
                        ✕
                      </button>
                    </div>
                    {e.line && (
                      <p className="mt-0.5 truncate text-[12px] text-ink3">
                        {e.line}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
        {!words.length && !phrases.length && (
          <p className="text-[12.5px] text-ink3">
            双击歌词里的单词 → 生词卡 → 收藏，单词会跟随这首歌
          </p>
        )}
      </Fold>

      <Fold k="⚙️ 歌曲工具">
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-[11px] text-ink3">
              歌词时间校准（毫秒，正=歌词提前）
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  acts.saveOffset(parseInt(offset || "0", 10) || 0),
                  "偏移已保存",
                );
              }}
            >
              <input
                name="offset-ms"
                inputMode="numeric"
                value={offset}
                onChange={(e) => setOffset(e.target.value)}
                placeholder={String(song?.audio_offset_ms ?? 0)}
                className={inputCls}
              />
              <Chip primary type="submit">
                保存
              </Chip>
            </form>
          </div>
          <div>
            <div className="mb-1 text-[11px] text-ink3">
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
    </aside>
  );
}
