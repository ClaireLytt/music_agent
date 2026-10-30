import { useRef, useState } from "react";
import { useAdminActions, useCatalog, useSongs } from "../api";
import { usePlayer } from "../store";
import Scrollable from "../components/Scrollable";

const chip = (primary = false) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[18.8px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
    primary
      ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

const inputCls =
  "rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[19.5px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";

export default function LibraryPage() {
  const acts = useAdminActions();
  const { data: songs = [] } = useSongs();
  const { songId, setSong } = usePlayer();
  const [q, setQ] = useState("");
  const catalog = useCatalog(q);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState("");
  // 手动添加
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [lrc, setLrc] = useState("");
  const lrcFileRef = useRef<HTMLInputElement>(null);

  const rows = catalog.data ?? [];
  const addable = rows.filter((r) => !r.in_library);
  const label = (r: { title: string; artist: string }) => `${r.title} — ${r.artist}`;

  const toggle = (v: string) =>
    setChecked((s) => {
      const n = new Set(s);
      if (n.has(v)) n.delete(v);
      else n.add(v);
      return n;
    });

  const run = (p: Promise<string>, after?: () => void) =>
    p.then((msg) => {
      setStatus(msg);
      after?.();
    }).catch((e) => setStatus(e instanceof Error ? e.message : "操作失败"));

  return (
    <Scrollable className="h-full min-h-0 bg-bg2" contentClassName="flex flex-col gap-5 px-10 py-6">
      <header className="flex items-center gap-3">
        <h1 className="text-[21px] font-bold tracking-wide">曲库管理</h1>
        <span className="text-[18px] text-ink3">共 {songs.length} 首歌</span>
        {status && <span className="ml-auto text-[18px] text-ink3">{status}</span>}
      </header>

      <section className="rounded-card border border-edge bg-panel p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-[19.5px] font-semibold">
            从内置曲库挑选（{rows.length} 首，其中 {addable.length} 首可添加）
          </h2>
          <input
            name="catalog-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索曲库（歌名 / 歌手 / 专辑）"
            className={`${inputCls} ml-auto w-64`}
          />
          <button
            className={chip()}
            disabled={!addable.length}
            title={addable.length ? undefined : "全部歌曲都已在曲库，没有可勾选的"}
            onClick={() => setChecked(new Set(addable.map(label)))}
          >
            全选
          </button>
          <button
            className={chip()}
            disabled={!checked.size}
            onClick={() => setChecked(new Set())}
          >
            取消全选
          </button>
          <button
            className={chip(true)}
            disabled={![...checked].some((v) => addable.some((r) => label(r) === v))}
            onClick={() =>
              run(
                acts
                  .addFromCatalog([...checked].filter((v) =>
                    addable.some((r) => label(r) === v),
                  ))
                  .then((r) => {
                    const parts = [];
                    if (r.added.length)
                      parts.push(`新增 ${r.added.length} 首:《${r.added.slice(0, 8).join("》《")}》${r.added.length > 8 ? "…" : ""}`);
                    if (r.existed.length) parts.push(`${r.existed.length} 首已在列表`);
                    if (r.missing.length) parts.push(`${r.missing.length} 首未找到`);
                    return parts.join("　") || "没有可添加的歌";
                  }),
                () => setChecked(new Set()),
              )
            }
          >
            添加勾选的歌曲
          </button>
        </div>
        <Scrollable className="max-h-80" contentClassName="grid grid-cols-2 gap-1 xl:grid-cols-3">
          {rows.map((r) => {
            const v = label(r);
            return (
              <label
                key={v}
                className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-[19.5px] ${
                  r.in_library ? "cursor-default text-ink3" : "text-ink2 hover:bg-panel2"
                }`}
              >
                {r.in_library ? (
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                    strokeLinejoin="round" className="flex-none">
                    <path d="M3 8.5l3.2 3L13 4.5" />
                  </svg>
                ) : (
                  <input
                    type="checkbox"
                    checked={checked.has(v)}
                    onChange={() => toggle(v)}
                    className="accent-[#7c9eff]"
                  />
                )}
                <span className="truncate">{v}</span>
                {r.in_library && <span className="ml-auto flex-none text-[16.5px]">已在列表</span>}
              </label>
            );
          })}
        </Scrollable>
      </section>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-3 text-[19.5px] font-semibold">手动添加曲库以外的歌曲</h2>
        <form
          className="flex flex-col gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            run(
              acts.addSong(title, artist, album, lrc).then((r) => {
                setSong(r.id);
                return `已添加《${title}》（${r.note}）· 音频可在播放页「歌曲工具」上传`;
              }),
              () => {
                setTitle(""); setArtist(""); setAlbum(""); setLrc("");
              },
            );
          }}
        >
          <div className="flex flex-wrap gap-2.5">
            <input name="add-title" required value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="歌曲标题（必填）" className={`${inputCls} w-56`} />
            <input name="add-artist" value={artist} onChange={(e) => setArtist(e.target.value)}
              placeholder="歌手（选填）" className={`${inputCls} w-48`} />
            <input name="add-album" value={album} onChange={(e) => setAlbum(e.target.value)}
              placeholder="专辑（选填）" className={`${inputCls} w-48`} />
          </div>
          <textarea
            name="add-lrc"
            value={lrc}
            onChange={(e) => setLrc(e.target.value)}
            placeholder={"LRC 歌词（选填 — 格式如 [00:12.34] 歌词内容，留空将自动从 LRCLIB 获取）"}
            rows={6}
            className="rounded-card border border-edge2 bg-panel2 px-3.5 py-2.5 text-[19.5px] leading-6 text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
          />
          <div className="flex items-center gap-2">
            <input
              ref={lrcFileRef}
              type="file"
              accept=".lrc,.txt"
              className="hidden"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setLrc(await f.text());
                e.target.value = "";
              }}
            />
            <button type="button" className={chip()} onClick={() => lrcFileRef.current?.click()}>
              或上传 .lrc 文件…
            </button>
            <button type="submit" className={chip(true)}>
              保存歌曲
            </button>
          </div>
        </form>
      </section>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-3 text-[19.5px] font-semibold">管理列表（删除歌曲）</h2>
        <ul className="grid grid-cols-2 gap-1 xl:grid-cols-3">
          {songs.map((s) => (
            <li
              key={s.id}
              className={`group flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[19.5px] ${
                s.id === songId ? "bg-accent-soft" : "hover:bg-panel2"
              }`}
            >
              <span className="truncate text-ink2">
                {s.title} — {s.artist}
              </span>
              <button
                className="invisible ml-auto flex-none text-ink3 hover:text-ink group-hover:visible"
                aria-label={`删除 ${s.title}`}
                onClick={() => {
                  if (window.confirm(`确定删除《${s.title}》？歌词、批注、音频将一并删除。`))
                    run(acts.deleteSong(s.id).then(() => `已删除《${s.title}》`));
                }}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </section>
    </Scrollable>
  );
}
