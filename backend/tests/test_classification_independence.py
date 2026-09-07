"""Classification is NOT access control. Proved in both directions.

THE RULE THIS FILE EXISTS FOR. `disciplines` and `document_role_access` decide
WHO MAY READ a document. `document_classification` and `document_subjects`
decide WHAT A DOCUMENT IS. Separate tables, separate concepts, and neither may
move the other.

WHY IT NEEDS A TEST RATHER THAN A COMMENT. The two look almost identical in a
schema diagram. `document_classification.discipline` holds the same 24 strings
a discipline ROLE holds - "Process (AXENS)" is both a column value here and
the name of a role people are granted - so a foreign key between them looks
like normalisation rather than a category error. It is a category error: the
register's discipline is a fact about a deliverable, and the Process role is a
permission held by a person. Wire them together and reclassifying a document
silently regrants it.

So this asserts the negative, which is the only kind of assertion that catches
it: change a classification, and `access.may_read` returns exactly what it
returned before, for every user and every document. Then the reverse.

Nothing here depends on the client's register or the real corpus. Both are
absent on a clean clone, and a test that needed either would prove nothing
anywhere else.
"""

from __future__ import annotations

import re

import pytest

from app import access, classification, db
from app.config import settings
from app.db import connect

NOW = "2026-09-07T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _user(user_id: str, role_name: str, kind: str = "discipline") -> str:
    role_id = f"role_{role_name}"
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@example.test", user_id, "h", NOW))
        conn.execute(
            "INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
            " VALUES (?,?,?,?,?)", (role_id, role_name, role_name, kind, NOW))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at)"
            " VALUES (?,?,?)", (user_id, role_id, NOW))
    return role_id


def _document(doc_id: str, filename: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (doc_id, filename, f"sha-{doc_id}", 1, f"/tmp/{doc_id}", "ready", NOW))


def _grant(doc_id: str, role_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_role_access (document_id,role_id,"
            "permission,granted_at,granted_by) VALUES (?,?,'read',?,NULL)",
            (doc_id, role_id, NOW))


def _subject(subject_id: str, name: str, kind: str = "system") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO subjects (id,name,kind,register_revision)"
            " VALUES (?,?,?,'rev-A')", (subject_id, name, kind))


def _scope_for(user_id: str) -> access.AccessScope:
    """A real scope, resolved the way a request resolves one."""
    return access.scope_for_user(user_id)


@pytest.fixture
def corpus():
    """Two documents, two disciplines, one user who may read only one."""
    process = _user("proc_user", "Process (AXENS)")
    piping = _user("pipe_user", "Piping")
    _document("doc_a", "hot-oil-pid.pdf")
    _document("doc_b", "firewater-layout.pdf")
    _grant("doc_a", process)
    _grant("doc_b", piping)
    _subject("sub_hotoil", "hot oil")
    _subject("sub_firewater", "firewater")
    _subject("sub_pw", "Project-wide", "project_wide")
    return {"process": process, "piping": piping}


# --------------------------------- classification does not move access


def test_classifying_a_document_changes_no_access_decision(corpus):
    """THE CENTRAL ASSERTION. Every (user, document) may_read answer is
    recorded, a full classification is written, and every answer is recorded
    again. Not one may differ."""
    users = ["proc_user", "pipe_user"]
    docs = ["doc_a", "doc_b"]

    before = {(u, d): _scope_for(u).may_read(d) for u in users for d in docs}
    assert before == {
        ("proc_user", "doc_a"): True, ("proc_user", "doc_b"): False,
        ("pipe_user", "doc_a"): False, ("pipe_user", "doc_b"): True,
    }, before

    # Classify doc_b into the Process discipline - deliberately the discipline
    # its reader does NOT hold. If classification touched access, this is the
    # edit that would show it.
    classification.write_suggestion(
        "doc_b",
        classification.Suggestion(
            doc_type="Drawing", discipline="Process (AXENS)",
            doc_class="PLOT PLAN", register_id=None,
            subject_ids=("sub_hotoil", "sub_firewater"),
            source={"doc_type": "register", "discipline": "register"},
        ),
        suggested_by="register",
    )

    after = {(u, d): _scope_for(u).may_read(d) for u in users for d in docs}
    assert after == before, (
        f"classification moved an access decision.\n  before: {before}\n"
        f"  after : {after}"
    )


def test_confirming_a_classification_changes_no_access_decision(corpus):
    """Confirmation is the privileged operation, so it is the likeliest place
    for someone to "also" grant something."""
    classification.write_suggestion(
        "doc_a", classification.Suggestion(
            doc_type="Document", discipline="Piping", doc_class=None,
            register_id=None, subject_ids=("sub_firewater",), source={}),
        suggested_by="pattern")

    before = {u: sorted(_scope_for(u).allowed_document_ids)
              for u in ("proc_user", "pipe_user")}

    classification.confirm("doc_a", doc_type="Document", discipline="Piping",
                           doc_class=None, subject_ids=["sub_firewater"],
                           confirmed_by="proc_user")

    after = {u: sorted(_scope_for(u).allowed_document_ids)
             for u in ("proc_user", "pipe_user")}
    assert after == before, (before, after)


