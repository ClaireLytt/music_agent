import { useQuery, useQueryClient } from "@tanstack/react-query";

export interface Song {
  id: string;
  title: string;
  artist: string;
  album: string;
  year: number;
  audio_type: "local" | "url" | "bilibili" | "preview" | "none";
  audio_offset_ms: number;
  bvid: string;
}

export interface TimedLine {
  line_index: number;
  timestamp_ms: number;
  text: string;
}

export interface Annotation {
  line_index: number;
  lyric_text: string;
  summary: string;
  metaphor_analysis: string | null;
  wordplay: string | null;
  emotional_tone: string;
}

export interface Lyrics {
  timed_lines: TimedLine[];
  annotations: Record<string, Annotation>;
}

export interface DictHit {
  word: string;
  phonetic: string;
  translation: string;
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

export const useSongs = (q = "") =>
  useQuery({
    queryKey: ["songs", q],
    queryFn: () =>
      get<Song[]>(`/api/songs${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

export const useLyrics = (songId: string | null) =>
  useQuery({
    queryKey: ["lyrics", songId],
    queryFn: () => get<Lyrics>(`/api/songs/${songId}/lyrics`),
    enabled: !!songId,
  });

export const useDict = (word: string | null) =>
  useQuery({
    queryKey: ["dict", word],
    queryFn: () => get<DictHit>(`/api/dict/${encodeURIComponent(word!)}`),
    enabled: !!word,
    retry: false,
  });

export const audioUrl = (songId: string) => `/api/songs/${songId}/audio`;

// ── 写操作与歌曲工具 ─────────────────────────────────────────

export interface Note {
  ts_ms: number;
  text: string;
}

export interface WordEntry {
  word: string;
  phonetic?: string;
  translation?: string;
  line?: string;
  song?: string;
  line_index?: number;
  note?: string;
}

export interface Favorite {
  id: string;
  line: string;
  title: string;
  artist: string;
  song_id?: string;
  line_index: number;
}

export interface IntroState {
  status: "done" | "running" | "error" | "none";
  text: string;
}

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${url}`);
  }
  return res.json();
}

export const useNotes = (songId: string | null) =>
  useQuery({
    queryKey: ["notes", songId],
    queryFn: () => get<Note[]>(`/api/songs/${songId}/notes`),
    enabled: !!songId,
  });

export const useFavorites = () =>
  useQuery({
    queryKey: ["favorites"],
    queryFn: () => get<Favorite[]>("/api/favorites"),
  });

export const useWordbook = (songTitle: string | null) =>
  useQuery({
    queryKey: ["wordbook", songTitle],
    queryFn: () =>
      get<WordEntry[]>(`/api/wordbook?song=${encodeURIComponent(songTitle!)}`),
    enabled: !!songTitle,
  });

export const useIntro = (songId: string | null) =>
  useQuery({
    queryKey: ["intro", songId],
    queryFn: () => get<IntroState>(`/api/songs/${songId}/intro`),
    enabled: !!songId,
    // 生成中每 2s 轮询一次（长耗时 LLM 铁律：结果永不押在长连接上）
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2000 : false,
  });

// ── 歌曲寻词（打字练习） ─────────────────────────────────────

export interface DrillEntry extends WordEntry {
  translation?: string;
  ai?: string;
  group?: string;
  review?: Record<string, number>;
}

export interface BookStats {
  total: number;
  practiced: number;
  mastered: number;
}

export interface DrillQueue {
  entries: DrillEntry[];
  stats: BookStats;
}

export interface DrillCardData {
  entry: DrillEntry;
  examples: string[];
  tts: boolean;
}

export interface WeakWord {
  word: string;
  attempts: number;
  wrong: number;
  peek: number;
  rate: number;
}

export interface Analysis {
  practice: [string, number][];
  collect: [string, number][];
  totals: { collected: number; practiced: number; mastered: number };
  weak: WeakWord[];
}

export const useDrillQueue = (group: string) =>
  useQuery({
    queryKey: ["drill-queue", group],
    queryFn: () =>
      get<DrillQueue>(`/api/drill/queue?group=${encodeURIComponent(group)}`),
    staleTime: Infinity, // 一轮内队列固定；打完一轮手动刷新
  });

export const useDrillCard = (word: string | null) =>
  useQuery({
    queryKey: ["drill-card", word],
    queryFn: () =>
      get<DrillCardData>(`/api/drill/card/${encodeURIComponent(word!)}`),
    enabled: !!word,
  });

export const useGroups = () =>
  useQuery({
    queryKey: ["wb-groups"],
    queryFn: () => get<string[]>("/api/wordbook/groups"),
  });

export const useAnalysis = (enabled: boolean) =>
  useQuery({
    queryKey: ["drill-analysis"],
    queryFn: () => get<Analysis>("/api/drill/analysis"),
    enabled,
  });

export const drillTtsUrl = (word: string) =>
  `/api/drill/tts/${encodeURIComponent(word)}`;
export const exportUrl = (format: "json" | "anki") =>
  `/api/wordbook/export?format=${format}`;

export function useDrillActions() {
  const qc = useQueryClient();
  return {
    reportResult: (word: string, clean: boolean, blind: boolean, peeks: number) =>
      send<{ stats: BookStats }>("/api/drill/result", "POST", {
        word, clean, blind, peeks,
      }).then((r) => {
        qc.invalidateQueries({ queryKey: ["drill-analysis"] });
        return r.stats;
      }),
    importWords: async (file: File, group: string) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(
        `/api/wordbook/import?group=${encodeURIComponent(group)}`,
        { method: "POST", body: fd },
      );
      if (!res.ok) {
        const d = await res.json().catch(() => null);
        throw new Error(d?.detail ?? `${res.status}`);
      }
      qc.invalidateQueries({ queryKey: ["wb-groups"] });
      qc.invalidateQueries({ queryKey: ["drill-queue"] });
      return res.json() as Promise<{ added: number; skipped: number; group: string }>;
    },
    deleteGroup: (group: string) =>
      send(`/api/wordbook/groups/${encodeURIComponent(group)}`, "DELETE").then(
        () => {
          qc.invalidateQueries({ queryKey: ["wb-groups"] });
          qc.invalidateQueries({ queryKey: ["drill-queue"] });
        },
      ),
    refreshQueue: () => qc.invalidateQueries({ queryKey: ["drill-queue"] }),
  };
}

