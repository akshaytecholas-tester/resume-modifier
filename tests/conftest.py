from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

TAXONOMY = """\
python:
  label: Python
  facet: tech
  aliases: [py]
go:
  label: Go
  facet: tech
rag:
  label: RAG Pipelines
  facet: skill
fintech:
  label: Financial Technology
  facet: domain
"""

ROLE = """\
---
id: acme-engineer
type: role
title: Software Engineer
org: Acme
dates: {start: 2024-01, end: present}
tags: [python]
depth: working
verifiable: true
visibility: public
---

Context for the role.
"""

FACT = """\
---
id: acme-pipeline
type: fact
parent: acme-engineer
title: Ingestion pipeline
tags: [python, rag]
metrics:
  - {value: "60%", what: "less manual intake"}
depth: working
verifiable: true
visibility: public
---

Built the pipeline.
"""


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    """A minimal, valid knowledge base: one role, one fact, a taxonomy."""
    root = tmp_path / "kb"
    for sub in ("roles", "facts", "projects", "blogs", "education", "certifications", "awards"):
        (root / sub).mkdir(parents=True)
    (root / "taxonomy.yaml").write_text(TAXONOMY, encoding="utf-8")
    (root / "roles" / "acme-engineer.md").write_text(ROLE, encoding="utf-8")
    (root / "facts" / "acme-pipeline.md").write_text(FACT, encoding="utf-8")
    return root


def write_entry(kb: Path, subdir: str, stem: str, frontmatter: str, body: str = "Body.") -> Path:
    path = kb / subdir / f"{stem}.md"
    path.write_text(
        f"---\n{textwrap.dedent(frontmatter).strip()}\n---\n\n{body}\n", encoding="utf-8"
    )
    return path
