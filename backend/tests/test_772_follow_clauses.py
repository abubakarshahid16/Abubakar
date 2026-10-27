"""#772 (R8), second half: a clause a held standard cites in another HELD standard is searched for in
that standard's own text and requirements, and each citation ends in a named state. Invented
standards only; identifiers and counts."""

from __future__ import annotations

import pytest

from app import db, reference_follow, standard_references
from app.config import settings
from app.db import connect


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    from app import submittal_review

    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _standard(doc_id, number, pages, requirements=()):
    """A held standard: its classification, page text and stored requirements (clause, text)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?, ?, ?, 1, '/nowhere', 'ready', '2026-01-01')",
            (doc_id, f"{number}.pdf", f"sha-{doc_id}"),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, document_number,"
            " suggested_by) VALUES (?, 'COMPANY_STANDARD', ?, 'human')",
            (doc_id, number),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
                " VALUES (?, ?, ?, ?, 0)",
                (doc_id, n, text, len(text)),
            )
        for i, (clause, text) in enumerate(requirements):
            conn.execute(
                "INSERT INTO standard_requirements (id, standard_document_id, clause, page,"
                " requirement_text, source_text, requirement_type, created_at, updated_at)"
                " VALUES (?, ?, ?, 1, ?, ?, 'must', '2026-01-01', '2026-01-01')",
                (f"{doc_id}-r{i}", doc_id, clause, text, text),
            )


def _allowed():
    return frozenset(r["id"] for r in connect().execute("SELECT id FROM documents"))


TARGET_PAGE = (
    "5.2 Relief valves shall be sized for the largest single contingency.\n"
    "5.3 The set pressure shall not exceed the maximum allowable working pressure.\n"
)
TARGET_REQS = [
    ("5.2", "Relief valves shall be sized for the largest single contingency."),
    (
        "5.3",
        "The set pressure shall not exceed the maximum allowable working pressure.",
    ),
]


def _states(result):
    return sorted((i["clause"], i["state"]) for i in result["checked"])


def test_a_cited_clause_that_the_held_copy_has_is_followed_and_one_it_lacks_is_named():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src",
        "SPEC-7",
        [
            "Valves shall be sized per XYZ-100 clause 5.2 and checked per XYZ-100 clause 9.9."
        ],
    )
    result = reference_follow.follow(["src"], _allowed())
    assert _states(result) == [
        ("clause 5.2", "followed"),
        ("clause 9.9", "clause_missing"),
    ]


def test_a_citation_of_the_standard_alone_is_counted_not_followed():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Valves shall comply with XYZ-100."])
    result = reference_follow.follow(["src"], _allowed())
    assert result["checked"] == [] and result["whole"] == 1


def test_a_held_copy_with_no_stored_requirements_is_not_checked_never_missing():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], [])
    _standard("src", "SPEC-7", ["Valves shall be sized per XYZ-100 clause 5.2."])
    result = reference_follow.follow(["src"], _allowed())
    assert _states(result) == [("clause 5.2", "not_checked")]


def test_a_standard_does_not_follow_a_clause_cited_in_itself():
    _standard(
        "tgt", "XYZ-100", ["See XYZ-100 clause 5.2 above. " + TARGET_PAGE], TARGET_REQS
    )
    assert reference_follow.follow(["tgt"], _allowed())["checked"] == []


def test_the_same_citation_printed_twice_counts_once():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src",
        "SPEC-7",
        ["Size per XYZ-100 clause 5.2.", "Again, size per XYZ-100 clause 5.2."],
    )
    assert len(reference_follow.follow(["src"], _allowed())["checked"]) == 1


def test_a_source_with_no_text_is_counted_unread():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", [])
    assert reference_follow.follow(["src"], _allowed())["unread"] == 1


def test_the_note_names_what_is_missing_and_states_the_counts():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src",
        "SPEC-7",
        ["Size per XYZ-100 clause 5.2 and per XYZ-100 clause 9.9. Also XYZ-100."],
    )
    [note] = reference_follow.notes(reference_follow.follow(["src"], _allowed()))
    assert note["count"] == 1
    assert "1 found in the held copy, 1 not found" in note["detail"]
    assert "XYZ-100 clause 9.9 (cited by SPEC-7)" in note["detail"]
    assert "nothing to follow" in note["detail"]


def test_no_clause_cited_means_no_note():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Valves shall comply with XYZ-100."])
    assert reference_follow.notes(reference_follow.follow(["src"], _allowed())) == []


def test_the_run_note_carries_both_halves_through_for_run(monkeypatch):
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Size per XYZ-100 clause 9.9 and ISO 99999."])
    with connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
            " text, token_count, content_hash) VALUES ('src-0', 'src', 'SPEC-7.pdf', 0, 1, 1,"
            " 'Size per XYZ-100 clause 9.9 and ISO 99999.', 9, 'h-src')"
        )
    used = ["src"]
    notes = standard_references.notes(*standard_references.not_held(used, _allowed()))
    follow_notes = reference_follow.for_run(used, _allowed())
    assert notes and "ISO 99999" in notes[0]["detail"]
    assert follow_notes and "not found" in follow_notes[0]["detail"]


def test_a_check_that_cannot_run_is_said_with_the_error_type_only(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("secret text")

    monkeypatch.setattr(reference_follow, "follow", boom)
    [note] = reference_follow.for_run(["x"], frozenset())
    assert note["count"] is None and "RuntimeError" in note["detail"]
    assert "secret" not in note["detail"]


def test_a_clause_inside_a_printed_range_is_counted_not_dropped():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Size per XYZ-100 clauses 5.1 to 5.4."])
    result = reference_follow.follow(["src"], _allowed())
    states = [i["state"] for i in result["checked"]]
    assert states.count("in_range") >= 1, states
    [note] = reference_follow.notes(result)
    assert "inside a printed range" in note["detail"]
    total = len(result["checked"])
    assert f"{total} clause reference(s)" in note["detail"]