def test_no_classification_table_references_the_access_tables():
    """STRUCTURAL, not behavioural. Read from the schema: if a foreign key
    into `roles` or `document_role_access` is ever added, this fails - and it
    fails before any behaviour has a chance to depend on it."""
    forbidden = {"roles", "document_role_access", "user_roles"}
    conn = connect()
    for table in ("deliverables_register", "subjects",
                  "document_classification", "document_subjects"):
        refs = {r["table"] for r in conn.execute(
            f"PRAGMA foreign_key_list({table})")}
        leaked = refs & forbidden
        assert not leaked, (
            f"{table} has a foreign key into {sorted(leaked)}. A "
            f"classification must not reference an access table: the "
            f"register's discipline is a fact about a deliverable and a "
            f"discipline role is a permission held by a person. Joining them "
            f"means reclassifying a document regrants it."
        )


def test_the_access_tables_have_no_classification_column():
    """The mirror. Nothing was added to the access side either."""
    conn = connect()
    for table in ("document_role_access", "roles"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for banned in ("doc_type", "subject_id", "doc_class",
                       "register_id", "classification"):
            assert banned not in cols, (
                f"{table} grew a {banned!r} column. Access control does not "
                f"record what a document is.")


# --------------------------------- access does not move classification


def test_revoking_access_leaves_the_classification_intact(corpus):
    """A document nobody may read is still a firewater layout. Losing the
    grant must not lose the fact - otherwise regranting it later would come
    back unclassified and silently drop out of every subject comparison."""
    classification.write_suggestion(
        "doc_b", classification.Suggestion(
            doc_type="Drawing", discipline="Piping", doc_class="PLOT PLAN",
            register_id=None, subject_ids=("sub_firewater",), source={}),
        suggested_by="register")
    before = classification.of_document("doc_b")

    with connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE document_id = ?",
                     ("doc_b",))

    assert _scope_for("pipe_user").may_read("doc_b") is False
    assert classification.of_document("doc_b") == before, (
        "revoking access changed the classification")


def test_deleting_a_role_leaves_the_classification_intact(corpus):
    """`document_role_access` cascades on role delete. The classification must
    not cascade with it - the discipline string in a classification is a
    label, not a pointer to the role of the same name."""
    classification.write_suggestion(
        "doc_a", classification.Suggestion(
            doc_type="Document", discipline="Process (AXENS)", doc_class=None,
            register_id=None, subject_ids=(), source={}),
        suggested_by="register")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM roles WHERE id = ?", (corpus["process"],))

    row = classification.of_document("doc_a")
    assert row is not None
    assert row["discipline"] == "Process (AXENS)", (
        "deleting the Process ROLE deleted or blanked the Process "
        "CLASSIFICATION - they are different things wearing the same string")


def test_a_classification_row_survives_only_its_own_document(corpus):
    """The one cascade that IS correct: classification is keyed on the
    document, so deleting the document takes it. Asserted so the ON DELETE
    CASCADE is deliberate rather than inherited."""
    classification.write_suggestion(
        "doc_a", classification.Suggestion(
            doc_type="Document", discipline="Piping", doc_class=None,
            register_id=None, subject_ids=("sub_firewater",), source={}),
        suggested_by="pattern")
    assert classification.of_document("doc_a") is not None

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM documents WHERE id = ?", ("doc_a",))

    assert classification.of_document("doc_a") is None
    with connect() as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM document_subjects WHERE document_id = ?",
            ("doc_a",)).fetchone()[0]
    assert left == 0, "subject links outlived their document"


def test_classification_writes_touch_no_access_table(corpus):
    """A WRITE-LEVEL assertion rather than a read-level one.

    The tests above compare answers before and after. This watches the SQL
    itself: every statement SQLite executes during a classification write is
    captured through `set_trace_callback`, and one naming an access table
    fails immediately - including an INSERT that happened to be harmless
    today.

    `set_trace_callback` rather than monkeypatching `Connection.execute`,
    which cannot be done: the type is immutable. It is also the better tool -
    it sees what SQLite actually ran, including statements issued through any
    path that did not go via `execute`.
    """
    seen: list[str] = []
    conn = connect()
    conn.set_trace_callback(lambda sql: seen.append(" ".join(str(sql).lower().split())))
    try:
        classification.write_suggestion(
            "doc_a", classification.Suggestion(
                doc_type="Document", discipline="Piping", doc_class="P&ID",
                register_id=None, subject_ids=("sub_firewater", "sub_pw"),
                source={}),
            suggested_by="pattern")
        classification.confirm("doc_a", doc_type="Document",
                               discipline="Piping", doc_class="P&ID",
                               subject_ids=["sub_pw"],
                               confirmed_by="proc_user")
    finally:
        conn.set_trace_callback(None)

    assert seen, "the tracer captured nothing - it is not wired to the calls"
    # It really did see the classification writes, or "no access table
    # appeared" would be true of an empty list.
    assert any("document_classification" in sql for sql in seen), seen
    for sql in seen:
        for table in ("document_role_access", "user_roles"):
            assert table not in sql, (
                f"classification executed SQL naming {table!r}: {sql}")
        # `roles` as a whole word, so `user_roles` above is not double-counted
        # and `document_role_access` does not false-positive on the substring.
        assert not re.search(r"roles", sql), (
            f"classification executed SQL naming the roles table: {sql}")
