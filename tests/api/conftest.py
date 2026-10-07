from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor.api.app import create_app

from ..conftest import ROLE, TAXONOMY


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with a `kb/` that is its own git repository.

    Mirrors the real layout (OQ-9): the knowledge base is versioned separately
    and has no remote, so the write path's commits must land there and not in
    any parent repository.
    """
    root = tmp_path / "project"
    kb = root / "kb"
    for sub in ("roles", "facts", "projects", "blogs", "education", "certifications", "awards"):
        (kb / sub).mkdir(parents=True)
    (kb / "taxonomy.yaml").write_text(TAXONOMY, encoding="utf-8")
    (kb / "roles" / "acme-engineer.md").write_text(ROLE, encoding="utf-8")
    (kb / "identity.yaml").write_text(
        "name: Ada Lovelace\nemail: ada@example.com\n", encoding="utf-8"
    )

    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(kb), *args], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(kb),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "seed",
        ],
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def client(project: Path) -> TestClient:
    with TestClient(create_app(project)) as test_client:
        yield test_client
