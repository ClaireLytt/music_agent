import { useEffect, useRef, useState } from "react";

export type SavePhase = "idle" | "saving" | "saved";

export function useSavePhase() {
  const [phase, setPhase] = useState<SavePhase>("idle");
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const wrap = async (save: () => Promise<unknown>) => {
    if (phase !== "idle") return;
    setPhase("saving");
    try {
      await save();
      setPhase("saved");
      timer.current = window.setTimeout(() => setPhase("idle"), 1500);
    } catch (e) {
      setPhase("idle");
      throw e;
    }
  };
  return { phase, wrap };
}

export function SaveLabel({ phase, children }: {
  phase: SavePhase;
  children: React.ReactNode;
}) {
  return (
    <span className="grid min-w-[30px] place-items-center">
      {phase === "idle" && children}
      {phase === "saving" && (
        <svg
          className="animate-spin"
          width="14" height="14" viewBox="0 0 16 16" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round"
        >
          <path d="M8 1.5a6.5 6.5 0 1 1-6.5 6.5" />
        </svg>
      )}
      {phase === "saved" && (
        <svg
          className="animate-popscale"
          width="14" height="14" viewBox="0 0 16 16" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2.5 8.5l3.5 3.5 7-8" />
        </svg>
      )}
    </span>
  );
}
