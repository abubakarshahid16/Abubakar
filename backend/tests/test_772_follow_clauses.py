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


def _standard(doc_id, number, pages, requirements=(), filename=None):
    """A held standard: its classification, page text and stored requirements (clause, text)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?, ?, ?, 1, '/nowhere', 'ready', '2026-01-01')",
            (doc_id, filename or f"{number}.pdf", f"sha-{doc_id}"),
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


# ----------------------------------------------- cloud's review of #1376: grants, editions, wiring


def test_a_source_the_caller_may_not_read_is_never_followed_nor_named():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Size per XYZ-100 clause 9.9."])
    result = reference_follow.follow(["src"], frozenset(["tgt"]))
    assert result["checked"] == [] and result["unread"] == 1
    assert reference_follow.notes(result) == []


def test_a_standard_held_in_two_editions_is_counted_not_dropped():
    _standard("t19", "XYZ-100", [TARGET_PAGE], TARGET_REQS, filename="XYZ-100-2019.pdf")
    _standard("t23", "XYZ-100", [TARGET_PAGE], TARGET_REQS, filename="XYZ-100-2023.pdf")
    _standard("src", "SPEC-7", ["Size per XYZ-100 clause 5.2."])
    result = reference_follow.follow(["src"], _allowed())
    assert [i["state"] for i in result["checked"]] == ["several_editions"]
    [note] = reference_follow.notes(result)
    assert "1 name a standard held in several editions" in note["detail"]


def test_a_cited_edition_the_held_copy_is_not_is_not_followed_into_it():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS, filename="XYZ-100-2023.pdf")
    _standard("src", "SPEC-7", ["Size per XYZ-100-2019 clause 5.2."])
    result = reference_follow.follow(["src"], _allowed())
    assert [i["state"] for i in result["checked"]] == ["other_edition"]


def test_a_clause_list_that_cannot_be_read_for_certain_is_not_checked_never_whole():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Size per XYZ-100 clauses 5.1 to 6.2."])
    result = reference_follow.follow(["src"], _allowed())
    assert result["whole"] == 0
    assert [i["state"] for i in result["checked"]] == ["not_checked"]


def test_five_mentions_of_one_standard_alone_count_once():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src",
        "SPEC-7",
        ["Use XYZ-100. Again XYZ-100. And XYZ-100. XYZ-100 too. XYZ-100."],
    )
    assert reference_follow.follow(["src"], _allowed())["whole"] == 1


def test_the_followed_clause_names_its_page_and_the_listing_sorts_numerically():
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src", "SPEC-7", ["Size per XYZ-100 clause 5.2 and per XYZ-100 clause 5.3."]
    )
    [note] = reference_follow.notes(reference_follow.follow(["src"], _allowed()))
    assert "XYZ-100 clause 5.2 p.1 (cited by SPEC-7)" in note["detail"]
    from app.reference_follow import _natural

    assert sorted(["8.10", "8.2", "8.1"], key=_natural) == ["8.1", "8.2", "8.10"]


def test_the_text_of_a_target_is_built_once_per_run(monkeypatch):
    from app import subject_scope

    built = []
    real = subject_scope.StandardText

    def counting(pages):
        built.append(1)
        return real(pages)

    monkeypatch.setattr(subject_scope, "StandardText", counting)
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard(
        "src",
        "SPEC-7",
        ["Per XYZ-100 clause 5.2. Per XYZ-100 clause 5.3. Per XYZ-100 clause 9.9."],
    )
    reference_follow.follow(["src"], _allowed())
    assert len(built) == 1


def test_the_run_note_reaches_the_review_notes_through_standard_references():
    from app import submittal_review

    submittal_review.ensure_schema()
    _standard("tgt", "XYZ-100", [TARGET_PAGE], TARGET_REQS)
    _standard("src", "SPEC-7", ["Size per XYZ-100 clause 9.9."])
    with connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at)"
            " VALUES ('r1', 'src', 'completed', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id,"
            " included, created_at) VALUES ('x1', 'r1', 'src', 1, '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, text,"
            " token_count, content_hash) VALUES ('c1', 'src', 'SPEC-7.pdf', 0, 1, 1,"
            " 'Size per XYZ-100 clause 9.9.', 6, 'h1')"
        )
    notes = standard_references.for_run("r1", _allowed())
    assert any(
        n["note"] == reference_follow.NOTE and "clause 9.9" in n["detail"]
        for n in notes
    )
