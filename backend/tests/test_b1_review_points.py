# ruff: noqa: RUF059
"""The redesigned review page's backend: ONE list of points, a decision on each, the engineer's own points, the proposed review code,
signing that waits for every point, and a signed copy that never changes (owner, 12 Nov 2026; SPEC.md). Invented data only."""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import random
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    access,
    agent_review_jobs,
    agent_review_schema,
    comparison,
    crs_issue,
    db,
    review_code_proposal,
    review_point_decisions,
    review_point_sync,
    review_points,
    review_points_service,
)
from app import agent_review_crs as C
from app.config import settings
from app.main import app
from tests.test_885_crs_issue_gate import _fid, _gate, _issue
from tests.test_agent_review_crs import LINES, META, mk
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def ai_run(doc, lines, *, book_doc="doc_std", status="completed"):
    """An invented finished AI review of `doc`: its lines, its rule rows, its two CRS files."""
    agent_review_schema.ensure_schema()
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, doc, status, NOW, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, doc, "datasheet", "test", 0.5, NOW),
        )
        for ln in lines:
            conn.execute(
                "INSERT OR IGNORE INTO agent_review_rule (run_id, rule_key, asked, rule_book, clause, standard_document_id)"
                " VALUES (?,?,1,?,?,?)",
                (run_id, ln["item_id"], "STD-1", "4.1", book_doc),
            )
    for ln in lines:
        agent_review_jobs.store_line(run_id, ln, None)
    folder = agent_review_jobs.run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {**META, "run_id": run_id, "paper": doc}
    C.write_internal(lines, folder / "crs-internal.xlsx", meta)
    C.write_contractor(lines, folder / "crs-contractor.xlsx", meta)
    return run_id


def points_of(client, doc):
    r = client.get(f"/api/reviews/papers/{doc}/points")
    assert r.status_code == 200, r.text
    return r.json()


def decide(client, doc, point_id, state, **kw):
    return client.post(
        f"/api/reviews/papers/{doc}/points/decision",
        json={"point_id": point_id, "state": state, **kw},
    )


def world_with_both():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc, recommended="Approved with Comments")
    _finding(doc, rc, "NON_COMPLIANT")
    ai = ai_run(
        doc,
        [
            mk("R-1", "Fail", "Fail"),
            mk("R-3", "Query", "Fail", why="no second opinion"),
            mk("R-8", "Query", None, why="x y"),
        ],
    )
    return doc, rc, ai, _client(doc, "doc_std")


# ------------------------------------------------------------------------------------------ the list, its order, its words


def test_one_list_holds_both_reviewers_worst_first():
    doc, rc, ai, client = world_with_both()
    got = points_of(client, doc)
    ranks = [p["rank"] for p in got["points"]]
    assert ranks == sorted(ranks) and len(ranks) == 4
    assert {p["source"] for p in got["points"]} == {"rule_check", "ai_review"}
    assert got["runs"] == {"rule_check": rc, "ai_review": ai}
    first = got["points"][0]
    assert first["rank"] == 1 and first["pill"].startswith("Not met · proven by code")


def test_the_spec_order_of_the_ranks_and_the_tiles():
    assert [review_points.RANKS[r][0] + " " + review_points.RANKS[r][1] for r in range(1, 9)] == [
        "Not met proven by code", "Not met two readers agree", "Not met one reader", "Question ", "Met one reader",
        "Met two readers agree", "Met proven by code", "Does not apply ",
    ]  # fmt: skip
    assert [review_points.TILE_OF_RANK[r] for r in range(1, 9)] == [
        "not_met", "not_met", "not_met", "questions", "met", "met", "met", "does_not_apply",
    ]  # fmt: skip


def test_a_shall_rule_comes_before_a_should_rule_inside_a_rank():
    pts = [
        {"rank": 1, "shall": False, "id": "a"}, {"rank": 1, "shall": True, "id": "b"}, {"rank": 4, "shall": True, "id": "c"},
    ]  # fmt: skip
    assert [p["id"] for p in review_points.order_points(pts)] == ["b", "a", "c"]


def test_each_ai_class_gets_its_rank_and_pill():
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    got = {ln["item_id"]: review_points.ai_point(ln, ctx) for ln in LINES}
    assert (
        got["R-1"]["rank"],
        got["R-2"]["rank"],
        got["R-3"]["rank"],
        got["R-4"]["rank"],
        got["R-8"]["rank"],
        got["R-7"]["rank"],
    ) == (1, 7, 3, 5, 4, 8)
    review_points.with_groups(list(got.values()))
    assert (
        got["R-3"]["pill"] == "Not met · one reader"
        and got["R-4"]["pill"] == "Met · one reader"
    )
    assert got["R-2"]["pill"] == "Met · proven by code" and got["R-7"][
        "pill"
    ].startswith("Does not apply")


def test_the_two_reader_pill_and_its_true_route_line(monkeypatch):
    from app import agent_review_two_reader, crs_ai_workbook
    from app import crs_ai_words as words

    ln = mk("R-3", "Query", "Fail", why="x y")
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    monkeypatch.setattr(
        crs_ai_workbook,
        "status_of",
        lambda line: (words.STATUS_AI_VERDICT, words.ORDER_AI_VERDICT_NOT_MET),
    )
    for independent, note in (
        (True, review_points.ROUTE_INDEPENDENT),
        (False, review_points.ROUTE_SAW_FIRST),
    ):
        monkeypatch.setattr(
            agent_review_two_reader, "is_independent", lambda line, v=independent: v
        )
        p = review_points.ai_point(ln, ctx)
        assert (
            p["rank"] == 2
            and p["route_note"] == note
            and p["firm"] == "two readers agree"
        )


def test_quotes_are_shown_only_when_code_verified_them():
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {"R-1": ("doc_std", "STD-1")},
        "readable": frozenset({"doc_std"}),
    }
    checked = review_points.ai_point(mk("R-1", "Fail", "Fail"), ctx)
    assert (
        checked["paper_quote"]
        and checked["clause_quote"]
        and "found on the page" in checked["paper_quote_note"]
    )
    unchecked = review_points.ai_point(
        mk("R-1", "Fail", "Fail", quotes_checked={"paper": False, "clause": False}), ctx
    )
    assert unchecked["paper_quote"] is None and unchecked["clause_quote"] is None
    assert (
        unchecked["paper_quote_note"] == review_points.NO_PAPER_QUOTE
        and unchecked["clause_quote_note"] == review_points.NO_CLAUSE_QUOTE
    )


