"""Backend registry.

One function turns configuration into a `RunnerBackend`. The pipeline imports
nothing from this package beyond `base`, so adding a provider is a new module
and one registry entry (AC-R15.1).
"""

from __future__ import annotations

import os

from ..config import Config
from .base import (
    AgentResult,
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    BackendError,
    ContextExceeded,
    HealthReport,
    ModelRefusedJSON,
    RunnerBackend,
    Usage,
)

__all__ = [
    "AgentResult",
    "AgentSpec",
    "BackendAuthError",
    "BackendCapabilities",
    "BackendError",
    "ContextExceeded",
    "HealthReport",
    "ModelRefusedJSON",
    "RunnerBackend",
    "Usage",
    "BACKENDS",
    "build_backend",
]

BACKENDS = ("claude_sdk", "claude_cli", "codex_cli", "openai_compat", "fake")


def build_backend(config: Config | None = None, name: str | None = None) -> RunnerBackend:
    """Construct the configured backend.

    Imports are deferred per branch so that a missing optional dependency —
    `claude-agent-sdk`, say — only matters to someone actually using it.
    """
    config = config or Config()
    name = name or config.backend_name()

    if name == "claude_sdk":
        from .claude_sdk import ClaudeSdkRunner

        return ClaudeSdkRunner(model=config.models.default)

    if name == "claude_cli":
        from .claude_cli import ClaudeCliRunner

        return ClaudeCliRunner(model=config.models.default)

    if name == "codex_cli":
        from .codex_cli import CodexCliRunner

        return CodexCliRunner(model=config.models.default)

    if name == "openai_compat":
        from .openai_compat import OpenAICompatRunner

        compat = config.openai_compat
        return OpenAICompatRunner(
            base_url=compat.base_url,
            model=compat.model,
            api_key=os.environ.get(compat.api_key_env),
            context_tokens=compat.context_tokens,
            native_json_schema=compat.native_json_schema,
        )

    if name == "fake":
        from .fake import FakeRunner

        return FakeRunner()

    raise BackendError(
        f"unknown backend {name!r}. Available: {', '.join(BACKENDS)}. "
        "Set it in resume-tailor.toml under [runtime], or with RUNNER_BACKEND."
    )
