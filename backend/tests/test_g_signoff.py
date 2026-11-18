# ruff: noqa: F811
"""The engineer's sign-off of a general review and the contractor copy (order 14). Invented papers only."""

from __future__ import annotations

import hashlib
import re
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import access, db
from app import aim_review_contractor as C
from app import aim_review_gate as G
from app import aim_review_signoff as SO
from app.main import app
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, _sheet, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

CODE = "Approved with Comments"


def client(*allowed: str, admin: bool = True) -> TestClient:
    """A signed-in user who may read `allowed`; a super user (the admin capability) unless `admin=False`."""
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng",
        allowed_document_ids=frozenset(allowed),
        capabilities=frozenset({access.ADMIN_CAPABILITY}) if admin else frozenset(),
    )
    return TestClient(app)


BASE = f"/api/reviews/papers/{PAPER}/general"


@pytest.fixture
def world(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run()


def _page(c):
    r = c.get(f"{BASE}?run_id={RUN}")
    assert r.status_code == 200, r.text
    return r.json()


def _decide(c, n, state="accept", **kw):
    r = c.post(
        f"{BASE}/decision", json={"run_id": RUN, "comment": n, "state": state, **kw}
    )
    assert r.status_code == 200, r.text


def _sign(c, code=CODE, **kw):
    return c.post(f"{BASE}/signoff", json={"run_id": RUN, "review_code": code, **kw})


def _accept_all(c):
    r = c.post(f"{BASE}/accept-rest", json={"run_id": RUN})
    assert r.status_code == 200, r.text
    return r.json()


def _contractor(c):
    return c.get(f"{BASE}/sheet?run_id={RUN}&copy=contractor")


def _rows(table):
    with db.connect() as conn:
        return conn.execute(f"SELECT * FROM {table}").fetchall()


def _cells(data: bytes):
    wb = load_workbook(BytesIO(data))
    return [
        (ws.title, v)
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for v in row
        if v is not None
    ]


def test_a_review_that_is_not_signed_says_so_and_lists_what_is_undecided(world):
    s = _page(client(PAPER, BOOK))["signoff"]
    assert (
        s["state"] == "not_signed"
        and s["undecided_count"] == 3
        and s["can_sign"] is False
        and s["signed"] is None
    )
    assert (
        set(s["codes"])
        >= {"Approved", "Approved with Comments", "Manual Review Required"}
        and len(s["codes"]) == 4
    )
    assert all(u["part"] == "comment" and u["title"] for u in s["undecided"])


def test_signing_with_undecided_comments_is_refused_naming_them_and_writes_nothing(
    world,
):
    c = client(PAPER, BOOK)
    _decide(c, 1)
    r = _sign(c)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert "not decided yet" in d["message"] and [b["n"] for b in d["blockers"]] == [
        3,
        5,
    ]
    assert _rows("aim_signoffs") == [] and _rows("aim_issued_copies") == []


def test_accept_rest_makes_one_decision_row_per_undecided_comment(world):
    c = client(PAPER, BOOK)
    _decide(c, 1, "reject", reason="The paper states it on page 3.")
    assert _accept_all(c)["accepted"] == 2
    rows = _rows("aim_comment_decisions")
    assert [r["state"] for r in rows] == ["reject", "accept", "accept"]
    assert _accept_all(c)["accepted"] == 0  # nothing left


def test_the_review_code_is_the_engineers_own_choice_of_the_four_labels(world):
    c = client(PAPER, BOOK)
    _accept_all(c)
    r = _sign(c, "Looks fine")
    assert (
        r.status_code == 409
        and "review code is one of" in r.json()["detail"]["message"]
    )
    assert _rows("aim_signoffs") == []


def test_sign_off_records_who_when_and_keeps_the_contractor_copy_byte_for_byte(world):
    c = client(PAPER, BOOK)
    _accept_all(c)
    r = _sign(c, statement="Checked against the datasheet.")
    assert r.status_code == 200, r.text
    s = r.json()["signoff"]
    assert (
        s["state"] == "signed"
        and s["signed"]["code"] == CODE
        and s["signed"]["statement"] == "Checked against the datasheet."
    )
    assert s["signed"]["by"] and s["signed"]["at"]
    cs = s["signed"]["copy_statement"]
    n = s["signed"]["counts"]
    assert cs.startswith(
        f"{n['points']} points reviewed, {n['in_file']} in this file, {n['not_issued']} not issued"
    )
    (issued,) = _rows("aim_issued_copies")
    one, two = _contractor(c), _contractor(c)
    assert one.status_code == 200 and one.content == two.content == bytes(
        issued["content"]
    )
    assert hashlib.sha256(one.content).hexdigest() == issued["sha256"]
    summary = _sheet(client(PAPER, BOOK).get(f"{BASE}/sheet?run_id={RUN}"))["Summary"]
    text = "\n".join(
        str(v) for r in summary.iter_rows(values_only=True) for v in r if v
    )
    assert "Signed by" in text and CODE in text


def test_no_contractor_copy_before_sign_off(world):
    r = _contractor(client(PAPER, BOOK))
    assert (
        r.status_code == 409
        and r.json()["detail"]["message"] == G.NO_CONTRACTOR_COPY_WORDS
    )


def test_a_decision_after_the_sign_off_flips_it_to_changed_and_the_copy_is_refused_until_signed_again(
    world,
):
    c = client(PAPER, BOOK)
    _accept_all(c)
    _sign(c)
    _decide(c, 1, "reject", reason="Not a real problem on this valve.")
    s = _page(c)["signoff"]
    assert s["state"] == "changed" and s["signed"]["code"] == CODE
    r = _contractor(c)
    assert r.status_code == 409 and r.json()["detail"]["message"] == SO.CHANGED_WORDS
    assert _sign(c).status_code == 200
    assert (
        _page(c)["signoff"]["state"] == "signed" and _contractor(c).status_code == 200
    )
    assert (
        len(_rows("aim_signoffs")) == 2 and len(_rows("aim_issued_copies")) == 2
    )  # the older ones stay


def test_a_rejected_comment_is_left_out_of_the_contractor_copy_and_the_points_add_up(
    world,
):
    c = client(PAPER, BOOK)
    _decide(c, 1, "reject", reason="The paper states it on page 3.")
    _accept_all(c)
    _sign(c)
    data = _contractor(c).content
    wb = load_workbook(BytesIO(data))
    first = "\n".join(
        str(v) for r in wb[C.SUMMARY].iter_rows(values_only=True) for v in r if v
    )
    m = re.search(
        r"(\d+) points reviewed, (\d+) in this file, (\d+) not issued: (.*)", first
    )
    assert m and int(m[2]) + int(m[3]) == int(m[1]) == 6  # M + K = N, in points
    assert "rejected by the engineer" in m[4]
    rows = [
        r
        for r in wb[C.COMMENTS].iter_rows(min_row=C.HEADER_ROW + 1, values_only=True)
        if r[0] is not None
    ]
    assert len(rows) == 2  # three comments, one rejected
    assert sum(r[C.HEADERS.index("Places")] for r in rows) == int(m[2])


def test_an_edited_comment_carries_the_engineers_text_in_the_contractor_copy_and_the_ai_text_in_the_team_file(
    world,
):
    c = client(PAPER, BOOK)
    original = _page(c)["comments"][0]["we_ask"]
    _decide(c, 1, "edit", text="State the design pressure of the test item.")
    _accept_all(c)
    _sign(c)
    contractor = [v for t, v in _cells(_contractor(c).content) if t == C.COMMENTS]
    assert (
        "State the design pressure of the test item." in contractor
        and original not in contractor
    )
    team = load_workbook(BytesIO(c.get(f"{BASE}/sheet?run_id={RUN}").content))
    assert any(
        original == v
        for row in team["Comments"].iter_rows(values_only=True)
        for v in row
    )


def test_the_contractor_copy_carries_no_internal_text_in_any_cell(world):
    c = client(PAPER, BOOK)
    _accept_all(c)
    _sign(c)
    cells = _cells(_contractor(c).content)
    assert cells
    for sheet, v in cells:
        for pattern, what in C.INTERNAL:
            assert not re.search(pattern, str(v)), (sheet, what)
    headers = {v for sheet, v in cells if sheet == C.COMMENTS}
    assert (
        "Status" not in headers
        and "Lines" not in headers
        and "Shown label" not in headers
    )  # no technical column
    assert next(v for s, v in cells if s == C.SUMMARY).startswith(
        "Comment sheet: signed off by "
    )


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("See document doc_abc123def456 for it.", "a document id"),
        ("The AI judged this one.", "the AI mark"),
        ("Claude read the paper.", "a model name"),
        ("note reference_checked: Schedule C", "a recorded code note"),
        ("per run 5d03d807-0f5d-42a7-ba5e-1c8875aabbcc", "a run id"),
        (G.AI_MARK, "the AI mark"),
    ],
)
def test_an_edited_text_that_carries_internal_text_stops_the_sign_off_naming_the_comment(
    world, text, what
):
    c = client(PAPER, BOOK)
    _decide(c, 1, "edit", text=text)
    _accept_all(c)
    r = _sign(c)
    assert r.status_code == 409
    blockers = r.json()["detail"]["blockers"]
    assert any(b["n"] == 1 and what in b["why"] for b in blockers), blockers
    assert _rows("aim_signoffs") == [] and _rows("aim_issued_copies") == []