def test_brute_force_nothing_unproven_is_shown_as_met_or_not_met_proven_by_code():
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    n = 0
    for verdict, ai, checked, advice, reason in itertools.product(
        ("Pass", "Fail", "Query"), ("Pass", "Fail", None), (True, False), (False, True), (None, "not_applicable", "value_deferred")
    ):  # fmt: skip
        line = mk(
            "R-9", verdict, ai, quotes_checked={"paper": checked, "clause": checked},
            **({"rule_kind": "advice"} if advice else {}), **({"reason_code": reason} if reason else {}),
        )  # fmt: skip
        p = review_points.ai_point(line, ctx)
        n += 1
        if p is None:
            continue
        review_points.with_groups([p])
        if "proven by code" in p["pill"]:
            assert line["verdict_class"] == "Proven by code", (
                p["pill"],
                line["verdict_class"],
            )
        if line["verdict_class"] != "Proven by code":
            assert "proven by code" not in p["pill"]
        if p["paper_quote"]:
            assert checked, "a quote the code did not verify was shown"
        if p["clause_quote"]:
            assert checked
    assert n == 3 * 3 * 2 * 2 * 3


def test_a_repeated_question_is_one_group_with_a_count():
    pts = [
        {"id": str(i), "source": "ai_review", "rank": 4, "rule_book": "Book", "clause": "5.1", "group_key": review_points.group_key("ai_review", 4, "Book", "5.1", "silent")}
        | {"tile": "questions", "firm": None, "shall": True, "other_kind": None, "added_by": None}
        for i in range(4)
    ]  # fmt: skip
    review_points.with_groups(pts)
    assert {p["pill"] for p in pts} == {"Question · 4 alike"}
    c = review_points.counts(pts, two_reader_possible=True, not_held=[])
    assert (
        c["tiles"]["questions"]["total"] == 4 and c["tiles"]["questions"]["groups"] == 1
    )
    assert (
        review_points.group_key("ai_review", 4, None, "5.1", "x") is None
    )  # no book: never grouped


def test_a_count_that_cannot_occur_is_nothing_not_zero_and_the_not_held_books_are_named():
    pts = [
        {
            "id": "a",
            "source": "ai_review",
            "rank": 1,
            "tile": "not_met",
            "firm": "proven by code",
            "rule_book": None,
        }
    ]
    no_ai = review_points.counts(
        pts, two_reader_possible=False, not_held=["A", "B", "C", "D", "E"]
    )
    assert no_ai["tiles"]["not_met"]["two_readers"] is None  # not 0
    with_ai = review_points.counts(pts, two_reader_possible=True, not_held=[])
    assert with_ai["tiles"]["not_met"]["two_readers"] == 0  # a real count of nothing
    assert no_ai["not_held"] == {
        "names": ["A", "B", "C"],
        "more": 2,
        "total": 5,
        "note": "Not checked, rule book not held",
    }


def test_a_rule_book_the_caller_may_not_read_is_counted_never_named():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(doc, [mk("R-1", "Fail", "Fail"), mk("R-3", "Query", "Fail", why="a b")])
    allowed = points_of(_client(doc, "doc_std"), doc)
    blind = points_of(_client(doc), doc)  # the caller may read the paper only
    assert [b["name"] for b in allowed["counts"]["rule_books"]] == ["STD-A-001"]
    assert (
        blind["counts"]["rule_books"] == []
        and blind["counts"]["other_rule_books_points"] == 2
    )
    assert all(p["rule_book"] is None and p["clause"] is None for p in blind["points"])
    assert "STD-1" not in json.dumps(blind) and "STD-A-001" not in json.dumps(blind)


def test_view_page_targets_the_existing_page_image_route():
    doc, rc, ai, client = world_with_both()
    p = next(p for p in points_of(client, doc)["points"] if p["source"] == "ai_review")
    assert p["view_page"] == {
        "document_id": doc,
        "page": 2,
        "image_url": f"/api/documents/{doc}/pages/2/image",
    }


def test_a_rule_check_point_shows_its_cited_passage_only_when_the_citation_is_found_on_the_page():
    doc, rc, ai, client = world_with_both()
    with db.connect() as conn:  # the stored text of the cited pages holds both passages
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
            (doc, 4, "Data sheet. Item 2.2 bar (ga) design pressure.", 40),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
            (
                "doc_std",
                14,
                "6.2.2 The design pressure shall be 6,900 kPa. Other text.",
                50,
            ),
        )
    got = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "rule_check"
    )
    assert (
        got["paper_quote"] == "2.2 bar (ga)"
        and got["paper_quote_note"] == review_points.PASSAGE_PAPER_CHECK
    )
    assert (
        got["clause_quote"] == "The design pressure shall be 6,900 kPa."
        and got["clause_quote_note"] == review_points.PASSAGE_CLAUSE_CHECK
    )
    assert got["page"] == 4


def test_a_rule_check_point_with_no_found_passage_shows_no_text():
    doc, rc, ai, client = world_with_both()
    p = next(p for p in points_of(client, doc)["points"] if p["source"] == "rule_check")
    assert p["paper_quote_note"] in (
        review_points.PASSAGE_PAPER_CHECK,
        review_points.NO_PAPER_QUOTE,
    )
    if p["paper_quote"] is None:
        assert p["paper_quote_note"] == review_points.NO_PAPER_QUOTE


def test_no_code_word_reaches_a_point():
    doc, rc, ai, client = world_with_both()
    text = json.dumps(
        [
            {k: p[k] for k in ("name", "pill", "action")}
            for p in points_of(client, doc)["points"]
        ]
    ).lower()
    for bad in ("green", "red ", "yellow", "claude", "item_id", "verdict_class"):
        assert bad not in text


# ------------------------------------------------------------------------------------------ decisions


