"""`rt` — the command line over the knowledge base and, later, the pipeline.

Exists ahead of the web UI on purpose: plain files are the state (spec-01 P1),
so validating and inspecting them must not require a running server.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .kb.identity import load_identity
from .kb.index import write_index
from .kb.loader import load_corpus
from .kb.paths import repo_root
from .kb.validate import validate_kb
from .render.compile import (
    CompileError,
    TectonicMissing,
    check_overflow,
    compile_pdf,
    healthcheck,
)
from .render.document import VisibilityViolation
from .render.latex import Geometry, render_baseline

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


@app.command("render")
def render(
    root: Path | None = ROOT_OPTION,
    out: Path | None = typer.Option(None, "--out", help="Output directory; default runs/baseline."),
    contact_set: str | None = typer.Option(
        None, "--contact-set", help="Render only this set; default renders every configured set."
    ),
    summary_file: Path | None = typer.Option(
        None, "--summary-file", help="Prose for the Summary section. Tailored per JD from M4 on."
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Compile with Tectonic."),
    budget: int = typer.Option(1, "--budget", help="Page budget; overflow is reported, never cut."),
    exact_source_margins: bool = typer.Option(
        False, "--exact-source-margins", help="Reproduce the source PDF's asymmetric margins."
    ),
) -> None:
    """Render the whole knowledge base to LaTeX and PDF — no agents involved.

    This is the baseline: everything, in knowledge-base order, with no selection
    and no rewriting. It is what proves AC-R7.1 and the reference the template
    is checked against.
    """
    base, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            "knowledge base has parse errors; run `rt kb validate`", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    identity_path = kb_dir / "identity.yaml"
    if not identity_path.is_file():
        typer.secho(
            "kb/identity.yaml not found — copy kb/identity.example.yaml to it and fill it in",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    identity = load_identity(identity_path)

    sets = [contact_set] if contact_set else identity.set_names
    for name in sets:
        if name not in identity.contacts:
            typer.secho(
                f"no contact set named {name!r}; have: {', '.join(sorted(identity.contacts))}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2)

    outdir = (out or base / "runs" / "baseline").resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    summary = summary_file.read_text(encoding="utf-8").strip() if summary_file else None

    geometry = Geometry(right="0.2in") if exact_source_margins else Geometry()

    for name in sets:
        try:
            doc, tex = render_baseline(corpus, identity, name, summary=summary, geometry=geometry)
        except VisibilityViolation as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

        tex_path = outdir / f"resume-{name}.tex"
        tex_path.write_text(tex, encoding="utf-8")
        typer.echo(f"  {tex_path.relative_to(base)}  ({len(doc.sources)} sources)")

        if not pdf:
            continue
        try:
            result = compile_pdf(tex_path, outdir)
        except TectonicMissing as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        except CompileError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

        typer.echo(f"  {result.pdf.relative_to(base)}")
        overflow = check_overflow(result, doc, budget=budget)
        colour = typer.colors.YELLOW if overflow.over else typer.colors.GREEN
        typer.secho(f"      {overflow.summary()}", fg=colour)
        for title, lead in overflow.candidates[:5]:
            typer.echo(f"        cut candidate: {title} - {lead}")
        for warning in result.overfull[:3]:
            typer.secho(f"      {warning}", fg=typer.colors.YELLOW)


@app.command("health")
def health(root: Path | None = ROOT_OPTION) -> None:
    """Render toolchain and corpus status."""
    base, kb_dir, _ = _resolve(root)
    for key, value in healthcheck().items():
        typer.echo(f"  {key:<12} {value}")
    corpus = load_corpus(kb_dir)
    typer.echo(f"  {'entries':<12} {len(corpus.entries)}")
    typer.echo(f"  {'est. tokens':<12} {corpus.estimated_tokens()}")


if __name__ == "__main__":
    app()
