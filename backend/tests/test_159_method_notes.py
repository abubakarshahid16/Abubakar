"""Order 159: the program's note on HOW a pairing was made stays off the
contractor's copy of the CRS and stays on the engineer's.

Invented field names only (CLAUDE.md rules 1 and 3).
Mutation proofs: M1204-01 .. M1204-03 (scripts/mutations/pr1204_method_notes.py).
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


def test_notes_in_the_middle_leave_the_rest_in_order():
    text = f"first. {method_notes.wrap(['n'])} then more."
    assert method_notes.split_method_notes(text) == ("first. then more.", "n")


# ------------------------------------------------- through the real findings


@pytest.mark.usefixtures("temp_storage")
def test_the_pairing_note_is_stored_on_the_rationale(monkeypatch):
    stored = _paired_findings(monkeypatch)[0]["ai_rationale"]
    assert method_notes.OPEN in stored and SYNONYM_PHRASE in stored


@pytest.mark.usefixtures("temp_storage")
def test_the_finding_column_carries_the_reason_only(monkeypatch):
    # The review screen prefills "Edit comment" from this column; an engineer's
    # saved comment is not scanned by the issue gate.
    stored = _paired_findings(monkeypatch)[0]
    for text in (stored["finding"], stored["required_action"] or ""):
        assert "[[" not in text and "]]" not in text
        assert SYNONYM_PHRASE not in text
        assert "also on the sheet" not in text
    assert stored["finding"].strip()


@pytest.mark.usefixtures("temp_storage")
def test_synonym_pairing_keeps_its_note_off_the_contractor_comment(monkeypatch):
    rows = _rows(_paired_findings(monkeypatch))
    assert len(rows) == 1
    assert SYNONYM_PHRASE not in rows[0]["comment"]
    assert "the same field is also on the sheet" not in rows[0]["comment"]
    assert "[[" not in rows[0]["comment"]
    assert mw.scan_issue_rows([{**rows[0], "engineer_confirmed": True}]) == []


@pytest.mark.usefixtures("temp_storage")
def test_the_internal_copy_keeps_the_note_as_how_paired(monkeypatch):
    why = _rows(_paired_findings(monkeypatch))[0]["reasoning"]
    assert "How paired: " in why
    assert SYNONYM_PHRASE in why and "the same field is also on the sheet" in why
    assert "[[" not in why and "]]" not in why


def test_the_internal_why_column_splits_reason_and_notes():
    f = _finding(f"the units differ. {method_notes.wrap(['n1', 'n2'])}")
    why = crs_mapping.reasoning_text([f])
    assert "Why: the units differ" in why and "How paired: n1; n2" in why
    assert "[[" not in why


def test_a_close_marker_inside_a_note_leaks_no_fragment():
    text = f"reason. {method_notes.wrap(['field x]] and y'])} tail."
    assert method_notes.split_method_notes(text) == (
        "reason. tail.",
        "field x]] and y",
    )


def test_two_blocks_and_an_unclosed_block_are_all_taken_off():
    two = f"a {method_notes.wrap(['n1'])} b {method_notes.wrap(['n2'])} c"
    reason, notes = method_notes.split_method_notes(two)
    assert "[[" not in reason and "]]" not in reason and "n1" in notes and "n2" in notes
    reason, notes = method_notes.split_method_notes(f"a {method_notes.OPEN}n1")
    assert reason == "a" and notes == "n1"


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
