"""Order 152.2: no machine wording in the contractor's copy. Invented data
only - field names here are made up and name no datasheet, label or standard.
"""

from __future__ import annotations

import pytest

from app import crs_issue
from app import crs_machine_words as mw
from app.config import settings

COVERED = {"pages_total": 1, "pages_not_read_into_fields": []}


def _row(n: int, comment: str, **over) -> dict:
    return {
        "finding_id": f"f{n}",
        "document_name": "inv.pdf",
        "page_section": f"p.{n}",
        "comment": comment,
        "comment_by": "AI Review",
        "row_kind": "missing_information",
        "engineer_confirmed": True,
        **over,
    }


# ------------------------------------------------------------ the words


@pytest.mark.parametrize(
    "text, word",
    [
        ("The widget_flow_limit is not stated.", "widget_flow_limit"),
        ("Verdict NEEDS_WIDGET_REVIEW was reached.", "NEEDS_WIDGET_REVIEW"),
        ("Read as gadgetRatingValue on page 2.", "gadgetRatingValue"),
        ("Computed by gadget.read(x) here.", "gadget.read("),
        ("Linked through the synonym table as 'pressure'.", "synonym table"),
        ("Paired by a containment match.", "containment match"),
    ],
)
def test_machine_words_are_found(text, word):
    assert word in mw.find_machine_words(text)


def test_model_and_engine_names_come_from_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "zorbex9:77b")
    mw._named.cache_clear()
    found = mw.find_machine_words("Worded by Zorbex9:77b, then checked by Ollama.")
    assert "Zorbex9:77b" in found and "Ollama" in found
    # the family part alone is a machine word too
    assert "zorbex9" in [w.lower() for w in mw.find_machine_words("the zorbex9 reader")]
    mw._named.cache_clear()


def test_plain_engineering_wording_is_clean():
    plain = (
        "Design pressure 12 bar at 40 degC; motor 15 kWh/d, 120 mmHg, 4 mA. "
        "Secondary containment is required (clause 4.2). Item FT_101 and tag "
        "ft_101a are listed. Please state the maximum working pressure."
    )
    assert mw.find_machine_words(plain) == []
    assert mw.find_machine_words(None) == [] and mw.find_machine_words("  ") == []


# ------------------------------------------------------- which cells count


def test_scan_reports_comment_number_cell_and_words():
    rows = [
        _row(1, "Plain words only."),
        _row(2, "Field widget_flow_limit missing.", crs_ref="CRS-001-002"),
        _row(3, "Fine.", standard_reference="NEEDS_WIDGET_REVIEW"),
    ]
    hits = mw.scan_issue_rows(rows)
    assert hits == [
        {"comment": "CRS-001-002", "cell": "comment", "words": ["widget_flow_limit"]},
        {
            "comment": "3",
            "cell": "standard_reference",
            "words": ["NEEDS_WIDGET_REVIEW"],
        },
    ]


def test_an_engineer_edited_row_is_not_scanned():
    row = _row(1, "my own note about widget_flow_limit", edited=True)
    assert mw.scan_issue_rows([row]) == []


def test_rows_the_issue_copy_does_not_carry_are_not_scanned():
    bad = "widget_flow_limit"
    rows = [
        _row(1, bad, engineer_confirmed=False),
        _row(2, bad, engineer_rejected=True),
        _row(3, bad, row_kind="safety_tick"),
        _row(4, bad, ai_review_comment="a draft"),
    ]
    assert mw.scan_issue_rows(rows) == []


# ------------------------------------------------------------- the gate


def test_gate_blocks_and_names_the_comment_and_the_word():
    rows = [_row(1, "Plain."), _row(2, "Field widget_flow_limit is missing.")]
    gate = crs_issue.open_items("run-1", rows, COVERED)
    assert gate["issuable"] is False
    (text,) = gate["blockers"]
    assert "widget_flow_limit" in text and "(2" in text
    assert "edit the wording" in text


def test_gate_is_open_for_plain_words():
    gate = crs_issue.open_items("run-1", [_row(1, "Plain.")], COVERED)
    assert gate["blockers"] == [] and gate["issuable"] is True


def test_a_standard_shown_by_its_stored_id_is_a_machine_word():
    """With no name on record the Standard Reference falls back to the stored
    id (`doc_<hash>`); that is not something a contractor can look up."""
    rows = [_row(1, "Plain.", standard_reference="doc_a3df49861559 cl. 4 (p.2)")]
    assert mw.scan_issue_rows(rows)[0]["words"] == ["doc_a3df49861559"]
