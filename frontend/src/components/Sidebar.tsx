import { useMemo, useState } from "react";
import { NavLink } from "react-router-dom";
import { Song } from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";
import {
  IconBook, IconExplore, IconGear, IconLibrary, IconNote, IconPlayNav,
} from "../icons";

const SORTS = [
  { key: "added", label: "最新添加" },
  { key: "title", label: "歌名 A-Z" },
  { key: "artist", label: "歌手" },
] as const;
type SortKey = (typeof SORTS)[number]["key"];

const SORT_STORE = "ll_sidebar_sort";
const loadSort = (): SortKey => {
  try {
    const v = localStorage.getItem(SORT_STORE);
    return SORTS.some((s) => s.key === v) ? (v as SortKey) : "added";
  } catch {
    return "added";
  }
};

function sortSongs(songs: Song[], key: SortKey): Song[] {
  const out = [...songs];
  if (key === "added") out.sort((a, b) => b.added_ts - a.added_ts);
  else if (key === "title")
    out.sort((a, b) => a.title.localeCompare(b.title, "en"));
  else
    out.sort((a, b) =>
      a.artist.localeCompare(b.artist, "en") ||
      a.title.localeCompare(b.title, "en"));
  return out;
}

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
  const [sort, setSort] = useState<SortKey>(loadSort);
  const sorted = useMemo(() => sortSongs(songs, sort), [songs, sort]);
  const cycleSort = () => {
    const i = SORTS.findIndex((s) => s.key === sort);
    const next = SORTS[(i + 1) % SORTS.length].key;
    setSort(next);
    try {
      localStorage.setItem(SORT_STORE, next);
    } catch {
      /* 隐私模式下不持久化 */
    }
  };
  return (
    <aside className="bg-deep flex h-full min-h-0 flex-col gap-3 px-3 py-4">
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
                `flex items-center gap-3 rounded-lg px-2.5 py-[6px] text-left text-[24.3px] font-medium transition-colors ${
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
              className="flex items-center gap-3 rounded-lg px-2.5 py-[6px] text-left text-[24.3px] font-medium text-ink2 transition-colors hover:bg-[#1b1b1f] hover:text-ink"
            >
              {n.icon}
              {n.label}
            </button>
          ),
        )}
      </nav>
      <div className="flex items-baseline px-2.5">
        <span className="text-[19.8px] font-semibold tracking-[0.12em] text-ink3">
          曲库
        </span>
        <button
          onClick={cycleSort}
          aria-label="切换排序方式"
          title="点击切换排序"
          className="ml-auto flex items-center gap-1 rounded-full border border-edge2 px-2.5 py-0.5 text-[16.5px] text-ink3 transition-colors hover:border-accent hover:text-accent"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M5 3v10M5 13l-2.5-2.5M5 13l2.5-2.5M11 13V3M11 3L8.5 5.5M11 3l2.5 2.5" />
          </svg>
          {SORTS.find((s) => s.key === sort)?.label}
        </button>
      </div>
      <input
        type="search"
        name="library-search"
        autoComplete="off"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder="搜歌名 / 歌手 / 歌词…"
        aria-label="搜索曲库"
        className="mx-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[22.5px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
      />
      <Scrollable className="min-h-0" contentClassName="flex flex-col gap-0.5">
        {sorted.length === 0 && query && (
          <p className="px-2.5 py-2 text-[21.6px] text-ink3">
            没有匹配「{query}」的歌曲
          </p>
        )}
        {sorted.map((s) => (
          <button
            key={s.id}
            aria-current={s.id === songId || undefined}
            onClick={() => setSong(s.id)}
            className={`flex min-w-0 items-baseline gap-2 rounded-lg px-2.5 py-[7px] text-left transition-colors ${
              s.id === songId ? "bg-accent-soft" : "hover:bg-[#1b1b1f]"
            }`}
          >
            <span
              className={`truncate text-[22.5px] font-medium ${
                s.id === songId ? "text-accent" : "text-ink2"
              }`}
            >
              {s.title}
            </span>
            <span className="flex-none truncate text-[16.5px] text-ink3">
              {s.artist}
            </span>
          </button>
        ))}
      </Scrollable>
    </aside>
  );
}
