"""The layout fits a full resume on one page (AC-R7.1, spec-05 §4).

`rt render` on a real knowledge base produces two pages, because the baseline
carries every declared skill and uses full fact titles as bullet lead-ins. That
is content volume, and it would be easy to mistake for a layout regression —
or, worse, to hide a real layout regression behind.

So this pins the layout itself: a resume of representative density, with the
same section structure, bullet count and prose length as a one-page document,
must compile to one page. If a later change to margins, leading, font size or
list metrics costs a page, this fails and says so.

The fixture is invented. The owner's real career record lives in a separate
local repository (open-questions OQ-9) and must not appear in a public one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.render.compile import available, compile_pdf
from resume_tailor.render.document import Bullet, Contact, Document, Entry, Section
from resume_tailor.render.latex import render_document

TECTONIC = pytest.mark.skipif(not available(), reason="tectonic is not installed")

SUMMARY = (
    "Results-driven software engineer with **4+ years of experience** across backend "
    "infrastructure, distributed systems and applied machine learning. Proven record of "
    "designing event-driven services handling **12,000+ requests per second** and leading "
    "platform migrations that reduced operating cost. Comfortable owning a service from "
    "design through on-call."
)

SKILLS = [
    ("Languages", "Python, Rust, TypeScript, SQL, Bash"),
    (
        "ML & Data",
        "Retrieval pipelines, vector search, feature stores, Spark, Airflow, "
        "experiment tracking, model evaluation",
    ),
    (
        "Backend & Cloud",
        "REST and gRPC APIs, microservices, message queues, AWS Lambda, Kubernetes, "
        "PostgreSQL, Redis, Terraform, CI/CD",
    ),
    ("Tooling", "Git, Docker, Grafana, pytest, shell scripting"),
]

EXPERIENCE = [
    (
        "Staff Backend Engineer",
        "Northwind Systems",
        "Dublin",
        "Mar 2024 – Present",
        [
            (
                "Throughput & Reliability",
                "Rebuilt the ingestion tier as an event-driven pipeline over Kafka with "
                "idempotent consumers and replay, sustaining **12,000+ requests per second** "
                "at a p99 under 80ms while removing a nightly batch window entirely.",
            ),
            (
                "Platform Migration",
                "Led the migration of fourteen services from EC2 to Kubernetes with no "
                "customer-visible downtime, cutting infrastructure spend by 38% and halving "
                "mean deploy time across the estate.",
            ),
            (
                "On-Call Ownership",
                "Owned the paging rotation for the ingestion domain, drove the error budget "
                "policy, and reduced recurring alerts by two thirds through a programme of "
                "root-cause fixes rather than threshold tuning.",
            ),
        ],
    ),
    (
        "Senior Software Engineer",
        "Harbour Analytics",
        "Bristol",
        "Jun 2022 – Mar 2024",
        [
            (
                "Retrieval Quality",
                "Designed a hybrid retrieval layer combining BM25 with dense embeddings and "
                "a learned reranker, lifting answer accuracy by 31% on the internal "
                "evaluation set and cutting escalations to human review.",
            ),
            (
                "Feature Platform",
                "Built a feature store serving both training and inference from one "
                "definition, eliminating a class of train/serve skew that had caused three "
                "production incidents in the preceding year.",
            ),
            (
                "Query Performance",
                "Profiled and rewrote the reporting layer's slowest queries, introducing "
                "partial indexes and materialised rollups to bring the dashboard's median "
                "load time from 4.2s to 600ms.",
            ),
        ],
    ),
    (
        "Software Engineer",
        "Meridian Labs",
        "Bristol",
        "Sep 2020 – Jun 2022",
        [
            (
                "Service Development",
                "Developed and shipped three customer-facing services in Python and Go, "
                "covering billing reconciliation, notification fan-out and audit logging for "
                "a regulated client base.",
            ),
            (
                "Test Automation",
                "Introduced contract testing between services and wired it into the release "
                "pipeline, which cut integration regressions reaching staging by roughly "
                "half over two quarters.",
            ),
        ],
    ),
]

INTERNSHIPS = [
    (
        "Infrastructure Intern — Cobalt Cloud *(Summer 2020)*",
        "Wrote tooling to detect orphaned cloud resources across accounts, which was adopted "
        "by the platform team and ran weekly thereafter.",
    ),
    (
        "Research Intern — University Robotics Lab *(Summer 2019)*",
        "Implemented a SLAM evaluation harness used to benchmark three competing mapping "
        "approaches for a published comparison.",
    ),
]

CREDENTIALS = [
    (
        "B.Sc. in Computer Science — Example University",
        "**First Class Honours** *(Coursework: algorithms, networks, operating systems)*",
    ),
    (
        "Awards & Certifications",
        "Departmental prize for final-year project | Certified Kubernetes Administrator",
    ),
]


def representative_document() -> Document:
    """A resume with the density of a real one-page document."""
    return Document(
        contact=Contact(
            name="Alex Taylor Morgan",
            headline="Backend & Platform Engineer",
            location="Dublin, Ireland",
            email="alex@example.com",
            phone="+00 0000000000",
            links=(
                ("linkedin", "linkedin.com/in/example-handle"),
                ("website", "example.com"),
            ),
        ),
        contact_set="default",
        sections=(
            Section(heading="Summary", kind="prose", prose=SUMMARY),
            Section(
                heading="Technical Skills",
                kind="bullets",
                bullets=tuple(Bullet(lead=lead, text=text) for lead, text in SKILLS),
            ),
            Section(
                heading="Professional Experience",
                kind="entries",
                entries=tuple(
                    Entry(
                        title=title,
                        org=org,
                        location=location,
                        dates=dates,
                        bullets=tuple(Bullet(lead=lead, text=text) for lead, text in bullets),
                    )
                    for title, org, location, dates, bullets in EXPERIENCE
                ),
            ),
            Section(
                heading="Internships",
                kind="bullets",
                bullets=tuple(Bullet(lead=lead, text=text) for lead, text in INTERNSHIPS),
            ),
            Section(
                heading="Education & Certifications",
                kind="bullets",
                bullets=tuple(Bullet(lead=lead, text=text) for lead, text in CREDENTIALS),
            ),
        ),
    )


@TECTONIC
def test_a_full_resume_fits_on_one_page(tmp_path: Path) -> None:
    """Eight experience bullets, four skill groups, a summary and credentials.

    This is the density the source document carries. If it stops fitting, the
    layout has drifted — margins, leading, font size or list metrics — and the
    cause is here rather than in whatever content happened to be rendered.
    """
    tex = tmp_path / "onepage.tex"
    tex.write_text(render_document(representative_document()), encoding="utf-8")
    result = compile_pdf(tex, tmp_path)
    assert result.pages == 1, (
        f"a representative one-page resume now compiles to {result.pages} pages; "
        "the layout has drifted"
    )


@TECTONIC
def test_nothing_runs_into_the_margin(tmp_path: Path) -> None:
    """Overfull boxes are what a too-long unbreakable string looks like before
    it is visibly outside the text block."""
    tex = tmp_path / "onepage.tex"
    tex.write_text(render_document(representative_document()), encoding="utf-8")
    result = compile_pdf(tex, tmp_path)
    assert not result.overfull, result.overfull


def test_fixture_carries_no_real_contact_details() -> None:
    """The repository is public; the real record lives elsewhere (OQ-9)."""
    doc = representative_document()
    assert doc.contact.email.endswith("example.com")
    assert set(doc.contact.phone.replace("+", "").replace(" ", "")) == {"0"}
    assert all("example" in url for _, url in doc.contact.links)
