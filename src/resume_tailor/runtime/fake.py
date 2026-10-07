"""A backend that replays recorded replies (no network, no cost).

Every pipeline test depends on this. Orchestration, merging, resumability and
error handling are all logic worth testing, and testing them against a live
model would make the suite slow, costly and non-deterministic — so the one
thing that would never get run is the suite.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .base import (
    AgentResult,
    AgentSpec,
    BackendCapabilities,
    HealthReport,
    Usage,
)
from .json_repair import parse_or_repair

CAPABILITIES = BackendCapabilities(
    min_context_tokens=1_000_000,
    harness_overhead=0,
    native_json_schema=True,
    prompt_caching=False,
    cost_per_run="free",
)


class FakeRunner:
    """Replays a scripted reply per agent.

    `replies` maps an agent name to the reply it should produce: a string
    (returned verbatim, so JSON repair can be exercised), a JSON-serialisable
    value, a list to return in sequence across calls, or a callable taking the
    prompt.
    """

    name = "fake"
    capabilities = CAPABILITIES

    def __init__(
        self,
        replies: dict[str, Any] | None = None,
        *,
        usage: Usage | None = None,
        fail_on: dict[str, Exception] | None = None,
    ) -> None:
        self.replies = replies or {}
        self.usage = usage or Usage(input_tokens=100, output_tokens=50)
        self.fail_on = fail_on or {}
        #: Every prompt seen, per agent. Tests assert on prompt *ordering* with
        #: this — corpus-first is a correctness property for caching, and
        #: nothing else would catch it silently regressing.
        self.calls: dict[str, list[str]] = defaultdict(list)
        self._sequence: dict[str, int] = defaultdict(int)

    def _reply_for(self, agent: str, prompt: str) -> str:
        if agent not in self.replies:
            raise KeyError(
                f"FakeRunner has no reply scripted for agent {agent!r}; "
                f"scripted: {sorted(self.replies) or 'none'}"
            )
        reply = self.replies[agent]

        if isinstance(reply, list):
            index = min(self._sequence[agent], len(reply) - 1)
            self._sequence[agent] += 1
            reply = reply[index]
        if isinstance(reply, Callable):
            reply = reply(prompt)
        return reply if isinstance(reply, str) else json.dumps(reply)

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        full = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        self.calls[agent.name].append(full)

        if agent.name in self.fail_on:
            raise self.fail_on[agent.name]

        text = self._reply_for(agent.name, full)

        async def reask(_instruction: str) -> str:
            return self._reply_for(agent.name, full)

        value, repairs = await parse_or_repair(text, agent=agent.name, reask=reask)
        return AgentResult(
            agent=agent.name,
            raw_text=text,
            json=value,
            usage=self.usage,
            session_id=session_id or "fake-session",
            repairs=repairs,
        )

    async def healthcheck(self) -> HealthReport:
        return HealthReport(self.name, True, "none", "replays recorded replies")


def from_fixtures(directory: Path) -> FakeRunner:
    """Build a runner from `<agent>.json` files in a directory."""
    replies = {p.stem: p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.json"))}
    return FakeRunner(replies)
