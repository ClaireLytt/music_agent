import { create } from "zustand";

interface PlayerState {
  songId: string | null;
  playing: boolean;
  /** 当前播放位置（ms，已含歌词偏移修正前的原始音频时间） */
  timeMs: number;
  durationMs: number;
  currentLine: number;
  /** 点选的歌词行（解读坞展示该句讲解） */
  pickedLine: number | null;
  showMv: boolean;
  /** 跳播请求（ms，歌词时间轴口径）；App 消费后置 null */
  seekMs: number | null;
  /** MV 歌词跟随：B 站 iframe 读不到进度，用本地时钟近似驱动。
      null = 未开启；否则记录对齐点（墙钟 ↔ 歌词时间轴） */
  follow: { wallStart: number; msStart: number } | null;
  /** 从打字练习跳歌过来时的返回地址（/words?...）；null = 无待返回 */
  drillReturn: string | null;
  setDrillReturn: (url: string | null) => void;
  setSong: (id: string) => void;
  setPlaying: (p: boolean) => void;
  setTime: (ms: number, duration: number) => void;
  setCurrentLine: (i: number) => void;
  pickLine: (i: number | null) => void;
  toggleMv: () => void;
  requestSeek: (ms: number) => void;
  clearSeek: () => void;
  startFollow: (msStart: number) => void;
  stopFollow: () => void;
}

export const usePlayer = create<PlayerState>((set) => ({
  songId: null,
  playing: false,
  timeMs: 0,
  durationMs: 0,
  currentLine: -1,
  pickedLine: null,
  showMv: false, // MV 默认收起
  seekMs: null,
  follow: null,
  drillReturn: null,
  setDrillReturn: (drillReturn) => set({ drillReturn }),
  setSong: (id) =>
    set({ songId: id, playing: false, timeMs: 0, currentLine: -1,
          pickedLine: null, follow: null }),
  setPlaying: (playing) => set({ playing }),
  setTime: (timeMs, durationMs) => set({ timeMs, durationMs }),
  setCurrentLine: (currentLine) => set({ currentLine }),
  pickLine: (pickedLine) => set({ pickedLine }),
  toggleMv: () => set((s) => ({ showMv: !s.showMv })),
  requestSeek: (seekMs) => set({ seekMs }),
  clearSeek: () => set({ seekMs: null }),
  startFollow: (msStart) =>
    set({ follow: { wallStart: Date.now(), msStart } }),
  stopFollow: () => set({ follow: null }),
}));
