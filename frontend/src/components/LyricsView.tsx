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
  const { timeMs, currentLine, pickedLine, pickLine, requestSeek, follow } =
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
      className="lyrics-mask min-h-0 w-full max-w-[680px] flex-1"
      contentClassName="scroll-smooth"
    >
      <ol className="flex flex-col gap-1.5 px-2 pb-28 pt-7 text-center">
        {lyrics.timed_lines.map((l, i) => {
          const cur = i === currentLine;
          const near = Math.abs(i - currentLine) === 1;
          const picked = i === pickedLine;
          return (
            <li
              key={i}
              ref={cur ? curRef : picked ? pickedRef : undefined}
              data-line={i}
              onClick={() => {
                pickLine(picked ? null : i);
                // 点句即跳播；MV 跟随中 = 重对齐本地时钟
                if (hasAudio || follow) requestSeek(l.timestamp_ms);
              }}
              className={`lyric-line cursor-pointer rounded-[10px] px-3 py-[7px] leading-[1.55] transition-colors ${
                cur
                  ? "text-[26px] font-bold text-[#f7f2e8]"
                  : near
                    ? "text-[19px] font-medium text-[#beb8a8] hover:bg-white/5"
                    : "text-[19px] font-medium text-[#8f8a7c] hover:bg-white/5 hover:text-[#beb8a8]"
              } ${picked && !cur ? "bg-[#f0c36a]/15" : ""}`}
            >
              {cur ? (
                <span className="karaoke" style={{ "--p": `${p}%` } as React.CSSProperties}>
                  {l.text}
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
