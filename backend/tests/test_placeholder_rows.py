"""Owner 3 Nov: a row whose contractor-facing comment is only "AI suggestion awaiting an engineer's decision" leaves the
CRS sheet of the internal copy; its AI words stay in the Review notes. Invented rows only."""

from __future__ import annotations

from app import crs_export
from app import crs_export_quality as quality
from app.config import settings
from app.crs_draft_lanes import AI_UNCONFIRMED_COMMENT

AI_WORDS = "A blank value here is unusual; contractor to state it."


def row(comment, ai="", confirmed=False, **over):
    base = {
        "document_name": "D.pdf",
        "page_section": "p.2 - Field",
        "comment": comment,
        "comment_by": "AI Review",
        "standard_reference": "STD-1 4.1",
        "row_kind": "datasheet_check",
        "engineer_confirmed": confirmed,
        "ai_review_comment": ai,
    }
    return {**base, **over}


ROWS = [
    row("Set pressure 12 barg is above the 10 barg limit."),
    row(AI_UNCONFIRMED_COMMENT, ai=AI_WORDS, standard_reference="STD-2 9.9"),
]
META = {"review_run_id": "run-1", "export_quality": True}


def view(copy, monkeypatch, on=True):
    monkeypatch.setattr(settings, "crs_drop_placeholder_rows_enabled", on)
    return crs_export.build_crs_view(ROWS, {**META, "copy": copy})


def test_off_the_placeholder_row_is_on_the_sheet(monkeypatch):
    assert len(view("internal", monkeypatch, on=False)["rows"]) == 2


def test_on_it_leaves_the_internal_sheet_and_its_words_go_to_the_review_notes(
    monkeypatch,
):
    v = view("internal", monkeypatch)
    assert [r["comment"] for r in v["rows"]] == [ROWS[0]["comment"]]
    parked = [n for n in v["review_notes"] if n["note"] == quality.NOTE_PARKED]
    assert len(parked) == 1
    assert parked[0]["detail"] == AI_WORDS and parked[0]["standard"] == "STD-2 9.9"


def test_the_contractor_copy_is_unchanged(monkeypatch):
    on = view("issue", monkeypatch)
    off = view("issue", monkeypatch, on=False)
    assert on["rows"] == off["rows"]
    assert quality.NOTE_PARKED not in [n["note"] for n in on["review_notes"]]


def test_a_row_with_an_issued_number_is_never_parked(monkeypatch):
    monkeypatch.setattr(settings, "crs_drop_placeholder_rows_enabled", True)
    kept = [
        row(AI_UNCONFIRMED_COMMENT, ai=AI_WORDS, confirmed=True, crs_ref="CRS-1-001")
    ]
    v = crs_export.build_crs_view(kept, {**META, "copy": "internal"})
    assert len(v["rows"]) == 1


def test_the_top_note_counts_the_moved_rows_so_nothing_vanishes_unseen(monkeypatch):
    v = view("internal", monkeypatch)
    assert "1 AI suggestions moved to Review notes" in v["run_status_note"]
    off = view("internal", monkeypatch, on=False)
    assert "moved to Review notes" not in off["run_status_note"]
    issue = view("issue", monkeypatch)
    assert "moved to Review notes" not in issue["run_status_note"]
