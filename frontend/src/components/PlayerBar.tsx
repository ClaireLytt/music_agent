import { useRef, useState } from "react";
import { Song } from "../api";
import { usePlayer } from "../store";
import {
  IconHeart, IconNext, IconPause, IconPlay, IconPrev,
  IconRhyme, IconSkipChorus, IconVolume,
} from "../icons";

function fmt(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function PlayerBar({
  song,
  songs,
  audioRef,
}: {
  song: Song | undefined;
  songs: Song[];
  audioRef: React.RefObject<HTMLAudioElement>;
}) {
  const { songId, setSong, playing, timeMs, durationMs } = usePlayer();
  // A-B 区间循环：第一次点设 A，第二次设 B，第三次清除
  const [ab, setAb] = useState<[number, number | null] | null>(null);
  const railRef = useRef<HTMLDivElement>(null);

  const step = (dir: 1 | -1) => {
    if (!songs.length) return;
    const i = songs.findIndex((s) => s.id === songId);
    setSong(songs[(i + dir + songs.length) % songs.length].id);
  };
  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play();
    else a.pause();
  };
  const seek = (e: React.MouseEvent) => {
    const rail = railRef.current;
    const a = audioRef.current;
    if (!rail || !a || !durationMs) return;
    const r = rail.getBoundingClientRect();
    a.currentTime = ((e.clientX - r.left) / r.width) * (durationMs / 1000);
  };
  const cycleAb = () => {
    if (!ab) setAb([timeMs, null]);
    else if (ab[1] === null) setAb(timeMs > ab[0] ? [ab[0], timeMs] : null);
    else setAb(null);
  };
  // 循环回跳由 App 的 timeupdate 读取：挂到 window 简单但脏——用 dataset 传递
  if (railRef.current) {
    railRef.current.dataset.a = ab ? String(ab[0]) : "";
    railRef.current.dataset.b = ab?.[1] != null ? String(ab[1]) : "";
  }

  const pct = durationMs ? (timeMs / durationMs) * 100 : 0;
  const abOn = !!ab;

  return (
    <footer className="grid grid-cols-[280px_1fr_280px] items-center gap-4 border-t border-line bg-deep px-5">
      <div className="flex min-w-0 items-center gap-3">
        <div className="h-[52px] w-[52px] flex-none rounded-lg bg-gradient-to-br from-[#4a6b58] to-[#22332a] shadow-art" />
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-semibold">
            {song ? song.title : "—"}
          </div>
          <div className="text-xs text-ink3">
            {song ? `${song.artist}${song.album ? ` · ${song.album}` : ""}` : ""}
          </div>
        </div>
        <button className="ml-1 text-ink2 transition-colors hover:text-ink" aria-label="收藏歌曲" disabled>
          <IconHeart />
        </button>
      </div>

      <div className="flex flex-col items-center gap-[7px] py-3">
        <div className="flex items-center gap-5">
          <button className="text-ink2 transition-colors hover:text-ink" aria-label="上一首" onClick={() => step(-1)}>
            <IconPrev />
          </button>
          <button
            className="grid h-[38px] w-[38px] place-items-center rounded-full bg-ink text-[#111] transition-transform hover:scale-105 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
            aria-label={playing ? "暂停" : "播放"}
            disabled={!song || song.audio_type === "none"}
            title={
              song && song.audio_type === "none"
                ? "请在设置中上传音频"
                : undefined
            }
            onClick={toggle}
          >
            {playing ? <IconPause /> : <IconPlay />}
          </button>
          <button className="text-ink2 transition-colors hover:text-ink" aria-label="下一首" onClick={() => step(1)}>
            <IconNext />
          </button>
          <button
            className={`text-[15px] leading-none transition-colors ${abOn ? "text-accent" : "text-ink2 hover:text-ink"}`}
            aria-label="A-B 循环"
            title={ab ? (ab[1] === null ? "再点设 B 点" : "再点清除循环") : "点击设 A 点"}
            onClick={cycleAb}
          >
            𝄆𝄇
          </button>
          <button className="text-ink2 opacity-40" aria-label="跳副歌" title="迁移中 · 暂在旧版界面" disabled>
            <IconSkipChorus />
          </button>
          <button
            className="text-ink2 transition-colors hover:text-ink"
            aria-label="静音"
            onClick={() => {
              const a = audioRef.current;
              if (a) a.muted = !a.muted;
            }}
          >
            <IconVolume />
          </button>
        </div>
        <div className="flex w-full max-w-[560px] items-center gap-2.5">
          <time className="text-[11px] tabular-nums text-ink3">{fmt(timeMs)}</time>
          <div ref={railRef} className="group relative h-1 flex-1 cursor-pointer rounded-sm bg-edge2" onClick={seek}>
            <div
              className="absolute inset-y-0 left-0 rounded-sm bg-accent group-hover:bg-[#9ab4ff]"
              style={{ width: `${pct}%` }}
            />
            {ab && durationMs > 0 && (
              <div className="absolute -top-[3px] h-2.5 w-0.5 rounded-sm bg-ink2" style={{ left: `${(ab[0] / durationMs) * 100}%` }} />
            )}
            {ab?.[1] != null && durationMs > 0 && (
              <div className="absolute -top-[3px] h-2.5 w-0.5 rounded-sm bg-ink2" style={{ left: `${(ab[1] / durationMs) * 100}%` }} />
            )}
          </div>
          <time className="text-[11px] tabular-nums text-ink3">{fmt(durationMs)}</time>
        </div>
      </div>

      <div className="flex items-center justify-end gap-4">
        {abOn && (
          <span className="rounded-full bg-accent-soft px-[11px] py-[5px] text-xs font-semibold text-accent">
            𝄆 A-B 循环{ab?.[1] == null ? "设 B 点…" : "中"} 𝄇
          </span>
        )}
        <button className="text-ink2 opacity-40" aria-label="韵脚高亮" title="迁移中 · 暂在旧版界面" disabled>
          <IconRhyme />
        </button>
      </div>
    </footer>
  );
}
