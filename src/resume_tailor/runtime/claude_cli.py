"""Driving the `claude` binary directly (spec-03 §2.1, §1.3).

The Agent SDK runs this same binary as a subprocess, and Anthropic's docs
endorse invoking it directly: *"run the CLI as a subprocess with the `-p` flag
and `--output-format json`"*. Nothing is patched, no credential is intercepted,
no auth method is disabled — it is ordinary Claude Code use.

Kept as a fallback even though OQ-1 resolved in the SDK's favour. Enforcement
behaviour can change, and a backend that only exists after it is needed is a
backend that does not exist.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from .base import (
    AgentResult,
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    BackendError,
    HealthReport,
    Usage,
)
from .json_repair import parse_or_repair

BINARY = "claude"

#: The flags that take a default `claude -p` call from 38,841 input tokens to
#: 8,004 (spec-06 §2). `--setting-sources ""` is the single largest saving:
#: without it the user's MCP servers load on every call.
LEAN_FLAGS = [
    "--output-format",
    "json",
    "--strict-mcp-config",
    "--mcp-config",
    '{"mcpServers":{}}',
    "--setting-sources",
    "",
    "--exclude-dynamic-system-prompt-sections",
]

DISALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "NotebookEdit",
    "BashOutput",
    "KillShell",
    "SlashCommand",
]

CAPABILITIES = BackendCapabilities(
    min_context_tokens=200_000,
    harness_overhead=8_004,
    native_json_schema=False,
    prompt_caching=True,
    cost_per_run="subscription",
)


class ClaudeCliRunner:
    name = "claude_cli"
    capabilities = CAPABILITIES

    def __init__(self, model: str | None = None, *, timeout: int = 600) -> None:
        self.model = model
        self.timeout = timeout

    def _command(self, agent: AgentSpec, prompt: str) -> list[str]:
        command = [BINARY, "-p", prompt, "--system-prompt", agent.system_prompt, *LEAN_FLAGS]
        for tool in DISALLOWED_TOOLS:
            command += ["--disallowed-tools", tool]
        model = agent.model or self.model
        if model:
            command += ["--model", model]
        return command

    async def _ask(self, agent: AgentSpec, prompt: str) -> tuple[str, Usage, str | None]:
        if shutil.which(BINARY) is None:
            raise BackendAuthError(
                self.name, "the `claude` CLI on PATH", "install Claude Code and run `claude login`"
            )

        process = await asyncio.create_subprocess_exec(
            *self._command(agent, prompt),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            raise BackendError(f"{self.name}: no reply within {self.timeout}s") from exc

        stderr = err.decode("utf-8", "replace").strip()
        if process.returncode != 0:
            lowered = stderr.lower()
            if any(w in lowered for w in ("auth", "401", "login", "credential", "unauthor")):
                raise BackendAuthError(
                    self.name, "a Claude subscription session (run `claude login`)", stderr
                )
            raise BackendError(f"{self.name}: exited {process.returncode}. {stderr}")

        return self._unwrap(out.decode("utf-8", "replace"))

    def _unwrap(self, raw: str) -> tuple[str, Usage, str | None]:
        """Pull the reply, usage and session id out of the CLI's JSON envelope.

        The envelope itself is JSON, and so is the agent's reply inside it, so
        a failure to parse the envelope must not be reported as the model
        refusing to produce JSON — those have different causes and fixes.
        """
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"{self.name}: could not parse the CLI's JSON envelope ({exc.msg}). "
                f"First 200 characters: {raw[:200]!r}"
            ) from exc

        if isinstance(envelope, list):
            envelope = envelope[-1] if envelope else {}

        usage = envelope.get("usage") or {}
        return (
            str(envelope.get("result") or envelope.get("text") or ""),
            Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            ),
            envelope.get("session_id"),
        )

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        full = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        text, usage, sid = await self._ask(agent, full)

        async def reask(instruction: str) -> str:
            nonlocal usage
            retry, extra, _ = await self._ask(agent, f"{full}\n\n{instruction}")
            usage = usage + extra
            return retry

        value, repairs = await parse_or_repair(text, agent=agent.name, reask=reask)
        return AgentResult(agent.name, text, value, usage, sid or session_id, repairs)

    async def healthcheck(self) -> HealthReport:
        path = shutil.which(BINARY)
        if path is None:
            return HealthReport(self.name, False, "the `claude` CLI on PATH", "not installed")
        process = await asyncio.create_subprocess_exec(
            BINARY,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await process.communicate()
        return HealthReport(
            self.name,
            True,
            "a Claude subscription session",
            path,
            model=self.model,
            version=out.decode().strip() or None,
        )
