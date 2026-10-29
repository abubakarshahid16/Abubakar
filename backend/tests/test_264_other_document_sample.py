"""Order 264.4: the sampling script puts each "requires another document" row in one class."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "sample_other_document_gate.py"
)


@pytest.fixture(scope="module")
def sample():
    spec = importlib.util.spec_from_file_location("sample_other_document_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CASES = [
    (
        "The vendor shall submit a calibration certificate for each gauge.",
        "plausible_deliverable",
    ),
    ("A test report shall be furnished before shipment.", "plausible_deliverable"),
    ("The pump shall be provided with API Plan 53B.", "fitment_provided_with"),
    (
        "The planetary gear shall run at 1500 rpm and be provided by the vendor.",
        "noun_inside_longer_word",
    ),
    (
        "The vendor shall provide the pump with a seal plan of 53B.",
        "fitment_provided_with",
    ),
    (
        "Vendor shall submit the pump; the recorded noise level shall not exceed 85 dB.",
        "noun_inside_longer_word",
    ),
    (
        "The bearing housing shall be provided. Nothing else is stated until a long way along the page, then a record.",
        "noun_far_from_verb",
    ),
    ("The vendor shall submit a procedure.", "weak_noun_only"),
    ("Wall thickness shall be at least 12 mm.", None),
]


@pytest.mark.parametrize("sentence, expected", CASES)
def test_classes(sample, sentence, expected):
    assert sample.classify(sentence) == expected


def test_counts_only_and_deterministic(sample):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE review_findings (id TEXT, review_run_id TEXT, compliance_status TEXT, "
        "ai_rationale TEXT, requirement_source_text TEXT, requirement TEXT)"
    )
    for n, (text, _k) in enumerate(CASES):
        conn.execute(
            "INSERT INTO review_findings VALUES (?,?,?,?,?,?)",
            (
                f"f{n}",
                "run",
                "NOT_IN_DOCUMENT_SCOPE",
                "requires_other_document: x",
                text,
                text,
            ),
        )
    conn.execute(
        "INSERT INTO review_findings VALUES ('o','other','NOT_IN_DOCUMENT_SCOPE','requires_other_document: x','t','t')"
    )
    report, _ids = sample.count(conn, "run", 5)
    again, _ = sample.count(conn, "run", 5)
    assert report == again
    assert report["sent_away_in_run"] == len(CASES) and report["sampled"] == 5
    assert sum(report["classes"].values()) == 5
    assert "The" not in str(report)  # no sentence text in the output


def test_marker_is_what_the_real_compare_writes(sample):
    from app import comparison

    requirement = {
        "requirement_type": "numeric_limit",
        "requirement_text": "The vendor shall submit a calibration certificate.",
        "required_evidence_type": "certificate",
    }
    verdict = comparison.compare(requirement, None)
    assert verdict["status"] == sample.STATUS
    assert sample.MARK in verdict["rationale"]
    assert sample.MARK == comparison.REQUIRES_OTHER_DOCUMENT
