"""SQLite storage. WAL mode, foreign keys on, one connection per thread."""

import sqlite3
import threading
from pathlib import Path

from .config import settings

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id                TEXT PRIMARY KEY,
    filename          TEXT NOT NULL,
    sha256            TEXT NOT NULL UNIQUE,
    size_bytes        INTEGER NOT NULL,
    stored_path       TEXT NOT NULL,
    page_count        INTEGER,
    pages_done        INTEGER NOT NULL DEFAULT 0,
    chunk_count       INTEGER NOT NULL DEFAULT 0,
    chunk_count_total INTEGER NOT NULL DEFAULT 0,
    chunk_signature   TEXT,
    status            TEXT NOT NULL DEFAULT 'queued',
    needs_ocr_pages   INTEGER NOT NULL DEFAULT 0,
    equation_pages    INTEGER NOT NULL DEFAULT 0,
    error_code        TEXT,
    error_message     TEXT,
    uploaded_at       TEXT NOT NULL,
    indexed_at        TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id                    TEXT PRIMARY KEY,
    document_id           TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage                 TEXT NOT NULL DEFAULT 'extract',
    state                 TEXT NOT NULL DEFAULT 'running',
    pages_total           INTEGER,
    pages_done            INTEGER NOT NULL DEFAULT 0,
    last_completed_batch  INTEGER,
    retries               INTEGER NOT NULL DEFAULT 0,
    error_code            TEXT,
    error_message         TEXT,
    started_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no       INTEGER NOT NULL,
    text          TEXT NOT NULL,
    char_count    INTEGER NOT NULL,
    needs_ocr     INTEGER NOT NULL DEFAULT 0,
    equation_heavy INTEGER NOT NULL DEFAULT 0,
    batch_no      INTEGER NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

-- Recognised text. A SEPARATE TABLE, deliberately, and this is the whole
-- point of it: extract.py writes `pages` with INSERT OR REPLACE, which deletes
-- the row and inserts a new one. Any column on `pages` - a provenance flag and
-- the recognised text alike - is therefore destroyed by a re-extraction, and
-- states.py explicitly permits re-extraction from both no_searchable_content
-- and failed. Twenty minutes of recognition would be silently overwritten by
-- the empty extraction that triggered it. Extraction cannot reach this table.
-- See ADR-0006.
CREATE TABLE IF NOT EXISTS page_ocr (
    document_id   TEXT    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no       INTEGER NOT NULL,
    text          TEXT    NOT NULL,      -- already through normalise_text
    char_count    INTEGER NOT NULL,
    -- Provenance: a result states what it ran against, so a number is never
    -- orphaned from its conditions.
    engine        TEXT    NOT NULL,      -- 'rapidocr-3.9.2'
    model         TEXT    NOT NULL,      -- 'PP-OCRv6_det_tiny+PP-OCRv6_rec_tiny'
    dpi           INTEGER NOT NULL,
    -- Confidence is data, not a knob. Stored so a threshold can be set from
    -- measurement later; NULL when the page produced no boxes at all.
    mean_conf     REAL,
    min_conf      REAL,
    box_count     INTEGER NOT NULL,
    -- Characters outside the document's expected script. Non-zero means the
    -- recogniser emitted something it should not be able to - under a
    -- Latin-only recogniser this should never fire, which makes it a guard on
    -- the guard.
    alphabet_violations INTEGER NOT NULL DEFAULT 0,
    alphabet_sample     TEXT,
    seconds       REAL    NOT NULL,
    recognised_at TEXT    NOT NULL,
    batch_no      INTEGER NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    page_start     INTEGER NOT NULL,
    page_end       INTEGER NOT NULL,
    section        TEXT,
    -- The parent block this chunk came out of. Retrieval works on the small
    -- chunk; the reader is shown the surrounding block, because a clause cut
    -- between its table and its notes answers with the notes and leaves the
    -- figure behind. See expand_passage.
    parent_id      TEXT,
    kind           TEXT NOT NULL DEFAULT 'prose',
    text           TEXT NOT NULL,
    token_count    INTEGER NOT NULL,
    content_hash   TEXT NOT NULL,
    retrievable    INTEGER NOT NULL DEFAULT 1,
    quality_flags  TEXT,
    -- 'extracted' | 'recognised'. If ANY page a chunk spans was recognised,
    -- the whole chunk is 'recognised': a reader cannot tell which sentence
    -- came from where, so the label makes the weaker claim. A third 'mixed'
    -- state was considered and rejected - it pushes an unresolvable hedge onto
    -- the reader. Carried here rather than joined back to pages so retrieval
    -- and the UI see it without a join.
    text_source    TEXT NOT NULL DEFAULT 'extracted',
    -- Minimum confidence over the chunk's recognised pages: the weakest
    -- evidence governs. NULL unless text_source = 'recognised'.
    ocr_min_conf   REAL,
    -- Characters in this chunk the document's script cannot contain. PROOF of
    -- a substitution rather than an opinion about one: two chunks can both sit
    -- at 0.95 confidence and one of them contains a CJK ideograph.
    ocr_alphabet_violations INTEGER NOT NULL DEFAULT 0,
    ocr_alphabet_sample     TEXT
);

CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    dim          INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vectors_document ON chunk_vectors(document_id);

CREATE TABLE IF NOT EXISTS exclusions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    scope         TEXT NOT NULL,          -- 'page' | 'chunk'
    page_start    INTEGER,
    page_end      INTEGER,
    chunk_id      TEXT,
    rule          TEXT NOT NULL,          -- which rule excluded it
    reason        TEXT,                   -- the detail behind the rule
    text_sample   TEXT NOT NULL,          -- what was dropped
    text_length   INTEGER NOT NULL,
    -- Non-zero means the dropped text carried numbered clause headings AND
    -- real prose. That combination is body text, so an exclusion carrying it
    -- almost certainly threw away real content - which is exactly what
    -- happened to NORSOK page 11 and its entire Clause 8. Surfaced in the UI
    -- as an ALERT rather than a count, and it doubles as a regression
    -- detector: the classifier gate should keep this at zero.
    clause_headings INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------- access
-- Entirely new ground: before this there was no user, tenant, grant, project
-- or role table anywhere in the schema. Additive and idempotent, matching the
-- existing style - CREATE TABLE IF NOT EXISTS here, PRAGMA table_info in
-- _migrate for columns on tables that already exist. No version table, because
-- this schema has never had one and inventing one for five tables would be a
-- second convention rather than a followed one.
--
-- ROLE GRANTS ONLY. The plan also specifies per-user allow/deny on documents;
-- that is deliberately NOT built here. Its primary key cannot represent both a
-- narrower allow and a deny for the same (user, document, permission), so the
-- semantics are ambiguous before the first row is written. Roles that work now,
-- a deny model when it is specified.

-- Reports: a frozen snapshot of one answer and the documents it cited, and
-- the PDF rendered from that snapshot alone. Additive, no version table.
--
-- message_id and conversation_id are ON DELETE SET NULL: deleting a
-- conversation must not delete the record that a report was issued - the same
-- reasoning audit_events uses for its actor. owner_username is denormalised
-- for the same reason.
CREATE TABLE IF NOT EXISTS reports (
    id                  TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    message_id          TEXT REFERENCES messages(id) ON DELETE SET NULL,
    conversation_id     TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    owner_user_id       TEXT,
    owner_username      TEXT,
    auth_mode           TEXT NOT NULL,
    -- the authorisation decision, frozen
    scope_unrestricted  INTEGER NOT NULL DEFAULT 0,
    scope_document_ids  TEXT NOT NULL,
    question            TEXT,
    resolved_question   TEXT,
    snapshot_json       TEXT NOT NULL,
    snapshot_sha256     TEXT NOT NULL,
    config_version      TEXT NOT NULL,
    renderer            TEXT NOT NULL,
    template_version    TEXT NOT NULL,
    -- NEVER serialised to a client. NULL once a cited document is deleted.
    stored_path         TEXT,
    suppressed_reason   TEXT,
    report_sha256       TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    page_count          INTEGER NOT NULL
);

