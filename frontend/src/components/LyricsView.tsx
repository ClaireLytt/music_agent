import { useEffect, useRef } from "react";
import { Lyrics } from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";

/** 卡拉OK进度：当前行已唱比例（按行时间戳线性估算） */
function karaokeP(timeMs: number, lines: Lyrics["timed_lines"], i: number) {
  if (i < 0 || i >= lines.length) return 0;
  const start = lines[i].timestamp_ms;
  const end = i + 1 < lines.length ? lines[i + 1].timestamp_ms : start + 5000;
  if (end <= start) return 0;
  return Math.min(100, Math.max(0, ((timeMs - start) / (end - start)) * 100));
}

export default function LyricsView({
  lyrics,
  hasAudio,
}: {
  lyrics: Lyrics;
  hasAudio: boolean;
}) {
  const { timeMs, currentLine, pickedLine, pickLine, requestSeek } =
    usePlayer();
  const curRef = useRef<HTMLLIElement>(null);
  const pickedRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    curRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [currentLine]);

  // 外部跳转（打字练习/收藏夹点过来）：滚到被点选的句子并闪一下高光
  useEffect(() => {
    if (pickedLine === null) return;
    pickedRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [pickedLine]);

  const p = karaokeP(timeMs, lyrics.timed_lines, currentLine);

  return (
    <Scrollable
      ariaLabel="同步歌词"
      className="lyrics-mask min-h-0 w-full max-w-[880px] flex-1"
      contentClassName="scroll-smooth"
    >
      <ol className="flex flex-col gap-1 px-4 pb-28 pt-7 text-left">
        {lyrics.timed_lines.map((l, i) => {
          const cur = i === currentLine;
          const near = Math.abs(i - currentLine) === 1;
          const picked = i === pickedLine;
          // 方案 B：当前句右侧的留白摆这句的 AI 批注摘要
          const gloss = cur ? lyrics.annotations[String(i)]?.summary : undefined;
          return (
            <li
              key={i}
              ref={cur ? curRef : picked ? pickedRef : undefined}
              data-line={i}
              onClick={() => {
                pickLine(picked ? null : i);
                // 点句即跳播
                if (hasAudio) requestSeek(l.timestamp_ms);
              }}
              className={`lyric-line cursor-pointer rounded-[10px] px-3 py-[7px] leading-[1.45] transition-colors ${
                cur
                  ? "my-1.5 text-[34px] font-extrabold tracking-[-.01em] text-[#f7f2e8]"
                  : near
                    ? "text-[23px] font-medium text-[#d8d2c2] hover:bg-white/5"
                    : "text-[23px] font-medium text-[#a39d8e] hover:bg-white/5 hover:text-[#d8d2c2]"
              } ${picked && !cur ? "bg-[#f0c36a]/15" : ""}`}
            >
              {cur ? (
                <span className="flex items-center gap-6">
                  <span
                    className="karaoke max-w-[56%] flex-none"
                    style={{ "--p": `${p}%` } as React.CSSProperties}
                  >
                    {l.text}
                  </span>
                  {gloss && (
                    <span
                      key={i} /* 换句重放进场动画 */
                      className="min-w-0 flex-1 animate-dropin border-l-2 border-accent pl-4 text-[14.5px] font-normal leading-[1.7] tracking-normal text-ink2"
                    >
                      <span className="mb-0.5 block text-[12px] font-semibold tracking-[.08em] text-accent">
                        AI 批注
                      </span>
                      {gloss}
                    </span>
                  )}
                </span>
              ) : (
                l.text
              )}
            </li>
          );
        })}
      </ol>
    </Scrollable>
  );
}
