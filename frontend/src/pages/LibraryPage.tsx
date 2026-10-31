import { useRef, useState } from "react";
import { useAdminActions, useCatalog, useSongs } from "../api";
import { usePlayer } from "../store";
import { SaveLabel, useSavePhase } from "../components/save";
import Scrollable from "../components/Scrollable";

const chip = (primary = false) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[18.8px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
    primary
      ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

const inputCls =
  "rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[19.5px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";


/** 匹配字高亮（搜索框与自动补全共用）。 */
function Mark({ text, q }: { text: string; q: string }) {
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0 || !q) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <span className="font-bold text-accent">{text.slice(i, i + q.length)}</span>
      {text.slice(i + q.length)}
    </>
  );
}

const HISTORY_KEY = "ll_catalog_search_history";
const loadHistory = (): string[] => {
  try {
    const v = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
};
const saveHistory = (h: string[]) => {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h));
  } catch {
    /* 隐私模式等场景拿不到 localStorage，历史只活在本次会话 */
  }
};

const IconSearch = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
       stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" />
  </svg>
);
const IconClock = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
       stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
    <circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.3 1.6" />
  </svg>
);
const IconNoteSm = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
       stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
    <path d="M5.5 13V3.8l7-1.3v8.9" />
    <circle cx="3.9" cy="13" r="1.7" /><circle cx="10.9" cy="11.4" r="1.7" />
  </svg>
);
const IconX = ({ size = 12 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" fill="none"
       stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M2 2l8 8M10 2l-8 8" />
  </svg>
);

/** 曲库搜索框（原型方案 A）：聚焦出最近搜索，输入变实时过滤。 */
function SearchBox({
  value, onChange, options, placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; sub?: string }[];
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<string[]>(loadHistory);
  const q = value.trim();
  const hits = q
    ? options.filter((o) =>
        (o.label + (o.sub ?? "")).toLowerCase().includes(q.toLowerCase()))
        .slice(0, 5)
    : [];
  const commit = (v: string) => {
    onChange(v);
    const next = [v, ...history.filter((x) => x !== v)].slice(0, 5);
    setHistory(next);
    saveHistory(next);
    setOpen(false);
  };
  const dropHistory = (h: string) => {
    const next = history.filter((x) => x !== h);
    setHistory(next);
    saveHistory(next);
  };
  const rowCls =
    "flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[17px] " +
    "text-ink transition-[background-color,padding] duration-200 " +
    "hover:bg-panel2 hover:pl-[22px]";
  const showPop = open && (q ? hits.length > 0 : history.length > 0);
  return (
    <div className="relative ml-auto w-72">
      <div className="group flex items-center gap-2.5 rounded-full border border-edge2 bg-panel2 px-3.5 transition-[border-color,box-shadow] duration-300 focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgba(124,158,255,.16)]">
        <span className="flex-none text-ink3 transition-[color,transform] duration-300 group-focus-within:scale-110 group-focus-within:text-accent">
          <IconSearch />
        </span>
        <input
          value={value}
          autoComplete="off"
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent py-2 text-[19.5px] text-ink caret-accent placeholder:text-ink3 focus:outline-none"
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => { if (e.key === "Enter" && q) commit(q); }}
        />
        <button
          type="button"
          aria-label="清空搜索"
          onMouseDown={(e) => { e.preventDefault(); onChange(""); setOpen(true); }}
          className={`grid h-6 w-6 flex-none place-items-center rounded-full text-ink3 transition-[opacity,transform,color,background-color] duration-200 hover:bg-edge2 hover:text-ink ${
            value ? "scale-100 opacity-100" : "pointer-events-none scale-50 opacity-0"
          }`}
        >
          <IconX />
        </button>
      </div>
      {showPop && (
        <div className="absolute inset-x-0 top-[calc(100%+8px)] z-10 animate-dropin overflow-hidden rounded-[12px] border border-edge bg-panel shadow-[0_18px_40px_-16px_rgba(0,0,0,.8)]">
          {!q && (
            <>
              <div className="flex items-center justify-between px-3.5 pb-1 pt-2.5 text-[12px] font-semibold tracking-[.1em] text-ink3">
                <span>最近搜索</span>
                <button
                  type="button"
                  className="tracking-normal transition-colors hover:text-accent"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    setHistory([]);
                    saveHistory([]);
                  }}
                >
                  清空
                </button>
              </div>
              {history.map((h) => (
                <div key={h} className={`${rowCls} group/row cursor-pointer`}
                     onMouseDown={(e) => { e.preventDefault(); commit(h); }}>
                  <span className="flex-none text-ink3"><IconClock /></span>
                  <span className="truncate">{h}</span>
                  <button
                    type="button"
                    aria-label={`删除历史 ${h}`}
                    className="ml-auto grid h-5 w-5 flex-none place-items-center rounded-full text-ink3 opacity-0 transition-opacity hover:bg-edge2 hover:text-ink group-hover/row:opacity-100"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      dropHistory(h);
                    }}
                  >
                    <IconX size={10} />
                  </button>
                </div>
              ))}
            </>
          )}
          {q && hits.map((o) => (
            <button
              type="button"
              key={o.label + (o.sub ?? "")}
              className={rowCls}
              onMouseDown={(e) => { e.preventDefault(); commit(o.label); }}
            >
              <span className="flex-none text-ink3"><IconNoteSm /></span>
              <span className="truncate font-medium"><Mark text={o.label} q={q} /></span>
              {o.sub && (
                <span className="ml-auto flex-none text-[14px] text-ink2">{o.sub}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 自绘自动补全（替代无法改样式的原生 datalist 白框）。 */
function AutoInput({
  value, onChange, onPick, options, placeholder, required, className,
}: {
  value: string;
  onChange: (v: string) => void;
  onPick?: (label: string) => void;
  options: { label: string; sub?: string }[];
  placeholder: string;
  required?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const hits = value.trim()
    ? options.filter((o) =>
        o.label.toLowerCase().includes(value.trim().toLowerCase())).slice(0, 7)
    : [];
  return (
    <div className={`relative ${className ?? ""}`}>
      <input
        required={required}
        value={value}
        placeholder={placeholder}
        className={`${inputCls} w-full`}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && hits.length > 0 && (
        <div className="absolute inset-x-0 top-[calc(100%+6px)] z-10 animate-dropin overflow-hidden rounded-[12px] border border-edge bg-panel shadow-[0_18px_40px_-16px_rgba(0,0,0,.8)]">
          {hits.map((o) => (
            <button
              type="button"
              key={o.label + (o.sub ?? "")}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[17px] text-ink transition-[background-color,padding] duration-200 hover:bg-panel2 hover:pl-[22px]"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(o.label);
                onPick?.(o.label);
                setOpen(false);
              }}
            >
              <span className="truncate font-medium">
                <Mark text={o.label} q={value.trim()} />
              </span>
              {o.sub && (
                <span className="ml-auto flex-none text-[14px] text-ink2">{o.sub}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

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
  const { phase: addPhase, wrap: wrapAddSave } = useSavePhase();
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
          <SearchBox
            value={q}
            onChange={setQ}
            placeholder="搜索曲库（歌名 / 歌手 / 专辑）"
            options={(fullCatalog.data ?? []).map((r) => ({
              label: r.title, sub: r.artist,
            }))}
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
            void wrapAddSave(() =>
              acts.addSong(title, artist, album, lrc).then((r) => {
                setSong(r.id);
                setStatus(`已添加《${title}》（${r.note}）· `
                  + "音频可在播放页「歌曲工具」上传");
                setTitle(""); setArtist(""); setAlbum(""); setLrc("");
              }),
            ).catch((err) =>
              setStatus(err instanceof Error ? err.message : "添加失败"));
          }}
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <AutoInput
              required
              value={title}
              className="w-80"
              placeholder="歌曲标题（必填 — 输入几个词可从热门歌曲里选）"
              options={catRows.map((r) => ({ label: r.title, sub: r.artist }))}
              onChange={(v) => {
                setTitle(v);
                // 命中热门歌曲 → 自动带出歌手/专辑（不覆盖已填内容）
                const hit = catRows.find((r) => r.title === v);
                if (hit) {
                  if (!artist.trim()) setArtist(hit.artist);
                  if (!album.trim()) setAlbum(hit.album);
                }
              }}
              onPick={(v) => {
                const hit = catRows.find((r) => r.title === v);
                if (hit) { setArtist(hit.artist); setAlbum(hit.album); }
              }}
            />
            <AutoInput
              value={artist}
              className="w-60"
              placeholder="歌手（选填 — 可选可输入）"
              options={artistOptions.map((a) => ({ label: a }))}
              onChange={setArtist}
            />
            <AutoInput
              value={album}
              className="w-60"
              placeholder="专辑（选填 — 可选可输入）"
              options={albumOptions.map((a) => ({ label: a }))}
              onChange={setAlbum}
            />
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
          </div>
          <div className="flex items-center gap-2">
            <button type="submit" className={chip(true)}
                    disabled={addPhase === "saving"}>
              <SaveLabel phase={addPhase}>保存歌曲</SaveLabel>
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