def test_a_card_that_names_a_book_the_signer_may_not_read_is_not_issued_until_edited_or_rejected(
    world,
):
    c = client(PAPER, BOOK)
    _decide(
        c,
        1,
        "edit",
        text="Compare with a rule book you may not open before it goes out.",
    )
    _accept_all(c)
    r = _sign(c)
    assert r.status_code == 409 and any(
        "cannot name" in b["why"] for b in r.json()["detail"]["blockers"]
    )
    _decide(
        c, 1, "reject", reason="Rests on a book the contractor must not be told about."
    )
    assert _sign(c).status_code == 200


def test_the_rows_must_add_up_to_the_statement_or_the_copy_is_refused(world):
    counts = {
        "points": 6,
        "in_file": 4,
        "not_issued": 2,
        "reasons": {"x": 2},
        "comments": 1,
        "confirmations": 0,
    }
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = C.COMMENTS
    for i, h in enumerate(C.HEADERS, 1):
        ws.cell(row=C.HEADER_ROW, column=i, value=h)
    ws.cell(row=C.HEADER_ROW + 1, column=1, value=1)
    ws.cell(
        row=C.HEADER_ROW + 1, column=C.HEADERS.index("Places") + 1, value=3
    )  # the rows say 3 points, the statement says 4
    out = BytesIO()
    wb.save(out)
    with pytest.raises(C.NotIssuable):
        C.read_back(out.getvalue(), counts)


