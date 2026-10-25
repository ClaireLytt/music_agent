"""Shared mutable app state (曾经是 create_app 里的 `ctx` 字典).

AppContext 仍然是 dict（历史 handler 都按 dict 用法访问），但把散落在
refresh_library / on_rebuild / on_manage_refresh 三处的缓存失效收敛成
具名方法，拆分后的各 tab 模块只调方法、不各自 pop 键。

键一览（值的生产者 → 消费者见 docs/architecture.md）：
  songs / searcher          曲库快照与语义搜索器
  echo_index / echo_maps    互文 embedding 索引 / 整歌彩蛋扫描缓存
  motifs / lyrics_blobs     各类懒加载缓存
  quote_index               考据引文校验索引
  lore_inflight             歌迷考据后台生成 in-flight 表
  autobind_running / corpus_rebuilding / kick_autobind
                            后台线程去重标志与回调
"""

from __future__ import annotations


class AppContext(dict):
    """dict + named cache-invalidation helpers."""

    def invalidate_library_views(self) -> None:
        """Library contents changed → drop everything derived from it."""
        self.pop("lyrics_blobs", None)

    def invalidate_echo_index(self) -> None:
        """Corpus/embeddings rebuilt → echo 索引和扫描结果全部作废."""
        for key in ("echo_index", "echo_maps"):
            self.pop(key, None)

    def invalidate_echo_scans(self) -> None:
        """All whole-song echo scans stale (e.g. manual library refresh)."""
        self.pop("echo_maps", None)

    def invalidate_song(self, song_dir: str) -> None:
        """One song's files changed/removed → drop its per-song caches."""
        self.setdefault("echo_maps", {}).pop(song_dir, None)


__all__ = ["AppContext"]
