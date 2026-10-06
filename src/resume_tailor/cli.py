"""`rt` — the command line over the knowledge base and, later, the pipeline.

Exists ahead of the web UI on purpose: plain files are the state (spec-01 P1),
so validating and inspecting them must not require a running server.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .kb.index import write_index
from .kb.loader import load_corpus
from .kb.paths import repo_root
from .kb.validate import validate_kb

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
kb_app = typer.Typer(no_args_is_help=True, help="Inspect and validate the knowledge base.")
app.add_typer(kb_app, name="kb")

ROOT_OPTION = typer.Option(
    None, "--root", help="Project root; defaults to the nearest ancestor holding kb/."
)


def _resolve(root: Path | None) -> tuple[Path, Path, Path]:
    base = (root or repo_root()).resolve()
    kb_dir = base / "kb"
    if not kb_dir.is_dir():
        typer.secho(f"no kb/ directory under {base}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    return base, kb_dir, base / ".cache"


@kb_app.command("validate")
def kb_validate(
    root: Path | None = ROOT_OPTION,
    warnings_as_errors: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
) -> None:
    """Check every entry against the ten rules in spec-01 §4."""
    base, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)
    report = validate_kb(kb_dir, corpus)

    for issue in report.errors:
        typer.secho(f"  {issue}", fg=typer.colors.RED)
    for issue in report.warnings:
        typer.secho(f"  {issue}", fg=typer.colors.YELLOW)

    typer.echo(
        f"\n{len(corpus.entries)} entries · {len(report.errors)} errors · "
        f"{len(report.warnings)} warnings"
    )

    if report.errors or (warnings_as_errors and report.warnings):
        raise typer.Exit(1)
    typer.secho("OK", fg=typer.colors.GREEN)


@kb_app.command("index")
def kb_index(root: Path | None = ROOT_OPTION) -> None:
    """Rebuild `.cache/index.json`. Safe to run at any time."""
    _, kb_dir, cache_dir = _resolve(root)
    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            f"{len(corpus.parse_errors)} file(s) failed to parse and are absent from the "
            "index; run `rt kb validate`",
            fg=typer.colors.YELLOW,
            err=True,
        )
    target = write_index(corpus, cache_dir)
    typer.echo(f"wrote {target} ({len(corpus.entries)} entries)")


@kb_app.command("stats")
def kb_stats(root: Path | None = ROOT_OPTION) -> None:
    """Corpus size and shape — the numbers OQ-2 is tracked against."""
    _, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)

    for entry_type in ("role", "fact", "project", "blog", "education", "certification", "award"):
        rows = corpus.of_type(entry_type)
        if rows:
            typer.echo(f"  {entry_type:<14} {len(rows):>4}")

    tokens = corpus.estimated_tokens()
    typer.echo(f"\n  taxonomy terms {len(corpus.taxonomy):>4}")
    typer.echo(f"  declared skills{len(corpus.skills):>5}")
    typer.echo(f"\n  entries        {len(corpus.entries):>4}")
    typer.echo(f"  est. tokens  {tokens:>6}  (chars/4 — an estimate, not a count)")

    # OQ-2's provisional trigger for revisiting full-corpus selection.
    if len(corpus.entries) >= 500 or tokens >= 100_000:
        typer.secho(
            "\n  Past the OQ-2 trigger (500 entries / 100K tokens). Re-examine whether "
            "full-corpus selection still holds.",
            fg=typer.colors.YELLOW,
        )

    for depth in ("expert", "working", "exposure"):
        count = sum(1 for e in corpus.entries if e.meta.depth == depth)
        if count:
            typer.echo(f"  depth:{depth:<9} {count:>4}")

    hidden = [e.id for e in corpus.entries if e.meta.visibility != "public"]
    if hidden:
        typer.echo(f"\n  non-public (never exported): {', '.join(hidden)}")


if __name__ == "__main__":
    app()
