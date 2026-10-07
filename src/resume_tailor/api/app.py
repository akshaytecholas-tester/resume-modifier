"""The FastAPI application (spec-04 §1, §3).

One process, one port, one command. The API lives under `/api`; the built React
bundle is served as static files from the same origin, so there is no CORS
configuration — which would otherwise exist only to be a liability.

**Binds `127.0.0.1` explicitly, never `0.0.0.0`** (AC-R1.2). This process has
filesystem write access and an authenticated model session; exposing it to the
LAN would hand both to anyone on the network.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..kb.gitops import has_remote, history, is_repo, show
from ..kb.index import build_index
from ..kb.loader import load_corpus
from ..kb.paths import entry_path, repo_root
from ..kb.validate import validate_kb
from ..kb.write import (
    NotFound,
    WriteError,
    content_hash,
    delete_entry,
    read_entry,
    validate_only,
    write_entry,
    write_yaml_file,
)
from ..kb.yamlio import load_yaml
from ..pipeline.artifacts import Run, list_runs, run_slug
from ..pipeline.orchestrator import Pipeline
from ..pipeline.report import render_gap_report
from ..render.compile import compile_pdf
from ..render.compile import healthcheck as render_health
from ..render.document import apply_validation, document_from_draft
from ..render.latex import Geometry, render_document
from ..runtime import build_backend
from . import errors
from .events import Hub, KbWatcher

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class Context:
    """Paths and shared state, resolved once at startup."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or repo_root()).resolve()
        self.kb_dir = self.root / "kb"
        self.runs_dir = self.root / "runs"
        self.cache_dir = self.root / ".cache"
        self.config = Config.load(self.root)
        self.hub = Hub()
        self.watcher = KbWatcher(self.kb_dir, self.hub)

    def corpus(self):
        return load_corpus(self.kb_dir)


