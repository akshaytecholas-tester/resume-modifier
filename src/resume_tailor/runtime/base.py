"""The one interface every model backend implements (spec-03 §2).

All agent invocation goes through `RunnerBackend`. No pipeline or agent code
references a backend directly, so swapping Claude for Codex or a local model is
configuration rather than a change to the pipeline (AC-R15.1).

The contract is the simplest one that exists — **string in, JSON out**. Agents
are given no tools ([spec-02 §5](../../../docs/spec-02-agent-pipeline.md)), so
nothing here needs tool loops, MCP, hooks or file access. That is what makes
supporting other providers additive work rather than a redesign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: Tokens left free for the model's own reply and for prompt scaffolding.
#: Not a tuning knob so much as an admission that `corpus + overhead` is a
#: floor, not the real requirement.
DEFAULT_HEADROOM = 8_000


class BackendError(RuntimeError):
    """Base for every backend failure that should reach the user as prose."""


class BackendAuthError(BackendError):
    """Authentication failed (AC-R15.3).

    Carries the backend and the credential it expected, never a stack trace.
    The two common failures — an expired OAuth session and a missing API key —
    look identical in a traceback and have completely different fixes.
    """

    def __init__(self, backend: str, credential: str, detail: str = "") -> None:
        self.backend = backend
        self.credential = credential
        self.detail = detail
        message = f"{backend}: authentication failed. Expected {credential}."
        if detail:
            message += f" ({detail})"
        super().__init__(message)


class ContextExceeded(BackendError):
    """The corpus does not fit in this backend's context window.

    **Raised instead of chunking, always.** Chunked selection silently
    reintroduces the lossy retrieval AC-R11.3 forbids, and the resulting
    omissions are invisible — the exact failure this product exists to prevent.
    A loud refusal is correct here; graceful degradation is not graceful.
    """

    def __init__(self, backend: str, needed: int, available: int, corpus: int) -> None:
        self.backend = backend
        self.needed = needed
        self.available = available
        super().__init__(
            f"{backend}: the knowledge base does not fit in this model's context. "
            f"Need ~{needed:,} tokens ({corpus:,} of corpus plus overhead and headroom), "
            f"window is {available:,}. Short by {needed - available:,}.\n"
            "Selection reads every fact in one pass by design, so this cannot be "
            "worked around by splitting the corpus. Use a model with a larger window."
        )


class ModelRefusedJSON(BackendError):
    """The model would not produce parseable JSON after a repair attempt.

    Failing here is deliberate: a half-parsed object passed downstream produces
    a resume built on fields that silently defaulted.
    """


@dataclass(frozen=True)
class Usage:
    """Token accounting, normalised across backends.

    Surfaced per run in the UI so cost accrues visibly rather than being
    discovered when a rate limit lands mid-session (RK-2).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class AgentSpec:
    """One pipeline agent, independent of which backend runs it."""

    name: str
    system_prompt: str
    model: str | None = None
    #: JSON Schema for the reply. Used for provider-native enforcement where
    #: `BackendCapabilities.native_json_schema` is true, and as repair context
    #: everywhere else.
    output_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    #: Lowest acceptable model strength. The Validator sets this high: it is
    #: the agent that degrades *invisibly* (spec-06 §6).
    requires_strong_model: bool = False


@dataclass(frozen=True)
class AgentResult:
    agent: str
    raw_text: str
    json: Any = None
    usage: Usage = field(default_factory=Usage)
    session_id: str | None = None
    #: How many repair rounds the reply needed. Non-zero is worth surfacing:
    #: a backend that always needs repair is a backend to stop using.
    repairs: int = 0


@dataclass(frozen=True)
class BackendCapabilities:
    """What a backend can do, declared rather than discovered (spec-06 §4)."""

    #: Usable window *after* harness overhead.
    min_context_tokens: int
    #: Measured tokens of system prompt and scaffolding per call.
    harness_overhead: int
    native_json_schema: bool
    prompt_caching: bool
    #: "subscription" | "free" | "metered"
    cost_per_run: str

    def assert_corpus_fits(
        self, backend: str, corpus_tokens: int, *, headroom: int = DEFAULT_HEADROOM
    ) -> None:
        """Refuse the run if the corpus cannot fit in one prompt.

        Full-corpus selection requires the entire knowledge base in a single
        prompt (spec-02 §2). This is the gate that keeps that true, and it is
        the real constraint on local models: a 7B model with an 8K window
        cannot run this pipeline on a realistic corpus, however good it is.
        """
        needed = corpus_tokens + self.harness_overhead + headroom
        if needed > self.min_context_tokens:
            raise ContextExceeded(backend, needed, self.min_context_tokens, corpus_tokens)


@dataclass(frozen=True)
class HealthReport:
    backend: str
    ok: bool
    #: What the backend expects to authenticate with, named so a failure is
    #: actionable (AC-R15.3).
    credential: str
    detail: str = ""
    model: str | None = None
    version: str | None = None

    def __str__(self) -> str:
        state = "ok" if self.ok else "unavailable"
        line = f"{self.backend}: {state} (auth: {self.credential})"
        return f"{line} — {self.detail}" if self.detail else line


@runtime_checkable
class RunnerBackend(Protocol):
    """What the orchestrator sees. Nothing more."""

    name: str
    capabilities: BackendCapabilities

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Run one agent to completion and return its parsed reply.

        `cache_prefix` carries the stable part of the prompt — the corpus —
        separately from the variable part, so backends that support prompt
        caching can mark the boundary. Backends that do not simply concatenate
        it, which is why the orchestrator never has to ask whether caching is
        available (spec-03 §6).
        """
        ...

    async def healthcheck(self) -> HealthReport: ...
