"""Phase 3A: clause hierarchy, atomic requirements, revisions, permissions.

The invariants under test, and each fails for its own reason:

  * a requirement CANNOT exist without a citation that resolves to a real
    chunk of the right document, on a page that chunk actually spans;
  * a clause the parser could not identify is recorded as low-confidence with
    a NULL clause - never inherited from whatever clause preceded it, because
    an inherited number resolves to the wrong place;
  * a superseded standard is excluded from SELECTION and stays READABLE and
    CITABLE, which are different questions;
  * every read is filtered in the query under `allowed_document_ids`;
  * zero requirements is a real answer meaning NONE EXTRACTED.

This layer points into the EXISTING chunks. There is no second index here, and
`test_no_second_index_was_created` asserts it.

Mutations: M27-M32, `python scripts/mutation_check.py --phase 3`.
"""

from __future__ import annotations

import pytest

from app import access, db, standards, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "standards.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str = "SAES-A-105.pdf") -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,?,?,'ready',20,?)""",
            (doc_id, filename, f"sha-{doc_id}", 1, filename, "2026-09-18T00:00:00Z"))
    return doc_id


def _standard(doc_id: str, **fields) -> str:
    """A document classified as a COMPANY_STANDARD."""
    columns = ["document_id", "suggested_by", "document_role"]
    values = [doc_id, "test", standards.COMPANY_STANDARD]
    for key, value in fields.items():
        columns.append(key); values.append(value)
    marks = ",".join("?" * len(values))
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({marks})", values)
    return doc_id


