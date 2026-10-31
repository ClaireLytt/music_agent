import { useEffect, useRef, useState } from "react";
import {
  backupExportUrl, importBackup, useAdminActions, useRebuild, useSettings,
} from "../api";
import Scrollable from "../components/Scrollable";

const chip = (primary = false) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[18.8px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
    primary
      ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

const inputCls =
  "rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[19.5px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";

const EMB_MODELS = [
  ["all-MiniLM-L6-v2", "英文为主(默认):all-MiniLM-L6-v2"],
  ["paraphrase-multilingual-MiniLM-L12-v2", "多语(中英均可):paraphrase-multilingual-MiniLM-L12-v2"],
] as const;

export default function SettingsPage() {
  const settings = useSettings();
  const fileRef = useRef<HTMLInputElement>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState("");
  const rebuild = useRebuild();
  const acts = useAdminActions();
  const [provider, setProvider] = useState("openai");
  const [key, setKey] = useState("");
  const [base, setBase] = useState("");
  const [model, setModel] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setProvider(s.llm_provider);
    setEmbModel(s.embedding_model);
    setBase(s.llm_base_url);
    setModel(s.model_name);
  }, [settings.data]);

  return (
    <Scrollable className="h-full min-h-0 bg-bg2" contentClassName="flex flex-col gap-5 px-10 py-6">
      <header className="flex items-center gap-3">
        <h1 className="text-[21px] font-bold tracking-wide">设置</h1>
        {status && <span className="ml-auto text-[18px] text-ink3">{status}</span>}
      </header>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-3 text-[19.5px] font-semibold">
          API 设置
          <span
            data-key-state={settings.data?.has_key ? "saved" : "missing"}
            className="ml-3 text-[17px] font-normal text-ink3"
          >
            {settings.data == null
              ? ""
              : settings.data.has_key
                ? "Key 已保存在本机，可直接使用"
                : "尚未配置 Key"}
          </span>
        </h2>
        <form
          className="flex flex-col gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            acts
              .saveSettings(provider, key, base, model)
              .then((r) => {
                setStatus(`已保存并生效（模型:${r.model_name}）`);
                setKey("");
              })
              .catch((err) => setStatus(err.message));
          }}
        >
          <div className="flex flex-wrap gap-2.5">
            <input name="api-key" type="password" autoComplete="off" required value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={settings.data?.has_key
                ? "已保存，输入新 Key 可替换"
                : "API Key（必填）"}
              className={`${inputCls} w-72`} />
            <input name="base-url" value={base} onChange={(e) => setBase(e.target.value)}
              placeholder="接口地址（选填，如 https://api.deepseek.com）"
              className={`${inputCls} w-80`} />
            <input name="model-name" value={model} onChange={(e) => setModel(e.target.value)}
              placeholder="模型名称（选填，留空用默认）" className={`${inputCls} w-64`} />
          </div>
          <div>
            <button type="submit" className={chip(true)}>保存设置</button>
          </div>
        </form>
      </section>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-1 text-[19.5px] font-semibold">语料库与 Embedding 模型</h2>
        <p className="mb-3 max-w-2xl text-[18.8px] leading-[1.6] text-ink3">
          彩蛋/互文/语义搜索使用本地 embedding 模型。默认英文模型对中文歌词区分度差;
          曲库以中文为主时，建议切换到多语模型后重建索引(首次会下载模型，重建需 1-3 分钟)。
        </p>
        <div className="flex flex-wrap items-center gap-2.5">
          <select
            name="emb-model"
            value={EMB_MODELS.some(([v]) => v === embModel) ? embModel : "custom"}
            onChange={(e) => e.target.value !== "custom" && setEmbModel(e.target.value)}
            className="rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[19.5px] text-ink focus:border-accent focus:outline-none"
          >
            {EMB_MODELS.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
            <option value="custom">自定义…</option>
          </select>
          <input
            name="emb-custom"
            value={embModel}
            onChange={(e) => setEmbModel(e.target.value)}
            placeholder="任意 sentence-transformers 模型名"
            className={`${inputCls} w-80`}
          />
          <button
            className={chip(true)}
            disabled={rebuild.data?.status === "running"}
            onClick={() =>
              acts.rebuildIndex(embModel).catch((e) => setStatus(e.message))
            }
          >
            重建语料库索引（含新添加的歌曲）
          </button>
        </div>
        {rebuild.data && rebuild.data.status !== "none" && (
          <p className="mt-2.5 text-[18.8px] text-ink3" aria-live="polite">
            {rebuild.data.status === "running" ? "⏳ " : ""}
            {rebuild.data.msg}
          </p>
        )}
      </section>
      {!settings.data?.public && (
        <section className="rounded-card border border-edge bg-panel p-5">
          <h2 className="mb-1 text-[19.5px] font-semibold">数据备份</h2>
          <p className="mb-1 max-w-2xl text-[18.8px] leading-[1.6] text-ink3">
            导出整个数据目录（学习数据、AI 缓存、歌曲音频）为 zip，换电脑时
            在新机器上传恢复即可。备份包内不含你的 API Key。
          </p>
          <p className="mb-3 max-w-2xl text-[18.8px] font-medium leading-[1.6] text-[#e5484d]">
            恢复会替换当前全部数据（原数据自动留底为 data.bak_时间戳）；
            请勿修改备份文件内容。
          </p>
          <div className="flex flex-wrap items-center gap-2.5">
            <a className={chip(true)} href={backupExportUrl} download>
              导出全部数据 (zip)
            </a>
            <button
              className={chip(false)}
              disabled={restoring}
              onClick={() => fileRef.current?.click()}
            >
              {restoring ? "恢复中…" : "从备份恢复…"}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                if (!window.confirm(
                  `确定用「${f.name}」替换当前全部数据？\n原数据会留底为 data.bak_时间戳，可手动找回。`))
                  return;
                setRestoring(true);
                setRestoreMsg("");
                importBackup(f)
                  .then((r) => setRestoreMsg(
                    `✅ 恢复完成，旧数据留底于 ${r.backup_of_old_data}；请刷新页面。`))
                  .catch((err) => setRestoreMsg(`⚠️ ${err.message}`))
                  .finally(() => setRestoring(false));
              }}
            />
          </div>
          {restoreMsg && (
            <p className="mt-2.5 text-[18.8px] text-ink2" aria-live="polite">
              {restoreMsg}
            </p>
          )}
        </section>
      )}
    </Scrollable>
  );
}
