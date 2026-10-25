"""Cross-tab runtime: library snapshot, lazy caches, background jobs.

create_app 开头 ~300 行的共享基础设施（曾全是闭包）提成 Runtime 类；
各 tab 模块通过 rt 调用，不再靠闭包偷看彼此的变量。
行为与拆分前一字不差——只是把 `ctx[...]` 换成 `self.cache[...]`、
`settings`/`public` 换成 `self.settings`/`self.public`。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import replace
from pathlib import Path

from ..archaeology import mine_motifs
from ..config import HACKATHON_PLAYLIST_SOURCE, Settings, default_model_for
from ..evidence import QuoteIndex
from ..search import LyricsSearcher
from ..ui_helpers import (
    _ECHO_NO_INDEX,
    _ECHO_OVERVIEW_EMPTY,
    _ECHO_SCAN_CACHE_DIR,
    _discover_songs,
    _load_song_data,
    _render_echo_overview,
)
from ..songdata import set_songs_root
from .context import AppContext

logger = logging.getLogger(__name__)

_SORT_KEYS = {
    "added": lambda s: s["added_ts"],
    "album": lambda s: (s["album"].lower(), s["title"].lower()),
    "artist": lambda s: (s["artist"].lower(), s["title"].lower()),
}

PUBLIC_KEY_HINT = ("⚠️ 公开体验版需使用你自己的 API Key：请到「⚙️ 设置」页签填写"
                   "（Key 只保存在你的浏览器里，服务器不落盘）。")


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        set_songs_root(settings.songs_dir)  # 路径穿越防护的根目录口径
        self.public = settings.public_mode
        self.cache = AppContext()
        self._echo_index_lock = threading.Lock()
        self._autobind_enabled = (os.getenv("BILI_AUTO_BIND", "1") != "0"
                                  and not settings.public_mode)
        self._init_done = False
        self.refresh_library()
        self._init_done = True

    # ── 曲库快照 ──────────────────────────────────────────

    def refresh_library(self) -> None:
        ctx = self.cache
        ctx.invalidate_library_views()  # library changed -> stale views
        # hackathon-playlist material is licensed for offline demo only —
        # never expose it on a public deployment
        songs = _discover_songs(
            self.settings.songs_dir,
            exclude_sources={HACKATHON_PLAYLIST_SOURCE} if self.public
            else None,
            # 产品定位：英文歌学英语——中文歌默认隐藏（数据保留）
            exclude_cjk=os.getenv("LL_SHOW_CJK", "") != "1")
        ctx["songs"] = songs
        searcher = LyricsSearcher(songs,
                                  model_name=self.settings.embedding_model,
                                  corpus_dir=self.settings.corpus_dir)
        ctx["searcher"] = searcher
        if songs:
            # pre-load the embedding model so the first semantic search
            # doesn't block on a ~90MB download / cold model init
            threading.Thread(target=searcher.warm_up, daemon=True).start()
        # new songs may need a bilibili MV auto-bound (skip during __init__:
        # 启动时由 warm_up 统一 kick，老代码经 ctx 间接调用也是同一语义)
        if self._init_done:
            self.kick_autobind()

    # ── 后台线程（MV 自动绑定 / 语料重建）──────────────────

    def kick_autobind(self) -> None:
        ctx = self.cache
        if not self._autobind_enabled or ctx.get("autobind_running"):
            return
        if not any(not s.get("bvid") for s in ctx["songs"]):
            return
        ctx["autobind_running"] = True

        def _run() -> None:
            try:
                from ..bilibili import auto_bind_missing
                n = auto_bind_missing(list(ctx["songs"]),
                                      lambda: self._autobind_enabled)
                if n:
                    self.refresh_library()
                    logger.info("auto-bound %d bilibili MVs", n)
            except Exception:
                logger.exception("MV auto-bind thread failed")
            finally:
                ctx["autobind_running"] = False

        threading.Thread(target=_run, daemon=True,
                         name="ll-autobind").start()

    def kick_corpus_rebuild(self) -> None:
        """新增歌曲后后台重建语料+embeddings（本地模型，零 LLM），
        让回声时刻/彩蛋把新歌纳入回声池，无需手跑命令或重启。"""
        ctx = self.cache
        if os.getenv("LL_CORPUS_REBUILD", "1") == "0":
            return  # probe/tests: keep runs from mutating the real corpus
        if ctx.get("corpus_rebuilding"):
            return
        ctx["corpus_rebuilding"] = True

        def _run() -> None:
            try:
                from ..intertextuality.corpus import build_corpus
                from ..intertextuality.embeddings import generate_embeddings
                n_songs, n_lines = build_corpus(
                    self.settings.songs_dir, self.settings.corpus_dir,
                    catalog_path="data/catalog/catalog.json")
                generate_embeddings(self.settings.corpus_dir,
                                    model_name=self.settings.embedding_model)
                # 让 echo 索引下次访问时重新加载（扫描缓存键含
                # embeddings mtime，自动失效）
                ctx.pop("echo_index", None)
                logger.info("corpus rebuilt: %d songs, %d lines",
                            n_songs, n_lines)
            except Exception:
                logger.exception("background corpus rebuild failed")
            finally:
                ctx["corpus_rebuilding"] = False

        threading.Thread(target=_run, daemon=True,
                         name="ll-corpus-rebuild").start()

    # ── 曲目选项工具 ──────────────────────────────────────

    def song_choice_label(self, s: dict) -> str:
        # titles are the identity in every handler; when two library songs
        # share a title (cross-artist covers), disambiguate with the artist
        title = s["title"]
        dup = sum(1 for o in self.cache.get("songs", [])
                  if o["title"] == title)
        return f"{title} — {s['artist']}" if dup > 1 else title

    def song_choices(self, sort: str = "added_desc") -> list[str]:
        field, _, direction = sort.rpartition("_")
        key = _SORT_KEYS.get(field, _SORT_KEYS["added"])
        ordered = sorted(self.cache["songs"], key=key,
                         reverse=direction == "desc")
        return [self.song_choice_label(s) for s in ordered]

    def find_song(self, choice: str) -> dict:
        songs = self.cache["songs"]
        return next(
            (s for s in songs
             if choice and self.song_choice_label(s) == choice),
            songs[0] if songs else {},
        )

    def label_of(self) -> dict[str, str]:
        return {s.get("title", ""): self.song_choice_label(s)
                for s in self.cache["songs"]}

    def lyrics_blob(self, label: str) -> str:
        """某首歌的全部歌词小写拼接（懒加载，随曲库刷新失效）。"""
        cache = self.cache.setdefault("lyrics_blobs", {})
        if label not in cache:
            info = self.find_song(label)
            try:
                data = _load_song_data(info["dir"])
                cache[label] = " ".join(
                    ln.text for ln in data["timed_lines"]).casefold()
            except Exception:
                cache[label] = ""
        return cache[label]

    def filtered_labels(self, sort: str, q: str) -> list[str]:
        labels = self.song_choices(sort)
        q = (q or "").strip().casefold()
        if q:
            # 歌名/歌手命中之外，也搜整首歌词——粘一句歌词就能找到歌
            labels = [
                l for l in labels
                if q in l.casefold()
                or q in self.find_song(l).get("artist", "").casefold()
                or q in self.lyrics_blob(l)
            ]
        return labels

    # ── 访客级 LLM 设置 ──────────────────────────────────

    def request_settings(self, cfg) -> Settings:
        """Per-visitor settings: in public mode the LLM config comes from the
        visitor's browser (gr.BrowserState), never from the server .env."""
        if not self.public:
            return self.settings
        cfg = cfg if isinstance(cfg, dict) else {}
        provider = (cfg.get("llm_provider") or "openai").strip()
        model = (cfg.get("model_name") or "").strip() \
            or default_model_for(provider)
        return replace(
            self.settings,
            api_key=(cfg.get("api_key") or "").strip(),
            llm_provider=provider,
            llm_base_url=(cfg.get("llm_base_url") or "").strip(),
            model_name=model,
        )

    # ── 互文/彩蛋索引 ────────────────────────────────────

    def echo_index(self):
        ctx = self.cache
        if "echo_index" in ctx:
            return ctx["echo_index"]
        with self._echo_index_lock:   # 启动窗口多路并发首查，只加载一份
            if "echo_index" not in ctx:
                try:
                    from ..intertextuality.embeddings import load_embeddings
                    ctx["echo_index"] = load_embeddings(
                        self.settings.corpus_dir,
                        self.settings.embedding_model)
                except Exception:
                    logger.exception("Intertextuality index unavailable")
                    ctx["echo_index"] = None
        return ctx["echo_index"]

    def find_echoes(self, line_text: str, info: dict) -> list[dict] | None:
        """Top-K similar lines from the same artist's other songs.

        Returns None when the corpus/embeddings are not built.
        """
        index = self.echo_index()
        if index is None:
            return None
        embeddings, corpus = index
        from ..intertextuality.search import search_similar
        hits = search_similar(
            line_text, embeddings, corpus,
            model_name=self.settings.embedding_model,
            top_k=self.settings.echo_top_k,
            min_similarity=self.settings.echo_search_min_similarity,
            min_similarity_cjk=self.settings.echo_search_min_similarity_cjk,
            exclude_song=info.get("title", ""),
            artist=info.get("artist") or None,
        )
        return [{"song": h.song, "album": h.album, "line": h.line,
                 "similarity": h.similarity} for h in hits]

    def build_echo_map(self, info: dict) -> tuple[str, str]:
        """Whole-song 🥚 scan → (JS payload JSON, overview panel HTML).

        The payload decorates echoing lyric lines with 🥚 markers; the
        overview panel lists every echoing line with its strongest target.
        """
        ctx = self.cache
        song_dir = info.get("dir")
        if not song_dir:
            return "", _ECHO_OVERVIEW_EMPTY
        index = self.echo_index()
        if index is None:
            return "", _ECHO_NO_INDEX
        # cache key: anything that changes the scan result invalidates it —
        # the song's lyrics, the corpus embeddings, model and thresholds
        lrc = Path(song_dir) / "lyrics.lrc"
        emb_file = Path(self.settings.corpus_dir) / "embeddings.npy"
        cache_key = [
            lrc.stat().st_mtime if lrc.exists() else 0.0,
            emb_file.stat().st_mtime if emb_file.exists() else 0.0,
            self.settings.embedding_model,
            self.settings.echo_min_similarity,
            self.settings.echo_min_similarity_cjk,
            "tour-v5",  # overview: hero 置顶 + 折叠列表
        ]
        cache = ctx.setdefault("echo_maps", {})
        cached = cache.get(song_dir)
        if cached and cached[0] == cache_key:
            return cached[1], cached[2]
        # disk cache: whole-song scans cost 1-2s of model encoding each —
        # persisting them makes every restart start warm
        disk_path = _ECHO_SCAN_CACHE_DIR / f"{Path(song_dir).name}.json"
        try:
            if disk_path.exists():
                blob = json.loads(disk_path.read_text(encoding="utf-8"))
                if blob.get("key") == cache_key:
                    cache[song_dir] = (cache_key, blob["payload"],
                                       blob["overview"])
                    return blob["payload"], blob["overview"]
        except Exception:
            logger.exception("Failed reading echo scan cache %s", disk_path)
        embeddings, corpus = index
        data = _load_song_data(song_dir)
        lines = data["timed_lines"]
        from ..intertextuality.search import find_song_echoes
        try:
            echoes = find_song_echoes(
                [ln.text for ln in lines], embeddings, corpus,
                model_name=self.settings.embedding_model,
                exclude_song=info.get("title", ""),
                min_similarity=self.settings.echo_min_similarity,
                min_similarity_cjk=self.settings.echo_min_similarity_cjk,
                artist=info.get("artist") or None,
            )
        except Exception:
            logger.exception("Echo map failed for %s", song_dir)
            return "", _ECHO_OVERVIEW_EMPTY
        from ..intertextuality.echo_map import is_filler_line
        hits = [
            (ln, e) for ln, e in zip(lines, echoes)
            if e is not None and not is_filler_line(ln.text)
        ]
        anns = data["annotations"]

        def _note(i: int) -> str:
            a = anns.get(i)
            s = (a.summary or "").strip() if a else ""
            return s[:90] + "…" if len(s) > 90 else s

        payload = json.dumps({
            "song": info.get("title", ""),
            "lines": [
                {"i": ln.line_index, "song": e.song, "sim": e.similarity,
                 "target": e.line[:80], "note": _note(ln.line_index),
                 "ti": e.line_index,
                 "label": self.label_of().get(e.song, "")}
                for ln, e in hits
            ],
        }, ensure_ascii=False)
        overview = _render_echo_overview(hits, info.get("artist", ""))
        cache[song_dir] = (cache_key, payload, overview)
        try:
            _ECHO_SCAN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            disk_path.write_text(json.dumps(
                {"key": cache_key, "payload": payload, "overview": overview},
                ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed writing echo scan cache %s", disk_path)
        return payload, overview

    def corpus_artists(self) -> list[str]:
        """Distinct primary artists in the corpus (display-name order)."""
        index = self.echo_index()
        if index is None:
            return []
        from ..intertextuality.search import primary_artist
        names: dict[str, str] = {}
        for line in index[1]:
            key = primary_artist(line.artist)
            if key:
                names.setdefault(key, line.artist)
        return sorted(names.values(), key=str.lower)

    def artist_motifs(self, artist: str) -> dict[str, int]:
        """word -> n_songs for the artist's mined motifs (cached)."""
        cache = self.cache.setdefault("motifs", {})
        if artist not in cache:
            index = self.echo_index()
            if index is None:
                cache[artist] = {}
            else:
                cache[artist] = {m["word"]: m["n_songs"]
                                 for m in mine_motifs(index[1], artist)}
        return cache[artist]

    def quote_verifier(self):
        ctx = self.cache
        idx = ctx.get("quote_index")
        if idx is None or idx._songs is not ctx["songs"]:
            idx = QuoteIndex(ctx["songs"])
            ctx["quote_index"] = idx
        return idx.verify

    # ── 启动预热 ─────────────────────────────────────────

    def start_warm_up(self) -> None:
        threading.Thread(target=self._warm_up, daemon=True,
                         name="ll-warmup").start()

    def _warm_up(self) -> None:
        # the first echo query otherwise blocks 10-20s on model load; warm
        # the embedding model + corpus index in the background at startup
        try:
            self.echo_index()
            from ..intertextuality.search import get_model
            get_model(self.settings.embedding_model)
            # pre-mine motifs for the library's artists so the first
            # line-pick doesn't stall 1-3s on corpus tokenization
            index = self.cache.get("echo_index")
            if index:
                motif_cache = self.cache.setdefault("motifs", {})
                for artist in {s.get("artist", "")
                               for s in self.cache["songs"]}:
                    if artist and artist not in motif_cache:
                        try:
                            motif_cache[artist] = {
                                m["word"]: m["n_songs"]
                                for m in mine_motifs(index[1], artist)}
                        except Exception:
                            motif_cache[artist] = {}
            logger.info("Warm-up done: model + index + motifs ready")
        except Exception:
            logger.exception("Warm-up failed (features degrade gracefully)")
        self.kick_autobind()