// ── 歌迷考据 / 游戏 / 曲库管理 / 设置 ────────────────────────

export interface FanloreClue {
  type: string;
  title: string;
  body: string;
  quote_a: [string, string] | null;
  quote_b: [string, string] | null;
}

export interface FanloreData {
  known: boolean;
  hook: string;
  clues: FanloreClue[];
  chain: [string, string][];
  summary: string;
  caveat: string;
}

export interface FanloreState {
  status: "done" | "running" | "error" | "none";
  data?: FanloreData;
  progress?: string;
  chars?: number;
  msg?: string;
}

export const useFanlore = (songId: string | null) =>
  useQuery({
    queryKey: ["fanlore", songId],
    queryFn: () => get<FanloreState>(`/api/songs/${songId}/fanlore`),
    enabled: !!songId,
    refetchInterval: (q) =>
      q.state.data?.status === "running" ? 2000 : false,
  });

export interface QuizQ {
  line: string;
  answer: string;
  artist: string;
  options: string[];
  line_index: number;
}

export interface PuzzleQ {
  masked: string;
  answer: string;
  title: string;
  artist: string;
  options: string[];
}

export const fetchQuiz = () => get<QuizQ>("/api/games/quiz");
export const fetchPuzzle = () => get<PuzzleQ>("/api/games/title-puzzle");

export interface CatalogRow {
  title: string;
  artist: string;
  album: string;
  in_library: boolean;
}

