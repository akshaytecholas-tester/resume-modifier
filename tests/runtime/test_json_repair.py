"""The JSON repair ladder (spec-06 §5).

Every case here is a real shape a model has returned when asked for JSON.
"""

from __future__ import annotations

import pytest

from resume_tailor.runtime.base import ModelRefusedJSON
from resume_tailor.runtime.json_repair import parse_or_repair, strip_fences, try_parse


def test_clean_json_parses() -> None:
    value, error = try_parse('{"a": 1}')
    assert value == {"a": 1} and error is None


def test_code_fences_are_stripped() -> None:
    assert try_parse('```json\n{"a": 1}\n```')[0] == {"a": 1}
    assert try_parse("```\n[1, 2]\n```")[0] == [1, 2]


def test_prose_around_the_object_is_survivable() -> None:
    """No amount of prompting reliably stops "Here is the selection: {...}"."""
    text = 'Here is the selection:\n{"selected": []}\nLet me know if you need more.'
    assert try_parse(text)[0] == {"selected": []}


def test_braces_inside_strings_do_not_confuse_the_scan() -> None:
    """A fact body legitimately contains braces; a naive depth count on the
    raw text would stop at the wrong place and yield invalid JSON."""
    text = 'prefix {"reason": "uses {braces} and \\"quotes\\" inside"} suffix'
    assert try_parse(text)[0] == {"reason": 'uses {braces} and "quotes" inside'}


def test_arrays_are_extracted_too() -> None:
    assert try_parse('note:\n[{"id": "a"}]\n')[0] == [{"id": "a"}]


def test_unparseable_reports_why() -> None:
    value, error = try_parse("this is not JSON at all")
    assert value is None
    assert error and "line" in error


def test_empty_reply_reports_why() -> None:
    value, error = try_parse("")
    assert value is None and error


def test_strip_fences_leaves_unfenced_text_alone() -> None:
    assert strip_fences('{"a": 1}') == '{"a": 1}'


# -- the async ladder ------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_reply_needs_no_repair() -> None:
    value, repairs = await parse_or_repair('{"ok": true}', agent="selector")
    assert value == {"ok": True} and repairs == 0


@pytest.mark.asyncio
async def test_one_repair_round_is_counted() -> None:
    async def reask(_instruction: str) -> str:
        return '{"ok": true}'

    value, repairs = await parse_or_repair("sorry, no JSON", agent="writer", reask=reask)
    assert value == {"ok": True} and repairs == 1


@pytest.mark.asyncio
async def test_the_repair_prompt_carries_the_parser_error() -> None:
    """Re-asking without saying what was wrong usually produces the same reply."""
    seen: list[str] = []

    async def reask(instruction: str) -> str:
        seen.append(instruction)
        return "{}"

    await parse_or_repair("nope", agent="analyst", reask=reask)
    assert "could not be parsed" in seen[0]
    assert "Parser error:" in seen[0]


@pytest.mark.asyncio
async def test_a_second_failure_is_loud() -> None:
    """spec-06 §5 step 4. A half-parsed object downstream produces a resume
    whose fields silently defaulted, and the first symptom is a missing bullet
    nobody can explain."""

    async def reask(_instruction: str) -> str:
        return "still not JSON"

    with pytest.raises(ModelRefusedJSON) as exc:
        await parse_or_repair("not JSON", agent="validator", reask=reask)
    assert "validator" in str(exc.value)
    assert "half-parsed" in str(exc.value)


@pytest.mark.asyncio
async def test_without_a_repair_turn_it_fails_immediately() -> None:
    with pytest.raises(ModelRefusedJSON):
        await parse_or_repair("not JSON", agent="recall")


@pytest.mark.asyncio
async def test_failure_shows_what_the_model_actually_said() -> None:
    """Debugging a refusal without the reply means re-running it to find out."""
    with pytest.raises(ModelRefusedJSON) as exc:
        await parse_or_repair("I cannot comply with that request.", agent="writer")
    assert "I cannot comply" in str(exc.value)
