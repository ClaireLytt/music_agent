import { useEffect, useRef, useState } from "react";
import { Song } from "../api";
import { usePlayer } from "../store";
import {
  IconNext, IconPause, IconPlay, IconPrev, IconVolume,
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
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  // >0 时显示"无音频"气泡；自增让摇头动画每次点击都重放
  const [hintTick, setHintTick] = useState(0);
  const hintTimer = useRef<number>();
  useEffect(() => () => window.clearTimeout(hintTimer.current), []);
  const railRef = useRef<HTMLDivElement>(null);

  const step = (dir: 1 | -1) => {
    if (!songs.length) return;
    const i = songs.findIndex((s) => s.id === songId);
    setSong(songs[(i + dir + songs.length) % songs.length].id);
  };
  const noAudio = !song || song.audio_type === "none";
  const toggle = () => {
    if (noAudio) {
      // 没有音频：摇头 + 气泡说明原因，3 秒后收起（重复点击重新计时）
      setHintTick((t) => t + 1);
      window.clearTimeout(hintTimer.current);
      hintTimer.current = window.setTimeout(() => setHintTick(0), 3000);
      return;
    }
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
  const onVolume = (v: number) => {
    setVolume(v);
    setMuted(v === 0);
    const a = audioRef.current;
    if (a) {
      a.volume = v;
      a.muted = v === 0;
    }
  };
  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    const a = audioRef.current;
    if (a) a.muted = next;
  };

  const pct = durationMs ? (timeMs / durationMs) * 100 : 0;

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
      </div>

      <div className="flex flex-col items-center gap-[7px] py-3">
        {/* prev/play/next 对称排列 → 播放键正对进度条中点 */}
        <div className="flex items-center gap-5">
          <button className="text-ink2 transition-colors hover:text-ink" aria-label="上一首" onClick={() => step(-1)}>
            <IconPrev />
          </button>
          <div className="relative">
            <button
              key={hintTick} /* remount 让摇头动画每次都重放 */
              className={`grid h-[38px] w-[38px] place-items-center rounded-full bg-ink text-[#111] transition-transform hover:scale-105 ${
                noAudio ? "opacity-40" : ""
              } ${hintTick > 0 ? "animate-headshake" : ""}`}
              aria-label={playing ? "暂停" : "播放"}
              onClick={toggle}
            >
              {playing ? <IconPause /> : <IconPlay />}
            </button>
            {hintTick > 0 && (
              <div
                role="status"
                className="absolute bottom-[calc(100%+12px)] left-1/2 w-max max-w-[260px] -translate-x-1/2 animate-popin rounded-[10px] border border-edge bg-panel2 px-3.5 py-2.5 text-left text-[13px] leading-normal shadow-pop after:absolute after:left-1/2 after:top-full after:-ml-[5px] after:border-[5px] after:border-transparent after:border-t-panel2"
              >
                <b className="mb-0.5 block font-semibold text-ink">
                  这首歌还没有音频
                </b>
                <span className="text-ink2">上传音频文件后即可播放。</span>
                <button
                  className="whitespace-nowrap font-medium text-accent hover:underline"
                  onClick={() => {
                    setHintTick(0);
                    window.dispatchEvent(new Event("ll-open-song-tools"));
                  }}
                >
                  去歌曲工具上传 →
                </button>
              </div>
            )}
          </div>
          <button className="text-ink2 transition-colors hover:text-ink" aria-label="下一首" onClick={() => step(1)}>
            <IconNext />
          </button>
          <div className="ml-3 flex items-center gap-2">
          <button
            className={`transition-colors hover:text-ink ${muted ? "text-ink3" : "text-ink2"}`}
            aria-label={muted ? "取消静音" : "静音"}
            onClick={toggleMute}
          >
            <IconVolume />
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            aria-label="音量"
            onChange={(e) => onVolume(Number(e.target.value))}
            className="h-1 w-24 cursor-pointer accent-accent"
          />
          </div>
        </div>
        <div className="flex w-full max-w-[560px] items-center gap-2.5">
          <time className="text-[11px] tabular-nums text-ink3">{fmt(timeMs)}</time>
          <div ref={railRef} className="group relative h-1 flex-1 cursor-pointer rounded-sm bg-edge2" onClick={seek}>
            <div
              className="absolute inset-y-0 left-0 rounded-sm bg-accent group-hover:bg-[#9ab4ff]"
              style={{ width: `${pct}%` }}
            />
          </div>
          <time className="text-[11px] tabular-nums text-ink3">{fmt(durationMs)}</time>
        </div>
      </div>

      <div />
    </footer>
  );
}