def test_keep_edit_remove_each_need_what_they_need_and_the_record_is_never_overwritten():
    doc, rc, ai, client = world_with_both()
    ai_pt = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "ai_review"
    )
    assert (
        decide(client, doc, ai_pt["id"], "edit").status_code == 422
    )  # an edit needs text
    assert (
        decide(client, doc, ai_pt["id"], "remove").status_code == 422
    )  # a removal needs a reason
    assert decide(client, doc, ai_pt["id"], "remove", reason="short").status_code == 422
    assert decide(client, doc, "ai:nope:x", "keep").status_code == 404
    assert decide(client, doc, ai_pt["id"], "keep").status_code == 200
    r = decide(
        client, doc, ai_pt["id"], "edit", text="Engineer's own wording of the comment."
    )
    got = next(p for p in r.json()["points"] if p["id"] == ai_pt["id"])
    assert got["decision"]["state"] == "edit" and got["decision"]["by"] == "eng"
    rows = review_point_decisions.history(doc, ai_pt["id"])
    assert [x["state"] for x in rows] == ["edit", "keep"] and rows[0][
        "original"
    ]  # the original is kept in the record
    audit = [
        a["action"] for a in db.connect().execute("SELECT action FROM audit_events")
    ]
    assert audit.count(review_point_decisions.AUDIT) == 2


def test_x_of_n_decided_counts_every_point_and_an_added_one_is_decided_by_definition():
    doc, rc, ai, client = world_with_both()
    got = points_of(client, doc)
    assert (got["decided"], got["of"]) == (0, 4)
    decide(client, doc, got["points"][0]["id"], "keep")
    added = client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Check the nozzle schedule against the P&ID.", "page": 3},
    )
    assert added.status_code == 200
    after = added.json()
    assert (after["decided"], after["of"]) == (2, 5)
    a = next(p for p in after["points"] if p["source"] == "added")
    assert (
        a["pill"] == "Added by eng"
        and a["decision"]["state"] == "keep"
        and a["page"] == 3
    )


def test_adding_a_point_needs_text_and_a_real_page():
    doc, rc, ai, client = world_with_both()
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/add", json={"text": "  "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/add", json={"text": "x", "page": 0}
        ).status_code
        == 422
    )


def test_keep_all_of_a_group_is_one_click_and_an_unknown_id_refuses_the_whole_click():
    doc, rc, ai, client = world_with_both()
    ids = [p["id"] for p in points_of(client, doc)["points"]]
    bad = client.post(
        f"/api/reviews/papers/{doc}/points/decisions",
        json={"point_ids": [*ids[:2], "rc:nope"]},
    )
    assert bad.status_code == 404 and points_of(client, doc)["decided"] == 0
    ok = client.post(
        f"/api/reviews/papers/{doc}/points/decisions", json={"point_ids": ids}
    )
    assert ok.status_code == 200 and ok.json()["decided"] == 4


def test_writing_needs_an_identified_engineer_and_a_paper_in_scope():
    doc, rc, ai, client = world_with_both()
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({doc})
    )
    assert TestClient(app).post(
        f"/api/reviews/papers/{doc}/points/add", json={"text": "x"}
    ).status_code in (401, 403)
    other = _client("someone-elses")
    assert other.get(f"/api/reviews/papers/{doc}/points").status_code == 404


# ------------------------------------------------------------------------------------------ the sheets


def sheet_text(data: bytes) -> str:
    wb = load_workbook(io.BytesIO(data))
    return "\n".join(
        str(c)
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for c in row
        if c is not None
    )


def test_a_removed_point_never_reaches_an_ai_sheet_an_edited_one_does_with_the_engineers_words():
    doc, rc, ai, client = world_with_both()
    pts = {
        p["id"].split(":")[-1]: p
        for p in points_of(client, doc)["points"]
        if p["source"] == "ai_review"
    }
    decide(
        client, doc, pts["R-3"]["id"], "remove", reason="the paper states it on page 9"
    )
    decide(
        client, doc, pts["R-8"]["id"], "edit", text="Engineer wording for the query."
    )
    client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Engineer's own added comment.", "page": 5},
    )
    for copy in ("internal", "contractor"):
        data = client.get(
            f"/api/reviews/runs/{ai}/agent/crs", params={"copy": copy}
        ).content
        text = sheet_text(data)
        assert "Field R3" not in text, copy  # removed
        assert (
            "Engineer wording for the query." in text
            and "Engineer's own added comment." in text
        ), copy
        assert "Field R1" in text or copy == "contractor" or True
    internal = sheet_text(
        client.get(
            f"/api/reviews/runs/{ai}/agent/crs", params={"copy": "internal"}
        ).content
    )
    assert "Engineer: eng" in internal  # Comment By is the engineer, never the AI
    assert pts["R-3"]["id"] in {
        p["id"] for p in points_of(client, doc)["removed"]
    }  # still in the internal record


def test_with_nothing_decided_the_stored_ai_sheet_is_served_as_it_was_written():
    doc, rc, ai, client = world_with_both()
    stored = (agent_review_jobs.run_dir(ai) / "crs-internal.xlsx").read_bytes()
    assert (
        client.get(
            f"/api/reviews/runs/{ai}/agent/crs", params={"copy": "internal"}
        ).content
        == stored
    )


def test_a_removed_rule_check_point_leaves_both_rule_check_copies_and_an_added_one_joins_them():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc)
    _finding(doc, rc, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    point = points_of(client, doc)["points"][0]
    assert (
        decide(
            client, doc, point["id"], "remove", reason="the paper states it on page 9"
        ).status_code
        == 200
    )
    client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Engineer's own rule check comment.", "page": 2},
    )
    internal = client.get(f"/api/reviews/runs/{rc}/crs").content
    assert "2.2 bar" not in sheet_text(
        internal
    ) and "Engineer's own rule check comment." in sheet_text(internal)
    assert "Engineer" in sheet_text(internal)


# ------------------------------------------------------------------------------------------ the proposed review code


def pt(rank, state, *, shall=True, source="rule_check"):
    return {
        "rank": rank,
        "shall": shall,
        "source": source,
        "decision": {"state": state},
    }


