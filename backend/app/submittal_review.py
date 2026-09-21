"""Schema and scoped read paths for the AI submittal review workflow.

PHASE 1 IS FOUNDATION ONLY. This module owns four tables and the queries that
read them under a caller's grants. It contains no extraction, no applicability
decision, no comparison and no export - those are later phases, and a table
existing here is not a claim that anything fills it yet.

WHY EVERY READ PATH TAKES `allowed_document_ids` KEYWORD-ONLY WITH NO DEFAULT

The same reason `search.search` and `keyword.search` do, recorded as entry 11
of the honesty audit: a default is a filter that can be forgotten. A caller
that omits the argument here raises TypeError at the call site, which a test
catches and a reviewer sees. A caller that omits a defaulted argument reads the
whole corpus and returns rows that look correct.

`deliverables.list_items` is the counter-example this module deliberately does
NOT copy. Its filter reads

    WHERE document_id IS NULL OR document_id IN (...)

which makes every NULL-document row readable by everyone. A review run always
has a submittal document, so there is no legitimate NULL here and NULL must
never mean world-readable. The filter below therefore has no NULL branch, and
an empty grant set resolves to `WHERE 1 = 0` - the caller is granted nothing,
so it sees nothing, which is not the same as being granted everything.

FILTERED IN THE QUERY, NEVER IN PYTHON AFTER IT. `metrics._where` carries the
rule and the reason: post-filtering happens to work while there is no LIMIT and
"silently becomes a leak the day someone adds one".
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import review
from .db import add_column_if_missing, connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    """A random uuid4, matching review.py:317 and deliverables.py:122.

    NOT the `doc_{sha256[:12]}` content hash. That identifier exists so that
    re-uploading the same bytes is recognised as the same document; a review
    run, a fact and a requirement are events, and two of them with identical
    contents are two different things that must not collide.
    """
    return str(uuid.uuid4())


def _scope_clause(
    allowed_document_ids: frozenset[str], column: str
) -> tuple[str, list[str]]:
    """A WHERE fragment restricting `column` to the caller's grants.

    Shaped after `metrics._where`, with one deliberate difference: there is no
    `None` meaning corpus-wide. Every table in this module is keyed to a
    submittal document, so "no restriction" is not a state a caller of this
    module may express. An admin's breadth arrives as a wide id set from
    `access.scope_for_user`, through the same parameter as everyone else's.

    An EMPTY set is not "everything". It means the caller holds no grants, and
    `1 = 0` is the honest translation of that.
    """
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


def ensure_schema() -> None:
    """Create this module's tables. Idempotent, and safe to call repeatedly.

    Module-local rather than in `db.SCHEMA`, following review.py: the workflow
    tables are created by the code that owns them, so a database that never
    runs a review never grows them.
    """
    # ORDERING, NOT POLITENESS. `review_runs.template_id` references
    # `review_templates` and `list_run_findings` reads `review_findings.
    # review_run_id`; both are created by review.ensure_schema(), and this
    # module's tables are unusable until they exist. With PRAGMA foreign_keys
    # ON, an INSERT against a table whose parent is missing fails at write
    # time rather than at create time - so a missing call here would surface
    # as a confusing runtime error in phase 2, not here.
    review.ensure_schema()
    conn = connect()
    with conn:
        # ---------------------------------------------------- standards side
        # One extracted requirement from a company standard. `standard_document_id`
        # IS a foreign key here, unlike on a finding: a requirement is OWNED by
        # the standard it was extracted from and is meaningless once that
        # document is gone, so it cascades. A FINDING that cited the standard
        # is not owned by it and must outlive it - that is the distinction, and
        # it is why the two columns of the same name behave differently.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS standard_requirements (
                id TEXT PRIMARY KEY,
                standard_document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                clause TEXT,
                page INTEGER,
                -- THE RESOLVING CITATION. A requirement is a claim about a
                -- document, and this project's first honesty invariant is that
                -- no claim exists without a citation that resolves. The chunk
                -- is what makes `clause` and `page` checkable: a reader can
                -- open the exact passage the sentence was read from.
                --
                -- It points into the EXISTING chunks - the same rows retrieval
                -- already searches, already in chunks_fts, already embedded in
                -- chunk_vectors. A second exact-text or vector store would
                -- duplicate retrieval and, worse, bypass the
                -- allowed_document_ids masking that only the existing path
                -- enforces.
                --
                -- ON DELETE CASCADE: re-chunking a document replaces its
                -- chunks, and a requirement whose chunk is gone cannot be
                -- resolved any more. Keeping it would leave a claim pointing
                -- at nothing, which is the state this column exists to
                -- prevent. Re-extraction rebuilds them.
                chunk_id TEXT REFERENCES chunks(id) ON DELETE CASCADE,
                requirement_text TEXT NOT NULL,
                -- The verbatim span this requirement was read from. Kept
                -- beside the paraphrase so a claim can always be resolved to
                -- the document - no claim without a resolving citation.
                source_text TEXT,
                category TEXT,
                equipment_type TEXT,
                service TEXT,
                -- 'extracted' | 'human' - a guess stays labelled a guess until
                -- a human confirms it. NULL means no tier recorded.
                extraction_method TEXT,
                confidence REAL,
                confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                confirmed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        # Phase 3A added `chunk_id` to a table Phase 1 created and never wrote
        # to. The ALTER is still required: a database created by the phase 1 or
        # phase 2 build has the table without the column, and `CREATE TABLE IF
        # NOT EXISTS` above is a no-op there. `row[1]` is review.py's PRAGMA
        # idiom, which this module follows.
        requirement_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(standard_requirements)")
        }
        # Phase 3B: the structured shape of a requirement. Added by ALTER for
        # the same reason chunk_id was - a phase 1/2/3A database has the table
        # without them.
        #
        # PLAIN TEXT AND REAL, NO CHECK CONSTRAINTS, as everywhere else in this
        # schema: SQLite cannot ALTER-ADD a CHECK, and the vocabularies are
        # enforced in Pydantic where a bad value is refused with a message.
        #
        # `value` is REAL and NULLABLE, and the nullability is load-bearing: an
        # unknown unit or an unparseable number leaves it NULL, never 0. A 0
        # here would read as a limit of zero, which is a real and very
        # different requirement.
        for _column, _type in (
            ("requirement_type", "TEXT"),
            ("field", "TEXT"),
            ("operator", "TEXT"),
            ("value", "REAL"),
            ("unit", "TEXT"),
            # The raw spellings exactly as the document wrote them, kept beside
            # the normalised pair. `claims.Measurement` preserves both for the
            # same reason: a value that could not be normalised must still be
            # quotable, and a reader checking a citation reads the document's
            # own words, not this system's canonical form.
            ("raw_value", "TEXT"),
            ("raw_unit", "TEXT"),
            ("condition", "TEXT"),
            # A JSON array. Acceptable here for the reason equipment_tags is:
            # an exception list is an immutable snapshot of what one clause
            # said, nothing joins on it, and nothing filters by it. If 3C ever
            # needs to query exceptions, it becomes a table then.
            ("exceptions", "TEXT"),
            ("discipline", "TEXT"),
            # Provenance for a value read out of a table rather than a
            # sentence: which parsed table row it came from.
            ("table_row", "INTEGER"),
            # WHAT THE CLAUSE IS TALKING ABOUT, in the document's own words -
            # the noun phrase before the comparator, with articles, modal
            # verbs and page-footer text removed.
            #
            # DESCRIPTIVE ONLY, AND DELIBERATELY NOT `field`. `field` is the
            # join key `comparison._match_fact` looks up against a datasheet's
            # normalised label, and it is exact equality. Measured over the
            # corpus, the noun phrase before the operator produces things like
            # "the material stress in the bottom parts of the vessel" - true
            # descriptions of the clause, and never a datasheet caption. Put in
            # `field` they would make the column read as populated while
            # matching nothing, hiding the fact that no requirement is
            # comparable yet. So they live here, where a human can read them
            # and no join can consume them.
            ("subject", "TEXT"),
        ):
            # RACE-SAFE, because this runs on read paths. See
            # `db.add_column_if_missing`.
            add_column_if_missing(conn, "standard_requirements", _column, _type)
        if requirement_columns and "chunk_id" not in requirement_columns:
            # No REFERENCES clause on the ALTER: SQLite cannot add a column
            # with a foreign key to an existing table. The constraint is
            # therefore present on a freshly created table and absent on a
            # migrated one - so `standards.create_requirement` enforces the
            # resolving citation in code, where it holds either way.
            add_column_if_missing(
                conn, "standard_requirements", "chunk_id", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_standard_requirements_document "
            "ON standard_requirements(standard_document_id, created_at DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_standard_requirements_chunk "
            "ON standard_requirements(chunk_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_standard_requirements_unconfirmed "
            "ON standard_requirements(confirmed_by, standard_document_id)")

        # ------------------------------------------------------- the run
        # `submittal_document_id` is NOT NULL and cascades: a run is about one
        # submittal and has no meaning without it. NOT NULL is also what makes
        # the scope filter safe - see the module docstring on NULL rows.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_runs (
                id TEXT PRIMARY KEY,
                submittal_document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                template_id TEXT REFERENCES review_templates(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                -- Why the run ended where it did. A refusal is a result and is
                -- recorded as one rather than left as an empty finding list.
                refusal_reason TEXT,
                model_name TEXT,
                -- config.config_version() at the time of the run: the hash of
                -- the settings that could change the answer, the same stamp
                -- reports.py freezes onto a delivered claim.
                config_version TEXT,
                started_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        # SECTION 15: the AI recommends, the engineer decides, and both are
        # kept. The recommendation lives in `refusal_reason` where
        # `_store_run_outcome` writes it; the DECISION gets columns of its
        # own, because "which reviews are waiting for an engineer" is a
        # question a dashboard asks in SQL and cannot ask of a JSON blob.
        for _column, _type in (
            # One of the four codes in section 15. NULL until an engineer
            # decides, which is the state "awaiting engineer decision".
            ("engineer_final_code", "TEXT"),
            # REQUIRED when the final code differs from the recommendation,
            # optional when it agrees. Enforced in `record_engineer_code`.
            ("override_reason", "TEXT"),
            ("decided_by", "TEXT REFERENCES users(id) ON DELETE SET NULL"),
            ("decided_at", "TEXT"),
        ):
            add_column_if_missing(conn, "review_runs", _column, _type)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_runs_submittal "
            "ON review_runs(submittal_document_id, status, created_at DESC)")

        # ------------------------------------------------- the submittal side
        conn.execute(
            """CREATE TABLE IF NOT EXISTS submittal_facts (
                id TEXT PRIMARY KEY,
                review_run_id TEXT NOT NULL
                    REFERENCES review_runs(id) ON DELETE CASCADE,
                submittal_document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                field_value TEXT,
                unit TEXT,
                page INTEGER,
                section TEXT,
                -- The span the value was read from. Without it a fact is an
                -- assertion; with it a reader can go and check.
                source_text TEXT,
                extraction_method TEXT,
                confidence REAL,
                confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                confirmed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        # Phase 4 made facts PER DOCUMENT by making `review_run_id`
        # nullable. That needed a table rebuild, and the rebuild does NOT
        # live here - see `migrate_facts_to_per_document`, which runs once
        # at startup. A conditional DROP/CREATE inside a function called on
        # every read makes the table's shape a function of execution
        # history: an old shape with a leftover row skips it, an old shape
        # with an empty table fires it, and either way it happens at a
        # moment no caller chose. Read paths assume the schema; they do not
        # repair it.
        # The resolving citation, same reasoning as standard_requirements in
        # 3A: a fact without a chunk is an assertion. Plus the normalised
        # shape a comparison engine will read in phase 5.
        facts_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(submittal_facts)")
        }
        for _column, _type in (
            ("chunk_id", "TEXT"),
            ("raw_value", "TEXT"),
            ("raw_unit", "TEXT"),
            ("normalized_value", "REAL"),
            ("normalized_unit", "TEXT"),
            # TRUE when the datasheet leaves the field for the contractor to
            # fill and it is still empty. MISSING_INFORMATION, never
            # NON_COMPLIANT and never a zero.
            ("is_blank", "INTEGER"),
            ("blank_marker", "TEXT"),
            ("field_label", "TEXT"),
            ("bbox", "TEXT"),
            # A PAIRING AN ENGINEER HAS REJECTED. See
            # `review_pair_rejections` below.
            # 'gauge', 'absolute', or NULL when the sheet did not say.
            #
            # A PRESSURE WITHOUT ITS REFERENCE IS NOT A NUMBER ANYONE CAN
            # COMPARE. `3.5 bar (ga)` and `3.5 bar` differ by an atmosphere,
            # and the difference runs in the direction that makes a vessel look
            # compliant. The reference is split off the unit so `bar` reaches
            # the conversion table, and kept here so the distinction survives.
            # Nothing converts between the two - that needs an ambient pressure
            # nobody has recorded.
            ("unit_reference", "TEXT"),
            # A RANGE HAS TWO NUMBERS AND NEITHER IS "THE" VALUE. `-3 to 55 C`
            # is an ambient band; averaging it invents a number the sheet does
            # not state, and picking one silently answers a question nobody
            # asked. Both ends are kept and `comparison.compare` chooses the
            # end the RULE asks about - the maximum for "shall not exceed",
            # the minimum for "shall be at least".
            #
            # NULL on an ordinary single value, where `raw_value` carries it.
            ("value_min", "REAL"),
            ("value_max", "REAL"),
            # WHICH EQUIPMENT THE FACT DESCRIBES, verbatim from the sheet's
            # own tag row - `2003-47-V-0001A/B`, `PSV-4301 A/B (for GC-9, 10 &
            # 19)`. NULL when the document does not say, which on a multi-tag
            # sheet is the honest answer for a page with no tag row.
            ("equipment_tag", "TEXT"),
            # The section heading this row actually sits under, or NULL. See
            # `datasheets._section_for`: it was previously filled with whatever
            # heading the CHUNK carried, which on a two-column form is another
            # column's text.
            ("section_heading", "TEXT"),
        ):
            add_column_if_missing(conn, "submittal_facts", _column, _type)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_submittal_facts_run "
            "ON submittal_facts(review_run_id, field_name, created_at DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_submittal_facts_document "
            "ON submittal_facts(submittal_document_id, created_at DESC)")

        # ------------------------------------------ pairings a human refused
        #
        # WHY THIS IS A TABLE AND NOT A FLAG ON THE FINDING. A finding is the
        # OUTPUT of one run and `replace=True` clears it; the judgement "this
        # requirement is not about this field" is about the PAIR, is true
        # whatever run observed it, and must outlive every re-extraction. Put
        # on the finding it would be destroyed by the next maintenance action
        # and the same wrong pairing proposed again - so the engineer rejects
        # it once and the matcher never offers it again.
        #
        # NO CASCADE FROM EITHER SIDE. Re-extracting a standard replaces its
        # requirement rows with new ids, and a cascade would quietly forget
        # every rejection at exactly the moment the pairings are recomputed.
        # The rows are matched by id and a stale one is harmless; a forgotten
        # one asks a person the same question twice.
        # KEYED ON WHAT THE ROWS ARE, NOT ON THEIR ROW IDS.
        #
        # `standard_requirements.id` and `submittal_facts.id` are uuid4,
        # regenerated on every `replace=True` extraction - and re-extraction is
        # how every fix to the extractors reaches the corpus. A rejection keyed
        # on those ids would match nothing after the next re-run: it would stop
        # applying SILENTLY, the same wrong pairing would be proposed again,
        # and the engineer would have no way to tell that their correction had
        # been forgotten rather than ignored.
        #
        # So the key is the IDENTITY of the pair: which standard, which clause
        # and what the requirement says; which submittal and which field. Those
        # survive re-extraction because they are what was extracted. The row
        # ids are kept beside them as informational columns - useful for
        # tracing the rejection back to the run that produced it, never used to
        # decide whether a rejection applies.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_pair_rejections (
                requirement_key TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                -- Informational only. NULL is acceptable: a rejection recorded
                -- against rows that have since been replaced is still valid.
                requirement_id TEXT,
                fact_id TEXT,
                rejected_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                rejected_at TEXT NOT NULL,
                -- WHY, in the engineer's words. A rejection with no reason is
                -- indistinguishable from a misclick six months later, and this
                -- is the record that stops the machine re-proposing a pairing.
                reason TEXT,
                PRIMARY KEY (requirement_key, fact_key)
            )""")

        # ------------------------------------- which standards applied, and why
        # A NORMALISED RELATION, not a JSON column on review_runs, and the
        # reason is the three things this data has to do:
        #   * it is JOINED - "which runs used this standard" is a question the
        #     Standards Library will ask, and JSON cannot answer it with an
        #     index.
        #   * it is PERMISSION FILTERED - a standard the caller cannot read
        #     must not be listed, which needs the id in a column.
        #   * it is AUDITED - `included` flipping to 0 with an
        #     `exclusion_reason` is a decision someone must be able to review.
        # JSON stays acceptable for immutable snapshots and exception lists,
        # which none of these three are.
        #
        # `standard_document_id` cascades: the row records that a standard was
        # CONSIDERED for a run, which is a statement about a document that now
        # exists. The FINDING that cited it is the record that outlives it.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_applicable_standards (
                id TEXT PRIMARY KEY,
                review_run_id TEXT NOT NULL
                    REFERENCES review_runs(id) ON DELETE CASCADE,
                standard_document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                selection_reason TEXT,
                -- 'rule' | 'model' | 'human' - WHICH TIER chose it, kept per
                -- row for the reason document_classification.suggested_by is:
                -- a standard a rule selected and a standard a model guessed
                -- are different facts and must not read alike.
                selection_method TEXT,
                confidence REAL,
                -- 1 = applied to this run, 0 = considered and ruled out. A
                -- ruled-out standard stays as a ROW rather than being deleted,
                -- because "we looked at this and decided it did not apply" is
                -- the answer to the question an engineer actually asks.
                included INTEGER NOT NULL DEFAULT 1,
                exclusion_reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(review_run_id, standard_document_id)
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_applicable_standards_run "
            "ON review_applicable_standards(review_run_id, included, created_at DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_applicable_standards_standard "
            "ON review_applicable_standards(standard_document_id, included)")


def create_review_run(
    *, submittal_document_id: str, allowed_document_ids: frozenset[str],
    started_by: str | None = None, template_id: str | None = None,
) -> str:
    """Open a review run over one submittal. Returns its id.

    SCOPED LIKE EVERY OTHER PATH: a caller who may not read the submittal may
    not start a review of it, and gets the same "no such document" a missing
    one gives rather than a 403 that confirms it exists.

    The run opens as `running` and `comparison._store_run_outcome` moves it to
    `completed`. That is not bookkeeping: a process that dies mid-review
    leaves the row saying `running`, which is what stops a second review being
    started over the same document and is the honest description of what
    happened.
    """
    ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "id")
    readable = connect().execute(
        "SELECT id FROM documents" + where + " AND id = ?",
        [*args, submittal_document_id]).fetchone()
    if readable is None:
        raise ValueError("no submittal with that id")
    run_id = str(uuid.uuid4())
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, template_id,"
            " status, started_by, started_at, created_at, updated_at)"
            " VALUES (?,?,?,'running',?,?,?,?)",
            (run_id, submittal_document_id, template_id, started_by, now,
             now, now))
    return run_id


#: What an orphaned run's failure says. One wording, so a reader who meets it
#: twice recognises it, and so the test can assert the sentence rather than a
#: paraphrase of it.
ORPHANED_RUN_REASON = (
    "orphaned: no process was running it when the server started")


def fail_orphaned_review_runs() -> int:
    """Mark every run still `running` at startup as failed. Returns the count.

    A CRASHED RUN IS HISTORY, NOT GARBAGE. It is not deleted: somebody started
    it, findings may have been written before it died, and removing the row
    would erase the only record that it ever happened. It is marked failed,
    with the reason, so the screen says what became of it.

    WHY STARTUP IS WHERE THIS IS SAFE, and it is the same fact
    `standards.recover_stale_extraction_jobs` relies on: this process has just
    begun, so it owns no run, and `run_comparison` is synchronous inside a
    request - there is no queue and no worker that could be carrying one. A
    run still marked `running` therefore belongs to a process that is gone.

    Without it the row is worse than a failure: it CLAIMS TO BE BUSY. The
    review endpoint refuses to start a second run while one is running for the
    same document, so a single crashed run locks that submittal out of the
    product permanently, and nothing on screen explains why.
    """
    ensure_schema()
    conn = connect()
    with conn:
        cur = conn.execute(
            "UPDATE review_runs SET status = 'failed', refusal_reason = ?,"
            " updated_at = ? WHERE status = 'running'",
            (json.dumps({"error": ORPHANED_RUN_REASON}), _now()))
        return cur.rowcount


# ------------------------------------------------------------- read paths
#
# Each takes `allowed_document_ids` keyword-only with NO DEFAULT. Deleting the
# scope clause from any one of them must make a permission test fail; that is
# the mutation the tests assert.


#: Every run, with the NAME of whoever signed it - resolved in the join, not
#: by a lookup per row. `decided_by` is a user id because it is a foreign key;
#: an id is not what a reader recognises, and a screen that printed it was
#: asking an engineer to know their own primary key. LEFT JOIN because the
#: column is `ON DELETE SET NULL`: a run signed by a since-deleted user keeps
#: its decision and simply has no name to show.
#:
#: EVERY COLUMN THE CALLERS ADD IS QUALIFIED `r.`, and that is not style.
#: `users` also has `id` and `created_at`, so the unqualified `AND id = ?` and
#: `ORDER BY created_at DESC, id DESC` these callers already carried became
#: `ambiguous column name` the moment a second table entered the FROM - eleven
#: scope tests said so. `submittal_document_id` is unambiguous and is left as
#: `_scope_clause` writes it, since that helper serves other tables too.
_RUN_SELECT = (
    "SELECT r.*, u.display_name AS decided_by_name"
    " FROM review_runs r LEFT JOIN users u ON u.id = r.decided_by"
)


def list_review_runs(
    *, allowed_document_ids: frozenset[str],
    submittal_document_id: str | None = None,
) -> list[dict]:
    """Review runs over submittals the caller may read."""
    ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")
    sql = _RUN_SELECT + where
    if submittal_document_id is not None:
        # AND, never OR: a caller narrowing to one document may only narrow.
        sql += " AND submittal_document_id = ?"
        args = [*args, submittal_document_id]
    # A TIEBREAKER, because `_now()` is second-granularity: two runs
    # created in the same second have no defined order without one, and a
    # caller comparing this list to an expected sequence gets whichever
    # order SQLite happened to produce. `review_status_for` below already
    # orders this way and picks the first row per document, so the two
    # must agree or "the latest run" means two different things in one
    # module.
    sql += " ORDER BY r.created_at DESC, r.id DESC"
    return [dict(row) for row in connect().execute(sql, args).fetchall()]


def get_review_run(run_id: str, *, allowed_document_ids: frozenset[str]) -> dict | None:
    """One run, or None when it does not exist OR the caller may not read its
    submittal. The two are deliberately indistinguishable, the same reason
    `api_utils.require_document` collapses forbidden into not-found: a 403
    confirms the row exists."""
    ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")
    row = connect().execute(
        _RUN_SELECT + where + " AND r.id = ?", [*args, run_id]
    ).fetchone()
    return dict(row) if row is not None else None


def list_submittal_facts(
    *, allowed_document_ids: frozenset[str], review_run_id: str | None = None,
) -> list[dict]:
    """Extracted submittal facts, restricted to readable submittals.

    Scoped on `submittal_facts.submittal_document_id` directly rather than by
    joining through `review_runs`: one column on the row being filtered is one
    place to get it wrong, and the denormalised id is on the table precisely so
    this filter never needs a join to be correct.
    """
    ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")
    sql = "SELECT * FROM submittal_facts" + where
    if review_run_id is not None:
        sql += " AND review_run_id = ?"
        args = [*args, review_run_id]
    sql += " ORDER BY created_at DESC, field_name"
    return [dict(row) for row in connect().execute(sql, args).fetchall()]


def list_applicable_standards(
    review_run_id: str, *, allowed_document_ids: frozenset[str],
    include_excluded: bool = True,
) -> list[dict]:
    """Standards considered for a run, filtered TWICE and on purpose.

    The run's submittal must be readable, AND each standard row is restricted
    to standards the caller may read. Both, because they are two different
    documents: a caller granted the submittal is not thereby granted every
    standard it was compared against, and listing a standard's id would
    disclose a document they hold no grant for.

    The result is an INTERSECTION with the caller's grants in both directions -
    never a union. A caller who may read the submittal but not a given standard
    sees the run without that row, which is narrower, not wider.
    """
    ensure_schema()
    if get_review_run(review_run_id, allowed_document_ids=allowed_document_ids) is None:
        # Not readable or not there. Same answer for both.
        return []
    where, args = _scope_clause(allowed_document_ids, "standard_document_id")
    sql = "SELECT * FROM review_applicable_standards" + where + " AND review_run_id = ?"
    args = [*args, review_run_id]
    if not include_excluded:
        sql += " AND included = 1"
    sql += " ORDER BY included DESC, created_at DESC"
    return [dict(row) for row in connect().execute(sql, args).fetchall()]


def list_standard_requirements(
    *, allowed_document_ids: frozenset[str], standard_document_id: str | None = None,
) -> list[dict]:
    """Requirements from standards the caller may read."""
    ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "standard_document_id")
    sql = "SELECT * FROM standard_requirements" + where
    if standard_document_id is not None:
        sql += " AND standard_document_id = ?"
        args = [*args, standard_document_id]
    # Same reason as list_review_runs: second-granularity timestamps make
    # a bare created_at ordering unstable for rows written together, and a
    # bulk extraction writes many requirements inside one second.
    sql += " ORDER BY created_at DESC, id DESC"
    return [dict(row) for row in connect().execute(sql, args).fetchall()]


def review_status_for(
    document_ids: list[str], *, allowed_document_ids: frozenset[str],
) -> dict[str, str]:
    """`{document_id: review status}` for documents the caller may read.

    THE MASTER-PLAN "review status" FIELD, DERIVED AND NEVER STORED. The
    authority is the latest `review_runs` row for that submittal; a document
    with no run is `not_reviewed`, which is a real answer rather than a null.
    A `review_status` column would be a second home for a fact `review_runs`
    already owns, and the two would disagree the first time a run was
    retried - CLAUDE.md rule 8.

    Documents the caller may not read are simply absent from the result. That
    is not the same as `not_reviewed`, and a caller must not render a missing
    key as "no review": it means "not yours to know".
    """
    ensure_schema()
    visible = [d for d in document_ids if d in allowed_document_ids]
    if not visible:
        return {}
    marks = ",".join("?" for _ in visible)
    # One row per document: the most recent run wins. Ordered by created_at
    # and then id so the choice is deterministic when two runs share a second -
    # the timestamps are second-resolution, so ties are real.
    rows = connect().execute(
        f"""SELECT submittal_document_id AS doc, status FROM review_runs
            WHERE submittal_document_id IN ({marks})
            ORDER BY created_at DESC, id DESC""",
        visible,
    ).fetchall()
    # First row per document wins, because the query is ordered newest-first.
    #
    # NOT `GROUP BY ... MAX(created_at), MAX(id)`: those two maxima are taken
    # INDEPENDENTLY, so the pair can describe a row that does not exist - which
    # is exactly what the first version of this function did, and it silently
    # reported every reviewed document as `not_reviewed`. The permission filter
    # is still in the query (`visible`); only the newest-per-document choice is
    # made here, where it is plainly correct.
    latest: dict[str, str] = {}
    for row in rows:
        latest.setdefault(row["doc"], row["status"])
    return {doc: latest.get(doc, "not_reviewed") for doc in visible}


def list_run_findings(
    review_run_id: str, *, allowed_document_ids: frozenset[str],
) -> list[dict]:
    """Findings belonging to a run, restricted to readable submittals.

    Scoped on `review_findings.document_id` - the submittal - and not on
    `standard_document_id`, which has no foreign key and may name a document
    that has since been deleted. A finding is the record that a citation was
    made; it is readable with the submittal it is about.
    """
    ensure_schema()
    if get_review_run(review_run_id, allowed_document_ids=allowed_document_ids) is None:
        return []
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT * FROM review_findings" + where + " AND review_run_id = ?"
        " ORDER BY updated_at DESC", [*args, review_run_id]
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for field in ("citation_ids", "governing_sources", "unresolved_evidence"):
            try:
                item[field] = json.loads(item.get(field) or "[]")
            except (TypeError, ValueError):
                item[field] = []
        out.append(item)
    return out


def migrate_pair_rejections_to_stable_keys() -> None:
    """Rebuild `review_pair_rejections` onto identity keys. ONCE, AT STARTUP.

    The first shape keyed on `requirement_id` and `fact_id`, which are uuid4
    and are regenerated by every `replace=True` extraction - so a rejection
    would have stopped applying at the next re-run, silently.

    AT STARTUP, NOT IN `ensure_schema`. A conditional DROP/CREATE in a function
    every read path calls is what caused the intermittent failures recorded as
    honesty-audit entry 18: DDL on one SQLite connection blocks readers on the
    others, and the table's shape becomes a function of execution history.

    The rebuild DROPS rather than migrates, and that is safe only because the
    old shape carried no way to recompute the new keys - the rows it held
    pointed at ids that no longer exist. Any rejections recorded against it
    were already dead. This is CHECKED rather than assumed: the rebuild runs
    only when the new column is absent.
    """
    conn = connect()
    columns = {row[1] for row in conn.execute(
        "PRAGMA table_info(review_pair_rejections)")}
    if not columns or "requirement_key" in columns:
        return
    with conn:
        conn.execute("DROP TABLE review_pair_rejections")
    ensure_schema()


def migrate_facts_to_per_document() -> None:
    """Make `submittal_facts.review_run_id` nullable. ONCE, AT STARTUP.

    THE DECISION, MADE EXPLICITLY RATHER THAN INHERITED. Phase 1 declared the
    column NOT NULL, which makes a fact unable to exist outside a run and
    forces a full re-extraction of a datasheet every time a review starts.
    Master plan section 24 asks the opposite on a 16 GB machine: "reuse cached
    extraction and embeddings for duplicate documents". A datasheet's facts are
    a property of the datasheet.

    SQLite cannot drop a NOT NULL, so this is a rebuild. It is safe only
    because the table has never been written to in any build - and that is
    CHECKED here rather than assumed: if any row exists the rebuild is skipped
    and the old shape is kept. Data is never dropped to satisfy a schema
    preference.

    IT LIVES HERE, NOT IN `ensure_schema`, and the distinction is the point. A
    structural migration is a one-time event with a defined moment; a schema
    guarantee is something every read may assert. Putting a DROP/CREATE in the
    function every read calls makes the table's shape depend on execution
    history and fires it at a moment no caller chose. Called from
    `main.lifespan` beside the other `ensure_schema()` calls.
    """
    ensure_schema()
    conn = connect()
    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(submittal_facts)")
    }
    run_column = columns.get("review_run_id")
    if run_column is None or run_column[3] != 1:        # notnull flag
        return                                          # already nullable
    if conn.execute("SELECT COUNT(*) FROM submittal_facts").fetchone()[0]:
        # Rows exist. The old shape is kept and the decision is deferred to
        # whoever is willing to migrate real data.
        return
    with conn:
        conn.execute("DROP TABLE submittal_facts")
        conn.execute(
            """CREATE TABLE submittal_facts (
                id TEXT PRIMARY KEY,
                -- NULLABLE now. Which run first produced this fact, or
                -- NULL when it was extracted outside any run.
                review_run_id TEXT REFERENCES review_runs(id) ON DELETE SET NULL,
                submittal_document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                field_value TEXT,
                unit TEXT,
                page INTEGER,
                section TEXT,
                source_text TEXT,
                extraction_method TEXT,
                confidence REAL,
                confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                confirmed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
    # The added columns are re-applied by ensure_schema, which is additive and
    # safe to call again.
    ensure_schema()
