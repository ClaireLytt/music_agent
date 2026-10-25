import { Song } from "../api";
import { usePlayer } from "../store";

export default function MvPanel({ song }: { song: Song }) {
  const { showMv, toggleMv } = usePlayer();
  if (!song.bvid) return null;
  if (!showMv)
    return (
      <button
        onClick={toggleMv}
        className="flex-none rounded-full bg-panel px-4 py-1.5 text-xs text-ink2 transition-colors hover:text-ink"
      >
        展开 MV ⌄
      </button>
    );
  return (
    <section aria-label="MV 视频" className="w-full max-w-[680px] flex-none">
      <div className="mb-1.5 flex items-center gap-2.5 px-1">
        <span className="text-[11px] font-semibold tracking-[0.08em] text-ink2">
          B 站 MV · 官方嵌入
        </span>
        <span className="text-[11px] text-ink3">
          视频不驱动歌词 · 同步依赖本地音频
        </span>
        <button
          onClick={toggleMv}
          className="ml-auto rounded-full bg-panel px-2.5 py-1 text-xs text-ink2 transition-colors hover:text-ink"
        >
          收起 ⌃
        </button>
      </div>
      <div className="relative aspect-video overflow-hidden rounded-card shadow-mv">
        <iframe
          title={`${song.title} MV`}
          src={`//player.bilibili.com/player.html?bvid=${song.bvid}&autoplay=0&danmaku=0`}
          className="absolute inset-0 h-full w-full border-0"
          allowFullScreen
        />
      </div>
    </section>
  );
}
