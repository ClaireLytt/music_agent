import { useState } from "react";
import { Song, useActions } from "../api";
import { usePlayer } from "../store";

const chip =
  "rounded-full bg-panel px-3 py-1 text-xs text-ink2 transition-colors hover:text-ink";

export default function MvPanel({ song }: { song: Song }) {
  const { showMv, toggleMv, follow, startFollow, stopFollow } = usePlayer();
  const { saveBvid } = useActions(song.id, song.title);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState("");

  const save = async () => {
    try {
      await saveBvid(value);
      setMsg(value.trim() ? "已绑定新视频" : "已解绑视频");
      setEditing(false);
      setValue("");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "保存失败");
    }
  };

  const bindForm = editing && (
    <form
      className="mb-1.5 flex items-center gap-2 px-1"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <input
        autoFocus
        name="bvid"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="粘贴 BV 号或 B 站链接，留空保存=解绑"
        className="min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-1.5 text-xs text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
      />
      <button type="submit" className={chip}>
        保存
      </button>
      <button type="button" className={chip} onClick={() => setEditing(false)}>
        取消
      </button>
    </form>
  );

  if (!showMv)
    return (
      <div className="flex w-full max-w-[680px] flex-none flex-col">
        <div className="flex items-center justify-center gap-2">
          {song.bvid && (
            <button onClick={toggleMv} className={chip}>
              展开 MV
            </button>
          )}
          <button onClick={() => setEditing((v) => !v)} className={chip}>
            换一个视频
          </button>
          {msg && <span className="text-xs text-ink3">{msg}</span>}
        </div>
        {bindForm && <div className="mt-2">{bindForm}</div>}
      </div>
    );

  return (
    <section aria-label="MV 视频" className="w-full max-w-[680px] flex-none">
      <div className="mb-1.5 flex items-center gap-2 px-1">
        <button onClick={toggleMv} className={chip}>
          收起 MV
        </button>
        <button onClick={() => setEditing((v) => !v)} className={chip}>
          换一个视频
        </button>
        <button
          onClick={() => (follow ? stopFollow() : startFollow(0))}
          title={
            follow
              ? "停止本地时钟驱动的歌词高亮"
              : "让 MV 从头播放的同时点此按钮，歌词随本地时钟跟着走；漂移时点任意歌词行重对齐"
          }
          className={`rounded-full px-3 py-1 text-xs transition-colors ${
            follow
              ? "bg-accent font-semibold text-[#0e1016]"
              : "bg-panel text-ink2 hover:text-ink"
          }`}
        >
          {follow ? "跟随中 · 点歌词行可重对齐" : "歌词跟随（与 MV 同点开始）"}
        </button>
        {msg && <span className="text-xs text-ink3">{msg}</span>}
      </div>
      {bindForm}
      {song.bvid && (
        <div className="relative aspect-video overflow-hidden rounded-card shadow-mv">
          <iframe
            title={`${song.title} MV`}
            src={`//player.bilibili.com/player.html?bvid=${song.bvid}&autoplay=0&danmaku=0`}
            className="absolute inset-0 h-full w-full border-0"
            allowFullScreen
          />
        </div>
      )}
    </section>
  );
}