def _chunk(chunk_id: str, doc_id: str, text: str, *, section: str | None = None,
           page: int = 1, ordinal: int = 0, retrievable: int = 1) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,?,?,?,?,'prose',?,?,?,?)""",
            (chunk_id, doc_id, "SAES-A-105.pdf", ordinal, page, page, section,
             text, len(text.split()), f"h-{chunk_id}", retrievable))
    return chunk_id


def _scope(*ids: str) -> frozenset[str]:
    return frozenset(ids)


SHALL = "The coating system shall be applied in three separate coats."
PROSE = "This document describes coating systems for offshore structures."


# -------------------------------------------------------- clause hierarchy

def test_clause_numbers_and_pages_resolve_to_the_real_chunk():
    doc = _standard(_doc("doc_std"))
    a = _chunk("c1", doc, SHALL, section="5.3.3 Coating systems", page=9, ordinal=0)
    _chunk("c2", doc, PROSE, section="5.4 Inspection", page=11, ordinal=1)
    clauses = standards.clause_hierarchy(doc, allowed_document_ids=_scope(doc))
    by_number = {c["clause"]: c for c in clauses}
    assert set(by_number) == {"5.3.3", "5.4"}
    assert by_number["5.3.3"]["page"] == 9
    assert by_number["5.3.3"]["chunk_id"] == a
    assert by_number["5.3.3"]["parent_clause"] == "5.3"
    assert by_number["5.3.3"]["depth"] == 3
    assert by_number["5.3.3"]["title"] == "Coating systems"
    assert by_number["5.4"]["parent_clause"] == "5"
    # And the chunk it names is a real one, on that page.
    row = db.connect().execute(
        "SELECT document_id, page_start FROM chunks WHERE id = ?", (a,)).fetchone()
    assert row["document_id"] == doc
    assert row["page_start"] == 9


def test_a_top_level_clause_has_no_parent():
    assert standards.parent_clause("5") is None
    assert standards.clause_depth("5") == 1


def test_an_unnumbered_section_is_never_guessed_into_a_clause():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section=None, page=3)
    assert standards.clause_hierarchy(doc, allowed_document_ids=_scope(doc)) == []
    assert standards.clause_number(None) is None
    assert standards.clause_number("Introduction") is None


# ------------------------------------------------------------ requirements

def test_a_requirement_cannot_be_created_without_a_resolving_citation():
    """THE MUTATION TARGET (M27). Three ways a citation fails to resolve."""
    doc = _standard(_doc("doc_std"))
    other = _standard(_doc("doc_other"), document_number="OTHER-1")
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    _chunk("c9", other, SHALL, section="1.1 Other", page=2)

    # 1. no such chunk
    with pytest.raises(standards.RequirementError):
        standards.create_requirement(
            standard_document_id=doc, chunk_id="nope", requirement_text=SHALL,
            source_text=SHALL, clause="5.1", page=4)
    # 2. a chunk of a DIFFERENT document - opens something real and wrong
    with pytest.raises(standards.RequirementError):
        standards.create_requirement(
            standard_document_id=doc, chunk_id="c9", requirement_text=SHALL,
            source_text=SHALL, clause="5.1", page=4)
    # 3. a page the cited chunk does not span
    with pytest.raises(standards.RequirementError):
        standards.create_requirement(
            standard_document_id=doc, chunk_id="c1", requirement_text=SHALL,
            source_text=SHALL, clause="5.1", page=99)
    # Nothing was written by any of them.
    assert db.connect().execute(
        "SELECT COUNT(*) FROM standard_requirements").fetchone()[0] == 0


def test_a_requirement_with_no_text_is_refused():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    with pytest.raises(standards.RequirementError):
        standards.create_requirement(
            standard_document_id=doc, chunk_id="c1", requirement_text="   ",
            source_text=SHALL, clause="5.1", page=4)


def test_extraction_records_obligations_with_their_clause_and_page():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, f"{PROSE} {SHALL}", section="5.3.3 Coating", page=9)
    result = standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    assert result["requirements"] == 1        # the prose sentence is not one
    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))
    assert len(rows) == 1
    row = rows[0]
    assert row["clause"] == "5.3.3"
    assert row["page"] == 9
    assert row["chunk_id"] == "c1"
    assert row["source_text"] == SHALL
    # A guess stays labelled a guess.
    assert row["extraction_method"] == "extracted"
    assert row["confirmed_by"] is None
    assert row["citation_resolves"] is True


def test_a_clause_the_parser_could_not_identify_is_marked_for_verification():
    """THE MUTATION TARGET (M28). Low confidence, NULL clause - never guessed."""
    doc = _standard(_doc("doc_std"))
    # A chunk with no section: the clause is unknown.
    _chunk("c1", doc, SHALL, section=None, page=7)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert row["clause"] is None, "a clause was invented for an unnumbered section"
    assert row["confidence"] < standards.VERIFICATION_THRESHOLD
    assert row["needs_verification"] is True
    # The page still resolves, so the reader can go and look.
    assert row["page"] == 7
    assert row["chunk_id"] == "c1"


def test_a_clause_is_never_inherited_from_the_preceding_chunk():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4, ordinal=0)
    _chunk("c2", doc, SHALL, section=None, page=5, ordinal=1)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))
    by_chunk = {r["chunk_id"]: r for r in rows}
    assert by_chunk["c1"]["clause"] == "5.1"
    assert by_chunk["c2"]["clause"] is None


def test_recommendations_are_not_recorded_as_requirements():
    """`should` is advice. Recording it manufactures non-compliance."""
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, "The coating should be inspected before despatch.",
           section="5.1 Coating", page=4)
    result = standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    assert result["requirements"] == 0


def test_a_prohibition_is_recorded_because_violating_it_is_a_finding():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, "Zinc primer shall not be applied below five degrees.",
           section="5.2 Primer", page=5)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert row["category"] == "prohibition"


def test_re_extracting_does_not_double_the_requirements():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    assert len(standards.list_requirements(doc, allowed_document_ids=_scope(doc))) == 1


def test_re_extracting_never_discards_a_confirmed_requirement():
    """3B lets a human confirm a row; re-extraction must not undo that."""
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users"
                     " (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES ('u1','u1@example.test','u1','x',1,'2026-09-18T00:00:00Z')")
        conn.execute("UPDATE standard_requirements SET confirmed_by='u1',"
                     " confirmed_at='2026-09-18T00:00:00Z'")
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))
    confirmed = [r for r in rows if r["confirmed_by"] == "u1"]
    assert len(confirmed) == 1, "the confirmed row was deleted by re-extraction"
    # Confirmation wins over confidence.
    assert confirmed[0]["needs_verification"] is False


def test_a_standard_with_no_requirements_reports_zero():
    doc = _standard(_doc("doc_std"), document_number="SAES-A-105")
    rows = standards.list_standards(allowed_document_ids=_scope(doc))
    assert rows[0]["requirement_count"] == 0
    assert rows[0]["awaiting_verification"] == 0
    # Zero is a real answer. It must not read as readiness - the document's own
    # status is the only thing that says where processing got to.
    assert rows[0]["status"] == "ready"


def test_an_unretrievable_chunk_is_not_extracted_from():
    """Excluded chunks are not part of the corpus retrieval can see, so a
    requirement read from one would cite a passage no answer can reach."""
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4, retrievable=0)
    assert standards.extract_requirements(
        doc, allowed_document_ids=_scope(doc))["requirements"] == 0


# ------------------------------------------------- revisions and supersession

def test_a_superseded_standard_is_excluded_from_selection_but_still_readable():
    """THE MUTATION TARGET (M29). Two different questions, and both asserted."""
    old = _standard(_doc("doc_old", "SAES-A-105-2019.pdf"),
                    document_number="SAES-A-105", revision="2019")
    new = _standard(_doc("doc_new", "SAES-A-105-2021.pdf"),
                    document_number="SAES-A-105", revision="2021")
    scope = _scope(old, new)
    standards.supersede(old, new, allowed_document_ids=scope)

    selectable = standards.selectable_standard_ids(allowed_document_ids=scope)
    assert new in selectable
    assert old not in selectable, "a superseded standard was still selectable"

    # STILL READABLE. An engineer must be able to open the revision a submittal
    # was reviewed against last year.
    listed = {r["id"]: r for r in standards.list_standards(allowed_document_ids=scope)}
    assert old in listed
    assert listed[old]["superseded"] is True
    assert listed[old]["superseded_by"] == new

    # STILL CITABLE: its requirements still resolve.
    _chunk("c1", old, SHALL, section="5.1 Coating", page=4)
    standards.extract_requirements(old, allowed_document_ids=scope)
    rows = standards.list_requirements(old, allowed_document_ids=scope)
    assert len(rows) == 1
    assert rows[0]["citation_resolves"] is True


def test_include_superseded_false_hides_it_from_the_list():
    old = _standard(_doc("doc_old"), document_number="S-1", revision="2019")
    new = _standard(_doc("doc_new"), document_number="S-1", revision="2021")
    scope = _scope(old, new)
    standards.supersede(old, new, allowed_document_ids=scope)
    ids = [r["id"] for r in standards.list_standards(
        allowed_document_ids=scope, include_superseded=False)]
    assert ids == [new]


def test_supersession_is_audited():
    old = _standard(_doc("doc_old"), document_number="S-1")
    new = _standard(_doc("doc_new"), document_number="S-1")
    scope = _scope(old, new)
    standards.supersede(old, new, allowed_document_ids=scope,
                        actor={"id": None, "email": "admin@example.test"})
    row = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'standard.superseded'").fetchone()
    assert row is not None, "superseding wrote no audit row"
    assert row["resource_id"] == old
    assert row["resource_type"] == "standard"
    assert new in (row["detail"] or "")


def test_a_standard_cannot_supersede_itself():
    doc = _standard(_doc("doc_std"))
    with pytest.raises(standards.RequirementError):
        standards.supersede(doc, doc, allowed_document_ids=_scope(doc))


def test_a_supersession_cannot_name_a_document_the_caller_cannot_read():
    """Otherwise a caller learns a document exists by pointing at it."""
    mine = _standard(_doc("doc_mine"))
    secret = _standard(_doc("doc_secret"))
    with pytest.raises(standards.RequirementError):
        standards.supersede(mine, secret, allowed_document_ids=_scope(mine))
    row = db.connect().execute(
        "SELECT superseded_by FROM document_classification WHERE document_id = ?",
        (mine,)).fetchone()
    assert row["superseded_by"] is None


def test_clearing_a_supersession_makes_it_selectable_again():
    old = _standard(_doc("doc_old"), document_number="S-1")
    new = _standard(_doc("doc_new"), document_number="S-1")
    scope = _scope(old, new)
    standards.supersede(old, new, allowed_document_ids=scope)
    standards.supersede(old, None, allowed_document_ids=scope)
    assert old in standards.selectable_standard_ids(allowed_document_ids=scope)


def test_revision_history_groups_by_document_number():
    a = _standard(_doc("doc_a"), document_number="SAES-A-105", revision="2019")
    b = _standard(_doc("doc_b"), document_number="SAES-A-105", revision="2021")
    c = _standard(_doc("doc_c"), document_number="SAES-B-999", revision="2020")
    scope = _scope(a, b, c)
    history = {r["id"] for r in standards.revision_history(a, allowed_document_ids=scope)}
    assert history == {a, b}
    assert c not in history


# --------------------------------------------------------------- permissions

def test_an_unauthorised_user_sees_no_standard_no_requirement_no_history():
    """THE MUTATION TARGET (M30/M31). Every read path, one test."""
    mine = _standard(_doc("doc_mine"), document_number="MINE-1")
    theirs = _standard(_doc("doc_theirs"), document_number="THEIRS-1")
    _chunk("c1", theirs, SHALL, section="5.1 Coating", page=4)
    standards.extract_requirements(theirs, allowed_document_ids=_scope(theirs))

    only_mine = _scope(mine)
    listed = [r["id"] for r in standards.list_standards(allowed_document_ids=only_mine)]
    assert listed == [mine]
    assert standards.list_requirements(theirs, allowed_document_ids=only_mine) == []
    assert standards.clause_hierarchy(theirs, allowed_document_ids=only_mine) == []
    assert standards.revision_history(theirs, allowed_document_ids=only_mine) == []
    assert theirs not in standards.selectable_standard_ids(
        allowed_document_ids=only_mine)


def test_an_empty_grant_set_sees_nothing_rather_than_everything():
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    empty = frozenset()
    assert standards.list_standards(allowed_document_ids=empty) == []
    assert standards.list_requirements(doc, allowed_document_ids=empty) == []
    assert standards.clause_hierarchy(doc, allowed_document_ids=empty) == []
    assert standards.revision_history(doc, allowed_document_ids=empty) == []
    assert standards.selectable_standard_ids(allowed_document_ids=empty) == frozenset()


def test_extraction_reads_no_chunk_outside_the_callers_grants():
    theirs = _standard(_doc("doc_theirs"))
    _chunk("c1", theirs, SHALL, section="5.1 Coating", page=4)
    result = standards.extract_requirements(theirs, allowed_document_ids=frozenset())
    assert result["chunks_read"] == 0
    assert result["requirements"] == 0


@pytest.mark.parametrize("call", [
    lambda: standards.list_standards(),
    lambda: standards.selectable_standard_ids(),
    lambda: standards.clause_hierarchy("d"),
    lambda: standards.list_requirements("d"),
    lambda: standards.revision_history("d"),
    lambda: standards.extract_requirements("d"),
    lambda: standards.supersede("d", None),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    """No default, so forgetting the scope is a crash and not a silent
    corpus-wide read. search.py's contract, not deliverables.py's."""
    with pytest.raises(TypeError):
        call()


def test_only_company_standards_appear_in_the_library():
    """The role decides what is IN the library; the grants decide what is
    VISIBLE. This asserts the first."""
    std = _standard(_doc("doc_std"))
    sub = _doc("doc_sub", "datasheet.pdf")
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,document_role)
            VALUES (?,?,'CONTRACTOR_SUBMITTAL')""", (sub, "test"))
    ids = [r["id"] for r in standards.list_standards(
        allowed_document_ids=_scope(std, sub))]
    assert ids == [std]


