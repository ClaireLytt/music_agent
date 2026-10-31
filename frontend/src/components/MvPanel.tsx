import { useState } from "react";
import { MvCandidate, Song, useActions } from "../api";
import { usePlayer } from "../store";
import Scrollable from "./Scrollable";

const chip =
  "rounded-full bg-panel px-3 py-1 text-xs text-ink2 transition-colors hover:text-ink";

const fmtPlay = (n: number) =>
  n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n);

export default function MvPanel({ song }: { song: Song }) {
  const { showMv, toggleMv } = usePlayer();
  const { saveBvid, searchMv } = useActions(song.id, song.title);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState("");
  const [cands, setCands] = useState<MvCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);

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

  const search = async () => {
    setSearching(true);
    setMsg("");
    try {
      const r = await searchMv();
      setCands(r);
      if (!r.length) setMsg("B 站搜索暂不可用，可手动粘 BV 号");
    } catch {
      setMsg("B 站搜索暂不可用，可手动粘 BV 号");
    } finally {
      setSearching(false);
    }
  };

  const pick = async (bvid: string) => {
    try {
      await saveBvid(bvid);
      setCands(null);
      setMsg(`已绑定 ${bvid}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "绑定失败");
    }
  };

  const candList = cands && cands.length > 0 && (
    <Scrollable className="mb-1.5 rounded-card border border-edge2 bg-panel2" contentClassName="max-h-48">
    <ul>
      {cands.map((c) => (
        <li key={c.bvid}>
          <button
            onClick={() => void pick(c.bvid)}
            className="flex w-full items-baseline gap-2 px-3.5 py-2 text-left text-xs transition-colors hover:bg-panel"
          >
            <span className="min-w-0 flex-1 truncate text-ink">{c.title}</span>
            <span className="flex-none text-ink3">{c.author}</span>
            <span className="flex-none text-ink3">{c.duration}</span>
            <span className="flex-none text-ink3">{fmtPlay(c.play)}播放</span>
          </button>
        </li>
      ))}
    </ul>
    </Scrollable>
  );

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
        autoComplete="off"
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
          <button onClick={() => void search()} disabled={searching} className={chip}>
            {searching ? "搜索中…" : "搜索 MV"}
          </button>
          {msg && <span className="text-xs text-ink3">{msg}</span>}
        </div>
        {bindForm && <div className="mt-2">{bindForm}</div>}
        {candList && <div className="mt-2">{candList}</div>}
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
        <button onClick={() => void search()} disabled={searching} className={chip}>
          {searching ? "搜索中…" : "搜索 MV"}
        </button>
        {msg && <span className="text-xs text-ink3">{msg}</span>}
      </div>
      {bindForm}
      {candList}
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
