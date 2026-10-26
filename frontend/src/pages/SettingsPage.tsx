import { useEffect, useState } from "react";
import { useAdminActions, useRebuild, useSettings, useUsage } from "../api";

const chip = (primary = false) =>
  `whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
    primary
      ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
      : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
  }`;

const inputCls =
  "rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[13px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none";

const EMB_MODELS = [
  ["all-MiniLM-L6-v2", "英文为主(默认):all-MiniLM-L6-v2"],
  ["paraphrase-multilingual-MiniLM-L12-v2", "多语(中英均可):paraphrase-multilingual-MiniLM-L12-v2"],
] as const;

export default function SettingsPage() {
  const settings = useSettings();
  const usage = useUsage();
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
    setBase(s.llm_base_url);
    setModel(s.model_name);
    setEmbModel(s.embedding_model);
  }, [settings.data]);

  const u = usage.data;
  const day = new Date().toISOString().slice(0, 10);
  const usageRows: [string, { calls?: number; input_tokens?: number; output_tokens?: number }][] =
    u?.total?.calls
      ? [
          ["今天", u.days?.[day] ?? {}],
          ["累计", u.total ?? {}],
          ...Object.entries(u.models ?? {}).sort(),
        ]
      : [];

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto bg-bg2 px-10 py-6">
      <header className="flex items-center gap-3">
        <h1 className="text-sm font-bold tracking-wide">设置</h1>
        {status && <span className="ml-auto text-xs text-ink3">{status}</span>}
      </header>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-2 text-[13px] font-semibold">用量</h2>
        {usageRows.length ? (
          <table className="text-[13px]">
            <thead>
              <tr className="text-[11px] text-ink3">
                <th className="pb-1 pr-6 text-left font-medium"> </th>
                <th className="pb-1 pr-6 text-left font-medium">调用</th>
                <th className="pb-1 pr-6 text-left font-medium">输入 tokens</th>
                <th className="pb-1 text-left font-medium">输出 tokens</th>
              </tr>
            </thead>
            <tbody>
              {usageRows.map(([name, b]) => (
                <tr key={name} className="border-t border-line">
                  <td className="py-1 pr-6 text-ink2">{name}</td>
                  <td className="py-1 pr-6 tabular-nums">{b.calls ?? 0}</td>
                  <td className="py-1 pr-6 tabular-nums">{(b.input_tokens ?? 0).toLocaleString()}</td>
                  <td className="py-1 tabular-nums">{(b.output_tokens ?? 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-[12.5px] text-ink3">还没有任何 LLM 调用记录。</p>
        )}
      </section>

      <section className="rounded-card border border-edge bg-panel p-5">
        <h2 className="mb-1 text-[13px] font-semibold">API 设置</h2>
        <p className="mb-3 text-[12.5px] text-ink3">
          填入你自己的大模型 API Key，保存后立即生效，无需改文件、无需重启。
          {settings.data?.has_key && "（当前已配置 Key）"}
        </p>
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
          <div className="flex gap-4 text-[13px]" role="radiogroup" aria-label="接口类型">
            {[
              ["openai", "OpenAI 兼容接口（DeepSeek / 通义 / Kimi 等）"],
              ["anthropic", "Anthropic（Claude）"],
            ].map(([v, label]) => (
              <label key={v} className="flex cursor-pointer items-center gap-1.5 text-ink2">
                <input
                  type="radio"
                  name="provider"
                  checked={provider === v}
                  onChange={() => setProvider(v)}
                  className="accent-[#7c9eff]"
                />
                {label}
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-2.5">
            <input name="api-key" type="password" autoComplete="off" required value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="API Key（必填）" className={`${inputCls} w-72`} />
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
        <h2 className="mb-1 text-[13px] font-semibold">语料库与 Embedding 模型</h2>
        <p className="mb-3 max-w-2xl text-[12.5px] leading-6 text-ink3">
          彩蛋/互文/语义搜索使用本地 embedding 模型。默认英文模型对中文歌词区分度差;
          曲库以中文为主时，建议切换到多语模型后重建索引(首次会下载模型，重建需 1-3 分钟)。
        </p>
        <div className="flex flex-wrap items-center gap-2.5">
          <select
            name="emb-model"
            value={EMB_MODELS.some(([v]) => v === embModel) ? embModel : "custom"}
            onChange={(e) => e.target.value !== "custom" && setEmbModel(e.target.value)}
            className="rounded-full border border-edge2 bg-panel2 px-3.5 py-2 text-[13px] text-ink focus:border-accent focus:outline-none"
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
          <p className="mt-2.5 text-[12.5px] text-ink3" aria-live="polite">
            {rebuild.data.status === "running" ? "⏳ " : ""}
            {rebuild.data.msg}
          </p>
        )}
      </section>
    </div>
  );
}
