"""Git operations against the knowledge-base repository (spec-01 §5).

**Scoped to `kb/` deliberately.** The knowledge base is versioned by its own
repository with no remote (OQ-9), so every command here passes `-C <kb_dir>`.
Committing to the parent repository instead would publish the career record to
a public remote on the next push, which is the one failure this arrangement
exists to prevent.

History is what gives AC-R8.3 its undo, spec-04 §3 its revert endpoint, and an
agent-proposed change a reviewable diff — none of which needed an undo stack
written for them.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitUnavailable(RuntimeError):
    """`kb/` is not a git repository. Writes still succeed; history does not."""


@dataclass(frozen=True)
class Commit:
    sha: str
    message: str
    when: str
    author: str


def _run(kb_dir: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(kb_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitUnavailable(f"git {' '.join(args)} failed in {kb_dir}: {result.stderr.strip()}")
    return result.stdout


def is_repo(kb_dir: Path) -> bool:
    return (kb_dir / ".git").exists()


def has_remote(kb_dir: Path) -> bool:
    """Whether `kb/` could be pushed anywhere.

    Surfaced by `/api/health` because adding a remote is the single action that
    would publish the career record, and nothing else in the design prevents it.
    """
    if not is_repo(kb_dir):
        return False
    return bool(_run(kb_dir, "remote", check=False).strip())


def commit_file(kb_dir: Path, path: Path, message: str) -> str | None:
    """Stage one file and commit it. Returns the sha, or None if nothing changed.

    A no-op write — saving a file byte-identical to what is on disk — must not
    produce an empty commit, or the history fills with noise and stops being
    worth reading.
    """
    if not is_repo(kb_dir):
        return None

    relative = path.relative_to(kb_dir)
    _run(kb_dir, "add", "--", str(relative))

    staged = _run(kb_dir, "diff", "--cached", "--name-only", check=False).strip()
    if not staged:
        return None

    _run(kb_dir, "commit", "-m", message, "--", str(relative))
    return _run(kb_dir, "rev-parse", "HEAD").strip()


def history(kb_dir: Path, path: Path, limit: int = 50) -> list[Commit]:
    if not is_repo(kb_dir):
        return []
    out = _run(
        kb_dir,
        "log",
        f"-{limit}",
        "--format=%H%x1f%s%x1f%aI%x1f%an",
        "--",
        str(path.relative_to(kb_dir)),
        check=False,
    )
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(Commit(*parts))
    return commits


def show(kb_dir: Path, sha: str, path: Path) -> str:
    """The content of one file at one commit, for diffing and revert."""
    return _run(kb_dir, "show", f"{sha}:{path.relative_to(kb_dir)}")
