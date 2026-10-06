#!/usr/bin/env python3
"""OQ-1 probe: does the Claude Agent SDK work on a subscription session?

The claim under test (spec-03 §1): the SDK spawns the Claude Code binary as a
subprocess, and with no ANTHROPIC_API_KEY present it falls back to the Pro/Max
credentials saved by `claude login`.

Run with the key explicitly removed, or the test proves nothing:

    env -u ANTHROPIC_API_KEY .venv/bin/python spike/auth_probe.py

Exit 0 if the SDK path works on subscription auth, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROMPT = "Reply with exactly: OK"


def line(c: str = "-") -> None:
    print(c * 68)


def environment() -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    others = sorted(
        k for k in os.environ
        if ("ANTHROPIC" in k or "CLAUDE" in k) and k != "ANTHROPIC_API_KEY"
    )
    in_claude_code = bool(os.environ.get("CLAUDECODE"))
    creds = Path.home() / ".claude" / ".credentials.json"
    cli = shutil.which("claude")
    version = None
    if cli:
        try:
            version = subprocess.run(
                [cli, "--version"], capture_output=True, text=True, timeout=30
            ).stdout.strip()
        except Exception as exc:                      # noqa: BLE001
            version = f"(could not read: {exc})"
    return {
        "api_key_present": bool(key),
        "inside_claude_code": in_claude_code,
        "api_key_preview": (key[:8] + "...") if key else None,
        "other_anthropic_env": others,
        "credentials_file": str(creds) if creds.exists() else None,
        "claude_cli": cli,
        "claude_version": version,
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
    }


async def probe_sdk() -> dict:
    """One trivial round-trip through the SDK, with the leanest possible config."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "stage": "import", "error": f"{type(exc).__name__}: {exc}"}

    # Lean config per spec-06 §2: no Claude Code preset, no settings, no MCP,
    # and tools removed via disallowed_tools. allowed_tools=[] does NOT restrict
    # which tools load — measured 18,184 vs 7,753 input tokens on 2026-10-06.
    options = ClaudeAgentOptions(
        system_prompt="You are a terse service. Reply with exactly what is asked.",
        setting_sources=[],
        mcp_servers={},
        allowed_tools=[],
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
            "WebSearch", "Task", "TodoWrite", "NotebookEdit", "BashOutput",
            "KillShell", "SlashCommand",
        ],
    )

    text, usage, blocks = [], None, 0
    try:
        async for message in query(prompt=PROMPT, options=options):
            blocks += 1
            for attr in ("content",):
                for block in getattr(message, attr, None) or []:
                    chunk = getattr(block, "text", None)
                    if chunk:
                        text.append(chunk)
            u = getattr(message, "usage", None)
            if u:
                usage = u if isinstance(u, dict) else getattr(u, "__dict__", str(u))
    except Exception as exc:                          # noqa: BLE001
        return {
            "ok": False,
            "stage": "query",
            "error": f"{type(exc).__name__}: {exc}",
            "partial_text": "".join(text) or None,
        }

    reply = "".join(text).strip()
    return {"ok": bool(reply), "stage": "complete", "reply": reply,
            "messages": blocks, "usage": usage}


def probe_cli() -> dict:
    """Control case: the CLI path, known to work on subscription auth."""
    cli = shutil.which("claude")
    if not cli:
        return {"ok": False, "error": "claude not on PATH"}
    try:
        proc = subprocess.run(
            [cli, "-p", PROMPT, "--output-format", "json",
             "--system-prompt", "You are a terse service.",
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
             "--setting-sources", ""],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timed out after 180s"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout)[-400:].strip()}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"unparseable output: {exc}"}
    return {"ok": True, "reply": str(data.get("result", "")).strip(),
            "usage": data.get("usage")}


async def main() -> int:
    env = environment()

    line("=")
    print("OQ-1 — Claude Agent SDK on a subscription session")
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    line("=")

    print("\nENVIRONMENT")
    for k, v in env.items():
        print(f"  {k:24} {v}")

    if env["inside_claude_code"]:
        print("\n  WARNING: running inside a Claude Code session. The subprocess may")
        print("  inherit session state, so a pass here is weaker evidence. Re-run")
        print("  from a plain terminal, or strip the CLAUDE_CODE_* variables.")

    if env["api_key_present"]:
        print("\n  ABORT: ANTHROPIC_API_KEY is set, so a success here would prove")
        print("  nothing about subscription auth. Re-run as:")
        print("      env -u ANTHROPIC_API_KEY .venv/bin/python spike/auth_probe.py")
        return 1

    print("\nSDK PATH")
    sdk = await probe_sdk()
    for k, v in sdk.items():
        print(f"  {k:24} {v}")

    print("\nCLI PATH (control)")
    cli = probe_cli()
    for k, v in cli.items():
        print(f"  {k:24} {v}")

    line("=")
    if sdk["ok"]:
        print("VERDICT: SDK works on subscription auth — no API key present.")
        print("         spec-03 default backend → sdk")
        verdict = 0
    elif cli.get("ok"):
        print("VERDICT: SDK rejected the subscription session; CLI works.")
        print("         spec-03 default backend → cli")
        verdict = 1
    else:
        print("VERDICT: both paths failed — check `claude login` first.")
        verdict = 1
    line("=")
    print("\nRecord this result, with today's date, in docs/open-questions.md OQ-1.")
    return verdict


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
