# Spec 03 — Runtime and Authentication

**Covers:** R15
**Related:** [PRD](PRD.md) · [Agents](spec-02-agent-pipeline.md) · [open-questions.md](open-questions.md) OQ-1

---

## 1. The open question

The stated preference is to run on the existing Claude subscription (R15). Whether the Agent SDK accepts a Pro/Max OAuth session is **unverified**, and the policy language cuts both ways. This spec records the evidence, defines an interface that survives either answer, and specifies the spike that settles it.

### 1.1 What the documentation says

From [Legal and compliance → Acceptable use](https://code.claude.com/docs/en/legal-and-compliance):

> Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code **and the Agent SDK**.

From the same page, *Authentication and credential use*:

> **OAuth authentication** is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications.
>
> **Developers** building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console… Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials **on behalf of their users**.

From the [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview):

> Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits **for their products**, including agents built on the Claude Agent SDK.

### 1.2 Reading

The prohibitions are scoped to products with end users: offering claude.ai login *into their own applications*, routing requests *on behalf of their users*, collecting or intermediating credentials. This system has one user, who is the account holder, running on their own machine, authenticating through Anthropic's own flow, with no other person's requests ever passing through it. That is the "ordinary, individual usage" the acceptable-use clause names — and that clause names the Agent SDK explicitly.

**However**, the SDK's own documentation steers developers to API keys without qualification, and third-party reports describe server-side enforcement rejecting consumer OAuth outside Claude Code itself. Those reports are unverified and may describe a different scenario. **Documentation reading is not a substitute for an empirical test**, and the architecture must not assume the outcome.

### 1.3 The fallback is legitimate, not a workaround

The Agent SDK "runs the Claude Code binary" ([SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)), and the docs endorse driving that binary directly:

> To drive the same agent loop from a language other than Python or TypeScript, run the CLI as a subprocess with the `-p` flag and `--output-format json`.

Invoking the unmodified `claude` binary, under the user's own login, on their own machine, for their own work, is ordinary Claude Code use. The legal page's condition that "the Claude Code binary must not be modified" is satisfied — nothing is patched, no credential is intercepted, no auth method is disabled.

## 2. `RunnerBackend` interface

All agent invocation goes through one interface. No pipeline or agent code references a backend directly. (AC-R15.1)

```python
class RunnerBackend(Protocol):
    name: str

    async def run_agent(
        self,
        agent: AgentSpec,          # system prompt, model, output schema
        prompt: str,               # user-turn content (JD, corpus, prior artifacts)
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult: ...          # .json, .raw_text, .usage, .session_id

    async def healthcheck(self) -> HealthReport: ...
```

`AgentResult.usage` carries input/output/cache token counts so the UI can report per-run cost regardless of backend (RK-2).

### 2.1 `CliSubprocessRunner`

Spawns `claude -p <prompt> --output-format json` with `--system-prompt`, `--model`, and `--disallowed-tools` set from the `AgentSpec`. Parses the JSON envelope for result text, session id, and usage.

- **Auth:** the user's existing CLI login. Nothing to configure.
- **Trade-off:** we manage sessions, retries, and JSON parsing ourselves instead of getting typed sessions and hooks from the SDK.
- **Subagents:** each pipeline agent is its own invocation, which the orchestrator already assumes ([spec-02](spec-02-agent-pipeline.md) §5).

### 2.2 `AgentSdkRunner`

Uses `claude_agent_sdk` with `ClaudeAgentOptions`, mapping each pipeline agent to an `AgentDefinition`.

- **Auth:** `ANTHROPIC_API_KEY` from Claude Console.
- **Trade-off:** costs money per run; zero policy ambiguity.
- **Gain:** native subagents, hooks, typed sessions, structured permissions.

### 2.3 Selection

`RUNNER_BACKEND=cli|sdk` in `.env`, defaulting to the spike's verdict. An auth failure reports which backend failed and which credential it expected (AC-R15.3) — never a raw stack trace, because the two failure modes (expired OAuth vs missing API key) have completely different fixes.

## 3. Spike protocol

**Run before any other implementation work.** Timebox 30 minutes.

```bash
cd /Users/amal/resume/resume-tailor
python3 -m venv .venv && .venv/bin/pip install claude-agent-sdk
env -u ANTHROPIC_API_KEY .venv/bin/python spike/auth_probe.py
```

`spike/auth_probe.py` sends one trivial prompt ("reply with the word OK") through `claude_agent_sdk` with **no** `ANTHROPIC_API_KEY` in the environment, and separately through `claude -p`. It prints, for each: success/failure, the error class and message, and token usage.

`env -u ANTHROPIC_API_KEY` is not optional — a key present anywhere in the environment makes the test meaningless by silently succeeding for the wrong reason.

### Outcomes

| Result | Verdict | Default backend |
|---|---|---|
| SDK succeeds without an API key | Subscription works with the SDK | `sdk` on subscription auth |
| SDK fails auth; CLI succeeds | Enforcement is real; fallback is required | `cli` |
| Both fail | Local Claude Code login is broken | Neither — fix `claude` login first |

**Result, 2026-10-06: the SDK succeeded with no API key present** — including with every `CLAUDE_CODE_*` session variable stripped. Default backend is therefore `sdk`. Full record in [open-questions.md](open-questions.md) OQ-1.

The result, the exact error text, and the date are recorded in [open-questions.md](open-questions.md) OQ-1. Enforcement behavior can change, so the record needs a date attached to be worth anything later.

## 4. Cost and rate limits

**CLI backend (subscription):** no marginal cash cost; consumes the same rate-limit budget as interactive Claude Code sessions. A heavy tailoring session can degrade interactive work — the practical constraint, and why the agent count is held at five.

**SDK backend (API key):** estimated per run, at a ~150-fact corpus (~18K tokens):

| Stage | Input | Note |
|---|---|---|
| Analyst | ~2K | JD only |
| Selector | ~20K | full corpus + requirements |
| Recall | ~20K | full corpus (cache hit) |
| Writer | ~4K | selected facts only |
| Validator | ~4K | draft + cited facts |

≈50K input, ≈8K output per run, materially reduced by caching on repeat runs in a session. Order of magnitude: cents to low tens of cents per tailored resume. Figures are estimates to be replaced with measured values after the spike.

## 5. Harness overhead

A coding CLI ships a large system prompt this pipeline does not use. Measured 2026-10-06, `claude -p "Reply with exactly: OK"`:

| Configuration | Input tokens |
|---|---|
| Default | 38,841 |
| Custom system prompt, dynamic sections excluded, built-in tools disallowed | 18,436 |
| Also `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources ""` | **8,004** |

Both CLI and SDK backends must apply the lean configuration in [spec-06 §2](spec-06-provider-backends.md). The Agent SDK is already lean by default — `system_prompt` defaults to `None` and Claude Code's prompt is opt-in — but `setting_sources` must be set to `[]` explicitly, or the user's MCP servers load and cost ~10K tokens per call.

## 6. Prompt caching

The corpus is stable; the JD changes every run. Prompts are therefore ordered **corpus first, JD last**, so the expensive prefix is cacheable across the Selector and Recall calls within a run and across runs within the cache TTL.

Cache invalidation is implicit: editing any KB file changes the prefix bytes and the next run re-caches. No manual invalidation step, and no way for a stale corpus to be silently reused.