export const useCatalog = (q: string) =>
  useQuery({
    queryKey: ["catalog", q],
    queryFn: () =>
      get<CatalogRow[]>(`/api/catalog${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

export interface SettingsInfo {
  llm_provider: string;
  has_key: boolean;
  public: boolean;
  llm_base_url: string;
  model_name: string;
  embedding_model: string;
}

export const useSettings = () =>
  useQuery({
    queryKey: ["settings"],
    queryFn: () => get<SettingsInfo>("/api/settings"),
  });

export const useUsage = () =>
  useQuery({
    queryKey: ["usage"],
    queryFn: () => get<Record<string, never> & {
      total?: { calls?: number; input_tokens?: number; output_tokens?: number };
      days?: Record<string, { calls?: number; input_tokens?: number; output_tokens?: number }>;
      models?: Record<string, { calls?: number; input_tokens?: number; output_tokens?: number }>;
    }>("/api/usage"),
  });

export interface RebuildState {
  status: "none" | "running" | "done" | "error";
  msg: string;
}

export const useRebuild = () =>
  useQuery({
    queryKey: ["rebuild"],
    queryFn: () => get<RebuildState>("/api/rebuild-index"),
    refetchInterval: (q) =>
      q.state.data?.status === "running" ? 2000 : false,
  });

export function useAdminActions() {
  const qc = useQueryClient();
  const refetch = (...keys: unknown[][]) =>
    keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));
  return {
    genFanlore: (songId: string) =>
      send(`/api/songs/${songId}/fanlore`, "POST").then(() =>
        refetch(["fanlore", songId]),
      ),
    chatLore: (song_id: string, question: string, history: { speaker: string; text: string }[]) =>
      send<{ answer: string }>("/api/chat/lore", "POST", {
        song_id, question, history,
      }),
    addFromCatalog: (labels: string[]) =>
      send<{ added: string[]; existed: string[]; missing: string[] }>(
        "/api/songs/from-catalog", "POST", { labels },
      ).then((r) => {
        refetch(["songs"], ["catalog"]);
        return r;
      }),
    addSong: (title: string, artist: string, album: string, lrc_text: string) =>
      send<{ id: string; note: string }>("/api/songs", "POST", {
        title, artist, album, lrc_text,
      }).then((r) => {
        refetch(["songs"], ["catalog"]);
        return r;
      }),
    deleteSong: (songId: string) =>
      send(`/api/songs/${songId}`, "DELETE").then(() =>
        refetch(["songs"], ["catalog"]),
      ),
    saveSettings: (provider: string, key: string, base: string, model: string) =>
      send<{ model_name: string }>("/api/settings", "PUT", {
        provider, key, base, model,
      }).then((r) => {
        refetch(["settings"]);
        return r;
      }),
    rebuildIndex: (model: string) =>
      send("/api/rebuild-index", "POST", { model }).then(() =>
        refetch(["rebuild"]),
      ),
  };
}

/** 写操作 + 失效对应查询。返回可直接 await 的函数集合。 */
export function useActions(songId: string | null, songTitle: string) {
  const qc = useQueryClient();
  const refetch = (...keys: unknown[][]) =>
    keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));
  return {
    addNote: (ts_ms: number, text: string) =>
      send(`/api/songs/${songId}/notes`, "POST", { ts_ms, text }).then(() =>
        refetch(["notes", songId]),
      ),
    delNote: (ts_ms: number) =>
      send(`/api/songs/${songId}/notes/${ts_ms}`, "DELETE").then(() =>
        refetch(["notes", songId]),
      ),
    collectWord: (word: string, line: string, line_index: number) =>
      send(`/api/wordbook`, "POST", {
        word,
        line,
        song: songTitle,
        line_index,
      }).then(() => refetch(["wordbook", songTitle])),
    removeWord: (word: string) =>
      send(`/api/wordbook/${encodeURIComponent(word)}`, "DELETE").then(() =>
        refetch(["wordbook", songTitle]),
      ),
    setWordNote: (word: string, note: string) =>
      send(`/api/wordbook/${encodeURIComponent(word)}/note`, "PUT", {
        note,
      }).then(() => refetch(["wordbook", songTitle])),
    addFav: (line_index: number) =>
      send("/api/favorites", "POST", {
        song_id: songId,
        line_index,
      }).then(() => refetch(["favorites"])),
    delFav: (fid: string) =>
      send(`/api/favorites/${encodeURIComponent(fid)}`, "DELETE").then(() =>
        refetch(["favorites"]),
      ),
    saveBvid: (value: string) =>
      send(`/api/songs/${songId}/bvid`, "PUT", { value }).then(() =>
        refetch(["songs"]),
      ),
    saveOffset: (offset_ms: number) =>
      send(`/api/songs/${songId}/offset`, "PUT", { offset_ms }).then(() =>
        refetch(["songs"]),
      ),
    genIntro: () =>
      send(`/api/songs/${songId}/intro`, "POST").then(() =>
        refetch(["intro", songId]),
      ),
    uploadAudio: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/songs/${songId}/audio`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `${res.status}`);
      }
      refetch(["songs"]);
    },
  };
}

// ── 数据备份（spec: .scratch/backup-restore/spec.md） ──
export const backupExportUrl = "/api/backup/export";

export async function importBackup(file: File): Promise<{ backup_of_old_data: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch("/api/backup/import", { method: "POST", body: fd });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new Error(detail?.detail ?? `恢复失败（HTTP ${resp.status}）`);
  }
  return resp.json();
}

// ── 行级 AI 助手（旧播放页「💬 AI 助手」迁移） ──
export interface ChatTurn {
  speaker: string;
  text: string;
}

export const useLineChat = (songId: string | null, line: number | null) =>
  useQuery({
    queryKey: ["lineChat", songId, line],
    enabled: !!songId && line !== null && line >= 0,
    queryFn: () =>
      get<{ history: ChatTurn[] }>(`/api/songs/${songId}/chat/${line}`),
  });

export async function askLine(
  songId: string, line: number, question: string, history: ChatTurn[],
): Promise<{ answer: string; history: ChatTurn[] }> {
  const resp = await fetch(`/api/songs/${songId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line_index: line, question, history }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new Error(detail?.detail ?? `提问失败（HTTP ${resp.status}）`);
  }
  return resp.json();
}
