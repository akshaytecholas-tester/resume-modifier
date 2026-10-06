"""Contact sets, including the flat back-compat path (spec-01 §2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.identity import Identity, load_identity, normalise_identity


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "identity.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_flat_form_reads_as_one_set_named_default(tmp_path: Path) -> None:
    """AC-R17.4: a user who never needs two sets never has to learn about them."""
    path = write(tmp_path, "name: A Person\nemail: a@example.com\nphone: '+1 555'\n")
    identity = load_identity(path)
    assert identity.set_names == ["default"]
    assert identity.contact("default").email == "a@example.com"


def test_named_sets_with_explicit_default(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "name: A Person\n"
        "contacts:\n"
        "  referral: {email: r@example.com, phone: '+1 111'}\n"
        "  direct: {email: d@example.com, phone: '+1 222'}\n"
        "default_set: direct\n",
    )
    identity = load_identity(path)
    # Default first: export order decides which resume a hurried user opens.
    assert identity.set_names == ["direct", "referral"]


def test_both_shapes_at_once_is_refused(tmp_path: Path) -> None:
    """Guessing would silently drop a phone number the user believes is live."""
    path = write(
        tmp_path,
        "name: A Person\nemail: flat@example.com\n"
        "contacts:\n  direct: {email: d@example.com}\ndefault_set: direct\n",
    )
    with pytest.raises(ValueError, match="both a flat email/phone and a `contacts` block"):
        load_identity(path)


def test_single_named_set_needs_no_default_set(tmp_path: Path) -> None:
    path = write(tmp_path, "name: A Person\ncontacts:\n  direct: {email: d@example.com}\n")
    assert load_identity(path).set_names == ["direct"]


def test_default_set_naming_a_missing_set_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "name: A Person\n"
        "contacts:\n  direct: {email: d@example.com}\n  referral: {email: r@example.com}\n"
        "default_set: nope\n",
    )
    with pytest.raises(ValueError, match="names no configured set"):
        load_identity(path)


def test_two_sets_without_default_set_is_refused(tmp_path: Path) -> None:
    """With two sets there is no obvious answer, so the user must say."""
    path = write(
        tmp_path,
        "name: A Person\n"
        "contacts:\n  direct: {email: d@example.com}\n  referral: {email: r@example.com}\n",
    )
    with pytest.raises(ValueError):
        load_identity(path)


def test_empty_contact_set_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "name: A Person\ncontacts:\n  direct: {}\n")
    with pytest.raises(ValueError, match="needs an email, a phone, or both"):
        load_identity(path)


def test_no_contacts_at_all_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_identity(write(tmp_path, "name: A Person\n"))


def test_blank_flat_values_are_not_treated_as_a_set(tmp_path: Path) -> None:
    """An example file with `email: ''` must not masquerade as a configured set."""
    with pytest.raises(ValueError):
        load_identity(write(tmp_path, "name: A Person\nemail: ''\nphone: ''\n"))


def test_unknown_contact_set_names_itself_in_the_error() -> None:
    identity = Identity.model_validate(normalise_identity({"name": "A", "email": "a@example.com"}))
    with pytest.raises(KeyError, match="referral"):
        identity.contact("referral")


def test_links_are_shared_across_sets(tmp_path: Path) -> None:
    """LinkedIn does not change with the application channel; only email and phone do."""
    path = write(
        tmp_path,
        "name: A Person\n"
        "contacts:\n  direct: {email: d@example.com}\n  referral: {email: r@example.com}\n"
        "default_set: direct\n"
        "links: {linkedin: linkedin.com/in/x, website: x.dev}\n",
    )
    identity = load_identity(path)
    assert [k for k, _ in identity.links.pairs()] == ["linkedin", "website"]
