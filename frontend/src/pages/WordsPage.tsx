import { Suspense, lazy, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  exportUrl, useDrillActions, useDrillQueue, useGroups,
} from "../api";
import Drill, { ROUND_LENS, loadRoundLen, saveRoundLen } from "../components/Drill";
import Scrollable from "../components/Scrollable";

// Recharts 很重：分析视图按需加载，不拖慢播放页
const Analysis = lazy(() => import("../components/Analysis"));

const PRESET_GROUPS = ["全部", "📖 歌词收藏", "🔤 单词", "🧩 词组"];

const chip = (on: boolean) =>
  `whitespace-nowrap rounded-full px-4 py-2 text-[18.8px] font-medium transition-colors ${
    on
      ? "bg-accent font-semibold text-[#0e1016]"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

export default function WordsPage({ analysis = false }: { analysis?: boolean }) {
  // 练习范围进 URL（分析页返回时不丢，链接可分享）
  const [params, setParams] = useSearchParams();
  const group = params.get("group") || "全部";
  const setGroup = (g: string) =>
    setParams(g === "全部" ? {} : { group: g }, { replace: true });
  const navigate = useNavigate();
  const [roundLen, setRoundLen] = useState(loadRoundLen);
  const [toast, setToast] = useState("");
  const groups = useGroups();
  const queue = useDrillQueue(group);
  const acts = useDrillActions();
  const fileRef = useRef<HTMLInputElement>(null);
  const [importGroup, setImportGroup] = useState("");

  const allGroups = [...PRESET_GROUPS, ...(groups.data ?? [])];
  const search = params.toString() ? `?${params.toString()}` : "";

  return (
    <Scrollable className="h-full min-h-0 bg-bg2" contentClassName="flex flex-col gap-4 px-10 py-6">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-[21px] font-bold tracking-wide">歌曲寻词</h1>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="练习范围">
          {allGroups.map((g) => (
            <button
              key={g}
              role="tab"
              aria-selected={g === group}
              className={chip(g === group)}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>
        {!analysis && (
          <div className="ml-3 flex items-center gap-1.5" role="radiogroup" aria-label="每轮词数">
            <span className="text-[16.5px] tracking-[0.1em] text-ink3">每轮</span>
            {ROUND_LENS.map((n) => (
              <button
                key={n}
                role="radio"
                aria-checked={n === roundLen}
                className={`${chip(n === roundLen)} !px-3.5 !py-1.5 !text-[18px]`}
                onClick={() => {
                  setRoundLen(n);
                  saveRoundLen(n);
                }}
              >
                {n === 0 ? "全部" : n}
              </button>
            ))}
          </div>
        )}
        <div className="ml-auto mr-[23%] flex items-center gap-2">
          {toast && <span className="text-xs text-ink3">{toast}</span>}
          <button
            className={
              analysis
                ? chip(true)
                : "whitespace-nowrap rounded-full bg-[#5fc79b] px-4 py-2 text-[18.8px] font-semibold text-[#0e1016] transition-colors hover:brightness-110"
            }
            onClick={() =>
              navigate(analysis ? `/words${search}` : `/words/analysis${search}`)
            }
          >
            {analysis ? "返回练习" : "数据分析"}
          </button>
        </div>
      </header>

      {analysis ? (
        <Suspense
          fallback={
            <p className="flex flex-1 items-center justify-center text-sm text-ink3">
              统计中…
            </p>
          }
        >
          <Analysis />
        </Suspense>
      ) : (
        <Drill
          group={group}
          roundLen={roundLen}
          queue={queue.data}
          loading={queue.isLoading}
          onNewQueue={() => acts.refreshQueue()}
        />
      )}

      <footer className="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <span className="text-[16.5px] font-semibold tracking-[0.1em] text-ink3">
          单词本管理
        </span>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.json,.csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f)
              acts
                .importWords(f, importGroup)
                .then((r) =>
                  setToast(`已导入 ${r.added} 词到「${r.group}」，跳过 ${r.skipped}`),
                )
                .catch((err) => setToast(err.message));
            e.target.value = "";
          }}
        />
        <input
          name="import-group"
          value={importGroup}
          onChange={(e) => setImportGroup(e.target.value)}
          placeholder="导入分组名（留空=文件名）"
          className="w-64 rounded-full border border-edge2 bg-panel2 px-4 py-2 text-[18px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
        />
        <button className={chip(false)} onClick={() => fileRef.current?.click()}>
          导入词表…
        </button>
        {group !== "全部" && !PRESET_GROUPS.includes(group) && (
          <button
            className={chip(false)}
            onClick={() =>
              acts
                .deleteGroup(group)
                .then(() => {
                  setToast(`已删除分组「${group}」`);
                  setGroup("全部");
                })
                .catch((err) => setToast(err.message))
            }
          >
            删除当前分组
          </button>
        )}
        <span className="mx-1 h-4 w-px bg-edge" />
        <a className={chip(false)} href={exportUrl("json")} download>
          导出 JSON 词典
        </a>
        <a className={chip(false)} href={exportUrl("anki")} download>
          导出 Anki
        </a>
      </footer>
    </Scrollable>
  );
}