-- One row per cited document with its state FROZEN at generation. document_id
-- is deliberately NOT a foreign key: a deleted document must not erase the
-- record that it was cited. revision and approval_status are NULL because no
-- such columns exist on documents - rendered as "not recorded", never invented.
CREATE TABLE IF NOT EXISTS report_documents (
    report_id        TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    document_id      TEXT NOT NULL,
    filename         TEXT NOT NULL,
    sha256           TEXT NOT NULL,
    page_count       INTEGER,
    chunk_signature  TEXT,
    indexed_at       TEXT,
    revision         TEXT,
    approval_status  TEXT,
    passages_cited   INTEGER NOT NULL DEFAULT 0,
    text_source      TEXT,
    PRIMARY KEY (report_id, document_id)
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    -- Hash only. There is no column a password could be stored in, which is a
    -- cheaper guarantee than a rule saying not to.
    password_hash TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    token_epoch   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS roles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    -- 'discipline' | 'capability'. The ONE thing this column exists to say:
    -- `admin` is a CAPABILITY, not a fifth discipline. An administrator also
    -- works somewhere - an IT administrator is IT *and* admin - so admin is
    -- orthogonal to the four disciplines (Civil Engineering, Mechanical,
    -- Chemical-Process, IT) rather than a member of them. Modelling it as a
    -- discipline forces a false choice and leaves an admin unable to see their
    -- own documents. See docs/design-admin-screen.md.
    --
    -- Why a column here rather than a boolean on `users` or a separate
    -- capability table: user_roles is ALREADY many-to-many, so a person
    -- holding IT and admin at once needs no new table and no new join - the
    -- storage was always capable of it. What was missing was any way to tell
    -- the two kinds APART, and without that the admin screen's `disciplines[]`
    -- and `is_admin` cannot be derived from the database at all; the split
    -- would live in a Python constant in one script that every other caller
    -- would have to import. A boolean on `users` would fix is_admin alone and
    -- leave a second capability needing a second column.
    --
    -- Defaulting to 'discipline' keeps every row written by existing code -
    -- all of which inserts (id, name, description, created_at) - meaningful
    -- rather than NULL.
    kind        TEXT NOT NULL DEFAULT 'discipline',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id    TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    -- NOT NULL AND NO DEFAULT, deliberately: a role grant with no recorded
    -- time is an audit record that cannot answer "when did this person get
    -- this access", which is the first question asked after an incident.
    --
    -- Stated here because it is not obvious from any calling code and costs
    -- twenty minutes to rediscover: a hand-written INSERT that omits this
    -- column fails with `NOT NULL constraint failed: user_roles.granted_at`,
    -- and every insert in the repository supplies it, so nothing demonstrates
    -- the requirement. Use `scripts/seed_access.py` rather than raw SQL.
    granted_at TEXT NOT NULL,
    granted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, role_id)
);

-- Which ROLES may see which documents. There is no row meaning "everyone", and
-- no wildcard document id: absence of a row is the only way to express "no
-- access", so deny-by-default is a property of the schema rather than of the
-- code that reads it.
CREATE TABLE IF NOT EXISTS document_role_access (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    role_id     TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission  TEXT NOT NULL DEFAULT 'read',
    granted_at  TEXT NOT NULL,
    granted_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (document_id, role_id, permission)
);

CREATE INDEX IF NOT EXISTS idx_dra_role ON document_role_access(role_id, permission);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);

-- Append-only record of who did what. `actor_user_id` is nullable and
-- ON DELETE SET NULL on purpose: deleting a user must not delete the evidence
-- that they acted, and an audit row that vanishes with its subject is not an
-- audit row.
CREATE TABLE IF NOT EXISTS audit_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    -- TWO FIELDS FOR THE ACTOR, ON PURPOSE, answering two different
    -- questions. The nullable FK answers "does this account still exist" and
    -- goes NULL when the user is deleted, so the row survives. The denormalised
    -- name answers "who did this", which is the question an audit trail exists
    -- for, and it is written at event time so deletion cannot take it away.
    --
    -- The two CAN disagree - after a rename, actor_username holds the name in
    -- force when the action happened while the FK resolves to the current one.
    -- That is intended: an audit record states what was true at the time, not
    -- what is true now. Reconstructing history from the live users table would
    -- be re-writing it.
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    actor_username TEXT NOT NULL,
    action        TEXT NOT NULL,
    resource_type TEXT,
    resource_id   TEXT,
    -- Response-safe detail only. Never a document title, chunk, question or
    -- answer: the audit log is the one table most likely to be exported.
    detail        TEXT,
    outcome       TEXT NOT NULL DEFAULT 'ok'
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_events(at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_user_id, at DESC);

