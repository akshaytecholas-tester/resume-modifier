"""`kb/identity.yaml` — the one PII-dense file, with named contact sets (spec-01 §2.1).

Two contact sets exist because the referral and direct application channels
carry different details, and every configured set gets its own rendered resume
(R17). One set is the common case and must stay effortless, so a flat
``email``/``phone`` file is read as a single set named ``default``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .yamlio import load_yaml

DEFAULT_SET_NAME = "default"


class ContactSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> ContactSet:
        if not self.email and not self.phone:
            raise ValueError("a contact set needs an email, a phone, or both")
        return self


class Links(BaseModel):
    model_config = ConfigDict(extra="allow")

    linkedin: str | None = None
    github: str | None = None
    website: str | None = None

    def pairs(self) -> list[tuple[str, str]]:
        """Non-empty links in declaration order, for the contact line."""
        out: list[tuple[str, str]] = []
        for key, value in self.model_dump(exclude_none=True).items():
            if isinstance(value, str) and value.strip():
                out.append((key, value.strip()))
        return out


class Identity(BaseModel):
    """Validated identity. ``contacts`` always holds at least one set."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    headline: str | None = None
    location: str | None = None
    contacts: dict[str, ContactSet] = Field(min_length=1)
    default_set: str
    links: Links = Field(default_factory=Links)

    @model_validator(mode="after")
    def _default_set_exists(self) -> Identity:
        if self.default_set not in self.contacts:
            known = ", ".join(sorted(self.contacts))
            raise ValueError(
                f"default_set {self.default_set!r} names no configured set; have: {known}"
            )
        return self

    @property
    def set_names(self) -> list[str]:
        """Configured set names, default first.

        Export order is observable — it decides which resume a hurried user
        opens first — so it is defined rather than left to dict ordering.
        """
        rest = sorted(n for n in self.contacts if n != self.default_set)
        return [self.default_set, *rest]

    def contact(self, set_name: str) -> ContactSet:
        try:
            return self.contacts[set_name]
        except KeyError:
            known = ", ".join(sorted(self.contacts))
            raise KeyError(f"no contact set named {set_name!r}; have: {known}") from None


def normalise_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """Fold the flat one-contact form into the named-set form.

    A file carrying both shapes is rejected rather than guessed at: picking one
    would silently drop the other, and the dropped one is a phone number the
    user believes is on their resume.
    """
    data = dict(raw)
    flat = {k: data.pop(k) for k in ("email", "phone") if k in data}
    flat = {k: v for k, v in flat.items() if v not in (None, "")}

    if flat and data.get("contacts"):
        raise ValueError(
            "identity.yaml has both a flat email/phone and a `contacts` block. "
            "Keep one: move the flat values into a named set, or delete them."
        )

    if flat:
        data["contacts"] = {DEFAULT_SET_NAME: flat}
        data.setdefault("default_set", DEFAULT_SET_NAME)

    contacts = data.get("contacts")
    if isinstance(contacts, dict) and len(contacts) == 1:
        # One set needs no `default_set` — requiring it would be friction with
        # exactly one possible answer.
        data.setdefault("default_set", next(iter(contacts)))

    return data


def load_identity(path: Path) -> Identity:
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return Identity.model_validate(normalise_identity(raw))
