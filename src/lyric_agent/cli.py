"""CLI entry point for lyric-agent."""

from __future__ import annotations

import logging

import click


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """AI-powered lyrics annotation player."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@cli.command()
@click.argument("song_dir", type=click.Path(exists=True))
@click.option("--chunk-size", default=10, help="Lines per LLM call")
@click.option("--fresh", is_flag=True,
              help="ignore existing annotations and regenerate everything "
                   "(default resumes: good lines kept, failed lines redone)")
def generate(song_dir: str, chunk_size: int, fresh: bool) -> None:
    """Generate annotations for a song directory (resumable)."""
    from .annotator.engine import generate_annotations
    from .config import load_settings

    settings = load_settings(require_api_key=True)
    song = generate_annotations(settings, song_dir, chunk_size, fresh=fresh)
    click.echo(f"Generated {len(song.annotations)} annotations for '{song.metadata.title}'")


@cli.command()
@click.option("--port", default=None, type=int, help="UI port (default: from .env)")
@click.option("--no-browser", is_flag=True,
              help="don't auto-open the page in the default browser")
def serve(port: int | None, no_browser: bool) -> None:
    """Launch the lyrics annotation player UI."""
    import logging as _logging

    class _MuteProactorNoise(_logging.Filter):
        """Windows：浏览器刷新/关标签时 SSE 断开，asyncio proactor 会打
        ConnectionResetError 堆栈——无害但刷屏误导排障，定向静音。"""
        def filter(self, record):
            msg = str(record.getMessage()) + str(record.exc_info)
            return not ("ConnectionResetError" in msg
                        or "_call_connection_lost" in msg)

    _logging.getLogger("asyncio").addFilter(_MuteProactorNoise())
    from .review import TTS_CACHE_DIR as _TTS_CACHE_DIR
    from pathlib import Path

    from .config import load_settings
    from .ui import create_app, launch_kwargs

    from .auth import login_enabled, verify

    settings = load_settings()
    app = create_app(settings)
    auth_kwargs = {}
    if login_enabled():
        # data/users.json exists -> login required (lyric-agent users-add)
        auth_kwargs = {
            "auth": verify,
            "auth_message": "歌词透镜 — 请登录",
        }
    app.launch(
        server_port=port or settings.ui_port,
        share=False,
        # public deployments run headless — never pop a browser there
        inbrowser=not no_browser and not settings.public_mode,
        allowed_paths=[str(Path(settings.songs_dir).resolve()),
                       # ⌨️ 单词练习 word-pronunciation mp3s（与 review.py
                       # 共用一个常量，避免字面量漂移导致发音静默 404）
                       str(_TTS_CACHE_DIR.resolve())],
        **auth_kwargs,
        **launch_kwargs(),
    )


@cli.command("generate-all")
def generate_all() -> None:
    """Generate annotations for all songs in the songs directory."""
    from pathlib import Path

    from .annotator.engine import generate_annotations
    from .config import load_settings

    settings = load_settings()
    songs_dir = Path(settings.songs_dir)

    for song_dir in sorted(songs_dir.iterdir()):
        if not song_dir.is_dir():
            continue
        lrc = song_dir / "lyrics.lrc"
        if not lrc.exists():
            click.echo(f"Skipping {song_dir.name} (no lyrics.lrc)")
            continue
        click.echo(f"Processing {song_dir.name}...")
        try:
            song = generate_annotations(settings, song_dir)
            click.echo(f"  -> {len(song.annotations)} annotations")
        except Exception as exc:
            click.echo(f"  -> ERROR: {exc}", err=True)


@cli.command("build-evolution")
def build_evolution() -> None:
    """Aggregate era data into data/evolution/evolution.json."""
    from pathlib import Path

    from .config import load_settings
    from .evolution.engine import build_and_save

    settings = load_settings()
    out = Path(settings.evolution_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    evo = build_and_save(settings.songs_dir, out)
    demo = [e for e in evo.eras if e.songs]
    click.echo(f"Built {len(evo.eras)} eras ({len(demo)} with demo songs) -> {out}")


@cli.command()
@click.argument("query")
@click.option("--semantic", is_flag=True, help="Use semantic (embedding) search")
@click.option("--limit", default=10)
def search(query: str, semantic: bool, limit: int) -> None:
    """Search lyrics across all songs."""
    from .config import load_settings
    from .search import LyricsSearcher
    from .ui import _discover_songs

    settings = load_settings()
    searcher = LyricsSearcher(_discover_songs(settings.songs_dir),
                              model_name=settings.embedding_model)
    if semantic:
        hits, mode = searcher.semantic(query, limit)
    else:
        hits, mode = searcher.keyword(query, limit), "keyword"
    click.echo(f"[{mode}] {len(hits)} hit(s) for '{query}':")
    for h in hits:
        mm, ss = divmod(h.timestamp_ms // 1000, 60)
        click.echo(f"  {h.song_title} [{mm:02d}:{ss:02d}] {h.text}")


@cli.command()
@click.option("--root", type=click.Path(exists=True, file_okay=False),
              default=".",
              help="Project root containing data/ (Claude Desktop spawns "
                   "the process with an arbitrary cwd)")
def mcp(root: str) -> None:
    """Run the MCP server (stdio) for Claude Code / Claude Desktop."""
    # stdout is the MCP protocol — no click.echo/print on this path
    import os

    os.chdir(root)  # Settings paths (data/songs, data/corpus) are cwd-relative
    from .mcp_server import create_server
    create_server().run("stdio")


def _fetch_lrc_for(song_dir) -> int:
    """Fetch synced lyrics from LRCLIB into song_dir/lyrics.lrc. Returns line count."""
    import json
    from pathlib import Path

    from .lrc_sources import fetch_synced_lyrics

    d = Path(song_dir)
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    synced = fetch_synced_lyrics(meta.get("title", d.name),
                                 meta.get("artist", ""), timeout=30)
    if not synced:
        raise click.ClickException(f"No synced lyrics found on LRCLIB for {d.name}.")
    (d / "lyrics.lrc").write_text(synced, encoding="utf-8")
    return len(synced.splitlines())


@cli.command("fetch-lrc")
@click.argument("song_dir", type=click.Path(exists=True))
def fetch_lrc(song_dir: str) -> None:
    """Fetch synced lyrics from LRCLIB for a song directory (uses metadata.json)."""
    n = _fetch_lrc_for(song_dir)
    click.echo(f"Saved lyrics.lrc ({n} lines) to {song_dir}")


@cli.command()
@click.argument("song_dir", type=click.Path(exists=True))
def review(song_dir: str) -> None:
    """Interactively review and edit annotations for a song."""
    from .annotator.reviewer import review_song
    review_song(song_dir)


@cli.command("review-all")
def review_all() -> None:
    """Interactively review annotations for all songs."""
    from .annotator.reviewer import review_all as _review_all
    from .config import load_settings

    settings = load_settings()
    _review_all(settings.songs_dir)


@cli.command()
def embed() -> None:
    """Generate sentence embeddings for the lyrics corpus."""
    from .config import load_settings
    from .intertextuality.embeddings import generate_embeddings

    settings = load_settings()
    embeddings, corpus = generate_embeddings(
        settings.corpus_dir,
        model_name=settings.embedding_model,
    )
    click.echo(f"Generated embeddings: {embeddings.shape[0]} lines, {embeddings.shape[1]} dims")


@cli.command("retry-failed")
@click.argument("song_dir", type=click.Path(exists=True))
def retry_failed(song_dir: str) -> None:
    """Retry annotations that failed during generate (placeholder summaries)."""
    from pathlib import Path

    from .annotator.engine import regenerate_annotation
    from .annotator.models import Song
    from .config import load_settings

    ann_path = Path(song_dir) / "annotations.json"
    if not ann_path.exists():
        raise click.ClickException(f"No annotations.json in {song_dir}")

    song = Song.load(ann_path)
    failed = [
        (i, a) for i, a in enumerate(song.annotations)
        if a.summary == "[Annotation generation failed]"
    ]
    if not failed:
        click.echo("No failed annotations found.")
        return

    settings = load_settings(require_api_key=True)
    click.echo(f"Retrying {len(failed)} failed annotation(s)...")
    fixed = 0
    for i, ann in failed:
        try:
            song.annotations[i] = regenerate_annotation(
                settings, song.metadata, ann.line_index, ann.lyric_text
            )
            fixed += 1
            click.echo(f"  line {ann.line_index + 1}: OK")
        except Exception as exc:
            click.echo(f"  line {ann.line_index + 1}: FAILED ({exc})", err=True)

    if fixed:
        song.save(ann_path)
    click.echo(f"Fixed {fixed}/{len(failed)} — saved to {ann_path}" if fixed
               else "Nothing fixed; file unchanged.")


@cli.command("build-corpus")
@click.option("--bulk", type=click.Path(exists=True), default=None,
              help="Optional bulk lyrics JSONL ({title, album, lyrics} per line)")
def build_corpus_cmd(bulk: str | None) -> None:
    """Build data/corpus/discography.jsonl from song LRC files."""
    from .config import load_settings
    from .intertextuality.corpus import build_corpus

    settings = load_settings()
    n_songs, n_lines = build_corpus(
        settings.songs_dir, settings.corpus_dir, bulk,
        catalog_path="data/catalog/catalog.json",
    )
    click.echo(f"Saved {n_songs} songs, {n_lines} lines to {settings.corpus_dir}/discography.jsonl")


@cli.command()
@click.option("--skip-fetch", is_flag=True, help="Skip LRC fetching")
@click.option("--skip-embed", is_flag=True, help="Skip embedding generation")
def pipeline(skip_fetch: bool, skip_embed: bool) -> None:
    """Full pipeline: fetch LRC -> annotate all -> build corpus -> embed -> evolution."""
    from pathlib import Path

    from .annotator.engine import generate_annotations
    from .config import load_settings
    from .evolution.engine import build_and_save
    from .intertextuality.corpus import build_corpus

    settings = load_settings(require_api_key=True)
    songs_dir = Path(settings.songs_dir)
    song_dirs = [d for d in sorted(songs_dir.iterdir()) if d.is_dir()] if songs_dir.exists() else []

    if not skip_fetch:
        click.echo("== Step 1: fetch LRC from LRCLIB ==")
        for d in song_dirs:
            if (d / "lyrics.lrc").exists():
                click.echo(f"  {d.name}: already has lyrics.lrc, skipping")
                continue
            if not (d / "metadata.json").exists():
                continue
            try:
                n = _fetch_lrc_for(d)
                click.echo(f"  {d.name}: {n} lines")
            except Exception as exc:
                click.echo(f"  {d.name}: FAILED ({exc})", err=True)

    click.echo("== Step 2: generate annotations ==")
    for d in song_dirs:
        if not (d / "lyrics.lrc").exists():
            continue
        try:
            song = generate_annotations(settings, d)
            click.echo(f"  {d.name}: {len(song.annotations)} annotations")
        except Exception as exc:
            click.echo(f"  {d.name}: FAILED ({exc})", err=True)

    click.echo("== Step 3: build corpus ==")
    n_songs, n_lines = build_corpus(
        settings.songs_dir, settings.corpus_dir,
        catalog_path="data/catalog/catalog.json",
    )
    click.echo(f"  {n_songs} songs, {n_lines} lines")

    if not skip_embed:
        click.echo("== Step 4: generate embeddings ==")
        from .intertextuality.embeddings import generate_embeddings
        embeddings, _ = generate_embeddings(
            settings.corpus_dir, model_name=settings.embedding_model
        )
        click.echo(f"  {embeddings.shape[0]} lines embedded")

    click.echo("== Step 5: build evolution ==")
    out = Path(settings.evolution_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    build_and_save(settings.songs_dir, out)
    click.echo(f"  -> {out}")

    click.echo("Done. Launch the UI with: lyric-agent serve")


@cli.command("users-add")
@click.argument("username")
@click.option("--role", type=click.Choice(["admin", "viewer"]),
              default="viewer", help="admin sees management tabs")
def users_add(username: str, role: str) -> None:
    """Add/update a login account (creates data/users.json; enables login)."""
    from .auth import add_user
    password = click.prompt("Password", hide_input=True,
                            confirmation_prompt=True)
    add_user(username, password, role)
    click.echo(f"Saved '{username}' (role={role}). "
               "Login is now required on `lyric-agent serve`.")


@cli.command("users-list")
def users_list() -> None:
    """List login accounts (empty = login disabled)."""
    from .auth import load_users
    users = load_users()
    if not users:
        click.echo("no users — login disabled")
        return
    for name, u in users.items():
        role = u.get("role", "viewer") if isinstance(u, dict) else "?"
        click.echo(f"{name}\trole={role}")


@cli.command()
def doctor() -> None:
    """Check library & corpus health (duplicates, stale corpus, embeddings)."""
    from rich.console import Console
    from rich.table import Table

    from .config import load_settings
    from .doctor import run_all

    settings = load_settings()
    findings = run_all(settings.songs_dir, settings.corpus_dir)
    console = Console()
    if not findings:
        console.print("[green]✅ 曲库、语料库与 embeddings 均无问题。[/green]")
        return
    table = Table(title="lyric-agent doctor")
    table.add_column("级别", width=6)
    table.add_column("范围", width=10)
    table.add_column("问题")
    for f in findings:
        level = "[red]错误[/red]" if f.severity == "error" else "[yellow]警告[/yellow]"
        table.add_row(level, f.area, f.message)
    console.print(table)
    errors = sum(1 for f in findings if f.severity == "error")
    console.print(f"共 {len(findings)} 项（错误 {errors} / 警告 {len(findings) - errors}）")
    raise SystemExit(1 if errors else 0)
if __name__ == "__main__":
    cli()
