import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useAnalysis } from "../api";

/** 热力图等级：顺序渐变（单一色相，明度单调），0 级用面板底色 */
const LEVELS = ["#24242a", "#2a3044", "#39497c", "#4f66b4", "#6584e2", "#7c9eff"];
const levelOf = (c: number) =>
  c <= 0 ? 0 : c <= 2 ? 1 : c <= 4 ? 2 : c <= 7 ? 3 : c <= 11 ? 4 : 5;

function Heatmap({ title, series }: { title: string; series: [string, number][] }) {
  // series 从一年前的周日对齐到今天：列=周，行=周日..周六（GitHub 同款网格）
  const weeks: [string, number][][] = [];
  for (let i = 0; i < series.length; i += 7) weeks.push(series.slice(i, i + 7));
  const total = series.reduce((a, [, c]) => a + c, 0);
  // 月份标签：该周出现新月份时标注在列顶
  let lastLabelAt = -9;
  const months = weeks.map((w, wi) => {
    const m = new Date(w[0][0]).getMonth();
    const prev = wi > 0 ? new Date(weeks[wi - 1][0][0]).getMonth() : -1;
    if (m === prev || wi - lastLabelAt < 3) return "";
    lastLabelAt = wi;
    return `${m + 1}月`;
  });
  const DAY_ROWS = [1, 3, 5]; // 周一 / 周三 / 周五
  const DAY_NAMES = ["一", "三", "五"];
  return (
    <div className="rounded-card border border-edge bg-panel p-4">
      <div className="mb-2.5 text-[15px] font-semibold text-ink2">
        {title}（{total} 次）
      </div>
      <div className="overflow-x-auto pb-1">
        {/* 月份行 */}
        <div className="mb-1 flex gap-[3px] text-[11px] leading-none text-ink3">
          <div className="w-6 flex-none" />
          {months.map((m, i) => (
            <div key={i} className="w-[12px] flex-none overflow-visible whitespace-nowrap">
              {m}
            </div>
          ))}
        </div>
        <div className="flex gap-[3px]">
          {/* 星期列 */}
          <div className="relative w-6 flex-none text-[11px] leading-none text-ink3">
            {DAY_ROWS.map((row, i) => (
              <span key={row} className="absolute left-0" style={{ top: row * 15 + 2 }}>
                {DAY_NAMES[i]}
              </span>
            ))}
          </div>
          {weeks.map((w, wi) => (
            <div key={wi} className="flex flex-col gap-[3px]">
              {w.map(([d, c]) => (
                <div
                  key={d}
                  title={`${d} · ${c} 次`}
                  className="h-[12px] w-[12px] rounded-[3px]"
                  style={{ background: LEVELS[levelOf(c)] }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Tile({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex-1 rounded-card border border-edge bg-panel p-4 text-center">
      <div className="text-2xl font-bold tabular-nums">{n}</div>
      <div className="mt-1 text-xs text-ink3">{label}</div>
    </div>
  );
}

export default function Analysis() {
  const { data, isLoading } = useAnalysis(true);
  if (isLoading || !data)
    return <p className="flex flex-1 items-center justify-center text-sm text-ink3">统计中…</p>;

  const last30 = data.practice.slice(-30).map(([d, c]) => ({
    day: d.slice(5),
    练习: c,
  }));
  const empty =
    !data.practice.some(([, c]) => c > 0) && !data.collect.some(([, c]) => c > 0);

  if (empty)
    return (
      <p className="flex flex-1 items-center justify-center text-sm text-ink3">
        还没有练习数据——去打几个词再来看看
      </p>
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-4">
        <Tile n={data.totals.collected} label="收藏" />
        <Tile n={data.totals.practiced} label="已练习" />
        <Tile n={data.totals.mastered} label="已掌握（盲打零错零提示 ≥3 次）" />
      </div>

      <div className="rounded-card border border-edge bg-panel p-4">
        <div className="mb-1 text-xs font-semibold text-ink2">近 30 天练习次数</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={last30} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
            <CartesianGrid stroke="#2a2a31" vertical={false} />
            <XAxis dataKey="day" tick={{ fill: "#a8a8b3", fontSize: 10 }} tickLine={false}
              axisLine={{ stroke: "#2a2a31" }} interval={4} />
            <YAxis tick={{ fill: "#a8a8b3", fontSize: 10 }} tickLine={false}
              axisLine={false} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: "rgba(124,158,255,.08)" }}
              contentStyle={{
                background: "#24242a", border: "1px solid #2a2a31",
                borderRadius: 8, fontSize: 12, color: "#f5f5f4",
              }}
            />
            <Bar dataKey="练习" fill="#7c9eff" radius={[4, 4, 0, 0]} maxBarSize={14} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <Heatmap title="过去一年 · 练习" series={data.practice} />
      <Heatmap title="过去一年 · 收藏" series={data.collect} />

      <div className="rounded-card border border-edge bg-panel p-4">
        <div className="mb-2.5 text-xs font-semibold text-ink2">
          弱点词（盲打错误 ≥3 次）
        </div>
        {data.weak.length ? (
          <table className="w-full text-left text-[19.5px]">
            <thead>
              <tr className="text-[16.5px] text-ink3">
                <th className="pb-1.5 font-medium">单词</th>
                <th className="pb-1.5 font-medium">练习</th>
                <th className="pb-1.5 font-medium">错误</th>
                <th className="pb-1.5 font-medium">Tab</th>
                <th className="pb-1.5 font-medium">错误率</th>
              </tr>
            </thead>
            <tbody>
              {data.weak.map((w) => (
                <tr key={w.word} className="border-t border-line">
                  <td className="py-1.5 font-semibold">{w.word}</td>
                  <td className="py-1.5 tabular-nums text-ink2">{String(w.attempts ?? "")}</td>
                  <td className="py-1.5 tabular-nums text-ink2">{String(w.wrong ?? "")}</td>
                  <td className="py-1.5 tabular-nums text-ink2">{String(w.peek ?? 0)}</td>
                  <td className="py-1.5 tabular-nums text-ink2">
                    {w.rate != null ? `${Math.round(Number(w.rate) * 100)}%` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-[12.5px] text-ink3">还没有弱点词——保持住</p>
        )}
      </div>
    </div>
  );
}