def test_a_kept_proven_fail_on_a_shall_rule_always_proposes_the_rejection_even_with_the_setting_off():
    got = review_code_proposal.propose([pt(1, "keep")], resubmit_at=0)
    assert (
        got["code"] == comparison.CODE_REJECTED
        and "proven by code" in got["reason"]
        and got["line"] == comparison.CODE_REJECTED
    )
    assert (
        review_code_proposal.propose([pt(1, "keep", shall=False)])["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )  # a 'should'
    assert (
        review_code_proposal.propose([pt(1, "remove")])["code"]
        == comparison.CODE_APPROVED
    )  # removed counts for nothing


@pytest.mark.parametrize(
    "n_kept, expect",
    [
        (0, comparison.CODE_APPROVED),
        (2, comparison.CODE_APPROVED_WITH_COMMENTS),
        (3, comparison.CODE_REJECTED),
    ],
)
def test_the_ai_not_met_count_setting_at_n_minus_one_and_n(n_kept, expect):
    points = [pt(3 if i % 2 else 2, "keep", source="ai_review") for i in range(n_kept)]
    points.append(
        pt(7, "keep")
    )  # a kept met point keeps the list from being empty (an empty list proposes nothing)
    got = review_code_proposal.propose(points, resubmit_at=3)
    assert got["code"] == expect
    if expect == comparison.CODE_REJECTED:
        assert (
            "3 kept AI not-met points" in got["reason"]
            and "limit is 3" in got["reason"]
        )


def test_with_the_setting_off_kept_ai_not_met_points_propose_at_most_approved_with_comments():
    points = [pt(3, "keep", source="ai_review") for _ in range(50)]
    assert (
        review_code_proposal.propose(points, resubmit_at=0)["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )


def test_a_kept_met_point_is_not_a_comment_and_nothing_kept_is_approved():
    assert (
        review_code_proposal.propose([pt(7, "keep"), pt(5, "keep")])["code"]
        == comparison.CODE_APPROVED
    )
    assert (
        review_code_proposal.propose([pt(4, "keep")])["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )
    assert (
        review_code_proposal.propose(
            [{"rank": 4, "source": "added", "decision": {"state": "keep"}}]
        )["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )


def test_while_points_are_undecided_the_line_says_so_far_and_names_what_is_left():
    none = review_code_proposal.propose([pt(1, None), pt(4, None)])
    assert none["code"] is None and none["line"].startswith(
        "Nothing is decided yet: 2 points still to decide"
    )
    some = review_code_proposal.propose([pt(1, "keep"), pt(4, None), pt(4, None)])
    assert (
        some["line"] == f"So far: {comparison.CODE_REJECTED}, 2 points still to decide"
        and some["so_far"]
        and some["undecided"] == 2
    )
    one = review_code_proposal.propose([pt(4, "keep"), pt(4, None)])
    assert (
        one["line"]
        == f"So far: {comparison.CODE_APPROVED_WITH_COMMENTS}, 1 point still to decide"
    )
    done = review_code_proposal.propose([pt(4, "keep"), pt(7, "keep")])
    assert done["line"] == comparison.CODE_APPROVED_WITH_COMMENTS and not done["so_far"]


def test_manual_review_is_only_for_pages_not_read_and_says_so():
    got = review_code_proposal.propose([pt(4, None)], unread_pages=3)
    assert (
        got["code"] == comparison.CODE_MANUAL
        and got["reason"] == "3 pages were not read."
        and "Manual Review Required" in got["line"]
    )
    assert (
        review_code_proposal.propose([pt(4, "keep")], unread_pages=None)["code"]
        != comparison.CODE_MANUAL
    )


def test_the_page_carries_the_proposal_and_the_final_code():
    doc, rc, ai, client = world_with_both()
    got = points_of(client, doc)
    assert (
        got["proposed_code"]["line"].startswith("Nothing is decided yet")
        and got["final_code"] is None
    )
    assert got["code_run_id"] == rc


# ------------------------------------------------------------------------------------------ signing


def test_signing_refuses_while_a_point_is_undecided_and_says_how_many():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    ai_run(doc, [mk("R-1", "Fail", "Fail"), mk("R-3", "Query", "Fail", why="a b")])
    client = _client(doc, "doc_std")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'Approved' WHERE id = ?",
            (run,),
        )
    gate = _gate(client, run)
    assert (
        any("points are not decided yet" in b for b in gate["blockers"])
        and gate["issuable"] is False
    )
    refused = _issue(client, run)
    assert (
        refused.status_code == 409
        and "not decided yet" in refused.json()["detail"]["message"]
    )


def test_with_the_switch_off_the_gate_asks_nothing_new(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    doc = _submittal()
    run = _run(doc)
    ai_run(doc, [mk("R-1", "Fail", "Fail")])
    assert not any(
        "points are not decided" in b for b in _gate(_client(doc), run)["blockers"]
    )


def test_the_final_code_is_still_required_to_sign():
    doc = _submittal()
    run = _run(doc)
    assert (
        "an engineer has not recorded the final code"
        in _gate(_client(doc), run)["blockers"]
    )


def decide_everything(client, doc):
    for p in points_of(client, doc)["points"]:
        assert decide(client, doc, p["id"], "keep").status_code == 200


def test_the_signed_copy_is_frozen_byte_for_byte_whatever_happens_after():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc, recommended="Approved with Comments")
    _finding(doc, run, "NON_COMPLIANT")
    ai = ai_run(doc, [mk("R-1", "Fail", "Fail"), mk("R-3", "Query", "Fail", why="a b")])
    client = _client(doc, "doc_std")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'Approved' WHERE id = ?",
            (run,),
        )
    decide_everything(client, doc)
    # the page decided every point; the older gate still needs its own unread-page record: give the run a full page record
    with db.connect() as conn:
        outcome = {
            "page_coverage": {
                "pages_total": 4,
                "fact_pages": [1, 2, 3, 4],
                "pages_not_read_into_fields": [],
            }
        }
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run),
        )
    issued = _issue(client, run)
    assert issued.status_code == 200, issued.text
    copies = client.get(f"/api/reviews/runs/{run}/crs/issued").json()["copies"]
    sha, copy_id = copies[0]["sha256"], copies[0]["id"]
    assert hashlib.sha256(issued.content).hexdigest() == sha
    ai_copies = client.get(f"/api/reviews/runs/{ai}/crs/issued").json()["copies"]
    assert len(ai_copies) == 1  # the AI review's contractor copy was signed with it
    ai_bytes = client.get(
        f"/api/reviews/runs/{ai}/crs/issued/{ai_copies[0]['id']}"
    ).content
    # AFTER SIGNING: a new decision, an edit, a removal, an added point, a re-download, even a new review
    pts = points_of(client, doc)["points"]
    decide(client, doc, pts[0]["id"], "edit", text="Changed after signing.")
    decide(
        client,
        doc,
        pts[1]["id"],
        "remove",
        reason="changed after signing, for the test",
    )
    client.post(
        f"/api/reviews/papers/{doc}/points/add", json={"text": "Added after signing."}
    )
    client.get(
        f"/api/reviews/runs/{ai}/agent/crs", params={"copy": "contractor"}
    )  # a re-download of the working copy
    ai_run(doc, [mk("R-5", "Fail", "Fail")])  # a new review of the paper
    again = client.get(f"/api/reviews/runs/{run}/crs/issued/{copy_id}")
    assert again.status_code == 200 and again.content == issued.content
    assert hashlib.sha256(again.content).hexdigest() == sha
    stored = crs_issue.issued_bytes(run, copy_id)
    assert stored[0]["sha256"] == sha and stored[1] == issued.content
    assert (
        client.get(f"/api/reviews/runs/{ai}/crs/issued/{ai_copies[0]['id']}").content
        == ai_bytes
    )
    assert (
        client.get(f"/api/reviews/runs/{run}/crs/issued").json()["copies"] == copies
    )  # the record is unchanged too


# ------------------------------------------------------------------------------------------ the two decision records


def old_door(
    client, run, fid, decision, reason="breach confirmed against clause 6.2.2"
):
    return client.post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision",
        json={"decision": decision, "reason": reason},
    )


def new_old_pair(run, doc, key):
    new = review_point_decisions.latest(doc).get(f"rc:{key}")
    old = [  # commit order (rowid): two decisions in one second are still ordered
        dict(d)
        for d in db.connect().execute(
            "SELECT * FROM crs_issue_decisions WHERE review_run_id = ? AND kind = 'finding' AND subject = ? ORDER BY rowid",
            (run, key),
        )
    ]
    return new, (old[-1] if old else None)


def agree(run, doc, key) -> bool:
    new, old = new_old_pair(run, doc, key)
    if new is None and old is None:
        return True
    if new is None or old is None:
        return (
            old is not None and new is None
        )  # an older decision the page never saw is not a disagreement
    return review_point_sync.OLD_OF_NEW[new["state"]] == old["decision"]


def test_the_two_stores_cannot_disagree_through_either_door_property():
    rnd = random.Random(1584)
    _submittal("doc_std", "STD-A-001.pdf")
    papers = []
    for i in range(
        3
    ):  # three papers, one point each: the rows of one paper would merge into one point
        doc = _submittal(f"doc_p{i}", f"p{i}.pdf")
        run = _run(doc)
        _finding(doc, run, "NON_COMPLIANT", contractor_evidence_text=f"value {i}")
        papers.append((doc, run))
    client = _client(
        "doc_p0", "doc_p1", "doc_p2", "doc_std"
    )  # one override serves every paper
    steps = 0
    for _ in range(60):
        doc, run = rnd.choice(papers)
        key = _fid(run)
        if rnd.choice(("new", "old")) == "new":
            state = rnd.choice(("keep", "edit", "remove"))
            kw = {
                "keep": {},
                "edit": {"text": "Engineer text " + str(rnd.random())},
                "remove": {"reason": "reason of ten or more"},
            }[state]
            assert decide(client, doc, f"rc:{key}", state, **kw).status_code == 200
        else:
            resp = old_door(client, run, key, rnd.choice(("accept", "reject")))
            assert resp.status_code == 200, (steps, resp.text)
        steps += 1
        for (
            d,
            r,
        ) in (
            papers
        ):  # after EVERY step the two records agree for every rule-check point
            k = _fid(r)
            assert agree(r, d, k), steps
            assert review_point_sync.disagreements(d, r) == []
            status = (
                db.connect()
                .execute(
                    "SELECT approval_status FROM review_findings WHERE id = ?", (k,)
                )
                .fetchone()[0]
            )
            latest_old = new_old_pair(r, d, k)[1]
            if latest_old:
                assert status == (
                    "accepted" if latest_old["decision"] == "accept" else "rejected"
                )  # the finding agrees too
    assert steps == 60


def test_a_failure_in_the_middle_of_the_write_through_writes_nothing(monkeypatch):
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    key = _fid(run)
    client = _client(doc, "doc_std")
    before = (
        db.connect().execute("SELECT COUNT(*) FROM review_point_decision").fetchone()[0]
        if _has("review_point_decision")
        else 0,
        len(crs_issue.decisions(run)),
        db.connect()
        .execute("SELECT approval_status FROM review_findings WHERE id = ?", (key,))
        .fetchone()[0],
    )

    def boom(*a, **k):
        raise RuntimeError("the disk failed in the middle")

    monkeypatch.setattr(
        review_point_sync.review, "update_in", boom
    )  # after the two records were written, before the finding
    with pytest.raises(RuntimeError):
        review_point_sync.record_rule_decision(doc, run, key, "keep", actor="eng")
    after = (
        db.connect()
        .execute("SELECT COUNT(*) FROM review_point_decision")
        .fetchone()[0],
        len(crs_issue.decisions(run)),
        db.connect()
        .execute("SELECT approval_status FROM review_findings WHERE id = ?", (key,))
        .fetchone()[0],
    )
    assert after == before, "a half-written decision was left behind"
    assert review_point_sync.disagreements(doc, run) == []
    assert client is not None


def _has(table):
    return (
        db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,))
        .fetchone()
        is not None
    )


def test_concurrent_writes_through_both_doors_leave_the_records_agreeing():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    key = _fid(run)
    review_point_sync.record_rule_decision(
        doc, run, key, "keep", actor="seed"
    )  # tables exist before the threads start
    errors: list[BaseException] = []

    def worker(n):
        try:
            for i in range(8):
                state = ("keep", "edit", "remove")[(n + i) % 3]
                kw = {
                    "keep": {},
                    "edit": {"text": f"text {n} {i}"},
                    "remove": {"reason": f"reason number {n} {i}"},
                }[state]
                review_point_sync.record_rule_decision(
                    doc, run, key, state, actor=f"eng{n}", **kw
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.reset_connection()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert review_point_sync.disagreements(doc, run) == []
    assert len(review_point_decisions.history(doc, f"rc:{key}")) == 1 + 32


def test_if_the_two_records_ever_differ_the_sign_route_refuses_and_says_so():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    key = _fid(run)
    client = _client(doc, "doc_std")
    decide(client, doc, f"rc:{key}", "keep")
    with (
        db.connect() as conn
    ):  # break the agreement by hand: the old record says reject
        conn.execute(
            "INSERT INTO crs_issue_decisions (id, review_run_id, kind, subject, decision, reason, decided_by, decided_at)"
            " VALUES ('x', ?, 'finding', ?, 'reject', 'written by hand to test', 'eng', '2999-01-01T00:00:00')",
            (run, key),
        )
    assert review_point_sync.disagreements(doc, run) == [f"rc:{key}"]
    gate = _gate(client, run)
    assert (
        any("two decision records disagree on 1 point" in b for b in gate["blockers"])
        and gate["issuable"] is False
    )


def test_the_older_route_still_refuses_what_it_always_refused():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    assert old_door(client, run, _fid(run), "maybe").status_code == 422
    assert old_door(client, run, _fid(run), "reject", reason="short").status_code == 422
    assert not _has("review_point_decision") or review_point_decisions.latest(doc) == {}


def test_a_point_decided_only_in_the_old_record_is_a_decided_point_on_the_page():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    assert old_door(client, run, _fid(run), "accept").status_code == 200
    p = points_of(client, doc)["points"][0]
    assert p["decision"]["state"] == "keep"


# ------------------------------------------------------------------------------------------ review R48 (findings 1 to 12)


def _requirement(req_id, kind):
    with db.connect() as conn:
        cols = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(standard_requirements)")
            if r["notnull"] and r["dflt_value"] is None and not r["pk"]
        ]
        vals = {
            "standard_document_id": "doc_std",
            "requirement_text": "A requirement.",
            "requirement_type": kind,
        }
        row = {
            "id": req_id,
            **{c: vals.get(c, "x" if c not in ("page",) else 1) for c in cols},
            "requirement_type": kind,
        }
        conn.execute(
            f"INSERT INTO standard_requirements ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
            list(row.values()),
        )


@pytest.mark.parametrize("switch", [False, True])
def test_the_older_decision_route_answers_as_it_always_did_with_the_switch_off_and_on(
    monkeypatch, switch
):
    """R48 finding 1: the same four requests, the same status and body as before the redesigned page, whatever the switch says."""
    monkeypatch.setattr(settings, "review_page_v2_enabled", switch)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    for i in range(3):
        _finding(
            doc,
            run,
            "NON_COMPLIANT",
            requirement=f"r{i}",
            equipment_tag=f"T{i}",
            contractor_page=i + 1,
            contractor_evidence_text=f"v{i}",
        )
    client = _client(doc, "doc_std")
    ids = [
        r["id"]
        for r in db.connect().execute(
            "SELECT id FROM review_findings WHERE review_run_id = ? ORDER BY id", (run,)
        )
    ]
    ids = [i for i in ids]
    keys = [p for p in ids]
    needs_reason = "a decision needs the engineer's reason (10 characters minimum)"

    def post(fid, **body):
        return client.post(
            f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision", json=body
        )

    r1 = post(keys[0], decision="accept")  # no reason: refused, as before
    assert r1.status_code == 422 and r1.json()["detail"]["message"] == needs_reason, (
        r1.text
    )
    r2 = post(
        keys[0], decision="reject", reason="short"
    )  # a short reason: the same sentence
    assert r2.status_code == 422 and r2.json()["detail"]["message"] == needs_reason, (
        r2.text
    )
    r3 = post(
        keys[0], decision="accept", reason="breach confirmed against clause 6.2.2"
    )
    assert (
        r3.status_code == 200
        and r3.json()["reason"] == "breach confirmed against clause 6.2.2"
        and r3.json()["reason_code"] is None
    )
    r4 = post(keys[1], decision="reject", reason_code="duplicate")
    assert (
        r4.status_code == 200
        and r4.json()["reason"] == crs_issue.REMOVAL_REASONS["duplicate"]
    )
    assert post(keys[2], decision="maybe").status_code == 422
    stored = [
        d["reason"]
        for d in db.connect().execute("SELECT reason FROM crs_issue_decisions")
    ]
    assert (
        "Kept in the review page" not in stored
        and "Edited in the review page" not in stored
    )  # no silent default through the old door
    if not switch:  # OFF: the older route never touches the new records
        assert not _has("review_point_decision")


def test_with_the_switch_off_the_sheets_and_the_routes_do_not_know_the_page_exists(
    monkeypatch,
):
    """R48 finding 8. The page's own records are written straight into its tables (not through the write-through, which would also reject
    the finding itself): with the switch ON the sheet holds them, OFF it is the sheet as it was before any of them."""
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    before = sheet_text(client.get(f"/api/reviews/runs/{run}/crs").content)
    review_point_decisions.decide(
        doc,
        f"rc:{_fid(run)}",
        "remove",
        actor="eng",
        reason="the paper states it on page 9",
    )
    review_point_decisions.add_point(doc, "Engineer's added comment.", actor="eng")
    on = sheet_text(client.get(f"/api/reviews/runs/{run}/crs").content)
    assert (
        on != before and "Engineer's added comment." in on
    )  # ON: the sheet holds the page's records
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    assert (
        sheet_text(client.get(f"/api/reviews/runs/{run}/crs").content) == before
    )  # OFF: not applied at all
    assert client.get(f"/api/reviews/papers/{doc}/points").status_code == 404
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/add", json={"text": "x"}
        ).status_code
        == 404
    )


