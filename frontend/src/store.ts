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
  /** 双击取词 */
  pickedWord: string | null;
  showMv: boolean;
  setSong: (id: string) => void;
  setPlaying: (p: boolean) => void;
  setTime: (ms: number, duration: number) => void;
  setCurrentLine: (i: number) => void;
  pickLine: (i: number | null) => void;
  pickWord: (w: string | null) => void;
  toggleMv: () => void;
}

export const usePlayer = create<PlayerState>((set) => ({
  songId: null,
  playing: false,
  timeMs: 0,
  durationMs: 0,
  currentLine: -1,
  pickedLine: null,
  pickedWord: null,
  showMv: true,
  setSong: (id) =>
    set({ songId: id, timeMs: 0, currentLine: -1, pickedLine: null, pickedWord: null }),
  setPlaying: (playing) => set({ playing }),
  setTime: (timeMs, durationMs) => set({ timeMs, durationMs }),
  setCurrentLine: (currentLine) => set({ currentLine }),
  pickLine: (pickedLine) => set({ pickedLine }),
  pickWord: (pickedWord) => set({ pickedWord }),
  toggleMv: () => set((s) => ({ showMv: !s.showMv })),
}));