CREATE TABLE IF NOT EXISTS stage_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stage        TEXT NOT NULL,
    document_id  TEXT,
    items        INTEGER NOT NULL,
    seconds      REAL NOT NULL,
    -- NULL when the interval was too short to measure. A rate divided by an
    -- almost-zero elapsed time is how the dashboard once reported
    -- 1021658887.25 pages/sec.
    rate         REAL,
    at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stage_runs_stage ON stage_runs(stage, id DESC);

-- What the watched drop folder actually did, one row per file per decision.
--
-- The folder is the only ingestion path with NO HUMAN AT THE OTHER END. A
-- manual upload reports its outcome to the person who pressed the button; a
-- file dropped into a share reports to nobody, so a document that was seen and
-- refused is indistinguishable from one that was never dropped unless the
-- refusal is written down. That is what this table is for, and it is why
-- 'duplicate' and 'failed' are recorded as loudly as 'ingested'.
--
-- `outcome` is CHECKed rather than left free text: the three values are the
-- whole vocabulary, and a fourth spelling invented at a call site would be a
-- status the status endpoint cannot count.
--
-- `document_id` is nullable and carries NO FOREIGN KEY, for two reasons that
-- point the same way. A 'failed' or 'duplicate'-of-nothing event has no
-- document to reference, and an event whose document is later deleted must
-- survive that deletion - a record of what arrived that disappears with what
-- arrived is not a record. `detail` is response-safe text only, the same rule
-- audit_events keeps: never document content.
CREATE TABLE IF NOT EXISTS watch_events (
    id          INTEGER PRIMARY KEY,
    filename    TEXT NOT NULL,
    source_path TEXT NOT NULL,
    -- The hash the decision was made on. EMPTY STRING means the file could not
    -- be read far enough to hash it - the one case where NOT NULL and "we do
    -- not know" collide, and it is spelled out in `detail` on every such row
    -- rather than left for a reader to infer from a blank column.
    sha256      TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK(outcome IN ('ingested','duplicate','failed')),
    document_id TEXT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_watch_events_observed ON watch_events(observed_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    document_id   TEXT REFERENCES documents(id) ON DELETE SET NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    ordinal           INTEGER NOT NULL,
    role              TEXT NOT NULL,      -- 'user' | 'assistant'
    text              TEXT,               -- question, or answer; null on a refusal
    -- user rows only: what retrieval actually ran, after follow-up resolution,
    -- and which terms were carried in. Stored so the UI can show the reader
    -- what was assumed rather than silently reinterpreting the question.
    resolved_question TEXT,
    carried_terms     TEXT,               -- JSON array
    -- assistant rows only
    answer_type       TEXT,
    reason            TEXT,
    explains_id       TEXT REFERENCES messages(id) ON DELETE SET NULL,
    payload           TEXT,               -- JSON: passages, citations, timings
    created_at        TEXT NOT NULL,
    UNIQUE (conversation_id, ordinal)
);

-- ==================================================== classification
--
-- WHAT A DOCUMENT IS. Not who may read it.
--
-- THE SEPARATION IS THE POINT AND IT IS STRUCTURAL. `disciplines` and
-- `document_role_access` decide WHO MAY READ a document, and nothing in this
-- section touches them: no foreign key into them, no column added to them, no
-- shared row. A classification says what a document is ABOUT; an access grant
-- says who is allowed to see it. They answer different questions and a
-- filter built on this may only ever NARROW what a caller already may read -
-- intersection, never union.
--
-- The reason to be this explicit is that the two look similar in a schema
-- diagram. `document_classification.discipline` and a discipline ROLE carry
-- the same 24 strings, and the temptation to make one a foreign key to the
-- other is real. It would be wrong: the register's "Process (AXENS)" is a
-- fact about a deliverable, and the Process role is a permission held by
-- people. Joining them would mean reclassifying a document silently
-- regranted it.
--
-- WHY subject IS THE COMPARISON AXIS, measured against the client's register:
-- subject terms cover 82% of 1,354 titles, and a subject spans 5.5
-- disciplines on average with 18 of 22 systems spanning three or more. A
-- discipline says who WROTE a document; a subject says what it is ABOUT, and
-- comparison happens along subject.

-- The client's Engineering Deliverables register, as imported. THE OFFICIAL
-- LIST, and authoritative for type and discipline: when a title matches a row
-- here, the classification is the client's own rather than this system's
-- guess.
--
-- Kept per revision rather than replaced, so a re-issued register does not
-- silently rewrite what earlier documents were classified against.
CREATE TABLE IF NOT EXISTS deliverables_register (
    id                TEXT PRIMARY KEY,
    -- 'Document' | 'Drawing' | 'LicensorFinalBEP'. Not a CHECK constraint:
    -- the importer refuses a fourth value outright, with a message naming it,
    -- which is a better error than a constraint violation - and a future
    -- register revision that legitimately adds a type should fail in the
    -- importer where a human reads the output, not in SQLite.
    doc_type          TEXT NOT NULL,
    -- THE VENDOR STAYS INSIDE THE LABEL, exactly as the register writes it:
    -- "Process (AXENS)". Measured decision: vendor is not its own axis
    -- because it is already inside the discipline string, and splitting it
    -- would create two sources of truth for one field.
    discipline        TEXT NOT NULL,
    -- Extracted from the label for display only, never for filtering. NULL
    -- for the majority of rows, which name no vendor.
    vendor            TEXT,
    title             TEXT NOT NULL,
    register_revision TEXT NOT NULL,
    imported_at       TEXT NOT NULL,
    UNIQUE (register_revision, doc_type, discipline, title)
);

-- The subject vocabulary, DERIVED from the register titles rather than
-- invented. ~25 systems, 6 facilities, plus one explicit 'project_wide'.
--
-- 'project_wide' is a KIND, not a system that happens to be named
-- "Project-wide". 18% of the register is philosophies, design criteria and
-- overall block diagrams that apply to everything, and those are exactly the
-- documents gap analysis should hold as baselines - so the kind is queryable
-- rather than being a string a caller has to know to match.
CREATE TABLE IF NOT EXISTS subjects (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('system', 'facility', 'project_wide')),
    register_revision TEXT NOT NULL,
    UNIQUE (register_revision, name)
);

