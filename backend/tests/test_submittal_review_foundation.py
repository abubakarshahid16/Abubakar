"""Phase 1 foundation: schema, vocabularies and the scope filter.

EVERY TEST HERE MUST FAIL WHEN ITS FEATURE IS DELETED (CLAUDE.md rule 6). The
mutations that were actually performed to prove that are recorded in
`docs/AI_SUBMITTAL_REVIEW_PROGRESS.md` under "Mutation proof", with the
resulting failure counts. A test that passes against a deleted feature is the
recurring defect this project has already recorded 24 times.

The permission tests are the ones that matter most: they are written so that
deleting the `_scope_clause` call from a read path makes them fail, rather than
merely asserting that an authorised caller gets rows back - which would pass
just as happily with no filter at all.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from pydantic import ValidationError

from app import db, review, submittal_review
from app.config import settings
from app.schemas import ComplianceStatus, DocumentRole


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "submittal.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, name: str, digest: str) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)
            VALUES (?,?,?,?,?,'ready',?)""",
            (doc_id, name, digest, 1, name, "2026-09-18T00:00:00Z"))
    return doc_id


def _run(submittal_id: str, run_id: str | None = None) -> str:
    run_id = run_id or str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending',?,?)""",
            (run_id, submittal_id, "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))
    return run_id


def _fact(run_id: str, submittal_id: str, field_name: str = "design_pressure") -> str:
    fact_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO submittal_facts
            (id,review_run_id,submittal_document_id,field_name,field_value,
             created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (fact_id, run_id, submittal_id, field_name, "10 bar",
             "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))
    return fact_id


def _finding(submittal_id: str, run_id: str, standard_id: str | None = None) -> str:
    finding_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_findings
            (id,document_id,category,severity,requirement,finding,required_action,
             review_run_id,compliance_status,standard_document_id,standard_clause,
             created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (finding_id, submittal_id, "materials", "major", "req", "found",
             "act", run_id, "NON_COMPLIANT", standard_id, "5.2.1",
             "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))
    return finding_id


# --------------------------------------------------------------- migration

#: The document_classification table EXACTLY as an earlier build wrote it -
#: before any submittal-review column existed.
#:
#: This literal is the whole point of the migration tests. A test that lets the
#: fixture build the table gets today's SCHEMA, which already contains the new
#: columns, so the ALTER path never runs and the test passes even with the
#: migration deleted. That is not a hypothetical: it was the first version of
#: these two tests, and mutations M6 and M7 passed against it. The legacy DDL
#: has to be written out for the migration to have anything to migrate.
_LEGACY_CLASSIFICATION_DDL = """
CREATE TABLE document_classification (
    document_id   TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    doc_type      TEXT,
    discipline    TEXT,
    doc_class     TEXT,
    register_id   TEXT REFERENCES deliverables_register(id) ON DELETE SET NULL,
    suggested_by  TEXT NOT NULL,
    confirmed_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at  TEXT
)"""

#: review_findings as it stood before the compliance columns, likewise.
_LEGACY_FINDINGS_DDL = """
CREATE TABLE review_findings (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    baseline_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    requirement TEXT NOT NULL,
    finding TEXT NOT NULL,
    required_action TEXT NOT NULL,
    citation_ids TEXT NOT NULL DEFAULT '[]',
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    approval_status TEXT NOT NULL DEFAULT 'pending',
    escalation_level INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""


def _make_legacy_table(ddl: str, table: str) -> None:
    """Replace `table` with its pre-migration shape, so the ALTER path runs."""
    conn = db.connect()
    with conn:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(ddl)


def test_existing_documents_remain_readable_after_migration():
    """A classification row written by an EARLIER BUILD survives the migration.

    Built against the legacy DDL on purpose - see `_LEGACY_CLASSIFICATION_DDL`.
    Deleting the migration block in db._migrate makes this fail with
    "no such column: document_role".
    """
    _make_legacy_table(_LEGACY_CLASSIFICATION_DDL, "document_classification")
    _doc("doc_old", "old-submittal.pdf", "sha-old")
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,doc_type,discipline,doc_class,suggested_by)
            VALUES (?,?,?,?,?)""",
            ("doc_old", "Drawing", "Civil", "DATASHEET", "pattern"))
    # Prove the starting point really is the old shape, or the test is vacuous.
    before = [r[1] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")]
    assert "document_role" not in before

    db.init_db()                       # THE MIGRATION UNDER TEST

    row = db.connect().execute(
        "SELECT * FROM document_classification WHERE document_id = 'doc_old'"
    ).fetchone()
    assert row is not None, "the pre-existing row was lost by the migration"
    assert row["doc_type"] == "Drawing"
    assert row["discipline"] == "Civil"
    assert row["suggested_by"] == "pattern"
    assert row["doc_class"] == "DATASHEET"
    # Every new column arrived...
    after = [r[1] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")]
    for column in ("document_role", "document_number", "revision",
                   "effective_date", "project", "contractor_vendor",
                   "equipment_type", "equipment_tags", "service",
                   "transmittal_number", "superseded_by"):
        assert column in after, f"{column} was not added by the migration"
    # ...and every one of them is NULL. NULL is an answer: not recorded. A
    # default role here would route a review confidently to the wrong baseline.
    assert row["document_role"] is None
    assert row["equipment_tags"] is None
    assert row["superseded_by"] is None


def test_existing_review_findings_still_work_unchanged():
    """A guided-review finding keeps its status and disposition.

    This is the test that catches `compliance_status` being bolted onto the
    existing `status` column instead of added beside it.
    """
    _make_legacy_table(_LEGACY_FINDINGS_DDL, "review_findings")
    _doc("doc_s", "submittal.pdf", "sha-s")
    finding_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_findings
            (id,document_id,category,severity,requirement,finding,required_action,
             status,approval_status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (finding_id, "doc_s", "welding", "minor", "req", "found", "act",
             "open", "pending",
             "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))
    before = [r[1] for r in db.connect().execute("PRAGMA table_info(review_findings)")]
    assert "compliance_status" not in before   # or this test proves nothing

    review.ensure_schema()        # THE MIGRATION UNDER TEST

    row = db.connect().execute(
        "SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    assert row is not None, "the pre-existing finding was lost by the migration"
    # The guided-review meaning is carried through the migration untouched.
    assert row["status"] == "open"
    assert row["approval_status"] == "pending"
    assert row["category"] == "welding"
    assert row["severity"] == "minor"
    # `disposition` predates this phase but postdates this row: the existing
    # ALTER block adds it as nullable, so it reads "no decision recorded".
    assert row["disposition"] is None
    after = [r[1] for r in db.connect().execute("PRAGMA table_info(review_findings)")]
    for column in ("review_run_id", "compliance_status", "contractor_page",
                   "contractor_section", "contractor_evidence_text",
                   "standard_document_id", "standard_clause", "standard_page",
                   "requirement_source_text", "ai_rationale"):
        assert column in after, f"{column} was not added by the migration"
    # The new vocabulary did not invent a verdict for a row that has none.
    # A default of COMPLIANT here would be the "not mentioned is never
    # compliant" invariant broken silently, in a migration, on every old row.
    assert row["compliance_status"] is None
    assert row["review_run_id"] is None


def test_guided_review_status_and_disposition_are_not_repurposed():
    """The two vocabularies coexist on ONE row and stay independent."""
    submittal = _doc("doc_both", "both.pdf", "sha-both")
    run_id = _run(submittal)
    finding_id = _finding(submittal, run_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET status='closed', disposition='rejected'"
            " WHERE id = ?", (finding_id,))
    row = db.connect().execute(
        "SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    assert row["status"] == "closed"
    assert row["disposition"] == "rejected"
    # Changing the guided-review columns did not touch the compliance verdict.
    assert row["compliance_status"] == "NON_COMPLIANT"


def test_migration_is_idempotent_when_run_twice():
    """Running init_db and ensure_schema twice changes nothing and loses nothing."""
    _doc("doc_i", "idem.pdf", "sha-i")
    run_id = _run("doc_i")
    _fact(run_id, "doc_i")
    _finding("doc_i", run_id)

    def shape():
        conn = db.connect()
        tables = sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"))
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                  for t in tables}
        cols = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                for t in tables}
        return tables, counts, cols

    first = shape()
    db.init_db(); review.ensure_schema(); submittal_review.ensure_schema()
    second = shape()
    db.init_db(); review.ensure_schema(); submittal_review.ensure_schema()
    third = shape()
    assert first == second == third
    assert first[1]["review_runs"] == 1
    assert first[1]["submittal_facts"] == 1
    assert first[1]["review_findings"] == 1


def test_the_four_new_tables_exist():
    tables = {r[0] for r in db.connect().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"standard_requirements", "review_runs", "submittal_facts",
            "review_applicable_standards"} <= tables


def test_new_workflow_ids_are_uuids_not_content_hashes():
    """Only documents.id is a content hash. A run is an event."""
    submittal = _doc("doc_uuid", "u.pdf", "sha-u")
    run_id = _run(submittal)
    assert uuid.UUID(run_id)              # raises if it is not a uuid
    assert not run_id.startswith("doc_")


# ------------------------------------------------------------ vocabularies

@pytest.mark.parametrize("role", [
    "CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT",
    "SUPPORTING_DOCUMENT", "CRS_TEMPLATE",
])
def test_every_document_role_validates(role):
    from pydantic import TypeAdapter
    assert TypeAdapter(DocumentRole).validate_python(role) == role


@pytest.mark.parametrize("bad", [
    "SUBMITTAL", "contractor_submittal", "", "STANDARD", "ADMIN", "None",
])
def test_an_invalid_document_role_is_rejected(bad):
    from pydantic import TypeAdapter
    with pytest.raises(ValidationError):
        TypeAdapter(DocumentRole).validate_python(bad)


@pytest.mark.parametrize("status", [
    "COMPLIANT", "NON_COMPLIANT", "MISSING_INFORMATION", "CONDITIONAL",
    "NOT_APPLICABLE", "NEEDS_ENGINEER_REVIEW",
])
def test_every_compliance_status_validates(status):
    from pydantic import TypeAdapter
    assert TypeAdapter(ComplianceStatus).validate_python(status) == status


@pytest.mark.parametrize("bad", [
    "compliant", "PASS", "FAIL", "", "OK", "PARTIAL", "UNKNOWN",
])
def test_an_invalid_compliance_status_is_rejected(bad):
    from pydantic import TypeAdapter
    with pytest.raises(ValidationError):
        TypeAdapter(ComplianceStatus).validate_python(bad)


def test_missing_information_is_a_distinct_status_from_non_compliant():
    """The honesty invariant: 'not mentioned' is never 'compliant', and it is
    not 'non-compliant' either."""
    assert "MISSING_INFORMATION" != "NON_COMPLIANT"
    from pydantic import TypeAdapter
    adapter = TypeAdapter(ComplianceStatus)
    assert adapter.validate_python("MISSING_INFORMATION") == "MISSING_INFORMATION"


# ------------------------------------------------------------- permissions

def test_an_authorised_user_can_read_their_review_run():
    submittal = _doc("doc_mine", "mine.pdf", "sha-mine")
    run_id = _run(submittal)
    runs = submittal_review.list_review_runs(
        allowed_document_ids=frozenset({submittal}))
    assert [r["id"] for r in runs] == [run_id]
    assert submittal_review.get_review_run(
        run_id, allowed_document_ids=frozenset({submittal}))["id"] == run_id


def test_an_unauthorised_user_cannot_read_another_users_review_run():
    """THE MUTATION TARGET. Deleting the _scope_clause call in
    list_review_runs/get_review_run makes this fail."""
    mine = _doc("doc_mine", "mine.pdf", "sha-mine")
    theirs = _doc("doc_theirs", "theirs.pdf", "sha-theirs")
    my_run = _run(mine)
    their_run = _run(theirs)
    # A caller granted ONLY their own document.
    scope = frozenset({mine})
    visible = [r["id"] for r in submittal_review.list_review_runs(
        allowed_document_ids=scope)]
    assert their_run not in visible
    assert visible == [my_run]
    # And by id: not found, never forbidden.
    assert submittal_review.get_review_run(their_run, allowed_document_ids=scope) is None


def test_an_unauthorised_user_cannot_read_another_users_submittal_facts():
    mine = _doc("doc_mine", "mine.pdf", "sha-mine")
    theirs = _doc("doc_theirs", "theirs.pdf", "sha-theirs")
    my_run, their_run = _run(mine), _run(theirs)
    _fact(my_run, mine, "mine_field")
    _fact(their_run, theirs, "their_field")
    facts = submittal_review.list_submittal_facts(
        allowed_document_ids=frozenset({mine}))
    names = {f["field_name"] for f in facts}
    assert names == {"mine_field"}
    assert "their_field" not in names


def test_an_unauthorised_user_cannot_read_another_users_findings():
    mine = _doc("doc_mine", "mine.pdf", "sha-mine")
    theirs = _doc("doc_theirs", "theirs.pdf", "sha-theirs")
    my_run, their_run = _run(mine), _run(theirs)
    _finding(mine, my_run)
    _finding(theirs, their_run)
    assert submittal_review.list_run_findings(
        their_run, allowed_document_ids=frozenset({mine})) == []
    assert len(submittal_review.list_run_findings(
        my_run, allowed_document_ids=frozenset({mine}))) == 1


def test_an_empty_grant_set_sees_nothing_rather_than_everything():
    """The deliverables.py defect, asserted absent: an empty scope is not
    'unrestricted', and a NULL-free schema means no row is world-readable."""
    submittal = _doc("doc_any", "any.pdf", "sha-any")
    run_id = _run(submittal)
    _fact(run_id, submittal)
    _finding(submittal, run_id)
    empty = frozenset()
    assert submittal_review.list_review_runs(allowed_document_ids=empty) == []
    assert submittal_review.list_submittal_facts(allowed_document_ids=empty) == []
    assert submittal_review.get_review_run(run_id, allowed_document_ids=empty) is None
    assert submittal_review.list_run_findings(run_id, allowed_document_ids=empty) == []
    assert submittal_review.list_standard_requirements(allowed_document_ids=empty) == []
    assert submittal_review.list_applicable_standards(
        run_id, allowed_document_ids=empty) == []


def test_a_standard_the_caller_cannot_read_is_not_listed_for_a_run_they_can():
    """The intersection rule in both directions: reading the submittal does not
    grant every standard it was compared against."""
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    open_std = _doc("doc_open", "open-standard.pdf", "sha-open")
    secret_std = _doc("doc_secret", "secret-standard.pdf", "sha-secret")
    run_id = _run(submittal)
    with db.connect() as conn:
        for std in (open_std, secret_std):
            conn.execute("""INSERT INTO review_applicable_standards
                (id,review_run_id,standard_document_id,selection_method,
                 included,created_at)
                VALUES (?,?,?,'rule',1,?)""",
                (str(uuid.uuid4()), run_id, std, "2026-09-18T00:00:00Z"))
    rows = submittal_review.list_applicable_standards(
        run_id, allowed_document_ids=frozenset({submittal, open_std}))
    ids = {r["standard_document_id"] for r in rows}
    assert ids == {open_std}
    assert secret_std not in ids


@pytest.mark.parametrize("call", [
    lambda: submittal_review.list_review_runs(),
    lambda: submittal_review.list_submittal_facts(),
    lambda: submittal_review.list_standard_requirements(),
    lambda: submittal_review.get_review_run("r"),
    lambda: submittal_review.list_applicable_standards("r"),
    lambda: submittal_review.list_run_findings("r"),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    """No default, so forgetting the filter is a crash and not a silent
    corpus-wide read. This is search.py's contract, not deliverables.py's."""
    with pytest.raises(TypeError):
        call()


@pytest.mark.parametrize("call", [
    lambda ids: submittal_review.list_review_runs(ids),
    lambda ids: submittal_review.list_submittal_facts(ids),
])
def test_the_filter_cannot_be_passed_positionally(call):
    """Keyword-only, so it cannot be supplied by accident in the wrong slot."""
    with pytest.raises(TypeError):
        call(frozenset({"doc_x"}))


# ------------------------------------------------------- foreign-key behaviour

def test_deleting_a_standard_does_not_erase_findings_that_cited_it():
    """`standard_document_id` on a finding has NO foreign key, deliberately.
    The finding is the record that the citation was made."""
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    standard = _doc("doc_std", "std.pdf", "sha-std")
    run_id = _run(submittal)
    finding_id = _finding(submittal, run_id, standard_id=standard)
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM documents WHERE id = ?", (standard,))
    row = db.connect().execute(
        "SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    assert row is not None, "the finding was erased with the standard"
    # The citation survives the document, verbatim.
    assert row["standard_document_id"] == standard
    assert row["standard_clause"] == "5.2.1"


def test_deleting_a_submittal_cascades_its_runs_and_facts():
    """Owned rows go with their owner."""
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    run_id = _run(submittal)
    _fact(run_id, submittal)
    conn = db.connect()
    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (submittal,))
    assert conn.execute("SELECT COUNT(*) FROM review_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM submittal_facts").fetchone()[0] == 0


def test_deleting_a_run_cascades_its_applicable_standards():
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    standard = _doc("doc_std", "std.pdf", "sha-std")
    run_id = _run(submittal)
    conn = db.connect()
    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,created_at)
            VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run_id, standard, "2026-09-18T00:00:00Z"))
    assert conn.execute(
        "SELECT COUNT(*) FROM review_applicable_standards").fetchone()[0] == 1
    with conn:
        conn.execute("DELETE FROM review_runs WHERE id = ?", (run_id,))
    assert conn.execute(
        "SELECT COUNT(*) FROM review_applicable_standards").fetchone()[0] == 0


def test_deleting_a_standard_removes_its_requirements():
    """A requirement is OWNED by the standard it was extracted from - unlike a
    finding, which merely cited it."""
    standard = _doc("doc_std", "std.pdf", "sha-std")
    conn = db.connect()
    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        conn.execute("""INSERT INTO standard_requirements
            (id,standard_document_id,requirement_text,created_at,updated_at)
            VALUES (?,?,?,?,?)""",
            (str(uuid.uuid4()), standard, "shall be stainless",
             "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))
    assert conn.execute(
        "SELECT COUNT(*) FROM standard_requirements").fetchone()[0] == 1
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (standard,))
    assert conn.execute(
        "SELECT COUNT(*) FROM standard_requirements").fetchone()[0] == 0


def test_a_run_cannot_reference_a_document_that_does_not_exist():
    conn = db.connect()
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("""INSERT INTO review_runs
                (id,submittal_document_id,status,created_at,updated_at)
                VALUES (?,?,'pending',?,?)""",
                (str(uuid.uuid4()), "doc_nonexistent",
                 "2026-09-18T00:00:00Z", "2026-09-18T00:00:00Z"))


def test_one_standard_appears_once_per_run():
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    standard = _doc("doc_std", "std.pdf", "sha-std")
    run_id = _run(submittal)
    conn = db.connect()
    with conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,created_at)
            VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run_id, standard, "2026-09-18T00:00:00Z"))
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("""INSERT INTO review_applicable_standards
                (id,review_run_id,standard_document_id,selection_method,included,created_at)
                VALUES (?,?,?,'model',1,?)""",
                (str(uuid.uuid4()), run_id, standard, "2026-09-18T00:00:01Z"))


def test_a_ruled_out_standard_is_kept_as_a_row_with_its_reason():
    """'We looked at this and decided it did not apply' is the answer an
    engineer asks for, so it is a row rather than an absence."""
    submittal = _doc("doc_sub", "sub.pdf", "sha-sub")
    standard = _doc("doc_std", "std.pdf", "sha-std")
    run_id = _run(submittal)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,confidence,included,exclusion_reason,created_at)
            VALUES (?,?,?,?,'rule',0.4,0,?,?)""",
            (str(uuid.uuid4()), run_id, standard, "matched equipment type",
             "different service class", "2026-09-18T00:00:00Z"))
    scope = frozenset({submittal, standard})
    everything = submittal_review.list_applicable_standards(
        run_id, allowed_document_ids=scope)
    assert len(everything) == 1
    assert everything[0]["included"] == 0
    assert everything[0]["exclusion_reason"] == "different service class"
    applied_only = submittal_review.list_applicable_standards(
        run_id, allowed_document_ids=scope, include_excluded=False)
    assert applied_only == []


# --------------------------------------------------------- the JSON boundary

def test_equipment_tags_round_trip_as_a_list():
    from app import classification
    _doc("doc_tags", "tags.pdf", "sha-tags")
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,equipment_tags) VALUES (?,?,?)""",
            ("doc_tags", "test", json.dumps(["pump", "centrifugal"])))
    out = classification.of_document("doc_tags")
    assert out["equipment_tags"] == ["pump", "centrifugal"]


def test_malformed_equipment_tags_read_as_none_recorded():
    from app import classification
    _doc("doc_bad", "bad.pdf", "sha-bad")
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,equipment_tags) VALUES (?,?,?)""",
            ("doc_bad", "test", "{not json"))
    assert classification.of_document("doc_bad")["equipment_tags"] == []


def test_a_classification_with_no_tags_reads_as_an_empty_list():
    from app import classification
    _doc("doc_notags", "notags.pdf", "sha-notags")
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by) VALUES (?,?)""", ("doc_notags", "test"))
    assert classification.of_document("doc_notags")["equipment_tags"] == []


# ----------------------------------------------- the read path holds no DDL

def _ensure_schema_body() -> str:
    """The source text of `submittal_review.ensure_schema`, and only that.

    Scoped to the FUNCTION rather than the file on purpose:
    `migrate_facts_to_per_document` legitimately contains a DROP and must keep
    it. The rule is about where the DDL lives, not whether it exists.
    """
    import inspect

    return inspect.getsource(submittal_review.ensure_schema)


def test_ensure_schema_contains_no_ddl():
    """DDL in a read path blocks concurrent readers on other connections.

    `ensure_schema()` is called by every read in this module. While it held a
    conditional DROP/CREATE of `submittal_facts`, three full-suite runs of one
    unchanged tree gave three different results: two permission tests failed,
    then nothing failed, then
    `test_access_routes::test_two_concurrent_requests_never_share_scope`
    failed. Different victims each run, with no random-order plugin installed
    and no hash-seed sensitivity, is the signature of lock contention rather
    than of ordering or pollution - and the concurrency test failing is what
    identified it.

    THIS WAS A PRODUCTION DEFECT, not a test defect. The same DDL would block
    concurrent readers in the running application; the first request after
    startup that triggered the rebuild could stall whatever else was in
    flight. The suite is simply what noticed.

    A BEHAVIOURAL TEST CANNOT HOLD THIS LINE, because the failure is a timing
    race that appears in maybe two runs of three - which is exactly how it
    survived a full green suite before. So this asserts the SHAPE that made the
    race possible is gone. The same idiom as
    `test_the_upload_module_guards_the_stored_path`.

    A structural migration belongs at startup, in `main.lifespan`, where it
    happens once at a moment somebody chose. Read paths assume the schema; they
    do not repair it.
    """
    body = _ensure_schema_body()
    assert "DROP TABLE" not in body, \
        "a DROP in ensure_schema blocks concurrent readers; move it to a " \
        "startup migration"
    assert "DROP INDEX" not in body
    # The migration still owns its rebuild - the rule is about WHERE the DDL
    # lives, and asserting the positive keeps this test from passing simply
    # because the migration was deleted too.
    import inspect
    migration = inspect.getsource(submittal_review.migrate_facts_to_per_document)
    assert "DROP TABLE submittal_facts" in migration


def test_the_facts_migration_is_called_at_startup():
    """The migration is only useful if something runs it.

    Asserted against `main.lifespan`'s source rather than by booting the app:
    the point is that the call sits beside the other schema calls at startup,
    which is a structural claim about where it lives.
    """
    import inspect

    from app import main
    assert "migrate_facts_to_per_document" in inspect.getsource(main.lifespan)