def create_app(root: Path | None = None) -> FastAPI:
    context = Context(root)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        context.watcher.start()
        try:
            yield
        finally:
            context.watcher.stop()

    app = FastAPI(
        title="resume-tailor",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.context = context
    errors.install(app)
    app.include_router(_router(context), prefix="/api")

    web = context.root / "web" / "dist"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    return app


def _router(context: Context) -> APIRouter:  # noqa: C901 — one route per endpoint
    router = APIRouter()

    # -- system ------------------------------------------------------------

    @router.get("/health")
    async def health() -> dict[str, Any]:
        corpus = context.corpus()
        backend = build_backend(context.config)
        report = await backend.healthcheck()
        capabilities = backend.capabilities
        tokens = corpus.estimated_tokens()

        fits, shortfall = True, 0
        try:
            capabilities.assert_corpus_fits(backend.name, tokens)
        except Exception as exc:
            fits = False
            shortfall = getattr(exc, "needed", 0) - getattr(exc, "available", 0)

        return {
            "backend": {
                "name": report.backend,
                "ok": report.ok,
                "credential": report.credential,
                "detail": report.detail,
                "window": capabilities.min_context_tokens,
                "overhead": capabilities.harness_overhead,
                "cost": capabilities.cost_per_run,
            },
            "render": render_health(),
            "corpus": {
                "entries": len(corpus.entries),
                "estimated_tokens": tokens,
                "fits_in_context": fits,
                "shortfall": max(0, shortfall),
                "parse_errors": len(corpus.parse_errors),
            },
            "kb": {
                "versioned": is_repo(context.kb_dir),
                # Surfaced because adding a remote is the single action that
                # would publish the career record (OQ-9).
                "has_remote": has_remote(context.kb_dir),
            },
        }

    @router.get("/events")
    async def kb_events() -> StreamingResponse:
        return StreamingResponse(
            context.hub.kb.subscribe(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    # -- knowledge base ----------------------------------------------------

    @router.get("/kb/index")
    async def kb_index() -> dict[str, Any]:
        return build_index(context.corpus())

    @router.get("/kb/validate")
    async def kb_validate() -> dict[str, Any]:
        report = validate_kb(context.kb_dir, context.corpus())
        return {
            "ok": report.ok,
            "errors": [_issue(i) for i in report.errors],
            "warnings": [_issue(i) for i in report.warnings],
        }

    @router.post("/kb/validate")
    async def kb_validate_candidate(payload: dict = Body(...)) -> dict[str, Any]:
        problems = validate_only(context.kb_dir, payload["type"], payload["id"], payload["raw"])
        return {"ok": not problems, "errors": problems}

    @router.get("/kb/{entry_type}/{entry_id}")
    async def kb_read(entry_type: str, entry_id: str) -> dict[str, Any]:
        return read_entry(context.kb_dir, entry_type, entry_id)

    @router.post("/kb/{entry_type}")
    async def kb_create(entry_type: str, payload: dict = Body(...)) -> dict[str, Any]:
        return _written(
            write_entry(
                context.kb_dir,
                entry_type,
                payload["id"],
                payload.get("raw") or payload.get("frontmatter") or {},
                payload.get("body", ""),
                cache_dir=context.cache_dir,
            )
        )

    @router.put("/kb/{entry_type}/{entry_id}")
    async def kb_update(
        entry_type: str, entry_id: str, payload: dict = Body(...)
    ) -> dict[str, Any]:
        return _written(
            write_entry(
                context.kb_dir,
                entry_type,
                entry_id,
                payload.get("raw") or payload.get("frontmatter") or {},
                payload.get("body", ""),
                base_hash=payload.get("base_hash"),
                cache_dir=context.cache_dir,
            )
        )

    @router.delete("/kb/{entry_type}/{entry_id}")
    async def kb_delete(entry_type: str, entry_id: str) -> dict[str, Any]:
        return {
            "deleted": entry_id,
            "commit": delete_entry(
                context.kb_dir, entry_type, entry_id, cache_dir=context.cache_dir
            ),
        }

    @router.get("/kb/{entry_type}/{entry_id}/history")
    async def kb_history(entry_type: str, entry_id: str) -> dict[str, Any]:
        path = entry_path(context.kb_dir, entry_type, entry_id)
        return {
            "commits": [
                {"sha": c.sha, "message": c.message, "when": c.when, "author": c.author}
                for c in history(context.kb_dir, path)
            ]
        }

    @router.post("/kb/{entry_type}/{entry_id}/revert")
    async def kb_revert(
        entry_type: str, entry_id: str, payload: dict = Body(...)
    ) -> dict[str, Any]:
        path = entry_path(context.kb_dir, entry_type, entry_id)
        previous = show(context.kb_dir, payload["sha"], path)
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        # Reverting writes through the same path as any other edit, so a
        # revert to a version that no longer validates is refused rather than
        # restoring a knowledge base the loader cannot read.
        return _written(
            write_entry(
                context.kb_dir,
                entry_type,
                entry_id,
                previous,
                base_hash=content_hash(current) if current else None,
                cache_dir=context.cache_dir,
                verb=f"revert {payload['sha'][:8]}",
            )
        )

    @router.get("/taxonomy")
    async def taxonomy_read() -> dict[str, Any]:
        path = context.kb_dir / "taxonomy.yaml"
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
        return {"terms": load_yaml(path) if path.is_file() else {}, "hash": content_hash(raw)}

    @router.put("/taxonomy")
    async def taxonomy_write(payload: dict = Body(...)) -> dict[str, Any]:
        return _written(
            write_yaml_file(
                context.kb_dir,
                "taxonomy.yaml",
                payload["terms"],
                base_hash=payload.get("base_hash"),
            )
        )

    # -- runs --------------------------------------------------------------

    @router.get("/runs")
    async def runs_list() -> dict[str, Any]:
        return {
            "runs": [
                {"id": r.id, "stages": r.completed_stages()} for r in list_runs(context.runs_dir)
            ]
        }

    @router.get("/runs/{run_id}")
    async def runs_read(run_id: str) -> dict[str, Any]:
        run = _run_or_404(context, run_id)
        return {
            "id": run.id,
            "stages": run.completed_stages(),
            **{stage: run.read(stage) for stage in run.completed_stages()},
        }

    @router.get("/runs/{run_id}/events")
    async def runs_events(run_id: str) -> StreamingResponse:
        return StreamingResponse(
            context.hub.run(run_id).subscribe(),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @router.post("/runs")
    async def runs_create(payload: dict = Body(...)) -> dict[str, Any]:
        posting = (payload.get("text") or "").strip()
        if not posting:
            raise WriteError(
                "no posting text supplied",
                remedy="Paste the posting, or fetch a URL and confirm the extracted text first.",
            )

        run = Run.create(context.runs_dir, run_slug(payload.get("role"), payload.get("company")))
        run.write("posting", posting)

        # Returns immediately; progress arrives on the SSE channel. A tailoring
        # run takes minutes, which is far longer than any sensible HTTP
        # timeout.
        asyncio.create_task(_execute(context, run, posting, payload))
        return {"run_id": run.id, "events": f"/api/runs/{run.id}/events"}

    @router.get("/runs/{run_id}/export.tex")
    async def runs_export_tex(run_id: str, contact_set: str = Query(None)) -> FileResponse:
        return FileResponse(_export(context, run_id, contact_set, compile_to_pdf=False))

    @router.get("/runs/{run_id}/export.pdf")
    async def runs_export_pdf(run_id: str, contact_set: str = Query(None)) -> FileResponse:
        return FileResponse(
            _export(context, run_id, contact_set, compile_to_pdf=True),
            media_type="application/pdf",
        )

    return router


# -- helpers ---------------------------------------------------------------


def _issue(issue) -> dict[str, Any]:
    return {
        "level": issue.level,
        "code": issue.code,
        "message": issue.message,
        "entry": issue.entry_id,
        "field": issue.field,
    }


def _written(result) -> dict[str, Any]:
    return {
        "hash": result.hash,
        "commit": result.commit,
        "path": result.path.name,
        "warnings": [_issue(w) for w in result.warnings],
    }


def _run_or_404(context: Context, run_id: str) -> Run:
    run = Run(context.runs_dir / run_id)
    if not run.directory.is_dir():
        raise NotFound(f"no run named {run_id!r}", remedy="List runs at /api/runs.")
    return run


async def _execute(context: Context, run: Run, posting: str, payload: dict) -> None:
    """Run the pipeline, streaming progress to the run's channel."""
    hub = context.hub

    def progress(stage: str, status: str, detail: dict) -> None:
        hub.publish_stage(run.id, stage, status, detail)

    try:
        pipeline = Pipeline(
            build_backend(context.config), context.corpus(), context.config, on_progress=progress
        )
        result = await pipeline.run(run, posting, bullets=int(payload.get("bullets", 9)))
        (run.directory / "gap-report.md").write_text(
            render_gap_report(
                result.requirements, result.selection, result.gaps, result.validation
            ),
            encoding="utf-8",
        )
        hub.run(run.id).publish(
            "done",
            {
                "run_id": run.id,
                "clean": result.clean,
                "gaps": len(result.gaps),
                "usage": vars(result.usage),
            },
        )
    except Exception as exc:
        # `resumable` tells the UI whether to offer a retry: every stage writes
        # before the next begins, so anything after the first is resumable.
        hub.run(run.id).publish(
            "error",
            {
                "message": str(exc),
                "code": type(exc).__name__,
                "resumable": bool(run.completed_stages()),
            },
        )


def _export(context: Context, run_id: str, contact_set: str | None, *, compile_to_pdf: bool):
    from ..kb.identity import load_identity

    run = _run_or_404(context, run_id)
    if not run.has("draft"):
        raise NotFound(
            f"run {run_id} has no draft yet",
            remedy="Wait for the writer stage, or resume the run.",
        )

    identity = load_identity(context.kb_dir / "identity.yaml")
    contact_set = contact_set or identity.default_set
    draft, _ = apply_validation(
        run.read("draft"), run.read("validation") if run.has("validation") else {}
    )
    document = document_from_draft(draft, context.corpus(), identity, contact_set)

    tex = run.directory / f"resume-{contact_set}.tex"
    tex.write_text(render_document(document, geometry=Geometry()), encoding="utf-8")
    if not compile_to_pdf:
        return tex
    return compile_pdf(tex, run.directory).pdf