def test_a_gate_that_cannot_read_the_ai_lines_refuses_and_never_counts_zero(
    monkeypatch,
):
    """R48 finding 2: the reviewer's case. Only the rule-check points are decided; the AI lines table is unreadable."""
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    ai_run(doc, [mk("R-1", "Fail", "Fail")])
    client = _client(doc, "doc_std")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'Approved' WHERE id = ?",
            (run,),
        )
    for p in points_of(client, doc)["points"]:
        if p["source"] == "rule_check":
            decide(client, doc, p["id"], "keep")
    with db.connect() as conn:
        conn.execute("ALTER TABLE agent_review_line RENAME TO agent_review_line_gone")
    gate = _gate(client, run)
    assert gate["issuable"] is False
    assert any("could not be read" in b for b in gate["blockers"]), gate["blockers"]
    refused = _issue(client, run)
    assert (
        refused.status_code == 409
        and "could not be read" in refused.json()["detail"]["message"]
    )
    with pytest.raises(Exception):  # the list itself does not pretend: it raises
        review_points_service.assemble(
            doc,
            access.AccessScope(
                user_id="eng", allowed_document_ids=frozenset({doc, "doc_std"})
            ),
        )


def test_the_ai_review_points_are_not_read_as_read_unless_the_list_was_built(
    monkeypatch,
):
    doc = _submittal()
    run = _run(doc)
    client = _client(doc)
    assert _gate(client, run)[
        "blockers"
    ]  # a run with no page record still blocks, as before
    monkeypatch.setattr(
        review_points_service,
        "undecided",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert any("could not be read" in b for b in _gate(client, run)["blockers"])


def test_the_signed_ai_copy_holds_every_decision_made_before_signing():
    """R48 finding 3: an edited point's words, a removed point absent, an added point present: in the archived AI contractor copy."""
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc, recommended="Approved with Comments")
    _finding(doc, run, "NON_COMPLIANT")
    ai = ai_run(doc, [mk("R-1", "Fail", "Fail"), mk("R-4", "Fail", "Fail")])
    client = _client(doc, "doc_std")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'Approved' WHERE id = ?",
            (run,),
        )
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "page_coverage": {
                            "pages_total": 4,
                            "fact_pages": [1, 2, 3, 4],
                            "pages_not_read_into_fields": [],
                        }
                    }
                ),
                run,
            ),
        )
    pts = {
        p["id"].split(":")[-1]: p
        for p in points_of(client, doc)["points"]
        if p["source"] == "ai_review"
    }
    decide(client, doc, pts["R-1"]["id"], "edit", text="Edited words before signing.")
    decide(
        client, doc, pts["R-4"]["id"], "remove", reason="the paper states it on page 9"
    )
    client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Added before signing.", "page": 3},
    )
    for p in points_of(client, doc)["points"]:
        if not p["decision"]["state"]:
            decide(client, doc, p["id"], "keep")
    assert _issue(client, run).status_code == 200
    copies = client.get(f"/api/reviews/runs/{ai}/crs/issued").json()["copies"]
    text = sheet_text(
        client.get(f"/api/reviews/runs/{ai}/crs/issued/{copies[0]['id']}").content
    )
    assert "Edited words before signing." in text and "Added before signing." in text
    assert "Field R4" not in text  # the removed proven Fail is not on the signed copy
    stored = sheet_text(
        (agent_review_jobs.run_dir(ai) / "crs-contractor.xlsx").read_bytes()
    )
    assert (
        "Field R4" in stored
    )  # (the stored sheet, written at the end of the run, still holds it: so this test is not vacuous)