# ------------------------------------------------------ no second index

def test_no_second_index_was_created():
    """The requirements layer POINTS INTO the existing chunks.

    A parallel exact-text or vector store would duplicate retrieval and bypass
    the allowed_document_ids masking that only the existing path enforces. This
    asserts no such table appeared.
    """
    tables = {r[0] for r in db.connect().execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for forbidden in ("standard_chunks", "standard_vectors", "requirement_vectors",
                      "standard_fts", "requirements_fts", "clause_vectors"):
        assert forbidden not in tables, f"a second index appeared: {forbidden}"
    # And the requirement rows reference the real chunks table.
    columns = {r[1] for r in db.connect().execute(
        "PRAGMA table_info(standard_requirements)")}
    assert "chunk_id" in columns


def test_a_requirement_points_at_a_chunk_retrieval_can_also_see():
    """The same chunk id the keyword index carries - one corpus, one path."""
    from app import keyword
    doc = _standard(_doc("doc_std"))
    _chunk("c1", doc, SHALL, section="5.1 Coating", page=4)
    keyword.ensure_schema()
    keyword.index_document(doc)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    indexed = db.connect().execute(
        "SELECT chunk_id FROM chunks_fts WHERE document_id = ?", (doc,)).fetchall()
    assert row["chunk_id"] in {r["chunk_id"] for r in indexed}
