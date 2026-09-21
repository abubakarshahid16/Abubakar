"""Phase 2: metadata writes, the role vocabulary, and the filter's intersection.

The filters are the feature, but the INTERSECTION is the invariant. A filter
that widens is worse than no filter: it hands a reader documents they hold no
grant for while looking like it narrowed. Mutations M11 (& becomes |) and M14
(a filter that matched nothing falls back to the corpus) are the two ways that
happens, and the tests here are written so that either one fails them.

Run the mutations with:  python scripts/mutation_check.py --phase 2
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, classification, db
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "metadata.sqlite")
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


def _doc(doc_id: str, name: str, digest: str) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)
            VALUES (?,?,?,?,?,'ready',?)""",
            (doc_id, name, digest, 1, name, "2026-09-18T00:00:00Z"))
    return doc_id


def _classify(doc_id: str, **fields) -> None:
    """Write a classification row directly, including the phase 2 columns."""
    columns = ["document_id", "suggested_by"]
    values = [doc_id, "test"]
    for key, value in fields.items():
        columns.append(key)
        values.append(value)
    marks = ",".join("?" * len(values))
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({marks})", values)


def _user(user_id: str = "admin1") -> str:
    """A real users row: `confirmed_by` is a foreign key."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users"
            " (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,?,1,?)",
            (user_id, f"{user_id}@example.test", user_id, "x",
             "2026-09-18T00:00:00Z"))
    return user_id


def _scope(*ids: str) -> access.AccessScope:
    return access.AccessScope(user_id="u1", allowed_document_ids=frozenset(ids))


# ------------------------------------------------------- the write path

def test_an_admin_can_assign_every_document_role():
    from app.schemas import ClassificationUpdate
    for role in ("CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT",
                 "SUPPORTING_DOCUMENT", "CRS_TEMPLATE"):
        body = ClassificationUpdate(document_role=role)
        assert body.document_role == role


@pytest.mark.parametrize("bad", ["SUBMITTAL", "contractor_submittal", "STANDARD", ""])
def test_an_invalid_role_is_rejected_at_the_update_boundary(bad):
    """M12 widens ClassificationUpdate.document_role to `str`; this fails."""
    from pydantic import ValidationError

    from app.schemas import ClassificationUpdate
    with pytest.raises(ValidationError):
        ClassificationUpdate(document_role=bad)


def test_confirm_writes_every_metadata_field():
    doc = _doc("doc_w", "w.pdf", "sha-w")
    classification.confirm(
        doc, doc_type="Datasheet", discipline="Mechanical", doc_class="DATASHEET",
        subject_ids=[], confirmed_by=_user(),
        metadata={
            "document_role": "CONTRACTOR_SUBMITTAL",
            "document_number": "DS-001", "title": "Pump datasheet",
            "revision": "B", "effective_date": "2026-01-01",
            "project": "Alpha", "contractor_vendor": "Acme",
            "equipment_type": "pump", "service": "crude",
            "transmittal_number": "T-9", "superseded_by": None,
        },
        equipment_tags=["pump", "centrifugal"])
    row = classification.of_document(doc)
    assert row["document_role"] == "CONTRACTOR_SUBMITTAL"
    assert row["document_number"] == "DS-001"
    assert row["title"] == "Pump datasheet"
    assert row["revision"] == "B"
    assert row["project"] == "Alpha"
    assert row["equipment_type"] == "pump"
    assert row["equipment_tags"] == ["pump", "centrifugal"]
    assert row["superseded_by"] is None
    # The pre-existing fields still work.
    assert row["doc_type"] == "Datasheet"
    assert row["confirmed"] is True


def test_metadata_is_replaced_not_merged():
    """A PUT sends the whole record, so a cleared field is actually cleared."""
    doc = _doc("doc_r", "r.pdf", "sha-r")
    full = {name: "x" for name in classification.METADATA_FIELDS}
    full["document_role"] = "COMPANY_STANDARD"
    classification.confirm(doc, doc_type=None, discipline=None, doc_class=None,
                           subject_ids=[], confirmed_by=_user(), metadata=full)
    assert classification.of_document(doc)["title"] == "x"
    cleared = {name: None for name in classification.METADATA_FIELDS}
    classification.confirm(doc, doc_type=None, discipline=None, doc_class=None,
                           subject_ids=[], confirmed_by=_user(), metadata=cleared)
    row = classification.of_document(doc)
    assert row["title"] is None
    assert row["document_role"] is None


def test_a_caller_that_passes_no_metadata_leaves_it_untouched():
    """Every pre-phase-2 caller keeps behaving exactly as before."""
    doc = _doc("doc_u", "u.pdf", "sha-u")
    classification.confirm(doc, doc_type=None, discipline=None, doc_class=None,
                           subject_ids=[], confirmed_by=_user(),
                           metadata={"document_role": "CRS_TEMPLATE",
                                     **{n: None for n in classification.METADATA_FIELDS
                                        if n != "document_role"}})
    # A later call with metadata=None must not wipe the role.
    classification.confirm(doc, doc_type="Drawing", discipline=None,
                           doc_class=None, subject_ids=[], confirmed_by=_user())
    row = classification.of_document(doc)
    assert row["document_role"] == "CRS_TEMPLATE"
    assert row["doc_type"] == "Drawing"


# ------------------------------------------------- the intersection rule

def test_a_role_filter_narrows_within_the_callers_grants():
    mine = _doc("doc_mine", "mine.pdf", "sha-m")
    other = _doc("doc_other", "other.pdf", "sha-o")
    _classify(mine, document_role="COMPANY_STANDARD")
    _classify(other, document_role="COMPANY_STANDARD")
    scope = _scope(mine)                      # granted ONE of the two
    narrowed, applied = classification.restrict(
        scope, classification.ScopeFilter(roles=("COMPANY_STANDARD",)))
    assert applied is True
    assert narrowed.allowed_document_ids == frozenset({mine})


def test_a_filter_can_never_widen_a_scope():
    """THE INVARIANT. M11 turns the & into a |; this fails."""
    mine = _doc("doc_mine", "mine.pdf", "sha-m")
    secret = _doc("doc_secret", "secret.pdf", "sha-s")
    _classify(mine, document_role="CONTRACTOR_SUBMITTAL", project="Alpha")
    _classify(secret, document_role="CONTRACTOR_SUBMITTAL", project="Alpha")
    scope = _scope(mine)
    for wanted in (
        classification.ScopeFilter(roles=("CONTRACTOR_SUBMITTAL",)),
        classification.ScopeFilter(projects=("Alpha",)),
        classification.ScopeFilter(roles=("CONTRACTOR_SUBMITTAL",),
                                   projects=("Alpha",)),
    ):
        narrowed, _ = classification.restrict(scope, wanted)
        assert secret not in narrowed.allowed_document_ids
        assert narrowed.allowed_document_ids <= scope.allowed_document_ids


def test_a_filter_that_matches_nothing_returns_nothing():
    """Fail closed. M14 makes it fall back to the whole corpus; this fails."""
    mine = _doc("doc_mine", "mine.pdf", "sha-m")
    _classify(mine, document_role="COMPANY_STANDARD")
    scope = _scope(mine)
    narrowed, applied = classification.restrict(
        scope, classification.ScopeFilter(roles=("CRS_TEMPLATE",)))
    assert applied is True
    assert narrowed.allowed_document_ids == frozenset()


def test_two_filter_axes_intersect_rather_than_union():
    a = _doc("doc_a", "a.pdf", "sha-a")
    b = _doc("doc_b", "b.pdf", "sha-b")
    _classify(a, document_role="COMPANY_STANDARD", equipment_type="pump")
    _classify(b, document_role="COMPANY_STANDARD", equipment_type="valve")
    scope = _scope(a, b)
    narrowed, _ = classification.restrict(scope, classification.ScopeFilter(
        roles=("COMPANY_STANDARD",), equipment_types=("pump",)))
    # "both", never "either".
    assert narrowed.allowed_document_ids == frozenset({a})


def test_filtering_does_not_change_who_the_caller_is():
    doc = _doc("doc_x", "x.pdf", "sha-x")
    _classify(doc, project="Alpha")
    scope = access.AccessScope(user_id="u9", allowed_document_ids=frozenset({doc}),
                               capabilities=frozenset({"admin"}))
    narrowed, _ = classification.restrict(
        scope, classification.ScopeFilter(projects=("Alpha",)))
    assert narrowed.user_id == "u9"
    assert narrowed.capabilities == frozenset({"admin"})


def test_an_unrestricted_scope_is_still_narrowed_by_a_filter():
    """`unrestricted` must not become a way to skip the filter."""
    a = _doc("doc_a", "a.pdf", "sha-a")
    b = _doc("doc_b", "b.pdf", "sha-b")
    _classify(a, document_role="COMPANY_STANDARD")
    _classify(b, document_role="CRS_TEMPLATE")
    scope = access.AccessScope(user_id=None, allowed_document_ids=frozenset({a, b}),
                               unrestricted=True)
    narrowed, applied = classification.restrict(
        scope, classification.ScopeFilter(roles=("COMPANY_STANDARD",)))
    assert applied is True
    assert narrowed.allowed_document_ids == frozenset({a})
    assert narrowed.unrestricted is True     # narrowing the search, not the caller


# --------------------------------------------------------- over the route

@pytest.fixture()
def client(monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    with TestClient(app) as c:
        yield c


def test_the_documents_route_filters_by_role(client):
    sub = _doc("doc_sub", "sub.pdf", "sha-sub")
    std = _doc("doc_std", "std.pdf", "sha-std")
    _classify(sub, document_role="CONTRACTOR_SUBMITTAL")
    _classify(std, document_role="COMPANY_STANDARD")
    body = client.get("/api/documents", params={"document_role": "COMPANY_STANDARD"}).json()
    assert [d["id"] for d in body] == [std]
    assert body[0]["document_role"] == "COMPANY_STANDARD"


def test_the_documents_route_rejects_an_unknown_role(client):
    r = client.get("/api/documents", params={"document_role": "BANANA"})
    assert r.status_code == 422


def test_the_documents_route_reports_review_status_as_not_reviewed(client):
    _doc("doc_n", "n.pdf", "sha-n")
    body = client.get("/api/documents").json()
    # A real answer, not a null, and never invented as "completed".
    assert body[0]["review_status"] == "not_reviewed"


def test_review_status_follows_the_latest_run(client):
    import uuid

    from app import submittal_review
    doc = _doc("doc_rs", "rs.pdf", "sha-rs")
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for ts, status in (("2026-09-18T00:00:00Z", "failed"),
                           ("2026-09-18T01:00:00Z", "completed")):
            conn.execute("""INSERT INTO review_runs
                (id,submittal_document_id,status,created_at,updated_at)
                VALUES (?,?,?,?,?)""",
                (str(uuid.uuid4()), doc, status, ts, ts))
    body = client.get("/api/documents").json()
    row = next(d for d in body if d["id"] == doc)
    assert row["review_status"] == "completed"


def test_review_status_is_not_a_stored_column():
    """It is DERIVED. A column would be a second home for the same claim."""
    columns = [r[1] for r in db.connect().execute(
        "PRAGMA table_info(document_classification)")]
    assert "review_status" not in columns
    columns = [r[1] for r in db.connect().execute("PRAGMA table_info(documents)")]
    assert "review_status" not in columns


def test_a_filtered_listing_never_shows_a_document_outside_the_scope(client, monkeypatch):
    """The route-level form of the intersection rule."""
    mine = _doc("doc_mine", "mine.pdf", "sha-m")
    secret = _doc("doc_secret", "secret.pdf", "sha-s")
    _classify(mine, project="Alpha")
    _classify(secret, project="Alpha")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: "u1")
    monkeypatch.setattr(access, "scope_for_user", lambda uid: _scope(mine))
    body = client.get("/api/documents", params={"project": "Alpha"}).json()
    ids = [d["id"] for d in body]
    assert ids == [mine]
    assert secret not in ids