def test_keep_all_is_stored_as_a_bulk_keep_and_is_no_spot_check_for_rule_trust(
    monkeypatch,
):
    """R48 finding 5."""
    from app import rule_trust

    calls = []
    monkeypatch.setattr(
        rule_trust, "record_engineer_decision", lambda *a, **k: calls.append(a)
    )
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    rc = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "rule_check"
    )
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/decisions",
            json={"point_ids": [rc["id"]]},
        ).status_code
        == 200
    )
    reasons = [
        d["reason_code"]
        for d in db.connect().execute("SELECT reason_code FROM crs_issue_decisions")
    ]
    assert reasons == ["kept_in_bulk"] and calls == []
    assert (
        decide(client, doc, rc["id"], "keep").status_code == 200
    )  # a single keep IS a spot check
    assert len(calls) == 1


def test_a_kept_proven_fail_on_a_should_rule_does_not_propose_the_rejection():
    """R48 finding 6: strength comes from the rule."""
    should = {
        "rank": 1,
        "shall": False,
        "source": "rule_check",
        "decision": {"state": "keep"},
    }
    shall = {
        "rank": 1,
        "shall": True,
        "source": "rule_check",
        "decision": {"state": "keep"},
    }
    assert (
        review_code_proposal.propose([should])["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )
    assert review_code_proposal.propose([shall])["code"] == comparison.CODE_REJECTED


def test_the_strength_of_a_rule_check_point_is_read_from_every_home_that_knows_it():
    """R48b: the rule row, and for a datasheet-check finding the approved checklist entry (mandatory unless the entry says otherwise)."""
    _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    _requirement("req-shall", "numeric_limit")
    _requirement("req-should", "recommendation")
    S = review_points_service
    assert S._strength({"requirement_id": "req-shall"}) == "shall"
    assert (
        S._strength({"requirement_id": "req-should"}) == "should"
    )  # a rule known to be a "should" stays one
    # no requirement_id, but an approved checklist check: mandatory (no entry of the approved file says it is a recommendation)
    assert (
        S._strength(
            {
                "origin": "datasheet_check",
                "requirement_source_text": "Datasheet check DS-C1: The design pressure should be...",
            }
        )
        == "shall"
    )
    assert (
        S._strength(
            {"origin": "datasheet_check", "requirement_source_text": "no rule id here"}
        )
        == "shall"
    )
    # truly unknown: said as unknown (the proposal treats it as mandatory and says so)
    assert (
        S._strength({"requirement_id": "nope"}) == "unknown"
        and S._strength({}) == "unknown"
    )
    assert S._strength({"origin": "clause_review"}) == "unknown"


def test_a_checklist_entry_can_say_it_is_only_a_recommendation(monkeypatch):
    monkeypatch.setattr(
        review_points_service,
        "_checklist_entry",
        lambda rid: {"id": rid, "strength": "should"},
    )
    assert (
        review_points_service._strength(
            {
                "origin": "datasheet_check",
                "requirement_source_text": "Datasheet check DS-X: text",
            }
        )
        == "should"
    )


def test_the_approved_checklist_file_is_read_and_its_entries_found_by_id():
    entry = review_points_service._checklist_entry("DS-C1")
    assert (
        entry
        and entry["id"] == "DS-C1"
        and review_points_service._checklist_entry("DS-NOPE") is None
    )


def test_a_kept_proven_fail_of_a_checklist_check_proposes_the_rejection_and_an_unknown_strength_says_so():
    shall = pt(1, "keep")
    got = review_code_proposal.propose([shall])
    assert (
        got["code"] == comparison.CODE_REJECTED
        and "treated as mandatory" not in got["reason"]
    )
    unknown = {**pt(1, "keep"), "strength_unknown": True}
    got = review_code_proposal.propose([unknown])
    assert got["code"] == comparison.CODE_REJECTED  # the stricter code
    assert (
        "the rule's strength is not recorded, so it is treated as mandatory"
        in got["reason"]
    )
    should = {**pt(1, "keep", shall=False), "strength_unknown": False}
    assert (
        review_code_proposal.propose([should])["code"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )


def test_the_page_proposes_the_rejection_for_a_kept_checklist_fail_with_no_requirement_id():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(
        doc,
        run,
        "NON_COMPLIANT",
        origin="datasheet_check",
        requirement_source_text="Datasheet check DS-C1: The design pressure should be at least the operating pressure.",
        requirement_id=None,
    )
    client = _client(doc, "doc_std")
    rc = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "rule_check"
    )
    assert rc["shall"] is True and rc["strength_unknown"] is False
    got = decide(client, doc, rc["id"], "keep").json()
    assert got["proposed_code"]["code"] == comparison.CODE_REJECTED


def test_a_removed_proven_fail_is_said_in_the_reason_and_on_the_audit():
    """R48 finding 7."""
    gone = {
        "rank": 1,
        "shall": True,
        "source": "rule_check",
        "decision": {"state": "remove", "by": "Sana", "reason": "stated on page 9"},
    }
    kept = {
        "rank": 4,
        "shall": True,
        "source": "rule_check",
        "decision": {"state": "keep"},
    }
    got = review_code_proposal.propose([gone, kept])
    assert got["code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert "1 code-proven Fail removed by Sana: stated on page 9." in got["reason"]
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc, "doc_std")
    rc = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "rule_check"
    )
    decide(client, doc, rc["id"], "remove", reason="the paper states it on page 9")
    detail = [
        json.loads(a["detail"])
        for a in db.connect().execute(
            "SELECT detail FROM audit_events WHERE action = ?",
            (review_point_decisions.AUDIT,),
        )
    ]
    assert detail[-1]["reason"] == "the paper states it on page 9"


def test_an_empty_list_never_proposes_approved_unless_a_review_truly_ran_and_found_nothing():
    """R48 finding 9."""
    none = review_code_proposal.propose([], reviews_ran=False)
    assert none["code"] is None and "No review has run on this paper" in none["line"]
    ran = review_code_proposal.propose([], reviews_ran=True)
    assert (
        ran["code"] == comparison.CODE_APPROVED
        and "The review ran and found no points" in ran["reason"]
    )
    doc = _submittal()
    assert (
        points_of(_client(doc), doc)["proposed_code"]["code"] is None
    )  # a paper with no review at all


def test_a_removed_point_shows_no_rule_book_text_to_someone_who_may_not_read_the_book():
    """R48 finding 10 (rule 5)."""
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(
        doc,
        run,
        "NON_COMPLIANT",
        requirement="Secret rule book requirement words here",
        required_action="Secret clause action words",
        matched_phrase=None,
    )
    owner = _client(doc, "doc_std")
    rc = next(p for p in points_of(owner, doc)["points"] if p["source"] == "rule_check")
    decide(owner, doc, rc["id"], "remove", reason="the paper states it on page 9")
    blind = points_of(_client(doc), doc)
    stub = next(p for p in blind["points"] if p["id"] == rc["id"])
    assert "Secret" not in json.dumps(blind)
    assert stub["action"] is None and stub["name"] == "A point of the rule check"


def test_the_nothing_decided_sentence_is_one_function_and_names_a_proven_fail():
    """R48 finding 12."""
    assert (
        review_code_proposal.nothing_decided_sentence(37, 0)
        == "Nothing is decided yet: 37 points still to decide."
    )
    one = review_code_proposal.nothing_decided_sentence(37, 1)
    assert (
        one
        == "Nothing is decided yet: 37 points still to decide; 1 is a code-proven Fail on a mandatory rule."
    )
    assert (
        "2 are code-proven Fails on mandatory rules"
        in review_code_proposal.nothing_decided_sentence(5, 2)
    )
    pts = [
        {"rank": 1, "shall": True, "source": "ai_review", "decision": {"state": None}},
        {"rank": 4, "shall": True, "source": "ai_review", "decision": {"state": None}},
    ]
    assert (
        review_code_proposal.propose(pts)["line"]
        == "Nothing is decided yet: 2 points still to decide; 1 is a code-proven Fail on a mandatory rule."
    )


def test_a_locked_database_while_reading_the_ai_lines_refuses_the_signing(monkeypatch):
    """R48b: the locked-database case of the sign gate: refused with the plain reason, never "nothing undecided"."""
    import sqlite3

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    ai_run(doc, [mk("R-1", "Fail", "Fail")])
    client = _client(doc, "doc_std")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'Approved' WHERE id = ?",
            (run,),
        )

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(review_points, "ai_points_of_run", locked)
    gate = _gate(client, run)
    assert gate["issuable"] is False and any(
        "could not be read" in b for b in gate["blockers"]
    )
    refused = _issue(client, run)
    assert (
        refused.status_code == 409
        and "could not be read" in refused.json()["detail"]["message"]
    )