def test_a_review_that_stopped_early_cannot_be_signed(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(status="stopped")
    c = client(PAPER, BOOK)
    _accept_all(c)
    r = _sign(c)
    assert r.status_code == 409 and "stopped early" in r.json()["detail"]["message"]


def test_only_a_signed_in_user_who_may_read_the_paper_can_sign_or_accept_the_rest(
    world,
):
    assert _sign(client(BOOK)).status_code == 404  # may not read the paper
    assert (
        client(BOOK).post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code
        == 404
    )
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({PAPER}), unrestricted=True
    )
    nobody = TestClient(app)
    assert (
        _sign(nobody).status_code == 401
        and nobody.post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code == 401
    )
    assert _rows("aim_signoffs") == [] and _rows("aim_comment_decisions") == []


def test_the_audit_names_the_sign_off_by_ids_and_counts_only(world):
    with db.connect() as conn, conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at) VALUES ('eng', 'eng@example.test', 'Eng', 'x', '2026-11-18T00:00:00+00:00')"
        )
    c = client(PAPER, BOOK)
    _decide(c, 1, "edit", text="A private engineering remark.")
    _accept_all(c)
    _sign(c, statement="A private statement.")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT action, detail, actor_user_id, actor_username FROM audit_events WHERE action IN ('general_review_signed','general_comments_accepted_rest')"
        ).fetchall()
    assert {r["action"] for r in rows} == {
        "general_review_signed",
        "general_comments_accepted_rest",
    }
    assert all("private" not in r["detail"] for r in rows)
    assert all(
        r["actor_user_id"] == "eng" and r["actor_username"] == "eng@example.test"
        for r in rows
    )


def test_only_a_super_user_can_sign_or_fetch_the_contractor_copy(world):
    """Deciding is any signed-in reader; the sign-off and the contractor copy need the admin capability AND may-read (until the owner
    names engineer accounts). A non-admin gets 403 with a plain sentence; a caller who may not read the paper still gets 404."""
    plain = client(PAPER, BOOK, admin=False)
    assert (
        plain.post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code == 200
    )  # deciding is open to a reader
    r = _sign(plain)
    assert (
        r.status_code == 403
        and "Only a super user can sign this review for now." in r.text
    )
    assert (
        _rows("aim_signoffs") == [] and _rows("aim_issued_copies") == []
    )  # nothing was written
    assert _page(plain)["signoff"]["may_sign"] is False
    assert "super user" in _page(plain)["signoff"]["may_sign_words"]
    boss = client(PAPER, BOOK)
    assert _page(boss)["signoff"]["may_sign"] is True
    assert _sign(boss).status_code == 200
    assert _contractor(boss).status_code == 200
    r = _contractor(
        client(PAPER, BOOK, admin=False)
    )  # signed, but this reader is not a super user
    assert r.status_code == 403 and "super user" in r.text
    assert (
        _sign(client(BOOK)).status_code == 404
    )  # an admin who may not read the paper: not found, never 403
    assert _contractor(client(BOOK)).status_code == 404
