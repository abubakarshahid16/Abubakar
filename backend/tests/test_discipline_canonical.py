"""The discipline overlay: one canonical value, and the raw one kept intact.

WHY BOTH COLUMNS EXIST. `discipline` is what the standard's own cover page
says - it is EVIDENCE, and this system does not rewrite evidence, the same
rule that keeps an AI recommendation beside an engineer's final code rather
than replacing it. `discipline_canonical` is the editorial answer to "are
these two the same discipline", derived from the raw value and stored beside
it.

THE RAW COLUMN IS NEVER WRITTEN. A migration that normalised in place would
destroy the only record of what the document said, with no way back:
"Non-metallic" and "Nonmetallic" are indistinguishable once merged. The test
that matters most here reads the raw column byte-for-byte after a backfill.

AND AN UNMAPPED VALUE COPIES THROUGH, NEVER NULL. The mapping is an editorial
overlay, not a whitelist. Blanking an unreviewed value would turn "nobody has
looked at this spelling yet" into "this document has no discipline".

`backend/app/reference/discipline_aliases.json` sat generated-but-unapplied
because collapsing spellings is a person's decision. Measured on the real
corpus when that decision was made: 52 raw spellings, 46 canonical, 179 of
274 rows carry a discipline at all, and 14 documents changed display.

Mutations: M232-M236, `python scripts/mutation_check.py --phase 21`.
"""

from __future__ import annotations

import pytest

from app import access, classification, db, disciplines
from app.config import settings

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "disc.sqlite")
    db.reset_connection()
    # `init_db` ALONE, deliberately. This fixture used to call
    # `disciplines.ensure_schema()` too, which added the column whatever
    # `init_db` did - so the test asserting that `init_db` creates it could
    # not have failed. Every test here now runs on the schema production
    # callers actually get.
    db.init_db()
    yield
    db.reset_connection()


def _classified(doc_id: str, discipline: str | None,
                role: str = "COMPANY_STANDARD") -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))
        conn.execute(
            "INSERT INTO document_classification (document_id,discipline,"
            "document_role,suggested_by) VALUES (?,?,?,'test')",
            (doc_id, discipline, role))
    return doc_id


def _row(doc_id: str) -> dict:
    return dict(db.connect().execute(
        "SELECT discipline, discipline_canonical FROM"
        " document_classification WHERE document_id = ?", (doc_id,)).fetchone())


# ============================================================ the mapping

def test_a_known_alias_collapses_to_its_canonical_spelling():
    assert disciplines.canonical("Non-metallic Standards Committee") \
        == "Nonmetallic Standards Committee"
    assert disciplines.canonical("Onshore Structure Standards Committee") \
        == "Onshore Structures Standards Committee"


def test_a_value_absent_from_the_mapping_copies_through_unchanged():
    """NEVER NULL A VALUE THAT EXISTS. An overlay, not a whitelist: a spelling
    nobody has reviewed is still the document's own answer."""
    assert disciplines.canonical("Submarine Basket Weaving Committee") \
        == "Submarine Basket Weaving Committee"


def test_absent_stays_absent():
    """Null renders as nothing, and inventing a discipline for a document
    whose cover page named none would be a claim it did not make."""
    assert disciplines.canonical(None) is None
    assert disciplines.canonical("   ") is None


def test_surrounding_whitespace_does_not_defeat_the_mapping():
    assert disciplines.canonical("  Non-metallic Standards Committee  ") \
        == "Nonmetallic Standards Committee"


def test_the_mapping_is_exhaustively_idempotent():
    """EVERY canonical value must itself map to itself, or applying the
    overlay twice would keep moving - and `backfill` would not be safe to
    re-run. Asserted over the whole file rather than a sample."""
    for raw, canon in disciplines.aliases().items():
        assert disciplines.canonical(canon) == canon, \
            f"{canon!r} (from {raw!r}) is not a fixed point"


# =========================================================== the backfill

def test_the_backfill_fills_canonical_and_leaves_raw_BYTE_UNTOUCHED():
    """THE ONE THAT MATTERS. Normalising in place would destroy the only
    record of what the cover page said, with no way back."""
    doc = _classified("d1", "Non-metallic Standards Committee")

    disciplines.backfill()

    row = _row(doc)
    assert row["discipline"] == "Non-metallic Standards Committee"
    assert row["discipline_canonical"] == "Nonmetallic Standards Committee"


