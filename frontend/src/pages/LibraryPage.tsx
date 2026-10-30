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
  // 热门歌曲候选/歌手/专辑建议：用不带筛选的完整内置曲库
  const fullCatalog = useCatalog("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState("");
  // 手动添加
  const [title, setTitle] = useState("");
  const [mp3, setMp3] = useState<File | null>(null);
  const mp3Ref = useRef<HTMLInputElement>(null);
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

  const catRows = fullCatalog.data ?? [];
  const artistOptions = [...new Set([
    ...catRows.map((r) => r.artist),
    ...songs.map((sg) => sg.artist),
  ])].filter(Boolean).sort();
  const albumOptions = [...new Set([
    ...catRows
      .filter((r) => !artist.trim() || r.artist === artist.trim())
      .map((r) => r.album),
    ...songs
      .filter((sg) => !artist.trim() || sg.artist === artist.trim())
      .map((sg) => sg.album ?? ""),
  ])].filter(Boolean).sort();
  const titleOptions = [...new Set(catRows.map((r) => r.title))].sort();

  return (
    <Scrollable className="h-full min-h-0 bg-bg2" contentClassName="flex flex-col gap-5 px-10 py-6">
      <header className="flex items-center gap-3">
        <h1 className="text-[21px] font-bold tracking-wide">曲库管理</h1>
        <span className="text-[18px] text-ink3">共 {songs.length} 首歌</span>
        {status && <span className="ml-auto text-[18px] text-ink3">{status}</span>}
      </header>

      <details className="group/pick rounded-card border border-edge bg-panel p-5">
        <summary className="cursor-pointer select-none list-none text-[19.5px] font-semibold transition-colors hover:text-ink">
          <span className="mr-1.5 inline-block transition-transform group-open/pick:rotate-90">
            ▸
          </span>
          从内置曲库挑选（{rows.length} 首，其中 {addable.length} 首可添加）
        </summary>
        <div className="mb-3 mt-3 flex flex-wrap items-center gap-2">
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
      </details>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-3 text-[19.5px] font-semibold">手动添加曲库以外的歌曲</h2>
        <form
          className="flex flex-col gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            const file = mp3;
            run(
              acts.addSong(title, artist, album, lrc).then(async (r) => {
                setSong(r.id);
                let audioNote = "音频可在播放页「歌曲工具」上传";
                if (file) {
                  const fd = new FormData();
                  fd.append("file", file);
                  const res = await fetch(`/api/songs/${r.id}/audio`, {
                    method: "POST", body: fd,
                  });
                  audioNote = res.ok ? "音频已上传" : "音频上传失败，可稍后在播放页「歌曲工具」重试";
                }
                return `已添加《${title}》（${r.note}）· ${audioNote}`;
              }),
              () => {
                setTitle(""); setArtist(""); setAlbum(""); setLrc("");
                setMp3(null);
              },
            );
          }}
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <input name="add-title" required value={title} list="title-options"
              onChange={(e) => {
                const v = e.target.value;
                setTitle(v);
                // 命中热门歌曲 → 自动带出歌手/专辑（不覆盖已填内容）
                const hit = catRows.find((r) => r.title === v);
                if (hit) {
                  if (!artist.trim()) setArtist(hit.artist);
                  if (!album.trim()) setAlbum(hit.album);
                }
              }}
              placeholder="歌曲标题（必填 — 输入几个词可从热门歌曲里选）"
              className={`${inputCls} w-72`} />
            <input name="add-artist" value={artist} list="artist-options"
              onChange={(e) => setArtist(e.target.value)}
              placeholder="歌手（选填 — 可选可输入）"
              className={`${inputCls} w-56`} />
            <input name="add-album" value={album} list="album-options"
              onChange={(e) => setAlbum(e.target.value)}
              placeholder="专辑（选填 — 可选可输入）"
              className={`${inputCls} w-56`} />
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
              {lrc ? `已选歌词（${lrc.split("\n").length} 行，点击更换）` : "上传 .lrc 歌词（选填，留空自动获取）…"}
            </button>
            <datalist id="title-options">
              {titleOptions.map((t) => <option key={t} value={t} />)}
            </datalist>
            <datalist id="artist-options">
              {artistOptions.map((a) => <option key={a} value={a} />)}
            </datalist>
            <datalist id="album-options">
              {albumOptions.map((a) => <option key={a} value={a} />)}
            </datalist>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={mp3Ref}
              type="file"
              accept=".mp3,.wav,.flac,.ogg,.m4a,audio/*"
              className="hidden"
              onChange={(e) => {
                setMp3(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
            />
            <button type="button" className={chip()} onClick={() => mp3Ref.current?.click()}>
              {mp3 ? `已选音频：${mp3.name}（点击更换）` : "上传歌曲音频（mp3/wav/flac/ogg/m4a）…"}
            </button>
            <button type="submit" className={chip(true)}>
              保存歌曲
            </button>
          </div>
        </form>
      </section>

      <details className="group/manage rounded-card border border-edge bg-panel p-5">
        <summary className="cursor-pointer select-none list-none text-[19.5px] font-semibold transition-colors hover:text-ink">
          <span className="mr-1.5 inline-block transition-transform group-open/manage:rotate-90">
            ▸
          </span>
          管理列表（删除歌曲）
        </summary>
        <ul className="mt-3 grid grid-cols-2 gap-1 xl:grid-cols-3">
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
      </details>
    </Scrollable>
  );
}
