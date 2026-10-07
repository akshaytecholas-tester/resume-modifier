"""OpenAI Codex CLI (spec-06 §3.3).

Verified working 2026-10-06: `gpt-5.5`, a 272,000-token window, and a
strict-JSON prompt returned a bare parseable object with no fences.

`--skip-git-repo-check` because the CLI otherwise refuses to run outside a git
repository, and stdin from `/dev/null` because it waits on input it will never
receive. Both were found by the tool hanging, not by reading the help text.

Whether the ChatGPT **Free** plan includes CLI access is still unresolved
(OQ-7): it works on this account, but that does not establish the plan.
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

BINARY = "codex"

CAPABILITIES = BackendCapabilities(
    min_context_tokens=272_000,
    harness_overhead=18_365,
    native_json_schema=False,
    prompt_caching=True,
    cost_per_run="subscription",
)


class CodexCliRunner:
    name = "codex_cli"
    capabilities = CAPABILITIES

    def __init__(self, model: str | None = None, *, timeout: int = 600) -> None:
        self.model = model
        self.timeout = timeout

    async def _ask(self, agent: AgentSpec, prompt: str) -> tuple[str, Usage]:
        if shutil.which(BINARY) is None:
            raise BackendAuthError(
                self.name, "the `codex` CLI on PATH", "install it and run `codex login`"
            )

        command = [BINARY, "exec", "--json", "--skip-git-repo-check"]
        if agent.model or self.model:
            command += ["--model", agent.model or self.model]
        command.append(f"{agent.system_prompt}\n\n{prompt}")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            raise BackendError(f"{self.name}: no reply within {self.timeout}s") from exc

        if process.returncode != 0:
            stderr = err.decode("utf-8", "replace").strip()
            if any(w in stderr.lower() for w in ("auth", "login", "401", "unauthor")):
                raise BackendAuthError(self.name, "a ChatGPT session (run `codex login`)", stderr)
            raise BackendError(f"{self.name}: exited {process.returncode}. {stderr}")

        return self._collect(out.decode("utf-8", "replace"))

    @staticmethod
    def _collect(stream: str) -> tuple[str, Usage]:
        """Read the newline-delimited event stream.

        The reply is the `item.completed` event whose item type is
        `agent_message`; `turn.completed` carries usage. Unparseable lines are
        skipped rather than fatal — the stream is a log, and a new event type
        in a future release should not break a working call.
        """
        text, usage = "", Usage()
        for line in stream.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = event.get("type")
            if kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = item.get("text") or item.get("content") or text
            elif kind == "turn.completed":
                counts = event.get("usage") or {}
                usage = Usage(
                    input_tokens=int(counts.get("input_tokens") or 0),
                    output_tokens=int(counts.get("output_tokens") or 0),
                    cache_read_tokens=int(counts.get("cached_input_tokens") or 0),
                )
        return text, usage

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        full = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        text, usage = await self._ask(agent, full)

        async def reask(instruction: str) -> str:
            nonlocal usage
            retry, extra = await self._ask(agent, f"{full}\n\n{instruction}")
            usage = usage + extra
            return retry

        value, repairs = await parse_or_repair(text, agent=agent.name, reask=reask)
        return AgentResult(agent.name, text, value, usage, session_id, repairs)

    async def healthcheck(self) -> HealthReport:
        path = shutil.which(BINARY)
        if path is None:
            return HealthReport(self.name, False, "the `codex` CLI on PATH", "not installed")
        return HealthReport(
            self.name, True, "a ChatGPT session (`codex login`)", path, model=self.model
        )