-- One row per classified document. EVERY CLASSIFICATION FIELD IS NULLABLE and
-- the NULLs are real answers:
--
--   * doc_type / discipline NULL -> nothing matched and nothing was guessed.
--     A discipline inferred from one word in a filename is worse than no
--     discipline, because it routes searches confidently to the wrong place.
--   * register_id NULL -> this document is not in the register (an uploaded
--     working document, a vendor drawing that never made the list).
--   * confirmed_by NULL -> SUGGESTED, NOT CONFIRMED. This is the state the
--     needs-classification queue is built from, so it has its own index: the
--     UI asks "what still needs a human" on every load.
--
-- `suggested_by` is 'register' | 'pattern' | 'none' - WHICH TIER produced the
-- value, kept per row so a reader can tell a client-authoritative
-- classification from a filename pattern match. A confirmed row keeps it:
-- knowing an admin confirmed something the register already said is
-- different from knowing they confirmed a guess.
CREATE TABLE IF NOT EXISTS document_classification (
    document_id   TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    doc_type      TEXT,
    discipline    TEXT,
    -- P&ID, DATASHEET, SLD, PHILOSOPHY... A CHIP ONLY. Measured: 88%
    -- derivable and nobody searches by it, so it is recorded and displayed
    -- and is deliberately NOT a filter axis.
    doc_class     TEXT,
    register_id   TEXT REFERENCES deliverables_register(id) ON DELETE SET NULL,
    suggested_by  TEXT NOT NULL,
    confirmed_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at  TEXT,
    -- ------------------------------------------- AI submittal review, phase 1
    -- The submittal-review vocabulary. Every column NULLABLE and every NULL an
    -- answer: this row already exists for every classified document written by
    -- an earlier build, and none of them can know what they are in a workflow
    -- that did not exist when they were written. NULL means NOT RECORDED, and
    -- is rendered as nothing - never as a default role and never as 0.
    --
    -- CLASSIFICATION IS STILL NOT ACCESS CONTROL (rule 5). `document_role`
    -- says what part a document plays in a review; it grants nothing. The
    -- grant tables decide who may read it, and a role filter may only narrow
    -- what a caller already holds.
    --
    -- PLAIN TEXT, NO CHECK CONSTRAINT. This schema carries exactly one CHECK
    -- (roles.kind) and adding a second here would be permanent: SQLite cannot
    -- ALTER-ADD a CHECK, so the next column migration on this table would
    -- force a full table rebuild. The five legal roles are enforced in
    -- Pydantic (`schemas.DocumentRole`), where a bad value is rejected at the
    -- boundary with a message instead of aborting a write deep in a migration.
    document_role      TEXT,
    document_number    TEXT,
    -- The HUMAN title, which is not the filename. `documents.filename` is the
    -- name of the file on disk and is authoritative for identity; a title is
    -- descriptive metadata about the same document and belongs here with the
    -- rest of it, not on the core table whose columns decide lifecycle.
    -- NULL means no title was recorded, and the UI falls back to the filename
    -- rather than inventing one. (Master-plan section 6 metadata mapping.)
    title              TEXT,
    revision           TEXT,
    effective_date     TEXT,
    project            TEXT,
    contractor_vendor  TEXT,
    equipment_type     TEXT,
    -- A JSON array as TEXT. Acceptable here because it is a flat list of tags
    -- nothing joins on, filters by, or audits. The applicable-standards
    -- relation is a TABLE for exactly the opposite reason.
    equipment_tags     TEXT,
    service            TEXT,
    transmittal_number TEXT,
    -- A document id, and DELIBERATELY NOT A FOREIGN KEY - the report_documents
    -- precedent (db.py:212-215). Deleting the superseding document must not
    -- erase the record that this one was superseded; that record is the reason
    -- an engineer does not quote a revision that was replaced.
    superseded_by      TEXT
);

