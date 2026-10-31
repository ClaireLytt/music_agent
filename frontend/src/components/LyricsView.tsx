import { useEffect, useRef } from "react";
import { Lyrics } from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";

/** 英文按元音簇、CJK 按字估算音节数（快歌慢歌的行内配速依据） */
function syllables(token: string) {
  if (/[぀-ヿ一-鿿]/.test(token)) return token.length;
  return (token.toLowerCase().match(/[aeiouy]+/g) ?? [""]).length || 1;
}

/** 卡拉OK进度（0-100，按文本字符位置计）。
 *  词级时间轴（Enhanced LRC）→ 逐字精确；
 *  行级 → 行内按音节加权插值（替代旧的匀速线性，快词慢词不再一个速度）。 */
function karaokeP(timeMs: number, lines: Lyrics["timed_lines"], i: number) {
  if (i < 0 || i >= lines.length) return 0;
  const line = lines[i];
  const start = line.timestamp_ms;
  const end = i + 1 < lines.length ? lines[i + 1].timestamp_ms : start + 5000;
  if (end <= start) return 0;

  // 真词级：当前词之前的字符全亮，当前词内部按词时长线性推进
  if (line.words && line.words.length > 1) {
    const total = line.words.reduce((n, [, w]) => n + w.length, 0);
    let chars = 0;
    for (let k = 0; k < line.words.length; k++) {
      const [ws, w] = line.words[k];
      const we = k + 1 < line.words.length ? line.words[k + 1][0] : end;
      if (timeMs < ws) break;
      if (timeMs < we) {
        const inWord = (timeMs - ws) / Math.max(1, we - ws);
        return Math.min(100, ((chars + w.length * inWord) / total) * 100);
      }
      chars += w.length;
    }
    return timeMs >= line.words[line.words.length - 1][0] ? 100 : 0;
  }

  // 行级：音节加权——把"行内已过时间比例"映射到字符位置
  const f = Math.min(1, Math.max(0, (timeMs - start) / (end - start)));
  const tokens = line.text.split(/(\s+)/).filter((t) => t.length);
  const weights = tokens.map((t) => (/^\s+$/.test(t) ? 0.3 : syllables(t)));
  const totalW = weights.reduce((a, b) => a + b, 0);
  const totalChars = line.text.length;
  let acc = 0;
  let chars = 0;
  for (let k = 0; k < tokens.length; k++) {
    const next = acc + weights[k];
    if (f * totalW <= next) {
      const inTok = (f * totalW - acc) / Math.max(1e-6, weights[k]);
      return Math.min(100, ((chars + tokens[k].length * inTok) / totalChars) * 100);
    }
    acc = next;
    chars += tokens[k].length;
  }
  return 100;
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
                <span className="flex flex-wrap items-center gap-x-6 gap-y-2">
                  {/* karaoke 必须是 inline：块级盒的水平渐变会让折行的
                      每一行同步点亮；inline 默认 slice，渐变跨行连续推进 */}
                  <span className="max-w-full flex-none">
                    <span
                      className="karaoke"
                      style={{ "--p": `${p}%` } as React.CSSProperties}
                    >
                      {l.text}
                    </span>
                  </span>
                  {gloss && (
                    <span
                      key={i} /* 换句重放进场动画 */
                      className="min-w-[240px] flex-1 animate-dropin border-l-2 border-accent pl-4 text-[14.5px] font-normal leading-[1.7] tracking-normal text-ink2"
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
