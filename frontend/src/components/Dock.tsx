import { Lyrics, useDict } from "../api";
import { usePlayer } from "../store";

function Chip({
  children,
  primary,
  onClick,
  disabled,
  title,
}: {
  children: React.ReactNode;
  primary?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors ${
        primary
          ? "bg-accent font-semibold text-[#0e1016] hover:brightness-110"
          : "border border-[#33333c] text-ink2 hover:border-accent hover:text-accent"
      } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[#33333c] disabled:hover:text-ink2`}
    >
      {children}
    </button>
  );
}

function Card({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-edge bg-panel p-4">
      <div className="mb-2.5 flex items-center gap-2 text-xs font-semibold text-ink2">
        {k}
      </div>
      {children}
    </div>
  );
}

export default function Dock({ lyrics }: { lyrics: Lyrics | undefined }) {
  const { currentLine, pickedLine, pickedWord, pickWord } = usePlayer();
  const line = pickedLine ?? currentLine;
  const ann = lyrics?.annotations[String(line)];
  const dict = useDict(pickedWord);

  return (
    <aside
      aria-label="解读面板"
      className="flex flex-col gap-3.5 overflow-y-auto border-l border-line bg-bg2 px-[18px] py-5"
    >
      <h2 className="text-xs font-semibold tracking-[0.1em] text-ink3">
        本句解读
      </h2>

      <Card k={ann ? `✏️ AI 讲解 · 第 ${line + 1} 句` : "✏️ AI 讲解"}>
        {ann ? (
          <p className="mx-auto text-center text-[13.5px] leading-[1.8] text-ink2">
            {ann.summary}
            {ann.metaphor_analysis && (
              <>
                <br />
                <b className="font-semibold text-ink">{ann.metaphor_analysis}</b>
              </>
            )}
          </p>
        ) : (
          <p className="mx-auto text-center text-[13.5px] leading-[1.8] text-ink3">
            点一句歌词，看这句的 AI 讲解
          </p>
        )}
      </Card>

      {pickedWord && (
        <Card k="📒 生词卡">
          {dict.data ? (
            <>
              <div className="text-center">
                <span className="text-[17px] font-bold">{dict.data.word}</span>
                {dict.data.phonetic && (
                  <span className="ml-2 text-[12.5px] text-ink3">
                    /{dict.data.phonetic}/
                  </span>
                )}
              </div>
              <p className="mt-1.5 whitespace-pre-line text-center text-[13px] text-ink2">
                {dict.data.translation}
              </p>
            </>
          ) : (
            <p className="text-center text-[13px] text-ink3">
              {dict.isLoading ? "查询中…" : `词典里没有「${pickedWord}」`}
            </p>
          )}
          <div className="mt-3 flex justify-center gap-2">
            <Chip primary disabled title="迁移中 · 暂在旧版界面">
              ⭐ 收藏到单词本
            </Chip>
            <Chip onClick={() => pickWord(null)}>关闭</Chip>
          </div>
        </Card>
      )}

      <Card k="💬 问 AI">
        <form className="flex gap-2" onSubmit={(e) => e.preventDefault()}>
          <input
            placeholder="双击取词 · 点句提问（迁移中）"
            disabled
            className="min-w-0 flex-1 rounded-full border border-edge2 bg-panel2 px-3.5 py-[9px] text-[13px] text-ink placeholder:text-ink3 focus:border-accent focus:outline-none disabled:opacity-50"
          />
          <Chip primary disabled title="迁移中 · 暂在旧版界面">
            发送
          </Chip>
        </form>
      </Card>

      <div className="flex flex-wrap justify-center gap-2 rounded-card border border-edge bg-panel p-4">
        <Chip disabled title="迁移中 · 暂在旧版界面">⭐ 收藏本句</Chip>
        <Chip disabled title="迁移中 · 暂在旧版界面">📝 记笔记</Chip>
        <Chip disabled title="迁移中 · 暂在旧版界面">🥚 查彩蛋</Chip>
        <Chip disabled title="迁移中 · 暂在旧版界面">🀄 整首翻译</Chip>
      </div>
    </aside>
  );
}
