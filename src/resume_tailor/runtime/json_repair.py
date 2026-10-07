"""Getting parseable JSON out of a model that was asked for JSON (spec-06 §5).

Providers differ in how reliably they return bare JSON, so the runner
normalises rather than every agent handling it. The ladder:

1. Provider-native schema enforcement, where the backend declares it.
2. Parse directly; on failure strip code fences and retry the parse.
3. Re-prompt **once**, with the parse error included.
4. Fail loudly.

Step 4 is the important one. A half-parsed object passed downstream produces a
resume whose fields silently defaulted, and the first visible symptom is a
missing bullet that nobody can explain. Claude and Codex both returned clean
bare JSON in testing; steps 2–4 earn their place on smaller local models.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .base import ModelRefusedJSON

#: ```json ... ``` or ``` ... ```, the most common wrapper a chat model adds.
_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)


def strip_fences(text: str) -> str:
    match = _FENCE.search(text)
    return match.group(1).strip() if match else text.strip()


def _first_balanced(text: str) -> str | None:
    """The first balanced `{...}` or `[...]`, ignoring braces inside strings.

    For replies that wrap JSON in prose — "Here is the selection: {...} Let me
    know if..." — which no amount of prompting reliably prevents.
    """
    start = next((i for i, c in enumerate(text) if c in "{["), None)
    if start is None:
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def try_parse(text: str) -> tuple[Any | None, str | None]:
    """Parse `text` as JSON, loosening progressively. Returns `(value, error)`.

    Each step is strictly more permissive than the last, and the first success
    wins, so a reply that is already clean never goes near the salvage paths.
    """
    last = "empty reply"
    for candidate in (text.strip(), strip_fences(text), _first_balanced(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError as exc:
            last = f"{exc.msg} at line {exc.lineno} column {exc.colno}"
    return None, last


async def parse_or_repair(
    text: str,
    *,
    agent: str,
    reask: Callable[[str], Awaitable[str]] | None = None,
) -> tuple[Any, int]:
    """Return `(value, repairs)` or raise `ModelRefusedJSON`.

    `reask` sends one follow-up turn carrying the parse error. It is optional
    so that backends with native schema enforcement, and tests, can skip it.
    """
    value, error = try_parse(text)
    if value is not None:
        return value, 0

    if reask is None:
        raise ModelRefusedJSON(
            f"{agent}: reply was not JSON and no repair turn was available ({error}). "
            f"First 200 characters: {text[:200]!r}"
        )

    retry = await reask(
        "Your previous reply could not be parsed as JSON.\n"
        f"Parser error: {error}\n\n"
        "Reply again with the JSON object only. No prose, no code fences, no "
        "explanation — the first character must be { or [."
    )

    value, error = try_parse(retry)
    if value is not None:
        return value, 1

    raise ModelRefusedJSON(
        f"{agent}: reply was not JSON after one repair attempt ({error}). "
        "Failing rather than passing a half-parsed object downstream, which "
        f"would silently default fields. First 200 characters: {retry[:200]!r}"
    )
