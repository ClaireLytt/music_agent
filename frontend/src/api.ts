import { useQuery } from "@tanstack/react-query";

export interface Song {
  id: string;
  title: string;
  artist: string;
  album: string;
  year: number;
  audio_type: "local" | "url" | "none";
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

export const useSongs = () =>
  useQuery({ queryKey: ["songs"], queryFn: () => get<Song[]>("/api/songs") });

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