def test_the_backfill_reports_numbers_a_person_can_check():
    """A migration that reported only "done" would be asking to be trusted."""
    _classified("d1", "Non-metallic Standards Committee")
    _classified("d2", "Nonmetallic Standards Committee")
    _classified("d3", None)

    result = disciplines.backfill()

    assert result["rows"] == 3
    assert result["with_discipline"] == 2
    assert result["rows_changed"] == 1, "only d1 reads differently"
    assert result["spellings_changed"] == [
        ("Non-metallic Standards Committee", "Nonmetallic Standards Committee")]


def test_running_the_backfill_twice_changes_nothing_the_second_time():
    """Idempotent because it derives from `discipline` every time, never from
    the previous canonical - which would compound."""
    _classified("d1", "Non-metallic Standards Committee")

    first = disciplines.backfill()
    second = disciplines.backfill()

    assert first == second
    assert _row("d1")["discipline"] == "Non-metallic Standards Committee"


def test_an_unmapped_spelling_survives_the_backfill_rather_than_going_null():
    doc = _classified("d1", "Submarine Basket Weaving Committee")

    disciplines.backfill()

    row = _row(doc)
    assert row["discipline_canonical"] == "Submarine Basket Weaving Committee"
    assert row["discipline_canonical"] is not None


def test_two_spellings_become_one_value_which_is_the_whole_point():
    _classified("d1", "Non-metallic Standards Committee")
    _classified("d2", "Nonmetallic Standards Committee")

    disciplines.backfill()

    canon = {r["discipline_canonical"] for r in db.connect().execute(
        "SELECT discipline_canonical FROM document_classification")}
    raw = {r["discipline"] for r in db.connect().execute(
        "SELECT discipline FROM document_classification")}
    assert canon == {"Nonmetallic Standards Committee"}
    assert len(raw) == 2, "the raw spellings were merged away"


# ============================================ through the real write paths
#
# THE TESTS ABOVE INSERT ROWS WITH SQL, AND THAT HID A DEFECT. The suggestion
# write in `classification.py` gained a ninth column and kept eight VALUES,
# so every document ingest would have failed to classify with "8 values for 9
# columns". Nothing above could see it, because nothing above went through
# the code that writes. The same shape of miss as standing rule 15, one layer
# down: a test that never calls the write path cannot see a defect in it.


def test_a_suggestion_is_written_with_its_canonical_beside_it():
    """THE PATH EVERY INGEST TAKES."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES ('d1','d1.pdf','s',1,"
            "'d1.pdf','ready',1,?)", (NOW,))

    classification.write_suggestion(
        "d1",
        classification.Suggestion(discipline="Non-metallic Standards Committee"),
        suggested_by="test")

    row = _row("d1")
    assert row["discipline"] == "Non-metallic Standards Committee"
    assert row["discipline_canonical"] == "Nonmetallic Standards Committee"


def test_an_administrators_confirmation_writes_both_as_well():
    """The other write path. Two INSERTs carry the column, so both are
    exercised - a fix to one would otherwise leave the other broken."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES ('d1','d1.pdf','s',1,"
            "'d1.pdf','ready',1,?)", (NOW,))

    classification.confirm(
        "d1", doc_type=None, discipline="Onshore Structure Standards Committee",
        doc_class=None, subject_ids=(), confirmed_by=None)

    row = _row("d1")
    assert row["discipline"] == "Onshore Structure Standards Committee"
    assert row["discipline_canonical"] == "Onshore Structures Standards Committee"


