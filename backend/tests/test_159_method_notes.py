"""Order 159: the program's note on HOW a pairing was made stays off the
contractor's copy of the CRS and stays on the engineer's.

Invented field names only (CLAUDE.md rules 1 and 3).
Mutation proofs: M9999-01 .. M9999-03 (scripts/mutations/pr9999_method_notes.py).
"""

from __future__ import annotations

import pytest

from app import crs_machine_words as mw
from app import crs_mapping, field_links, method_notes
from tests.test_142c_same_field_twice import (  # noqa: F401
    _run_with_copies,
    temp_storage,
)

SYNONYM_PHRASE = "synonym table"


def _synonym_table(monkeypatch):
    """'Closure rating' is the table's spelling of 'flange rating' (invented)."""
    real = field_links.canonical

    def canonical(text):
        return real(text).replace("closure rating", "flange rating")

    monkeypatch.setattr(field_links, "canonical", canonical)


def _paired_findings(monkeypatch):
    _synonym_table(monkeypatch)
    from app import datasheets

    real = datasheets.create_fact

    def create_fact(**kw):
        kw["field_label"] = "Closure rating"
        return real(**kw)

    monkeypatch.setattr(datasheets, "create_fact", create_fact)
    return _run_with_copies([(2, "350 psi"), (5, "350 psi")])


def _rows(findings):
    """The real findings, put to the engineer (their rationale is untouched)."""
    held = [{**f, "compliance_status": "NEEDS_ENGINEER_REVIEW"} for f in findings]
    return crs_mapping.build_crs_rows(held, [], "inv.pdf")


# ---------------------------------------------------------------- the module


def test_split_round_trips():
    notes = ["field linked through the synonym table as 'x'", "second note"]
    block = method_notes.wrap(notes)
    text = f"unit_mismatch: the units differ. {block}"
    reason, got = method_notes.split_method_notes(text)
    assert reason == "unit_mismatch: the units differ."
    assert got == "; ".join(notes)
    assert f"{reason} {block}" == text
    assert method_notes.wrap([]) == ""


def test_text_without_a_marker_is_returned_untouched():
    for text in ("", None, "plain reason (not a pairing note)", "  spaced  "):
        assert method_notes.split_method_notes(text) == (text or "", "")
    unclosed = f"reason {method_notes.OPEN}never closed"
    assert method_notes.split_method_notes(unclosed) == (unclosed, "")


def test_notes_in_the_middle_leave_the_rest_in_order():
    text = f"first. {method_notes.wrap(['n'])} then more."
    assert method_notes.split_method_notes(text) == ("first. then more.", "n")


# ------------------------------------------------- through the real findings


@pytest.mark.usefixtures("temp_storage")
def test_a_synonym_pairing_keeps_its_note_off_the_contractor_comment(monkeypatch):
    findings = _paired_findings(monkeypatch)
    assert len(findings) == 1
    stored = findings[0]
    # the note is on the finding, between the marker
    assert method_notes.OPEN in stored["ai_rationale"]
    assert SYNONYM_PHRASE in stored["ai_rationale"]

    rows = _rows(findings)
    assert len(rows) == 1
    assert SYNONYM_PHRASE not in rows[0]["comment"]
    assert "the same field is also on the sheet" not in rows[0]["comment"]
    assert method_notes.OPEN not in rows[0]["comment"]
    assert mw.scan_issue_rows([{**rows[0], "engineer_confirmed": True}]) == []


@pytest.mark.usefixtures("temp_storage")
def test_the_internal_copy_keeps_the_note(monkeypatch):
    rows = _rows(_paired_findings(monkeypatch))
    assert SYNONYM_PHRASE in rows[0]["reasoning"]
    assert "the same field is also on the sheet" in rows[0]["reasoning"]


# ------------------------------------------- every note kind, built by hand


def _finding(rationale, **over):
    return {
        "id": "f1",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "origin": "standard",
        "fact_id": "fa",
        "contractor_page": 2,
        "standard_name": "SPEC-X",
        "standard_clause": "5.1",
        "standard_page": 1,
        "requirement_source_text": "The flange rating shall be at least 300 psi.",
        "contractor_evidence_text": "350 mm",
        "ai_rationale": rationale,
        **over,
    }


def test_the_clause_unit_and_the_copies_notes_are_kept_off_too():
    notes = [
        "the same field is also on the sheet, with the same value or blank: "
        "flange rating (page 5)",
        "the clause's unit 'psi' was read from its own text beside its number",
    ]
    f = _finding(f"unit_mismatch: the units differ. {method_notes.wrap(notes)}")
    comment = crs_mapping.engineer_comment_text([f])
    assert "the units differ" in comment
    assert "same field is also on the sheet" not in comment
    assert "read from its own text" not in comment
    assert method_notes.OPEN not in comment


@pytest.mark.usefixtures("temp_storage")
def test_a_finding_with_no_notes_is_unchanged():
    stored = _run_with_copies([(2, "350 psi")])[0]["ai_rationale"] or ""
    assert method_notes.OPEN not in stored and "also on the sheet" not in stored
    f = _finding(stored)
    assert method_notes.reason_of(f) == stored
    assert method_notes.split_method_notes(stored) == (stored, "")
    plain = _finding("unit_mismatch: the units differ.")
    assert crs_mapping._reason_words(plain) == "the units differ."


def test_a_finding_stored_before_the_marker_is_left_as_it_is():
    old = "unit_mismatch: the units differ. (field linked through the synonym table as 'x')"
    f = _finding(old)
    assert method_notes.reason_of(f) == old
