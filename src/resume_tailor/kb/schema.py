"""Frontmatter schemas for knowledge-base entries (spec-01 §3).

These models describe the YAML frontmatter only. Body text lives alongside them
in `loader.Entry`, because the body is prose the model reads verbatim and has no
structure to validate.

`extra="forbid"` throughout: a mistyped field name would otherwise be accepted
and silently do nothing, which for `visibility` or `depth` means a guard that
looks configured but is not.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
ID_RE = re.compile(ID_PATTERN)
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

Depth = Literal["expert", "working", "exposure"]
Visibility = Literal["public", "nda", "private"]
EntryType = Literal["role", "fact", "project", "blog", "education", "certification", "award"]

Slug = Annotated[str, Field(pattern=ID_PATTERN)]
NonEmpty = Annotated[str, Field(min_length=1)]

#: Types whose entries live under ``kb/<dir>/``. Keyed by ``type``.
TYPE_DIRS: dict[str, str] = {
    "role": "roles",
    "fact": "facts",
    "project": "projects",
    "blog": "blogs",
    "education": "education",
    "certification": "certifications",
    "award": "awards",
}

#: Types that may be named as a fact's ``parent``.
PARENT_TYPES = frozenset({"role", "project"})


class Metric(BaseModel):
    """A number the Writer may reuse without retyping it (spec-02 §3.4).

    Structured rather than left in prose so a bullet cannot drift from the
    figure it came from.
    """

    model_config = ConfigDict(extra="forbid")

    value: NonEmpty
    what: NonEmpty


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str | None = None

    @field_validator("start", "end")
    @classmethod
    def _month_or_present(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v == "present":
            return v
        if not MONTH_RE.match(v):
            raise ValueError(f"expected YYYY-MM or 'present', got {v!r}")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if self.end and self.end != "present" and self.end < self.start:
            raise ValueError(f"end {self.end} precedes start {self.start}")
        return self


class BaseEntry(BaseModel):
    """Fields every entry type carries (spec-01 §3.3)."""

    model_config = ConfigDict(extra="forbid")

    id: Slug
    type: EntryType
    title: NonEmpty
    tags: list[Slug] = Field(min_length=1)
    depth: Depth
    verifiable: bool
    visibility: Visibility
    metrics: list[Metric] = Field(default_factory=list)
    related: list[Slug] = Field(default_factory=list)
    locked_phrasing: str | None = None
    #: Author-chosen display order within a parent; lower comes first.
    #: Unset sorts last, then by id, so ordering is always deterministic.
    #:
    #: Only the baseline render and ties obey it. A tailored run orders bullets
    #: by relevance to the posting, which is the Writer's job and changes per
    #: job description — this is the default when no posting is involved.
    order: int | None = None

    @field_validator("tags")
    @classmethod
    def _unique_tags(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            dupes = sorted({t for t in v if v.count(t) > 1})
            raise ValueError(f"duplicate tags: {', '.join(dupes)}")
        return v


class Role(BaseEntry):
    type: Literal["role"] = "role"
    org: NonEmpty
    location: str | None = None
    dates: DateRange
    employment: str | None = None


class Fact(BaseEntry):
    type: Literal["fact"] = "fact"
    parent: Slug


class Project(BaseEntry):
    type: Literal["project"] = "project"
    dates: DateRange
    org: str | None = None
    url: str | None = None
    role: str | None = None


class Blog(BaseEntry):
    type: Literal["blog"] = "blog"
    url: NonEmpty
    published: str | None = None
    #: Extracted body text. Selection must never depend on a live fetch
    #: (AC-R9.3) — URLs rot and the pipeline has to work offline.
    snapshot: str | None = None


class Education(BaseEntry):
    type: Literal["education"] = "education"
    org: NonEmpty
    dates: DateRange | None = None
    credential: str | None = None
    location: str | None = None


class Certification(BaseEntry):
    type: Literal["certification"] = "certification"
    issuer: NonEmpty
    issued: str | None = None
    credential_id: str | None = None
    url: str | None = None


class Award(BaseEntry):
    type: Literal["award"] = "award"
    org: NonEmpty
    awarded: str | None = None


ENTRY_MODELS: dict[str, type[BaseEntry]] = {
    "role": Role,
    "fact": Fact,
    "project": Project,
    "blog": Blog,
    "education": Education,
    "certification": Certification,
    "award": Award,
}


def model_for(entry_type: str) -> type[BaseEntry]:
    try:
        return ENTRY_MODELS[entry_type]
    except KeyError:
        known = ", ".join(sorted(ENTRY_MODELS))
        raise ValueError(f"unknown type {entry_type!r}; expected one of: {known}") from None


class SkillDeclaration(BaseModel):
    """One row of ``kb/skills.yaml`` (spec-01 §3.5).

    ``evidence`` is required and non-empty: a declared skill with nothing
    backing it is exactly where resume inflation lives, so it is rejected
    rather than carried.
    """

    model_config = ConfigDict(extra="forbid")

    skill: Slug
    depth: Depth
    evidence: list[Slug] = Field(min_length=1)
    #: Presentation grouping for the rendered Skills section ("Languages",
    #: "Backend & Cloud"). Editorial and user-controlled: the taxonomy's facets
    #: describe what a term *is*, which is not the same as how a reader wants
    #: skills grouped on a page. Falls back to the facet when unset.
    group: str | None = None


class TaxonomyTerm(BaseModel):
    """One term of ``kb/taxonomy.yaml`` (spec-01 §3.6).

    Aliases bridge the gap between the user's vocabulary and a posting's, for
    the tag UI and the audit view. They are **not** a retrieval mechanism — the
    model reads fact bodies regardless (R11).
    """

    model_config = ConfigDict(extra="forbid")

    label: NonEmpty
    facet: Literal["skill", "tech", "domain", "role-type", "artifact-type", "impact-type"]
    parent: Slug | None = None
    aliases: list[str] = Field(default_factory=list)