-- MANY-TO-MANY ON PURPOSE. A firewater layout for the substation has two
-- subjects, and forcing a single one would lose the link that makes
-- comparison work: the document would appear under firewater OR under
-- substation, and a reader comparing either would be handed an incomplete
-- set without being told.
CREATE TABLE IF NOT EXISTS document_subjects (
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    subject_id   TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    suggested_by TEXT NOT NULL,
    confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (document_id, subject_id)
);

-- The needs-classification queue, which the UI reads on every load, so it is
-- an index rather than a scan of the whole table.
CREATE INDEX IF NOT EXISTS idx_classification_unconfirmed
    ON document_classification(confirmed_by, document_id);
CREATE INDEX IF NOT EXISTS idx_classification_discipline
    ON document_classification(discipline);
CREATE INDEX IF NOT EXISTS idx_classification_type
    ON document_classification(doc_type);
CREATE INDEX IF NOT EXISTS idx_document_subjects_subject
    ON document_subjects(subject_id, document_id);
CREATE INDEX IF NOT EXISTS idx_register_revision
    ON deliverables_register(register_revision, discipline);
CREATE INDEX IF NOT EXISTS idx_subjects_revision
    ON subjects(register_revision, kind);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_exclusions_document ON exclusions(document_id, scope);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_pages_ocr ON pages(document_id, needs_ocr);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
