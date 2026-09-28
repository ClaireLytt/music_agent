"""CLI tool for reviewing and editing generated annotations.

Provides an interactive terminal workflow to:
1. View annotations line by line
2. Accept, edit, or regenerate individual annotations
3. Mark quality issues for re-generation
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .models import Song

console = Console()


def review_song(song_dir: str | Path) -> None:
    """Interactive review session for a song's annotations."""
    song_dir = Path(song_dir)
    ann_path = song_dir / "annotations.json"

    if not ann_path.exists():
        console.print(f"[red]No annotations.json in {song_dir}[/red]")
        console.print("Run `lyric-agent generate` first.")
        return

    song = Song.load(ann_path)
    console.print(
        Panel(
            f"[bold]{song.metadata.title}[/bold] — {song.metadata.album} ({song.metadata.year})\n"
            f"Era: {song.metadata.era} | {len(song.annotations)} annotations",
            title="Review Session",
        )
    )

    modified = False
    reviewed = 0
    i = 0
    while i < len(song.annotations):
        ann = song.annotations[i]
        console.print(
            f"\n[dim]─── Annotation {i + 1}/{len(song.annotations)}"
            f" · Lyric line {ann.line_index + 1} ───[/dim]"
        )
        console.print(f'[bold cyan]"{ann.lyric_text}"[/bold cyan]\n')

        table = Table(show_header=False, border_style="dim", pad_edge=False)
        table.add_column("Field", style="bold", min_width=12)
        table.add_column("Content")

        table.add_row("Summary", ann.summary or "[dim]empty[/dim]")
        table.add_row("Metaphor", ann.metaphor_analysis or "[dim]—[/dim]")
        table.add_row("Allusions", ", ".join(ann.allusions) if ann.allusions else "[dim]—[/dim]")
        table.add_row("Wordplay", ann.wordplay or "[dim]—[/dim]")
        table.add_row("Tone", ann.emotional_tone or "[dim]—[/dim]")
        table.add_row("Cultural", ann.cultural_context or "[dim]—[/dim]")
        table.add_row("TS Context", ann.taylor_swift_context or "[dim]—[/dim]")

        if ann.related_lines:
            related = "\n".join(
                f'  "{r.line}" — {r.song} ({r.album})'
                for r in ann.related_lines
            )
            table.add_row("Related", related)

        console.print(table)

        action = Prompt.ask(
            "\n[bold]Action[/bold] (a=accept e=edit r=regenerate s=skip d=delete q=quit)",
            choices=["a", "e", "r", "s", "d", "q"],
            default="a",
        )

        if action == "a":  # accept
            reviewed += 1
            i += 1
        elif action == "e":  # edit a field
            if _edit_annotation(ann):
                modified = True
            reviewed += 1
            i += 1
        elif action == "r":  # regenerate via LLM
            if _regenerate(song, ann, i):
                modified = True
                reviewed += 1
                i += 1
            # on failure stay on the same annotation
        elif action == "s":  # skip (go to next)
            reviewed += 1
            i += 1
        elif action == "d":  # delete this annotation
            if Confirm.ask("Delete this annotation?"):
                song.annotations.pop(i)
                modified = True
                reviewed += 1
                console.print("[yellow]Deleted[/yellow]")
            # don't increment i
        elif action == "q":  # quit
            break

    if modified:
        if Confirm.ask("\nSave changes?"):
            song.save(ann_path)
            console.print(f"[green]Saved to {ann_path}[/green]")
        else:
            console.print("[yellow]Changes discarded[/yellow]")

    # Print summary
    console.print(
        Panel(
            f"Reviewed: {reviewed}/{len(song.annotations)} annotations\n"
            f"Modified: {'Yes' if modified else 'No'}",
            title="Review Complete",
        )
    )


_EDITABLE_FIELDS = {
    "summary": "summary",
    "metaphor": "metaphor_analysis",
    "allusions": "allusions",
    "wordplay": "wordplay",
    "tone": "emotional_tone",
    "cultural": "cultural_context",
    "ts": "taylor_swift_context",
}


def _edit_annotation(ann) -> bool:
    """Edit any field of an annotation. Returns True if modified."""
    field_key = Prompt.ask(
        "Which field?",
        choices=list(_EDITABLE_FIELDS),
        default="summary",
    )
    attr = _EDITABLE_FIELDS[field_key]
    current = getattr(ann, attr)
    if attr == "allusions":
        default = ", ".join(current) if current else ""
        raw = Prompt.ask("New allusions (comma-separated)", default=default)
        new_value: object = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        new_value = Prompt.ask(f"New {field_key}", default=current or "")
    if new_value == current:
        return False
    setattr(ann, attr, new_value)
    console.print(f"[green]Updated {field_key}[/green]")
    return True


def _regenerate(song: Song, ann, index: int) -> bool:
    """Regenerate one annotation via the LLM. Returns True on success."""
    from ..config import load_settings
    from .engine import regenerate_annotation

    try:
        settings = load_settings(require_api_key=True)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return False

    console.print("[dim]Regenerating via LLM...[/dim]")
    try:
        new_ann = regenerate_annotation(
            settings, song.metadata, ann.line_index, ann.lyric_text
        )
    except Exception as exc:
        console.print(f"[red]Regeneration failed: {exc}[/red]")
        return False

    song.annotations[index] = new_ann
    console.print("[green]Regenerated[/green]")
    return True


def review_all(songs_dir: str | Path) -> None:
    """Review all songs in the songs directory."""
    songs_dir = Path(songs_dir)
    for song_dir in sorted(songs_dir.iterdir()):
        if not song_dir.is_dir():
            continue
        ann_path = song_dir / "annotations.json"
        if not ann_path.exists():
            continue
        console.print(f"\n[bold]{'='*50}[/bold]")
        if Confirm.ask(f"Review {song_dir.name}?"):
            review_song(song_dir)
