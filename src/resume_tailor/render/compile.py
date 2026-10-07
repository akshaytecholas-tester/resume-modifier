"""Compiling LaTeX to PDF with Tectonic (spec-05 §2).

Tectonic is a single ~20MB binary that fetches packages on demand and caches
them, chosen over MacTeX (~5GB for one document) and a Docker LaTeX image (a
container runtime for a tool whose premise is running locally and simply).

The **first** compile needs network access to fetch packages; later ones are
offline. `healthcheck` reports both facts so a missing engine or a cold cache
surfaces at startup rather than at the moment the user wants a PDF.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TECTONIC = "tectonic"

#: Tectonic reports errors as `path:LINE: message`, and separately as a LaTeX
#: `l.LINE` echo. Both are tried, because which one appears depends on whether
#: the failure is in the file or inside a package.
_ERROR_LINE = re.compile(r"^(?P<file>[^\s:]+\.tex):(?P<line>\d+):\s*(?P<msg>.+)$", re.M)
_TEX_LINE = re.compile(r"^l\.(?P<line>\d+)\s*(?P<msg>.*)$", re.M)


class TectonicMissing(RuntimeError):
    """The engine is not installed. Carries the install command, not a trace."""

    def __init__(self) -> None:
        super().__init__(
            "tectonic is not installed. Install it with `brew install tectonic` "
            "(single binary, ~20MB). It is the LaTeX engine that turns the "
            "generated .tex into a PDF."
        )


@dataclass
class CompileError(RuntimeError):
    """A compile failure with the offending source line (AC-R6.2)."""

    message: str
    line: int | None = None
    source_line: str | None = None
    log: str = ""

    def __str__(self) -> str:
        where = f" at line {self.line}" if self.line else ""
        source = f"\n    {self.source_line.strip()}" if self.source_line else ""
        return f"LaTeX compile failed{where}: {self.message}{source}"


@dataclass
class CompileResult:
    pdf: Path
    pages: int
    #: Non-fatal LaTeX warnings worth surfacing — overfull boxes mostly, which
    #: are what a too-long unbreakable string looks like before it visibly
    #: runs into the margin.
    warnings: list[str] = field(default_factory=list)

    @property
    def overfull(self) -> list[str]:
        return [w for w in self.warnings if "overfull" in w.lower()]


def available() -> bool:
    return shutil.which(TECTONIC) is not None


def healthcheck() -> dict[str, object]:
    """What `/api/health` reports about rendering (spec-04 §3)."""
    path = shutil.which(TECTONIC)
    if path is None:
        return {"tectonic": False, "path": None, "version": None, "cache_warm": False}

    try:
        version = subprocess.run(
            [TECTONIC, "--version"], capture_output=True, text=True, timeout=15, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = None

    cache = _cache_dir()

    return {
        "tectonic": True,
        "path": path,
        "version": version,
        "cache_dir": str(cache) if cache else None,
        # A cold cache means the first compile downloads the package bundle:
        # over three minutes here, against 1.3s warm. Worth reporting, because
        # offline it is the difference between a quick render and a long hang.
        "cache_warm": bool(cache),
    }


def _cache_dir() -> Path | None:
    """Tectonic's package cache, if it exists and holds anything.

    Tectonic uses the `app_dirs2` crate, which on macOS produces
    `~/Library/Caches/TectonicProject.Tectonic` — not `.../Tectonic`, which an
    earlier version of this function looked for and never found. It reported a
    cold cache on a machine compiling in 1.3s, which would have set a 900s
    timeout on every warm compile.
    """
    candidates = [
        Path(os.environ["TECTONIC_CACHE_DIR"]) if os.environ.get("TECTONIC_CACHE_DIR") else None,
        Path.home() / "Library" / "Caches" / "TectonicProject.Tectonic",
        Path.home() / ".cache" / "Tectonic",
        Path(os.environ["XDG_CACHE_HOME"]) / "Tectonic"
        if os.environ.get("XDG_CACHE_HOME")
        else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return None


def page_count(pdf: Path) -> int:
    """Page count via `pdfinfo`, falling back to counting `/Type /Page`.

    The fallback matters because the page count drives the overflow report
    (spec-05 §6), and poppler is a convenience on this machine rather than a
    declared dependency of the project.
    """
    if shutil.which("pdfinfo"):
        out = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, check=False
        ).stdout
        match = re.search(r"^Pages:\s+(\d+)$", out, re.M)
        if match:
            return int(match.group(1))

    data = pdf.read_bytes()
    return max(1, data.count(b"/Type /Page") - data.count(b"/Type /Pages"))


def _explain(log: str, tex_source: str) -> CompileError:
    source_lines = tex_source.splitlines()

    for pattern in (_ERROR_LINE, _TEX_LINE):
        match = pattern.search(log)
        if match:
            line = int(match.group("line"))
            source = source_lines[line - 1] if 0 < line <= len(source_lines) else None
            return CompileError(match.group("msg").strip(), line, source, log)

    tail = "\n".join(log.strip().splitlines()[-12:])
    return CompileError(tail or "tectonic produced no diagnostic output", log=log)


#: Warm compiles take about a second. The *first* one downloads Tectonic's
#: package bundle over the network, which took over three minutes here, so the
#: default has to accommodate a cold cache or the very first render of a fresh
#: install fails for a reason that has nothing to do with the document.
COLD_TIMEOUT = 900
WARM_TIMEOUT = 120


def compile_pdf(
    tex_path: Path, outdir: Path | None = None, *, timeout: int | None = None
) -> CompileResult:
    """Compile a `.tex` file. Raises `CompileError` rather than leaving a stub.

    AC-R6.2 requires a failure to name the offending source line and never
    produce an empty file. A zero-byte PDF that opens blank is worse than an
    error, because it looks like it worked.
    """
    if not available():
        raise TectonicMissing

    tex_path = tex_path.resolve()
    outdir = (outdir or tex_path.parent).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    warm = bool(healthcheck().get("cache_warm"))
    if timeout is None:
        timeout = WARM_TIMEOUT if warm else COLD_TIMEOUT

    try:
        proc = subprocess.run(
            [TECTONIC, "--outdir", str(outdir), "--keep-logs", str(tex_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # A raw TimeoutExpired traceback tells the user nothing actionable, and
        # spec-04 §8 requires every error to carry a remedy.
        (outdir / f"{tex_path.stem}.pdf").unlink(missing_ok=True)
        remedy = (
            "the package cache is cold, so this compile had to download Tectonic's "
            "bundle. Check network access and retry; later compiles take about a second."
            if not warm
            else "the cache is warm, so this is unexpected — check for a runaway macro "
            "or a pathological table in the template."
        )
        raise CompileError(
            f"tectonic did not finish within {timeout}s. {remedy}",
            log=str(exc),
        ) from exc

    log = f"{proc.stdout}\n{proc.stderr}"
    pdf = outdir / f"{tex_path.stem}.pdf"

    if proc.returncode != 0:
        pdf.unlink(missing_ok=True)
        raise _explain(log, tex_path.read_text(encoding="utf-8"))

    if not pdf.is_file() or pdf.stat().st_size == 0:
        pdf.unlink(missing_ok=True)
        raise CompileError("tectonic reported success but produced no PDF", log=log)

    warnings = [
        line.strip()
        for line in log.splitlines()
        if "warning" in line.lower() or "overfull" in line.lower()
    ]
    return CompileResult(pdf=pdf, pages=page_count(pdf), warnings=warnings)


@dataclass
class OverflowReport:
    """Length budget outcome (spec-05 §6).

    Reports; never truncates. Dropping content automatically to fit a page is a
    silent omission — the precise failure this product exists to prevent.
    """

    pages: int
    budget: int
    over: bool
    candidates: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        if not self.over:
            return f"{self.pages} page(s), within the {self.budget}-page budget"
        return (
            f"{self.pages} page(s), over the {self.budget}-page budget. "
            f"{len(self.candidates)} bullet(s) identified as cut candidates — "
            "nothing has been removed; this is yours to decide."
        )


def check_overflow(result: CompileResult, doc, budget: int = 1) -> OverflowReport:
    """Compare the compiled page count against the budget.

    Cut candidates are the last bullets of the oldest entries: on a resume that
    runs long, the weakest material is almost always the oldest, and ordering by
    a model's relevance score would make the suggestion unreproducible.
    """
    if result.pages <= budget:
        return OverflowReport(result.pages, budget, over=False)

    candidates: list[tuple[str, str]] = []
    for section in reversed(doc.rendered_sections):
        for entry in reversed(getattr(section, "entries", ())):
            for bullet in reversed(entry.bullets):
                candidates.append((entry.title, bullet.lead or bullet.text[:60]))
    return OverflowReport(result.pages, budget, over=True, candidates=candidates)
