import { useEffect, useMemo, useRef, useState } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { audioUrl, useLyrics, useSongs } from "./api";
import { usePlayer } from "./store";
import DictPops from "./components/DictPops";
import Dock from "./components/Dock";
import LyricsView from "./components/LyricsView";
import MvPanel from "./components/MvPanel";
import PlayerBar from "./components/PlayerBar";
import Sidebar from "./components/Sidebar";
import WordsPage from "./pages/WordsPage";
import ExplorePage from "./pages/ExplorePage";
import LibraryPage from "./pages/LibraryPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  const [query, setQuery] = useState("");
  const { data: songs = [], isLoading } = useSongs(query);
  const {
    songId, setSong, setPlaying, setTime, setCurrentLine, currentLine,
    seekMs, clearSeek, follow, startFollow, drillReturn, setDrillReturn,
  } = usePlayer();
  const audioRef = useRef<HTMLAudioElement>(null);
  const navigate = useNavigate();

  // 侧栏宽度：拖动右缘调整，拖到很窄自动收起；双击分隔条展开/收起。
  // localStorage 只是每浏览器的便利记忆，读写都要兜底。
  const SIDEBAR_W = 420;
  const [sideW, setSideW] = useState(() => {
    try {
      const v = localStorage.getItem("ll_side_w");
      return v === null ? SIDEBAR_W : Math.max(0, Number(v) || 0);
    } catch {
      return SIDEBAR_W;
    }
  });
  const applySideW = (w: number) => {
    setSideW(w);
    try {
      localStorage.setItem("ll_side_w", String(w));
    } catch {
      /* 私密窗口等场景忽略 */
    }
  };
  const onSplitDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sideW;
    const move = (ev: PointerEvent) => {
      const w = Math.min(520, Math.max(0, startW + ev.clientX - startX));
      setSideW(w < 140 ? 0 : w); // 太窄直接吸附收起
    };
    const up = (ev: PointerEvent) => {
      const w = Math.min(520, Math.max(0, startW + ev.clientX - startX));
      applySideW(w < 140 ? 0 : w);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // 首次加载：默认进入 cardigan（没有则退回第一首）
  useEffect(() => {
    if (!songId && songs.length)
      setSong((songs.find((s) => s.id === "cardigan") ?? songs[0]).id);
  }, [songId, songs, setSong]);

  const song = useMemo(() => songs.find((s) => s.id === songId), [songs, songId]);
  const { data: lyrics } = useLyrics(songId);

  // 消费跳播请求（歌词时间轴口径 → 音频时间，扣掉试听片段偏移）。
  // MV 跟随中：点句 = 重新对齐本地时钟（漂移时点一下对应行即可拉回）
  useEffect(() => {
    if (seekMs === null) return;
    if (follow) {
      startFollow(seekMs);
      clearSeek();
      return;
    }
    const a = audioRef.current;
    if (a && song && song.audio_type !== "none") {
      a.currentTime = Math.max(0, (seekMs - song.audio_offset_ms) / 1000);
      if (a.paused) void a.play();
    }
    clearSeek();
  }, [seekMs, song, follow, startFollow, clearSeek]);

  // MV 歌词跟随：本地时钟驱动高亮（iframe 读不到进度的近似方案）
  useEffect(() => {
    if (!follow || !lyrics) return;
    audioRef.current?.pause(); // 跟随与音频二选一
    const lines = lyrics.timed_lines;
    const end = lines.length
      ? lines[lines.length - 1].timestamp_ms + 8000 : 0;
    const tick = setInterval(() => {
      const t = follow.msStart + (Date.now() - follow.wallStart);
      setTime(Math.min(t, end), end);
      let i = -1;
      for (let k = 0; k < lines.length; k++) {
        if (lines[k].timestamp_ms <= t) i = k;
        else break;
      }
      setCurrentLine(i);
    }, 250);
    return () => clearInterval(tick);
  }, [follow, lyrics, setTime, setCurrentLine]);

  // HTML5 Audio → 歌词同步（含 audio_offset_ms 试听片段对齐）
  useEffect(() => {
    const a = audioRef.current;
    if (!a || !lyrics || !song) return;
    const lines = lyrics.timed_lines;
    const onTime = () => {
      const t = a.currentTime * 1000 + song.audio_offset_ms;
      setTime(t, (a.duration || 0) * 1000 + song.audio_offset_ms);
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
    <div
      className="relative grid h-screen grid-rows-[1fr_88px] overflow-hidden bg-bg font-sans text-ink"
      style={{ gridTemplateColumns: `${sideW}px 1fr 460px` }}
    >
      <div className="min-w-0 overflow-hidden">
        <Sidebar songs={songs} query={query} onQuery={setQuery} />
      </div>
      <div
        role="separator"
        aria-label="拖动调整侧栏宽度，双击收起/展开"
        title="拖动调整侧栏；双击收起/展开"
        className="absolute bottom-[88px] top-0 z-20 w-[7px] -translate-x-1/2 cursor-col-resize after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent hover:after:bg-accent"
      style={{ left: sideW }}
        onPointerDown={onSplitDown}
        onDoubleClick={() => applySideW(sideW === 0 ? SIDEBAR_W : 0)}
      />
      {sideW === 0 && (
        <button
          aria-label="展开侧栏"
          title="展开侧栏"
          className="absolute left-2 top-2 z-20 grid h-8 w-8 place-items-center rounded-full border border-edge bg-panel text-ink2 shadow-art transition-colors hover:border-accent hover:text-ink"
          onClick={() => applySideW(SIDEBAR_W)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round"
            strokeLinejoin="round">
            <path d="M6 3l5 5-5 5" />
          </svg>
        </button>
      )}
      <Routes>
        <Route
          path="/"
          element={
            <>
              <main className="relative overflow-hidden [background:radial-gradient(90%_70%_at_50%_-10%,#2e4639_0%,#1a2420_45%,#121212_100%)]">
                {drillReturn && (
                  <button
                    className="absolute right-4 top-4 z-10 rounded-full border border-edge bg-panel px-3.5 py-1.5 text-[12.5px] font-medium text-ink2 shadow-art transition-colors hover:border-accent hover:text-accent"
                    onClick={() => {
                      const url = drillReturn;
                      setDrillReturn(null);
                      navigate(url);
                    }}
                  >
                    回到打字练习
                  </button>
                )}
                <div className="flex h-full flex-col items-center gap-5 px-12 pb-3 pt-7">
                  {song && <MvPanel song={song} />}
                  {lyrics ? (
                    <LyricsView
                      lyrics={lyrics}
                      hasAudio={!!song && song.audio_type !== "none"}
                    />
                  ) : (
                    <p className="flex flex-1 items-center text-sm text-ink3">
                      {isLoading
                        ? "加载曲库中…"
                        : "曲库为空：先用旧版界面或 CLI 添加歌曲"}
                    </p>
                  )}
                </div>
              </main>
              <Dock lyrics={lyrics} song={song} />
              <DictPops song={song} />
            </>
          }
        />
        <Route
          path="/words"
          element={
            <div className="col-span-2 min-h-0 overflow-hidden">
              <WordsPage />
            </div>
          }
        />
        <Route
          path="/words/analysis"
          element={
            <div className="col-span-2 min-h-0 overflow-hidden">
              <WordsPage analysis />
            </div>
          }
        />
        <Route
          path="/explore"
          element={
            <div className="col-span-2 min-h-0 overflow-hidden">
              <ExplorePage />
            </div>
          }
        />
        <Route
          path="/library"
          element={
            <div className="col-span-2 min-h-0 overflow-hidden">
              <LibraryPage />
            </div>
          }
        />
        <Route
          path="/settings"
          element={
            <div className="col-span-2 min-h-0 overflow-hidden">
              <SettingsPage />
            </div>
          }
        />
      </Routes>
      <div className="col-span-3">
        <PlayerBar song={song} songs={songs} audioRef={audioRef} />
      </div>
      {song && song.audio_type !== "none" && (
        <audio ref={audioRef} src={audioUrl(song.id)} preload="metadata" />
      )}
    </div>
  );
}
