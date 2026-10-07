"""`rt` — the command line over the knowledge base and, later, the pipeline.

Exists ahead of the web UI on purpose: plain files are the state (spec-01 P1),
so validating and inspecting them must not require a running server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from .config import Config
from .kb.identity import load_identity
from .kb.index import write_index
from .kb.loader import load_corpus
from .kb.paths import repo_root
from .kb.validate import validate_kb
from .pipeline.artifacts import Run, run_slug
from .pipeline.orchestrator import Pipeline
from .pipeline.report import render_gap_report
from .render.compile import (
    CompileError,
    TectonicMissing,
    check_overflow,
    compile_pdf,
    healthcheck,
)
from .render.document import VisibilityViolation, apply_validation, document_from_draft
from .render.latex import Geometry, render_baseline, render_document
from .runtime import BackendError, ContextExceeded, build_backend

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

    # The defaults ARE the source document's measurements, so there is no
    # "corrected" variant to opt out of.
    geometry = Geometry()

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
def health(
    root: Path | None = ROOT_OPTION,
    backend: str | None = typer.Option(None, "--backend", help="Check this backend instead."),
) -> None:
    """Model backend, render toolchain and corpus status (spec-04 §3)."""
    base, kb_dir, _ = _resolve(root)
    config = Config.load(base)

    typer.secho("render", bold=True)
    for key, value in healthcheck().items():
        typer.echo(f"  {key:<14} {value}")

    corpus = load_corpus(kb_dir)
    tokens = corpus.estimated_tokens()
    typer.secho("\ncorpus", bold=True)
    typer.echo(f"  {'entries':<14} {len(corpus.entries)}")
    typer.echo(f"  {'est. tokens':<14} {tokens:,}  (chars/4 — an estimate)")

    typer.secho("\nmodel backend", bold=True)
    name = backend or config.backend_name()
    if config.source:
        typer.echo(f"  {'config':<14} {config.source.relative_to(base)}")
    try:
        runner = build_backend(config, name)
    except BackendError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    report = asyncio.run(runner.healthcheck())
    caps = runner.capabilities
    typer.echo(f"  {'backend':<14} {report.backend}")
    typer.echo(f"  {'auth':<14} {report.credential}")
    typer.echo(f"  {'window':<14} {caps.min_context_tokens:,} tokens")
    typer.echo(f"  {'overhead':<14} {caps.harness_overhead:,} tokens/call")
    typer.echo(f"  {'cost':<14} {caps.cost_per_run}")
    if report.version:
        typer.echo(f"  {'version':<14} {report.version}")
    typer.secho(
        f"  {'status':<14} {'ok' if report.ok else 'unavailable'}"
        + (f" — {report.detail}" if report.detail else ""),
        fg=typer.colors.GREEN if report.ok else typer.colors.RED,
    )

    # The gate that refuses rather than chunks (spec-06 §4). Reported here so a
    # corpus that has outgrown the model surfaces before a run, not during one.
    try:
        caps.assert_corpus_fits(report.backend, tokens)
        typer.secho(f"  {'context':<14} corpus fits", fg=typer.colors.GREEN)
    except ContextExceeded as exc:
        typer.secho(f"  {'context':<14} {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@app.command("tailor")
def tailor(
    text: str | None = typer.Option(None, "--text", help="The job posting, pasted."),
    file: Path | None = typer.Option(None, "--file", help="Read the posting from a file."),
    root: Path | None = ROOT_OPTION,
    company: str | None = typer.Option(None, "--company", help="Used in the run's folder name."),
    bullets: int = typer.Option(9, "--bullets", help="Bullet budget for the Writer."),
    sequential: bool = typer.Option(
        False, "--sequential", help="Run Recall after the Selector, so it can see its picks."
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Render and compile the result."),
    resume_run: str | None = typer.Option(
        None, "--resume", help="Continue an existing run from its last completed stage."
    ),
) -> None:
    """Tailor the resume to a job posting — the full five-agent pipeline."""
    base, kb_dir, _ = _resolve(root)
    config = Config.load(base)

    posting = (file.read_text(encoding="utf-8") if file else text or "").strip()
    if not posting and not resume_run:
        typer.secho("give me the posting: --text or --file", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            "knowledge base has parse errors; run `rt kb validate`", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    runs_dir = base / "runs"
    if resume_run:
        run = Run(runs_dir / resume_run)
        if not run.directory.is_dir():
            typer.secho(f"no run named {resume_run!r} under runs/", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        posting = posting or run.read("posting")
        typer.echo(f"resuming {run.id} — done: {', '.join(run.completed_stages()) or 'nothing'}")
    else:
        run = Run.create(runs_dir, run_slug(_guess_role(posting), company))

    def progress(stage: str, status: str, detail: dict) -> None:
        if status == "running":
            typer.secho(f"  {stage:<10} running...", fg=typer.colors.CYAN, nl=False)
            typer.echo("\r", nl=False)
        elif status == "skipped":
            typer.secho(f"  {stage:<10} skipped ({detail.get('reason')})", fg=typer.colors.BLUE)
        else:
            repairs = f"  repairs={detail['repairs']}" if detail.get("repairs") else ""
            typer.secho(
                f"  {stage:<10} done   in={detail.get('input', 0):>7,} "
                f"out={detail.get('output', 0):>6,} cached={detail.get('cached', 0):>7,}{repairs}",
                fg=typer.colors.GREEN,
            )

    backend = build_backend(config)
    pipeline = Pipeline(backend, corpus, config, on_progress=progress)

    typer.secho(f"\nrun {run.id}  —  backend {backend.name}", bold=True)
    try:
        result = asyncio.run(pipeline.run(run, posting, bullets=bullets, concurrent=not sequential))
    except ContextExceeded as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    except BackendError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        typer.secho(f"resume with: rt tailor --resume {run.id}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1) from exc

    counts = result.selection.to_dict()["counts"]
    typer.secho("\nselection", bold=True)
    typer.echo(
        f"  {counts['total']} facts  "
        f"({counts['both']} both passes, {counts['selector_only']} selector only, "
        f"{counts['recall_only']} recall only)  —  {counts['rejected']} considered and rejected"
    )

    report = render_gap_report(
        result.requirements, result.selection, result.gaps, result.validation
    )
    (run.directory / "gap-report.md").write_text(report, encoding="utf-8")

    absent = [g for g in result.gaps if g["status"] == "absent"]
    weak = [g for g in result.gaps if g["status"] == "weak"]
    typer.secho("\ngaps", bold=True)
    typer.secho(
        f"  {len(absent)} absent, {len(weak)} weak",
        fg=typer.colors.YELLOW if result.gaps else typer.colors.GREEN,
    )
    for gap in absent[:5]:
        typer.echo(f"    absent: {gap['text']}")

    cuts = result.validation.get("cuts") or []
    warnings = result.validation.get("warnings") or []
    typer.secho("\nvalidator", bold=True)
    typer.secho(
        f"  {len(cuts)} cut, {len(warnings)} flagged",
        fg=typer.colors.GREEN if result.clean else typer.colors.YELLOW,
    )
    for cut in cuts[:3]:
        typer.echo(f"    cut: {cut.get('reason')}")

    draft, notes = apply_validation(result.draft, result.validation)
    for note in notes[:3]:
        typer.echo(f"    {note}")

    # Prompt tokens are input + cache reads. Reporting `input_tokens` alone
    # showed "in 66" on a run that sent 49,000 tokens, because the corpus was
    # served from cache and Anthropic counts that separately — a number that
    # looks like the cost and is not.
    usage = result.usage
    prompt_tokens = usage.input_tokens + usage.cache_read_tokens
    typer.secho("\ntokens", bold=True)
    typer.echo(
        f"  prompt {prompt_tokens:,}  ({usage.cache_read_tokens:,} from cache)  "
        f"output {usage.output_tokens:,}"
    )
    if prompt_tokens:
        saved = usage.cache_read_tokens / prompt_tokens
        typer.echo(f"  {saved:.0%} of the prompt was cached across the five agents")

    identity_path = kb_dir / "identity.yaml"
    if not identity_path.is_file():
        typer.secho("\nkb/identity.yaml missing — not rendering", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    identity = load_identity(identity_path)
    typer.secho("\noutput", bold=True)
    for contact_set in identity.set_names:
        document = document_from_draft(draft, corpus, identity, contact_set)
        tex_path = run.directory / f"resume-{contact_set}.tex"
        tex_path.write_text(render_document(document, geometry=Geometry()), encoding="utf-8")
        typer.echo(f"  {tex_path.relative_to(base)}")

        if not pdf:
            continue
        try:
            compiled = compile_pdf(tex_path, run.directory)
        except (TectonicMissing, CompileError) as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            continue
        typer.echo(f"  {compiled.pdf.relative_to(base)}")
        overflow = check_overflow(compiled, document, budget=config.page_budget)
        typer.secho(
            f"      {overflow.summary()}",
            fg=typer.colors.YELLOW if overflow.over else typer.colors.GREEN,
        )

    typer.echo(f"  {(run.directory / 'gap-report.md').relative_to(base)}")


def _guess_role(posting: str) -> str:
    """A slug from the posting's first substantial line.

    Only ever used for a folder name, so a poor guess is cosmetic. The
    application archive (M7) takes the role from the user explicitly, where
    getting it right actually matters.
    """
    for line in posting.splitlines():
        line = line.strip()
        if 3 < len(line) < 80:
            return line
    return "posting"


@app.command("serve")
def serve(
    root: Path | None = ROOT_OPTION,
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes."),
) -> None:
    """Run the local web interface.

    Binds 127.0.0.1 only, never 0.0.0.0 (AC-R1.2). This process has filesystem
    write access and an authenticated model session; putting it on the LAN
    would hand both to anyone on the network.
    """
    import uvicorn

    base, _, _ = _resolve(root)
    typer.secho(f"  http://127.0.0.1:{port}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  serving {base}")
    if not (base / "web" / "dist").is_dir():
        typer.secho(
            "  no web/dist yet — API only (the UI is M6). Try /api/health.",
            fg=typer.colors.YELLOW,
        )

    uvicorn.run(
        "resume_tailor.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
