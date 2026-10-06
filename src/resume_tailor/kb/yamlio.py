"""YAML I/O in round-trip mode (spec-01 §5).

`ruamel.yaml` in round-trip mode throughout, never `yaml.safe_dump`. The
knowledge base is hand-edited in a text editor as a first-class path (spec-01
P1), so comments and key order are content. A reformatting dump would turn
every UI save into a large meaningless diff and destroy the git history that
AC-R8.3 depends on.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _yaml() -> YAML:
    y = YAML()  # round-trip by default
    y.preserve_quotes = True
    y.width = 4096  # never re-wrap; a wrapped line is a spurious diff
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def parse_yaml(text: str) -> Any:
    return _yaml().load(text) if text.strip() else None


def dump_yaml(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def load_yaml(path: Path) -> Any:
    return parse_yaml(path.read_text(encoding="utf-8"))