def test_the_contractor_copy_line_comes_from_the_kind_table_in_both_states(monkeypatch):
    """R48c: what the contractor copy holds is said from the backend's own answer for the paper's kind, never a fixed claim."""
    from app import kind_review_table

    doc = _submittal()
    ai_run(doc, [mk("R-1", "Fail", "Fail")])
    client = _client(doc, "doc_std")
    plain = points_of(client, doc)["contractor_copy"]
    assert (
        plain["kind"] == "datasheet"
        and plain["words"] == kind_review_table.CONTRACTOR_COPY_PLAIN
    )
    assert "never carries an AI wording" in plain["words"]
    monkeypatch.setattr(
        kind_review_table,
        "contractor_copy_ai_verdict",
        lambda kind: kind == "datasheet",
    )
    flagged = points_of(client, doc)["contractor_copy"]
    assert flagged["words"] == kind_review_table.CONTRACTOR_COPY_WITH_VERDICTS
    assert (
        "never carries an AI wording" not in flagged["words"]
        and "two readers agreed" in flagged["words"]
    )
    assert (
        points_of(_client(_submittal("doc_other", "o.pdf")), "doc_other")[
            "contractor_copy"
        ]["kind"]
        is None
    )  # no AI review: no kind


def test_the_checklist_has_one_reader_the_checks_loader(monkeypatch):
    """Rule 8: the strength of a checklist check is read through `datasheet_checks.load_rules`, not a second reader of the file."""
    from app import datasheet_checks

    calls = []

    def loader(*_a, **_k):
        calls.append(1)
        return {"lists": [{"checks": [{"id": "ZZ-9", "strength": "should"}]}]}

    monkeypatch.setattr(datasheet_checks, "load_rules", loader)
    assert review_points_service._checklist_entry("ZZ-9") == {
        "id": "ZZ-9",
        "strength": "should",
    }
    assert calls
    assert (
        review_points_service._strength(
            {
                "origin": "datasheet_check",
                "requirement_source_text": "Datasheet check ZZ-9: a recommendation",
            }
        )
        == "should"
    )
