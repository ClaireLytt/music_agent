import { Song } from "../api";
import { usePlayer } from "../store";
import { IconBook, IconExplore, IconLibrary, IconNote, IconPlayNav } from "../icons";

const NAV = [
  { label: "播放解读", icon: <IconPlayNav />, current: true },
  { label: "词汇练习", icon: <IconBook /> },
  { label: "互动探索", icon: <IconExplore /> },
  { label: "曲库管理", icon: <IconLibrary /> },
];

export default function Sidebar({ songs }: { songs: Song[] }) {
  const { songId, setSong } = usePlayer();
  return (
    <aside className="bg-deep flex min-h-0 flex-col gap-[18px] px-3 py-5">
      <div className="flex items-center gap-2.5 px-2.5 font-bold tracking-wide">
        <span className="grid h-[26px] w-[26px] place-items-center rounded-lg bg-gradient-to-br from-accent to-[#4a6cf7]">
          <IconNote />
        </span>
        歌词透镜
      </div>
      <nav className="flex flex-col gap-0.5" aria-label="主导航">
        {NAV.map((n) => (
          <button
            key={n.label}
            aria-current={n.current ? "page" : undefined}
            title={n.current ? undefined : "迁移中 · 暂在旧版界面"}
            className={`flex items-center gap-3 rounded-lg px-2.5 py-[9px] text-left text-[13.5px] font-medium transition-colors ${
              n.current
                ? "bg-[#202026] text-ink"
                : "text-ink2 hover:bg-[#1b1b1f] hover:text-ink"
            }`}
          >
            {n.icon}
            {n.label}
          </button>
        ))}
      </nav>
      <div className="px-2.5 text-[11px] font-semibold tracking-[0.12em] text-ink3">
        曲库
      </div>
      <div className="flex min-h-0 flex-col gap-0.5 overflow-y-auto">
        {songs.map((s) => (
          <button
            key={s.id}
            aria-current={s.id === songId || undefined}
            onClick={() => setSong(s.id)}
            className={`flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
              s.id === songId ? "bg-accent-soft" : "hover:bg-[#1b1b1f]"
            }`}
          >
            <span
              className={`text-[13.5px] font-medium ${
                s.id === songId ? "text-accent" : "text-ink2"
              }`}
            >
              {s.title}
            </span>
            <span className="text-[11.5px] text-ink3">{s.artist}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
