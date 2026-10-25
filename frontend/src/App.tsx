import { useEffect, useMemo, useRef } from "react";
import { audioUrl, useLyrics, useSongs } from "./api";
import { usePlayer } from "./store";
import Dock from "./components/Dock";
import LyricsView from "./components/LyricsView";
import MvPanel from "./components/MvPanel";
import PlayerBar from "./components/PlayerBar";
import Sidebar from "./components/Sidebar";

export default function App() {
  const { data: songs = [], isLoading } = useSongs();
  const {
    songId, setSong, setPlaying, setTime, setCurrentLine, currentLine,
  } = usePlayer();
  const audioRef = useRef<HTMLAudioElement>(null);

  // 首次加载：默认选第一首（黄金路径）
  useEffect(() => {
    if (!songId && songs.length) setSong(songs[0].id);
  }, [songId, songs, setSong]);

  const song = useMemo(() => songs.find((s) => s.id === songId), [songs, songId]);
  const { data: lyrics } = useLyrics(songId);

  // HTML5 Audio → 歌词同步（含 audio_offset_ms 试听片段对齐 + A-B 循环）
  useEffect(() => {
    const a = audioRef.current;
    if (!a || !lyrics || !song) return;
    const lines = lyrics.timed_lines;
    const onTime = () => {
      const t = a.currentTime * 1000 + song.audio_offset_ms;
      setTime(t, (a.duration || 0) * 1000 + song.audio_offset_ms);
      // A-B 循环（PlayerBar 经 rail dataset 传递区间）
      const rail = document.querySelector<HTMLElement>("[data-a]");
      const A = rail?.dataset.a ? Number(rail.dataset.a) : NaN;
      const B = rail?.dataset.b ? Number(rail.dataset.b) : NaN;
      if (!Number.isNaN(A) && !Number.isNaN(B) && t > B) {
        a.currentTime = (A - song.audio_offset_ms) / 1000;
        return;
      }
      let i = -1;
      for (let k = 0; k < lines.length; k++) {
        if (lines[k].timestamp_ms <= t) i = k;
        else break;
      }
      if (i !== currentLine) setCurrentLine(i);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
    };
  }, [lyrics, song, currentLine, setTime, setCurrentLine, setPlaying]);

  return (
    <div className="grid h-screen grid-cols-[232px_1fr_320px] grid-rows-[1fr_88px] overflow-hidden bg-bg font-sans text-ink">
      <Sidebar songs={songs} />
      <main className="relative overflow-hidden [background:radial-gradient(90%_70%_at_50%_-10%,#2e4639_0%,#1a2420_45%,#121212_100%)]">
        <div className="flex h-full flex-col items-center gap-5 px-12 pb-3 pt-7">
          {song && <MvPanel song={song} />}
          {lyrics ? (
            <LyricsView lyrics={lyrics} />
          ) : (
            <p className="flex flex-1 items-center text-sm text-ink3">
              {isLoading ? "加载曲库中…" : "曲库为空：先用旧版界面或 CLI 添加歌曲"}
            </p>
          )}
        </div>
      </main>
      <Dock lyrics={lyrics} />
      <div className="col-span-3">
        <PlayerBar song={song} songs={songs} audioRef={audioRef} />
      </div>
      {song && song.audio_type !== "none" && (
        <audio ref={audioRef} src={audioUrl(song.id)} preload="metadata" />
      )}
    </div>
  );
}
