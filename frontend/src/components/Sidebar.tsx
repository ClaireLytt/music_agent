import { NavLink } from "react-router-dom";
import { Song } from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";
import {
  IconBook, IconExplore, IconGear, IconLibrary, IconNote, IconPlayNav,
} from "../icons";

const NAV = [
  { label: "播放解读", icon: <IconPlayNav />, to: "/" },
  { label: "词汇练习", icon: <IconBook />, to: "/words" },
  { label: "互动探索", icon: <IconExplore />, to: "/explore" },
  { label: "曲库管理", icon: <IconLibrary />, to: "/library" },
  { label: "设置", icon: <IconGear />, to: "/settings" },
];

export default function Sidebar({
  songs,
  query,
  onQuery,
}: {
  songs: Song[];
  query: string;
  onQuery: (q: string) => void;
}) {
  const { songId, setSong } = usePlayer();
  return (
    <aside className="bg-deep flex h-full min-h-0 flex-col gap-[18px] px-3 py-5">
      <div className="flex items-center gap-2.5 px-2.5 font-bold tracking-wide">
        <span className="grid h-[26px] w-[26px] place-items-center rounded-lg bg-gradient-to-br from-accent to-[#4a6cf7]">
          <IconNote />
        </span>
        Learn from Music
      </div>
      <nav className="flex flex-col gap-0.5" aria-label="主导航">
        {NAV.map((n) =>
          n.to ? (
            <NavLink
              key={n.label}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-2.5 py-[9px] text-left text-[16.2px] font-medium transition-colors ${
                  isActive
                    ? "bg-[#202026] text-ink"
                    : "text-ink2 hover:bg-[#1b1b1f] hover:text-ink"
                }`
              }
            >
              {n.icon}
              {n.label}
            </NavLink>
          ) : (
            <button
              key={n.label}
              title="迁移中 · 暂在旧版界面"
              className="flex items-center gap-3 rounded-lg px-2.5 py-[9px] text-left text-[16.2px] font-medium text-ink2 transition-colors hover:bg-[#1b1b1f] hover:text-ink"
            >
              {n.icon}
              {n.label}
            </button>
          ),
        )}
      </nav>
      <div className="px-2.5 text-[13.2px] font-semibold tracking-[0.12em] text-ink3">
        曲库
      </div>
      <input
        type="search"
        name="library-search"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder="搜歌名 / 歌手 / 歌词…"
        aria-label="搜索曲库"
        className="mx-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[15px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
      />
      <Scrollable className="min-h-0" contentClassName="flex flex-col gap-0.5">
        {songs.length === 0 && query && (
          <p className="px-2.5 py-2 text-[14.4px] text-ink3">
            没有匹配「{query}」的歌曲
          </p>
        )}
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
              className={`text-[16.2px] font-medium ${
                s.id === songId ? "text-accent" : "text-ink2"
              }`}
            >
              {s.title}
            </span>
            <span className="text-[13.8px] text-ink3">{s.artist}</span>
          </button>
        ))}
      </Scrollable>
    </aside>
  );
}
