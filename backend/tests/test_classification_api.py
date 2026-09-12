"""The routes, the filter, and who is allowed to do what.

THREE PROPERTIES THIS FILE EXISTS FOR:

  * THE FILTER NARROWS AND NEVER WIDENS. Applied by intersecting with the
    caller's own grants before retrieval, so a subject whose documents they
    may not read yields nothing rather than a leak - and yields it without
    saying whether any such document exists.
  * ABSENT SCOPE REPRODUCES TODAY'S BEHAVIOUR EXACTLY. Asserted by running
    the same request with and without the parameter and comparing results,
    not by reading the code.
  * AUTHORITY. Every user may filter and see the vocabulary; only the admin
    capability may confirm or change. A discipline the caller cannot read
    stays VISIBLE with a zero count.

Nothing depends on the client's register or the real corpus.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import access, auth, classification, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-07T00:00:00Z"
REVISION = "rev-API"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    # A real signing key, because the admin gate needs a real bearer token -
    # see `as_admin`. Generated per test, never a fixture value: there is no
    # demo credential in this repository to leak.
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
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


def _document(doc_id: str, filename: str, role_id: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (doc_id, filename, f"sha-{doc_id}", 1, f"/tmp/{doc_id}", NOW))
        if role_id:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                "role_id,permission,granted_at,granted_by)"
                " VALUES (?,?,'read',?,NULL)", (doc_id, role_id, NOW))


def _subject(name: str, kind: str = "system") -> str:
    sub_id = classification.new_id("sub")
    with connect() as conn:
        conn.execute(
            "INSERT INTO subjects (id,name,kind,register_revision)"
            " VALUES (?,?,?,?)", (sub_id, name, kind, REVISION))
    return sub_id


def _register(title: str, doc_type: str, discipline: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO deliverables_register (id,doc_type,discipline,vendor,"
            "title,register_revision,imported_at) VALUES (?,?,?,NULL,?,?,?)",
            (classification.new_id("reg"), doc_type, discipline, title,
             REVISION, NOW))


@pytest.fixture
def corpus(monkeypatch):
    """Two disciplines, three documents, one register, and identities.

    `proc_user` holds Process (AXENS) and may read doc_hot and doc_fire.
    `civil_user` holds Civil and may read doc_civil only.
    `admin_user` holds the admin capability.
    """
    process = _user("proc_user", "Process (AXENS)")
    civil = _user("civil_user", "Civil")
    admin_role = _user("admin_user", "admin", "capability")

    _document("doc_hot", "Hot Oil System P&ID.pdf", process)
    _document("doc_fire", "Firewater Ring Main Layout.pdf", process)
    _document("doc_civil", "Substation Foundation Drawing.pdf", civil)

    # EVERY DOCUMENT IS ALSO GRANTED TO THE ADMIN CAPABILITY, because that is
    # what production does: `admin.grant_on_upload` gives every new document
    # the admin capability precisely so a document no administrator can see
    # cannot exist. Granting it here makes the fixture match.
    #
    # The first version of this fixture did not, and the PUT tests failed 404 -
    # correctly. The route asks TWO questions, deliberately: does the caller
    # hold the admin capability, and may they read this document. An admin
    # with no grant fails the second, and that is the right answer rather than
    # something to work around by skipping the scope check for admins.
    for doc_id in ("doc_hot", "doc_fire", "doc_civil"):
        with connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                "role_id,permission,granted_at,granted_by)"
                " VALUES (?,?,'read',?,NULL)", (doc_id, admin_role, NOW))

    _register("Hot Oil System P&ID", "Drawing", "Process (AXENS)")
    _register("Substation Foundation Drawing", "Drawing", "Civil")
    ids = {
        "hot_oil": _subject("hot oil"),
        "firewater": _subject("firewater"),
        "substation": _subject("substation"),
        "pw": _subject(classification.PROJECT_WIDE, "project_wide"),
    }

    classification.write_suggestion("doc_hot", classification.Suggestion(
        doc_type="Drawing", discipline="Process (AXENS)", doc_class="P&ID",
        subject_ids=(ids["hot_oil"],)), suggested_by="register")
    classification.write_suggestion("doc_fire", classification.Suggestion(
        doc_type="Drawing", discipline="Process (AXENS)", doc_class="PLOT PLAN",
        subject_ids=(ids["firewater"],)), suggested_by="pattern")
    classification.write_suggestion("doc_civil", classification.Suggestion(
        doc_type="Drawing", discipline="Civil", doc_class=None,
        subject_ids=(ids["substation"],)), suggested_by="register")

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda r: r.headers.get("x-test-user") or None)
    return ids


def as_user(user: str) -> dict:
    """Identity for the SCOPE, via the test resolver."""
    return {"x-test-user": user}


def as_admin(user: str) -> dict:
    """Identity for the ADMIN GATE, which needs a real bearer token.

    `admin.current_admin` resolves identity through `auth.resolve_user_id` and
    nothing else - the same one-way boundary the whole admin surface uses - so
    the scope resolver a test installs does not reach it. That is the design
    working: the admin gate cannot be satisfied by a header a test happens to
    set, and this had to issue a real token to get past it. Both headers are
    sent, because the route asks both questions.
    """
    return {"x-test-user": user,
            "Authorization": f"Bearer {auth.issue_token(user)}"}


# ---------------------------------------------------------- the vocabulary


def test_every_user_sees_the_whole_vocabulary(corpus):
    """USE THE FILTER, SEE THE VOCABULARY: EVERY user. The Process engineer
    filtering IS the feature."""
    client = TestClient(app)
    body = client.get("/api/classification/vocabulary",
                      headers=as_user("proc_user")).json()

    assert body["register_revision"] == REVISION
    assert set(body["types"]) == {"Drawing"}
    assert sorted(body["disciplines"]) == ["Civil", "Process (AXENS)"]
    assert classification.PROJECT_WIDE in {s["name"] for s in body["subjects"]}


def test_a_discipline_the_caller_cannot_read_stays_visible(corpus):
    """DO NOT HIDE IT. Discipline names are project structure, not evidence
    that a document exists. Hiding one teaches a user the system is broken
    rather than that they need access."""
    client = TestClient(app)
    body = client.get("/api/classification/vocabulary",
                      headers=as_user("proc_user")).json()

    # proc_user cannot read any Civil document...
    assert access.scope_for_user("proc_user").may_read("doc_civil") is False
    # ...and Civil is still listed.
    assert "Civil" in body["disciplines"]


def test_a_discipline_the_caller_cannot_read_counts_zero_in_scope(corpus):
    """VISIBLE, WITH A ZERO. The vocabulary is not scoped; the COUNTS are."""
    client = TestClient(app)
    body = client.get("/api/classification/coverage",
                      headers=as_user("proc_user")).json()

    by_discipline = {r["discipline"]: r for r in body["by_discipline"]}
    assert by_discipline["Civil"]["uploaded"] == 0, by_discipline["Civil"]
    # ...and the register denominator is still shown, because that is project
    # structure rather than a statement about this caller's documents.
    assert by_discipline["Civil"]["in_register"] == 1
    assert by_discipline["Process (AXENS)"]["uploaded"] == 2


def test_in_register_is_null_when_no_register_is_loaded(monkeypatch):
    """The frontend must never compute a percentage against a denominator it
    was not handed. A null cannot be divided by; a zero invites it."""
    _user("solo", "Piping")
    _document("doc_x", "x.pdf", "role_Piping")
    classification.write_suggestion("doc_x", classification.Suggestion(
        doc_type="Drawing", discipline="Piping"), suggested_by="pattern")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda r: r.headers.get("x-test-user") or None)

    body = TestClient(app).get("/api/classification/coverage",
                               headers=as_user("solo")).json()
    assert body["register_loaded"] is False
    assert body["register_revision"] is None
    for row in body["by_discipline"]:
        assert row["in_register"] is None, row


def test_the_needs_classification_count_is_scoped(corpus):
    client = TestClient(app)
    proc = client.get("/api/classification/vocabulary",
                      headers=as_user("proc_user")).json()
    civil = client.get("/api/classification/vocabulary",
                       headers=as_user("civil_user")).json()
    # Two unconfirmed for proc_user, one for civil_user - each counts only
    # what they may read.
    assert proc["needs_classification"] == 2, proc["needs_classification"]
    assert civil["needs_classification"] == 1, civil["needs_classification"]


def test_disciplines_spanned_is_reported_per_subject(corpus):
    """The measurement that made subject the comparison axis, on the caller's
    own corpus rather than taken on trust."""
    body = TestClient(app).get("/api/classification/coverage",
                               headers=as_user("admin_user")).json()
    spans = {r["subject"]: r["disciplines_spanned"] for r in body["by_subject"]}
    assert spans, body["by_subject"]
    assert all(v >= 1 for v in spans.values()), spans


# --------------------------------------------------------------- authority


def test_a_non_admin_put_is_refused(corpus):
    """CONFIRM OR CHANGE REQUIRES THE ADMIN CAPABILITY. A wrong
    classification misroutes searches for everyone, not just the person who
    set it, so it needs a role that answers for everyone."""
    client = TestClient(app)
    response = client.put(
        "/api/documents/doc_hot/classification",
        headers=as_user("proc_user"),
        json={"doc_type": "Document", "discipline": "Civil",
              "doc_class": None, "subject_ids": []})

    assert response.status_code == 404, response.text
    # ...and nothing changed.
    row = classification.of_document("doc_hot")
    assert row["confirmed_by"] is None
    assert row["discipline"] == "Process (AXENS)"


def test_an_admin_put_confirms_and_records_who(corpus):
    client = TestClient(app)
    response = client.put(
        "/api/documents/doc_hot/classification",
        headers=as_admin("admin_user"),
        json={"doc_type": "Drawing", "discipline": "Process (AXENS)",
              "doc_class": "P&ID",
              "subject_ids": [corpus["hot_oil"], corpus["pw"]]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmed"] is True
    assert body["confirmed_by"] == "admin_user"
    assert body["confirmed_at"].endswith("Z")
    assert sorted(s["id"] for s in body["subjects"]) == sorted(
        [corpus["hot_oil"], corpus["pw"]])


def test_a_confirm_replaces_the_subject_set_rather_than_merging(corpus):
    """An administrator removing a subject must be able to remove it. Merging
    would leave a document permanently attached to a comparison it does not
    belong in."""
    client = TestClient(app)
    client.put("/api/documents/doc_fire/classification",
               headers=as_admin("admin_user"),
               json={"doc_type": "Drawing", "discipline": "Process (AXENS)",
                     "doc_class": None, "subject_ids": [corpus["substation"]]})

    row = classification.of_document("doc_fire")
    assert [s["id"] for s in row["subjects"]] == [corpus["substation"]], (
        "the previously suggested firewater subject was merged rather than "
        "replaced")


def test_a_document_outside_scope_is_404_on_read_and_write(corpus):
    """The same answer every read path gives, and the reason it is 404 rather
    than 403: a 403 confirms the document exists."""
    client = TestClient(app)
    assert client.get("/api/documents/doc_civil/classification",
                      headers=as_user("proc_user")).status_code == 404
    assert client.put("/api/documents/doc_civil/classification",
                      headers=as_user("proc_user"),
                      json={"subject_ids": []}).status_code == 404


def test_an_in_scope_unclassified_document_reads_as_empty_not_404(corpus):
    """"In scope but never classified" is an answer, and it is not the same
    answer as "you may not see this"."""
    _document("doc_new", "unclassified.pdf", "role_Process (AXENS)")
    body = TestClient(app).get("/api/documents/doc_new/classification",
                               headers=as_user("proc_user"))
    assert body.status_code == 200, body.text
    row = body.json()
    assert row["doc_type"] is None and row["discipline"] is None
    assert row["confirmed"] is False
    assert row["subjects"] == []


# ------------------------------------------------------------- the filter


def _search(client, user: str, **params):
    return client.get("/api/search",
                      params={"q": "system", "limit": 10, **params},
                      headers=as_user(user))


def test_an_absent_scope_reproduces_todays_behaviour(corpus):
    """BYTE FOR BYTE, asserted by comparison rather than by reading the code.

    The same request with no filter parameters must return exactly what it
    returned before classification existed - the hit list, the counts and the
    mode - so adding the feature is provably additive.
    """
    client = TestClient(app)
    plain = _search(client, "proc_user").json()
    with_empty = _search(client, "proc_user", types=[], disciplines=[],
                         subject_ids=[]).json()

    for key in ("hits", "total", "mode", "keyword_candidates",
                "dense_candidates", "reranked"):
        assert plain[key] == with_empty[key], key
    # The echo says it did not apply, rather than being absent.
    assert plain["applied_scope"]["applied"] is False
    assert plain["applied_scope"]["types"] == []


def test_the_filter_narrows(corpus):
    client = TestClient(app)
    unfiltered = _search(client, "proc_user").json()
    filtered = _search(client, "proc_user",
                       subject_ids=[corpus["firewater"]]).json()

    assert filtered["applied_scope"]["applied"] is True
    assert filtered["applied_scope"]["documents_in_scope"] == 1
    assert unfiltered["applied_scope"]["documents_in_scope"] == 2
    got = {h["document_id"] for h in filtered["hits"]}
    assert got <= {"doc_fire"}, got


def test_the_filter_never_widens(corpus):
    """A subject whose documents the caller may NOT read yields nothing - not
    a leak, and not a fallback to the whole corpus.

    This is where the mechanism deliberately differs from
    `analysis.narrow_to_named`, which treats "nothing resolved" as "do not
    narrow" because a misspelt document name is better answered broadly. A
    filter is the opposite: the caller ASKED for substations, so matching
    nothing must return nothing. Falling back would hand them results they
    had explicitly excluded, indistinguishably from the filter working.
    """
    client = TestClient(app)
    filtered = _search(client, "proc_user",
                       subject_ids=[corpus["substation"]]).json()

    assert filtered["applied_scope"]["applied"] is True
    assert filtered["applied_scope"]["documents_in_scope"] == 0
    assert filtered["hits"] == []
    # And it says nothing about whether such a document exists.
    assert "doc_civil" not in filtered["applied_scope"]["subject_ids"]
    assert str(filtered).count("doc_civil") == 0


def test_a_discipline_filter_cannot_reach_another_disciplines_documents(corpus):
    client = TestClient(app)
    filtered = _search(client, "proc_user", disciplines=["Civil"]).json()
    assert filtered["hits"] == []
    assert filtered["applied_scope"]["documents_in_scope"] == 0


def test_a_type_filter_narrows_within_what_the_caller_may_read(corpus):
    client = TestClient(app)
    filtered = _search(client, "proc_user", types=["Drawing"]).json()
    assert filtered["applied_scope"]["documents_in_scope"] == 2
    filtered = _search(client, "proc_user", types=["Document"]).json()
    assert filtered["applied_scope"]["documents_in_scope"] == 0


def test_an_unknown_subject_id_yields_nothing_rather_than_everything(corpus):
    """FAIL CLOSED. A stale id from a bookmarked filter must not silently
    become an unfiltered search."""
    client = TestClient(app)
    filtered = _search(client, "proc_user", subject_ids=["sub_does_not_exist"]).json()
    assert filtered["applied_scope"]["applied"] is True
    assert filtered["applied_scope"]["documents_in_scope"] == 0
    assert filtered["hits"] == []


# ------------------------------------------- the echo, on search and analysis


def test_search_echoes_the_applied_scope(corpus):
    body = _search(TestClient(app), "proc_user",
                   types=["Drawing"], subject_ids=[corpus["hot_oil"]]).json()
    echo = body["applied_scope"]
    assert echo["applied"] is True
    assert echo["types"] == ["Drawing"]
    assert echo["subject_ids"] == [corpus["hot_oil"]]
    assert echo["documents_in_scope"] == 1


def test_analysis_gaps_echoes_the_applied_scope(corpus):
    """`gaps` makes no model call, so it is the analysis engine that can be
    asserted without a model being up."""
    response = TestClient(app).post(
        "/api/analysis/gaps",
        headers=as_user("proc_user"),
        json={"question": "compare the systems", "limit": 8,
              "scope": {"types": [], "disciplines": ["Process (AXENS)"],
                        "subject_ids": []}})

    assert response.status_code == 200, response.text
    echo = response.json()["applied_scope"]
    assert echo["applied"] is True
    assert echo["disciplines"] == ["Process (AXENS)"]
    assert echo["documents_in_scope"] == 2


def test_analysis_gaps_with_no_scope_reports_not_applied(corpus):
    response = TestClient(app).post(
        "/api/analysis/gaps", headers=as_user("proc_user"),
        json={"question": "compare the systems", "limit": 8})
    assert response.status_code == 200, response.text
    echo = response.json()["applied_scope"]
    assert echo["applied"] is False
    assert echo["documents_in_scope"] == 2


def test_the_narrowed_scope_is_what_reaches_the_analysis_engine(corpus,
                                                               monkeypatch):
    """THE FILTER MUST REACH RETRIEVAL, NOT JUST THE ECHO.

    Asserted by capturing the scope the engine is actually handed, because the
    obvious assertion is vacuous here: these fixture documents carry no chunks,
    so `evidence_ledger` is empty whether the filter applied or not. The first
    version of this test asserted exactly that and PASSED against a mutation
    that echoed the filter while passing the unnarrowed scope to the engine -
    which is the one bug this test exists to catch.

    So the assertion is on the scope object itself: what the engine received
    must be the narrowed set, not the caller's whole grant.
    """
    from app import analysis as analysis_mod

    seen: list[frozenset] = []
    real = analysis_mod.gaps

    def spy(question, scope, **kwargs):
        seen.append(scope.allowed_document_ids)
        return real(question, scope, **kwargs)

    monkeypatch.setattr("app.main.analysis_mod.gaps", spy)

    response = TestClient(app).post(
        "/api/analysis/gaps", headers=as_user("proc_user"),
        json={"question": "compare the systems", "limit": 8,
              "scope": {"types": [], "disciplines": [],
                        "subject_ids": [corpus["firewater"]]}})

    assert response.status_code == 200, response.text
    assert seen, "the engine was never called"
    assert seen[0] == frozenset({"doc_fire"}), (
        f"the engine received {sorted(seen[0])} - the filter was echoed but "
        f"not applied to retrieval")
    assert response.json()["applied_scope"]["documents_in_scope"] == 1


def test_a_filter_matching_nothing_leaves_the_analysis_with_no_evidence(corpus):
    """The fail-closed direction, end to end: narrowed to a subject whose
    documents this caller may not read, the engine has nothing at all."""
    response = TestClient(app).post(
        "/api/analysis/gaps", headers=as_user("proc_user"),
        json={"question": "compare the systems", "limit": 8,
              "scope": {"types": [], "disciplines": [],
                        "subject_ids": [corpus["substation"]]}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied_scope"]["documents_in_scope"] == 0
    assert body["evidence_ledger"] == [], body["evidence_ledger"]


# ---------------------------------------------- the filter is not access


def test_filtering_changes_no_access_decision(corpus):
    """The filter narrows a SEARCH. It must not touch what the caller may
    read, before or after."""
    before = sorted(access.scope_for_user("proc_user").allowed_document_ids)
    _search(TestClient(app), "proc_user", subject_ids=[corpus["substation"]])
    after = sorted(access.scope_for_user("proc_user").allowed_document_ids)
    assert after == before == ["doc_fire", "doc_hot"], (before, after)


def test_the_narrowed_scope_keeps_the_callers_identity(corpus):
    """`restrict` returns a narrower scope, not a different caller. A filter
    changes WHAT IS SEARCHED and never WHO IS ASKING.

    ASSERTED ON A CALLER WHO ACTUALLY HOLDS A CAPABILITY. The first version
    used `proc_user`, who holds only a discipline role - so
    `capabilities == capabilities` was `frozenset() == frozenset()` and passed
    against a mutation that cleared them. A caller with nothing to lose cannot
    demonstrate that nothing was lost.
    """
    scope = access.scope_for_user("admin_user")
    assert scope.capabilities, "the fixture admin holds no capability"
    assert scope.is_admin

    wanted = classification.ScopeFilter(subject_ids=(corpus["firewater"],))
    narrowed, applied = classification.restrict(scope, wanted)

    assert applied is True
    assert narrowed.user_id == scope.user_id
    assert narrowed.capabilities == scope.capabilities
    assert narrowed.is_admin is True, (
        "narrowing a filter stripped the caller's admin capability - a filter "
        "changes what is searched, never who is asking")
    assert narrowed.unrestricted == scope.unrestricted
    assert narrowed.allowed_document_ids < scope.allowed_document_ids


def test_restrict_never_returns_an_id_the_scope_did_not_hold(corpus):
    """THE INTERSECTION, asserted directly and for every axis."""
    scope = access.scope_for_user("proc_user")
    for wanted in (
        classification.ScopeFilter(types=("Drawing",)),
        classification.ScopeFilter(disciplines=("Civil",)),
        classification.ScopeFilter(subject_ids=(corpus["substation"],)),
        classification.ScopeFilter(types=("Drawing",), disciplines=("Civil",)),
    ):
        narrowed, _applied = classification.restrict(scope, wanted)
        assert narrowed.allowed_document_ids <= scope.allowed_document_ids, wanted


# ------------------------------------------------- the ingest hook (stage 5)


def _pdf_bytes(text: str) -> bytes:
    """A one-page PDF whose first page carries `text`, built with fitz so the
    first-page read the hook performs has something real to find."""
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def test_an_upload_is_classified_by_suggestion_not_confirmed(corpus):
    """ONE HOOK COVERS BOTH INGEST PATHS - the manual upload route and the
    watched folder both come through `upload.ingest`, so this exercises both.

    SUGGESTION ONLY. `confirmed_by` stays NULL: confirming needs the admin
    capability, because a wrong classification misroutes searches for
    everyone.
    """
    import io as _io

    from app import upload as upload_mod

    row, _job, _dup = upload_mod.ingest(
        _io.BytesIO(_pdf_bytes("Firewater ring main for the substation")),
        "Hot Oil System P&ID.pdf")

    stored = classification.of_document(row["id"])
    assert stored is not None, "the ingest hook wrote nothing"
    # TIER 1: the title matched the register, so type and discipline are the
    # client's own.
    assert stored["doc_type"] == "Drawing"
    assert stored["discipline"] == "Process (AXENS)"
    assert stored["suggested_by"] == classification.SOURCE_REGISTER
    # ...and it is NOT confirmed.
    assert stored["confirmed_by"] is None
    assert stored["confirmed"] is False


def test_the_first_page_text_reaches_the_suggestion(corpus):
    """A drawing whose filename is a document number still says what it is
    about on its face, so the first page is read at upload time."""
    import io as _io

    from app import upload as upload_mod

    row, _job, _dup = upload_mod.ingest(
        _io.BytesIO(_pdf_bytes("FIREWATER RING MAIN - substation feeder")),
        "DWG-77219.pdf")

    stored = classification.of_document(row["id"])
    names = {s["name"] for s in stored["subjects"]}
    assert names == {"firewater", "substation"}, names
    # No register hit, so nothing was invented for type or discipline.
    assert stored["doc_type"] is None
    assert stored["discipline"] is None


def test_an_unmatched_upload_still_gets_a_row_so_the_queue_sees_it(corpus):
    """"No row" and "no match" would look identical to the UI. An
    unclassifiable document must appear in the needs-classification queue
    rather than being absent from it."""
    import io as _io

    from app import upload as upload_mod

    before = TestClient(app).get("/api/classification/vocabulary",
                                 headers=as_user("admin_user")
                                 ).json()["needs_classification"]

    row, _job, _dup = upload_mod.ingest(
        _io.BytesIO(_pdf_bytes("scanned page, no useful text")),
        "IMG_20260907_113244.pdf")

    stored = classification.of_document(row["id"])
    assert stored is not None
    assert stored["doc_type"] is None and stored["discipline"] is None
    assert stored["subjects"] == []
    assert stored["suggested_by"] == classification.SOURCE_NONE

    # NOT YET IN ANYONE'S QUEUE, and that is correct rather than a defect.
    # `upload.ingest` classifies but does not GRANT - `admin.grant_on_upload`
    # does, from the route and from the watcher, immediately after. Until then
    # the document is in no caller's scope, and `needs_classification` is
    # scoped because a count is a statement about documents.
    #
    # The first version of this test asserted the queue rose immediately and
    # failed. The count was right and the expectation was wrong, and the
    # ordering it exposed is worth pinning: a document ingested and never
    # granted is invisible to every queue, which is the orphan state #79
    # exists to prevent.
    mid = TestClient(app).get("/api/classification/vocabulary",
                              headers=as_user("admin_user")
                              ).json()["needs_classification"]
    assert mid == before, (before, mid)

    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_role_access (document_id,role_id,"
            "permission,granted_at,granted_by) VALUES (?,?,'read',?,NULL)",
            (row["id"], "role_admin", NOW))

    after = TestClient(app).get("/api/classification/vocabulary",
                                headers=as_user("admin_user")
                                ).json()["needs_classification"]
    assert after == before + 1, (before, after)


def test_a_failing_suggestion_never_fails_the_ingest(corpus, monkeypatch):
    """A document that failed to be classified is still a document. Losing an
    upload over a suggestion would trade the valuable thing for the cheap
    one."""
    import io as _io

    from app import upload as upload_mod

    def explode(*_a, **_k):
        raise RuntimeError("classification is broken")

    monkeypatch.setattr(classification, "suggest", explode)
    row, job_id, _dup = upload_mod.ingest(
        _io.BytesIO(_pdf_bytes("Hot oil")), "whatever.pdf")

    assert row["id"], "the ingest lost the document"
    assert job_id, "the ingest lost the extraction job"
    assert classification.of_document(row["id"]) is None


def test_existing_documents_are_not_back_classified(corpus):
    """Back-classifying the current corpus is a HUMAN-CONFIRMED step, not a
    side effect of deploying this. Documents that predate the feature keep
    whatever they had - here, nothing."""
    _document("doc_old", "Hot Oil System P&ID.pdf", "role_Process (AXENS)")
    # Its title WOULD match the register, and nothing ran over it.
    assert classification.of_document("doc_old") is None