"""


def connect() -> sqlite3.Connection:
    """Thread-local connection. WAL lets one writer and many readers coexist."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        settings.ensure_dirs()
        conn = sqlite3.connect(settings.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        _local.conn = conn
    return conn


def columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    """The column names of `table`, empty when there is no such table."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str,
                          definition: str) -> bool:
    """`ALTER TABLE ... ADD COLUMN`, safe when two threads do it at once.

    CHECK-THEN-ALTER IS A RACE AND IT FIRED IN PRODUCTION CODE. Every
    `ensure_schema` is called from ordinary read paths, so two requests can
    reach the same migration together: both read `PRAGMA table_info`, both see
    the column missing, both issue the ALTER, and the loser dies with
    `sqlite3.OperationalError: duplicate column name`. Measured on
    `tests/test_access_routes.py`, which failed 3 runs in 10 on that error
    while the tree was otherwise green.

    NO LOCK, BECAUSE THE DATABASE ALREADY HAS ONE. SQLite serialises the two
    ALTERs itself; the only thing missing was an answer for the thread that
    arrives second, and "the column is already there" is that answer. A
    migration lock table would be a second thing to get wrong, and
    `busy_timeout` does not help - this is not a busy database, it is a
    duplicate statement.

    Returns True when THIS call added the column. False means it was already
    present, whoever put it there, which is all any caller needs.

    THE DUPLICATE ERROR IS THE ONLY ONE SWALLOWED, and even then the column is
    re-read before the failure is accepted as benign. A swallowed ALTER that
    did not actually happen would leave the schema short of a column while
    every caller believed it present - a worse failure than the crash, because
    it is silent.
    """
    existing = columns_of(conn, table)
    if not existing or column in existing:
        # No such table - whoever creates it owns its shape - or the column is
        # already there and there is nothing to do.
        return False
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise
        if column not in columns_of(conn, table):
            raise
        return False
    return True


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations for databases created by an earlier build."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    roles = {r["name"] for r in conn.execute("PRAGMA table_info(roles)")}
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if user_columns and "token_epoch" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN token_epoch INTEGER NOT NULL DEFAULT 0")
    if roles and "kind" not in roles:
        conn.execute(
            "ALTER TABLE roles ADD COLUMN kind TEXT NOT NULL DEFAULT 'discipline'"
        )
    if have and "retrievable" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN retrievable INTEGER NOT NULL DEFAULT 1")
    if have and "quality_flags" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN quality_flags TEXT")
    if have and "parent_id" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN parent_id TEXT")
    exc = {r["name"] for r in conn.execute("PRAGMA table_info(exclusions)")}
    if exc and "clause_headings" not in exc:
        conn.execute(
            "ALTER TABLE exclusions ADD COLUMN clause_headings INTEGER NOT NULL DEFAULT 0")
    pg = {r["name"] for r in conn.execute("PRAGMA table_info(pages)")}
    if pg and "equation_heavy" not in pg:
        conn.execute("ALTER TABLE pages ADD COLUMN equation_heavy INTEGER NOT NULL DEFAULT 0")
    docs = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    if docs and "chunk_count_total" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN chunk_count_total INTEGER NOT NULL DEFAULT 0")
    if docs and "chunk_signature" not in docs:
        conn.execute("ALTER TABLE documents ADD COLUMN chunk_signature TEXT")
    if docs and "equation_pages" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN equation_pages INTEGER NOT NULL DEFAULT 0")
    if docs and "embedded_count" not in docs:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN embedded_count INTEGER NOT NULL DEFAULT 0")
    # ------------------------------------------------------------------ OCR
    # Every existing chunk resolves to 'extracted', and that is a FACT rather
    # than a convenient default: OCR has never run in any build of this system,
    # so no recognised text can exist in any database this migration will meet.
    if have and "text_source" not in have:
        conn.execute(
            "ALTER TABLE chunks ADD COLUMN text_source TEXT NOT NULL DEFAULT 'extracted'")
    if have and "ocr_min_conf" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN ocr_min_conf REAL")
    if have and "ocr_alphabet_violations" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN ocr_alphabet_violations"
                     " INTEGER NOT NULL DEFAULT 0")
    if have and "ocr_alphabet_sample" not in have:
        conn.execute("ALTER TABLE chunks ADD COLUMN ocr_alphabet_sample TEXT")
    if docs and "recognised_pages" not in docs:
        # A count, not a boolean, matching needs_ocr_pages and equation_pages.
        # A 546-page document with 12 recognised pages must never read as
        # "OCR'd"; the UI states the fraction.
        conn.execute(
            "ALTER TABLE documents ADD COLUMN recognised_pages INTEGER NOT NULL DEFAULT 0")
    # The old rule name asserted a property of the SYSTEM - "OCR is not
    # implemented" - which goes false the day OCR ships, leaving rows carrying
    # a name that no longer describes reality. The new name asserts a property
    # of the PAGE, which was true when the row was written and stays true.
    # Chunking regenerates exclusions per document, so this only matters for
    # documents that are never re-chunked - which is why it is done here too.
    conn.execute(
        "UPDATE exclusions SET rule = 'ocr_not_run',"
        " reason = 'scanned page with no extractable text; recognition has not run'"
        " WHERE rule = 'needs_ocr_not_implemented'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_page_ocr_document ON page_ocr(document_id)"
    )
    # --------------------------------------------- AI submittal review, phase 1
    # The submittal-review vocabulary on an existing classification row. Every
    # column is nullable with no default, so an existing row keeps every value
    # it had and gains NULLs that mean NOT RECORDED. Nothing is back-filled and
    # nothing is guessed: a document classified before this workflow existed
    # cannot know its role, and inventing one would route a review confidently
    # to the wrong baseline.
    #
    # `r["name"]` and not `row[1]` on purpose - it is the idiom this file
    # already uses. review.py reads `row[1]` for the same PRAGMA and the two
    # are deliberately left disagreeing rather than unified in this phase.
    classification_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(document_classification)")
    }
    if classification_cols:
        for _column in (
            "document_role", "document_number", "title", "revision",
            "effective_date", "project", "contractor_vendor", "equipment_type",
            "equipment_tags", "service", "transmittal_number", "superseded_by",
        ):
            if _column not in classification_cols:
                conn.execute(
                    f"ALTER TABLE document_classification ADD COLUMN {_column} TEXT")
    # ------------------------------------------------------------- access
    # `roles` predates the distinction between a discipline and a capability:
    # every role in a database written before this column was, by construction,
    # undifferentiated. 'discipline' is the right default for all of them -
    # they were seeded to carry document grants - with exactly one exception,
    # corrected by name below.
    role_cols = {r["name"] for r in conn.execute("PRAGMA table_info(roles)")}
    if role_cols and "kind" not in role_cols:
        conn.execute(
            "ALTER TABLE roles ADD COLUMN kind TEXT NOT NULL DEFAULT 'discipline'")
    # Idempotent and by NAME, not by id: `admin` is a capability in every
    # database, including one seeded by an earlier build that had no idea the
    # two kinds differed. Re-asserted on every init for the same reason the
    # exclusions rule rename above is - a database that is never re-seeded
    # would otherwise keep the wrong answer forever.
    conn.execute("UPDATE roles SET kind = 'capability' WHERE name = 'admin'")
    # Created HERE and not in SCHEMA, for the reason the retrievable and
    # parent indexes below are: executescript(SCHEMA) runs BEFORE _migrate, so
    # an index over `kind` in SCHEMA fails outright on a database whose roles
    # table predates the column. Measured, not reasoned about - it raised
    # "no such column: kind" on a legacy database.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_roles_kind ON roles(kind, name)")
    # conversations predate ownership. NULL means "written before there were
    # users", and it must read as INACCESSIBLE rather than as unowned-and-
    # therefore-public. Deliberately no DEFAULT: there is no user to attribute
    # a legacy conversation to, and inventing one would be a false record.
    convs = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    if convs and "owner_user_id" not in convs:
        conn.execute("ALTER TABLE conversations ADD COLUMN owner_user_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_owner"
        " ON conversations(owner_user_id, updated_at DESC)"
    )
    # created after the migration so it cannot reference a missing column
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_retrievable ON chunks(retrievable)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id, ordinal)"
    )
    conn.commit()


def init_db(path: Path | None = None) -> None:
    if path is not None:
        settings.db_path = path
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def reset_connection() -> None:
    """Test helper - drop the thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