def test_the_column_exists_without_the_startup_backfill_having_run():
    """`init_db` alone must produce it. It used to exist only after
    `disciplines.ensure_schema()`, so a write path depended on a migration it
    never called - and 29 test setups failed on it."""
    columns = {r["name"] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")}

    assert "discipline_canonical" in columns


def test_an_existing_database_gains_the_column_through_the_migration(
        tmp_path, monkeypatch):
    """THE MIGRATION, ON A DATABASE THAT PREDATES IT.

    Honesty audit entry 6: two migration tests once passed with the migration
    DELETED, because their fixture built the table from today's schema - the
    column was already there and the ALTER never ran. So this builds the
    table in its OLD shape first, with no `discipline_canonical`, and only
    then lets `init_db` see it.

    It is also the only way to observe the migration at all. On a fresh
    database the CREATE TABLE and the migration loop BOTH add the column, so
    deleting either one alone changes nothing - M243, which deleted the
    CREATE TABLE line, was withdrawn for exactly that reason.
    """
    # EVERYTHING CURRENT EXCEPT THIS ONE TABLE. A first attempt built a bare
    # `documents(id)` and `init_db` then failed on `documents.status` - a
    # fixture too minimal to be a real old database. So: build today's schema,
    # then put `document_classification` back into its pre-phase-8 shape.
    monkeypatch.setattr(settings, "db_path", tmp_path / "old.sqlite")
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE document_classification")
        conn.execute(
            "CREATE TABLE document_classification ("
            " document_id TEXT PRIMARY KEY, doc_type TEXT, discipline TEXT,"
            " doc_class TEXT, register_id TEXT, suggested_by TEXT NOT NULL,"
            " confirmed_by TEXT, confirmed_at TEXT)")
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES ('old','old.pdf','s',1,"
            "'old.pdf','ready',1,?)", (NOW,))
        conn.execute(
            "INSERT INTO document_classification (document_id, discipline,"
            " suggested_by) VALUES ('old', 'Non-metallic Standards Committee',"
            " 'test')")
        conn.execute("PRAGMA foreign_keys = ON")
    before = {r["name"] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")}
    assert "discipline_canonical" not in before, "the fixture is not the old shape"

    db.init_db()

    after = {r["name"] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")}
    assert "discipline_canonical" in after
    # And the old row survived the ALTER with its evidence intact.
    row = db.connect().execute(
        "SELECT discipline FROM document_classification WHERE document_id='old'"
    ).fetchone()
    assert row["discipline"] == "Non-metallic Standards Committee"


# ============================================================ the filter

def _narrow(asked: str, *ids: str) -> set[str]:
    """What `narrow_to_scope` returns for one discipline, under a real scope.

    The real filtering path, not a hand-built query: the intersection that
    makes a filter safe is written once, there, and a test that rebuilt it
    here would be asserting against its own copy.
    """
    scope = access.AccessScope(user_id="u", allowed_document_ids=frozenset(ids))
    found, applied = classification.narrow_to_scope(
        scope, classification.ScopeFilter(disciplines=(asked,)))
    assert applied, "the filter reported that it did not apply"
    return set(found)


def test_filtering_finds_both_spellings_whichever_one_is_asked_for():
    """THE REASON THE COLUMN EXISTS. Before this, a caller asking for
    "Non-metallic" and a caller asking for "Nonmetallic" got different
    documents depending on which spelling each document happened to use."""
    _classified("d1", "Non-metallic Standards Committee")
    _classified("d2", "Nonmetallic Standards Committee")
    disciplines.backfill()

    for asked in ("Non-metallic Standards Committee",
                  "Nonmetallic Standards Committee"):
        assert _narrow(asked, "d1", "d2") == {"d1", "d2"}, \
            f"asking for {asked!r} did not find both"


def test_filtering_still_narrows_rather_than_returning_everything():
    """The guard on the filter: one that matched everything would satisfy the
    test above and destroy the feature."""
    _classified("d1", "Nonmetallic Standards Committee")
    _classified("d2", "Piping Standards Committee")
    disciplines.backfill()

    assert _narrow("Piping Standards Committee", "d1", "d2") == {"d2"}


def test_the_filter_may_only_narrow_what_the_caller_already_holds():
    """CLAUDE.md rule 5: intersection, never union. A document that matches
    the discipline but sits outside the grant set stays outside it."""
    _classified("d1", "Piping Standards Committee")
    _classified("d2", "Piping Standards Committee")
    disciplines.backfill()

    assert _narrow("Piping Standards Committee", "d1") == {"d1"}


def test_a_row_written_before_the_column_existed_is_still_findable():
    """COALESCE, and why. Until the startup backfill runs, an old row has
    NULL there; falling back to the raw value keeps it findable by its own
    spelling instead of silently dropping out of every filtered result."""
    _classified("d1", "Piping Standards Committee")
    with db.connect() as conn:
        conn.execute("UPDATE document_classification"
                     " SET discipline_canonical = NULL")

    assert _narrow("Piping Standards Committee", "d1") == {"d1"}
