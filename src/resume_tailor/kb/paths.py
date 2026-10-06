"""Path resolution and containment (spec-04 §2 step 2).

An entry ``id`` becomes a filesystem path. Without resolving and asserting
containment, an id like ``../../../.ssh/authorized_keys`` is an arbitrary-write
primitive on the user's machine. The check is three lines; omitting it is
severe, so it lives in one place that every writer goes through.
"""

from __future__ import annotations

from pathlib import Path

from .schema import ID_RE, TYPE_DIRS


class PathEscape(ValueError):
    """A resolved path fell outside the directory it was required to stay in."""


def repo_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding a `kb/` directory, else the current directory."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "kb").is_dir():
            return candidate
    return here


def contain(path: Path, root: Path) -> Path:
    """Resolve `path` and assert it stays inside `root`. Returns the resolved path."""
    root = root.resolve()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathEscape(f"{path} resolves to {resolved}, outside {root}")
    return resolved


def entry_path(kb_dir: Path, entry_type: str, entry_id: str) -> Path:
    """Where an entry of this type and id belongs.

    The id is pattern-checked *before* it is joined. Containment is still
    asserted afterwards: two independent checks, because this is the function
    that turns user input into a write target.
    """
    try:
        subdir = TYPE_DIRS[entry_type]
    except KeyError:
        known = ", ".join(sorted(TYPE_DIRS))
        raise ValueError(f"unknown type {entry_type!r}; expected one of: {known}") from None

    if not ID_RE.match(entry_id):
        raise PathEscape(
            f"id {entry_id!r} is not a slug (lowercase alphanumerics and single hyphens)"
        )

    return contain(Path(subdir) / f"{entry_id}.md", kb_dir)
