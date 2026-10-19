"""Release 1b (cloud's danger-zone review of #1178): an AI/web comment an
engineer confirmed and issued as a permanent number must stay on a LATER
run's contractor copy when the AI raises the same item again, unconfirmed -
and a number whose stored wording is empty is counted and named, never
dropped unseen. Invented data only (the `world` run of test_review_screen)."""

from __future__ import annotations

import uuid

from app import crs_export, crs_issue, crs_mapping, crs_numbers, db, main
from app.access import AccessScope
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

WORDS = "Confirm the invented coupling guard is fitted. (Engineer's words.)"
DRAFT = "Please check that an invented coupling guard is fitted."
COVERED = {"pages_total": 1, "pages_not_read_into_fields": []}


def _scope(scope):
    return AccessScope(user_id="eng-1", allowed_document_ids=scope)


def _add_ai_item(run) -> str:
    """The AI engineering check raises one item (unconfirmed) on the run."""
    conn = db.connect()
    base = dict(
        conn.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? LIMIT 1", (run,)
        ).fetchone()
    )
    row = {
        **base,
        "id": str(uuid.uuid4()),
        "origin": "ai_engineering_check",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "finding": DRAFT,
        "fact_id": None,
        "requirement_id": None,
        "contractor_page": 1,
        "confirmed_by": None,
        "engineer_comment": None,
        "approval_status": "pending",
    }
    conn.execute(
        f"INSERT INTO review_findings ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )
    conn.commit()
    return row["id"]


def _ai_row(rows):
    [row] = [
        r
        for r in rows
        if r.get("row_kind") == crs_mapping.ROW_KIND_AI_ENGINEERING_CHECK
    ]
    return row


def _issued_number(world_, snapshot_comment) -> tuple[str, str]:
    """Run 1: the engineer confirmed the AI item - issued as number N with
    `snapshot_comment` stored. Returns (key, ref)."""
    sub, run, scope = world_
    rows, *_ = main._crs_content(run, _scope(scope))
    key = _ai_row(rows)["crs_row_key"]
    crs_scope, label = main._crs_scope_of(sub)
    stored = crs_numbers.assign(
        crs_scope,
        label,
        [key],
        document_id=sub,
        review_run_id=run,
        snapshots={
            key: {"comment": snapshot_comment, "comment_by": "AI, confirmed by Eng"}
        },
        user_id="eng-1",
    )
    return key, stored[key]["ref"]


def _copy(run, scope, copy):
    rows, meta, *_ = main._crs_content(run, _scope(scope), copy)
    return rows, crs_export.build_crs_view(rows, meta)


# ------------------------------------------- the defect: an issued comment vanished


def test_an_issued_ai_comment_stays_on_a_later_runs_contractor_copy(world):  # noqa: F811
    _sub, run, scope = world
    _add_ai_item(run)
    key, ref = _issued_number(world, WORDS)
    rows, view = _copy(run, scope, "issue")
    [mine] = [r for r in view["rows"] if r["item_no"] == ref]
    assert WORDS in mine["comment"]
    assert mine["final_resolution"] == "Open"
    assert mine["comment_by"] == "AI, confirmed by Eng"  # the issued byline too
    assert mine["ai_review_comment"] == ""  # the draft never leaves the building
    assert DRAFT not in mine["comment"]
    assert crs_mapping.AI_UNCONFIRMED_COMMENT not in mine["comment"]
    assert view["rows_withheld_no_text"] == 0
    # nothing to block: the issued words are there
    gate = crs_issue.open_items(run, rows, COVERED)
    assert not any("no text" in b for b in gate["blockers"])
    # the same words are what the number stores for the next run (kept)
    assert (
        crs_numbers.lookup(main._crs_scope_of(world[0])[0], [key])[key]["comment"]
        == WORDS
    )


def test_the_internal_copy_does_not_say_not_issued_beside_an_issued_number(world):  # noqa: F811
    _sub, run, scope = world
    _add_ai_item(run)
    _key, ref = _issued_number(world, WORDS)
    _rows, view = _copy(run, scope, "internal")
    [mine] = [r for r in view["rows"] if r["item_no"] == ref]
    assert "Not issued to the contractor" not in mine["comment"]
    assert WORDS in mine["comment"]
    assert DRAFT in mine["ai_review_comment"]  # the draft stays internal
    assert mine["comment_missing"] is False


def test_a_still_unconfirmed_item_without_a_number_is_still_a_draft(world):  # noqa: F811
    """The fix is for ISSUED numbers only: an unnumbered unconfirmed item
    keeps its waiting sentence and stays off the contractor copy."""
    _sub, run, scope = world
    _add_ai_item(run)
    rows, issue = _copy(run, scope, "issue")
    assert all(
        crs_mapping.AI_UNCONFIRMED_COMMENT not in r["comment"] for r in issue["rows"]
    )
    assert _ai_row(rows)["engineer_confirmed"] is False
    assert issue["rows_withheld_no_text"] == 0
    _r, internal = _copy(run, scope, "internal")
    assert any(
        crs_mapping.AI_UNCONFIRMED_COMMENT in r["comment"] for r in internal["rows"]
    )


# ------------------------- an issued number with no words: counted and named


def test_an_issued_number_with_no_stored_wording_is_counted_and_blocks(world):  # noqa: F811
    _sub, run, scope = world
    _add_ai_item(run)
    _key, ref = _issued_number(world, "")
    rows, issue = _copy(run, scope, "issue")
    assert all(r["item_no"] != ref for r in issue["rows"])
    assert issue["rows_withheld_no_text"] == 1  # counted, not dropped unseen
    gate = crs_issue.open_items(run, rows, COVERED)
    assert gate["issuable"] is False
    assert crs_issue.no_text_blocker([ref]) in gate["blockers"]
    _r, internal = _copy(run, scope, "internal")
    [mine] = [r for r in internal["rows"] if r["item_no"] == ref]
    assert mine["comment_missing"] is True
    assert f"Comment {ref} was issued" in mine["comment"]
    assert "Not issued to the contractor" not in mine["comment"]


def test_a_waiting_sentence_stored_by_the_old_overwrite_is_never_issued(world):  # noqa: F811
    sentence = crs_mapping.AI_UNCONFIRMED_COMMENT
    _sub, run, scope = world
    _add_ai_item(run)
    _key, ref = _issued_number(world, sentence)
    rows, issue = _copy(run, scope, "issue")
    assert all(sentence not in r["comment"] for r in issue["rows"])
    assert issue["rows_withheld_no_text"] == 1
    gate = crs_issue.open_items(run, rows, COVERED)
    assert crs_issue.no_text_blocker([ref]) in gate["blockers"]
    # and the internal copy does not print the sentence as the issued words
    _r, internal = _copy(run, scope, "internal")
    [mine] = [r for r in internal["rows"] if r["item_no"] == ref]
    assert mine["comment_missing"] is True
    assert sentence not in mine["comment"]


def test_carry_issued_wording_treats_either_waiting_sentence_as_no_words():
    for sentence in (
        crs_mapping.AI_UNCONFIRMED_COMMENT,
        crs_mapping.WEB_UNCONFIRMED_COMMENT,
    ):
        row = {"comment": sentence, "ai_review_comment": DRAFT}
        crs_mapping.carry_issued_wording(row, {"comment": sentence})
        assert row["comment"] == ""
        assert crs_mapping.row_has_no_text(row) is True


def test_carry_issued_wording_leaves_a_row_without_a_draft_alone():
    row = {"comment": "The engineer's own words.", "ai_review_comment": ""}
    crs_mapping.carry_issued_wording(row, {"comment": "older words", "comment_by": "x"})
    assert row == {"comment": "The engineer's own words.", "ai_review_comment": ""}


# -------------------------- the export and the gate, row by row (no database)


def _row(**over):
    return {
        "finding_id": "f1",
        "document_name": "inv.pdf",
        "page_section": "p.1",
        "comment": WORDS,
        "comment_by": "AI, confirmed by Eng",
        "row_kind": crs_mapping.ROW_KIND_AI_ENGINEERING_CHECK,
        "engineer_confirmed": True,
        "ai_review_comment": DRAFT,
        "crs_ref": "CRS-INV-001",
        "crs_status": "Open",
        **over,
    }


def test_a_confirmed_row_holding_a_draft_is_issued_with_its_words_not_dropped():
    view = crs_export.build_crs_view([_row()], {"copy": crs_export.COPY_ISSUE})
    assert [r["item_no"] for r in view["rows"]] == ["CRS-INV-001"]
    assert view["rows"][0]["ai_review_comment"] == ""
    assert view["rows_withheld_no_text"] == 0


def test_an_unconfirmed_row_holding_a_draft_is_still_dropped():
    view = crs_export.build_crs_view(
        [_row(engineer_confirmed=False)], {"copy": crs_export.COPY_ISSUE}
    )
    assert view["rows"] == [] and view["rows_withheld_no_text"] == 0


def test_a_confirmed_row_with_a_draft_and_a_waiting_sentence_is_counted_not_issued():
    waiting = _row(comment=crs_mapping.AI_UNCONFIRMED_COMMENT)
    view = crs_export.build_crs_view([waiting], {"copy": crs_export.COPY_ISSUE})
    assert view["rows"] == [] and view["rows_withheld_no_text"] == 1
    gate = crs_issue.open_items("run-1", [waiting], COVERED)
    assert gate["blockers"] == [crs_issue.no_text_blocker(["CRS-INV-001"])]


def test_the_blocker_names_every_comment_and_says_what_to_do():
    one = crs_issue.no_text_blocker(["CRS-INV-004"])
    assert "CRS-INV-004" in one and "confirm or edit" in one
    two = crs_issue.no_text_blocker(["CRS-INV-004", "CRS-INV-009"])
    assert "2 confirmed comments" in two
    assert "CRS-INV-004, CRS-INV-009" in two


def test_the_blocker_offers_to_close_only_a_comment_that_closing_clears():
    """Review of #1188: closing clears a comment CARRIED FORWARD from an
    earlier run, never one this run raised again - so "close" is offered for
    the first kind only."""
    assert "close" not in crs_issue.no_text_blocker(["CRS-INV-004"])
    assert "close" not in crs_issue.no_text_blocker(["CRS-INV-004", "CRS-INV-009"])
    one = crs_issue.no_text_blocker(["CRS-INV-004"], ["CRS-INV-004"])
    assert "or close the comment" in one
    two = crs_issue.no_text_blocker(["CRS-INV-004", "CRS-INV-009"], ["CRS-INV-009"])
    assert "CRS-INV-009 can also be closed" in two
    assert "CRS-INV-004 can also be closed" not in two


def test_following_the_advice_clears_a_re_raised_comment(world):  # noqa: F811
    """Closing the number does NOT clear a row this run raised again (its
    number still marks the row confirmed and the row stays empty), so the
    advice is to confirm the item - and that does clear the gate."""
    _sub, run, scope = world
    ai_id = _add_ai_item(run)
    _key, ref = _issued_number(world, "")
    rows, _view = _copy(run, scope, "issue")
    gate = crs_issue.open_items(run, rows, COVERED)
    blocker = crs_issue.no_text_blocker([ref])
    assert blocker in gate["blockers"] and "close" not in blocker
    _r, internal = _copy(run, scope, "internal")
    [mine] = [r for r in internal["rows"] if r["item_no"] == ref]
    assert "close" not in mine["comment"]
    # closing the number leaves it blocked: the advice does not offer it
    crs_scope, _label = main._crs_scope_of(world[0])
    crs_numbers.set_status(
        crs_scope, crs_numbers.parse_ref(ref)[1], crs_numbers.CLOSED, user_id="eng-1"
    )
    rows, view = _copy(run, scope, "issue")
    assert blocker in crs_issue.open_items(run, rows, COVERED)["blockers"]
    assert view["rows_withheld_no_text"] == 1
    # the advice: the engineer confirms the item in the review
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET confirmed_by = 'eng-1',"
            " approval_status = 'accepted' WHERE id = ?",
            (ai_id,),
        )
    rows, view = _copy(run, scope, "issue")
    assert blocker not in crs_issue.open_items(run, rows, COVERED)["blockers"]
    assert view["rows_withheld_no_text"] == 0
    assert any(r["item_no"] == ref and DRAFT in r["comment"] for r in view["rows"])


def test_following_the_advice_clears_a_carried_forward_comment(world):  # noqa: F811
    """A comment issued on an earlier run, saved empty and not raised again:
    closing it does clear the gate, so that advice is offered."""
    sub, run, scope = world
    crs_scope, label = main._crs_scope_of(sub)
    key = "invented-carried-key"
    ref = crs_numbers.assign(
        crs_scope,
        label,
        [key],
        document_id=sub,
        review_run_id=run,
        snapshots={key: {"comment": ""}},
        user_id="eng-1",
    )[key]["ref"]
    rows, view = _copy(run, scope, "issue")
    gate = crs_issue.open_items(run, rows, COVERED)
    assert crs_issue.no_text_blocker([ref], [ref]) in gate["blockers"]
    assert "or close the comment" in crs_issue.no_text_blocker([ref], [ref])
    assert view["rows_withheld_no_text"] == 1
    _r, internal = _copy(run, scope, "internal")
    [mine] = [r for r in internal["rows"] if r["item_no"] == ref]
    assert mine["comment"] == crs_export.empty_comment_text(ref, True)
    assert "close the comment" in mine["comment"]
    crs_numbers.set_status(
        crs_scope, crs_numbers.parse_ref(ref)[1], crs_numbers.CLOSED, user_id="eng-1"
    )
    rows, view = _copy(run, scope, "issue")
    assert not any(
        "no text" in b for b in crs_issue.open_items(run, rows, COVERED)["blockers"]
    )
    assert view["rows_withheld_no_text"] == 0


def test_a_carried_forward_comment_saved_empty_is_named_by_the_gate():
    """Cloud's non-blocking item 1: a snapshot saved empty by the old
    overwrite - the blocker names the comment, the copy says which and what."""
    carried = _row(
        comment="",
        ai_review_comment="",
        row_kind=crs_mapping.ROW_KIND_CARRIED_FORWARD,
        crs_ref="CRS-INV-007",
    )
    gate = crs_issue.open_items("run-1", [carried], COVERED)
    assert gate["blockers"] == [
        crs_issue.no_text_blocker(["CRS-INV-007"], ["CRS-INV-007"])
    ]
    assert "CRS-INV-007" in gate["blockers"][0]
    assert "or close the comment" in gate["blockers"][0]
    internal = crs_export.build_crs_view([carried], {"copy": crs_export.COPY_INTERNAL})
    text = internal["rows"][0]["comment"]
    assert text == crs_export.empty_comment_text("CRS-INV-007", True)
    assert "CRS-INV-007" in text and "An engineer must write it" not in text


def test_an_unconfirmed_numbered_draft_with_no_text_is_not_said_to_be_issued():
    """Review of #1188: a machine draft's number is not issued. Its empty
    comment keeps the plain sentence, not "was issued but its wording was not
    kept" beside Final Resolution "Draft (not issued)"."""
    draft = _row(
        comment="",
        ai_review_comment="",
        engineer_confirmed=False,
        crs_status="Draft (not issued)",
    )
    view = crs_export.build_crs_view([draft], {"copy": crs_export.COPY_INTERNAL})
    text = view["rows"][0]["comment"]
    assert text == crs_export.EMPTY_COMMENT_TEXT
    assert "was issued" not in text
    assert view["rows"][0]["final_resolution"] == "Draft (not issued)"


def test_issued_words_with_no_stored_byline_never_sit_under_the_drafts_byline():
    """Review of #1188: older snapshots kept no byline. The issued words are
    still carried (a comment is never hidden), but the row must not keep the
    AI draft's byline beside the engineer's text."""
    row = {
        "comment": crs_mapping.AI_UNCONFIRMED_COMMENT,
        "comment_by": "AI - engineer to confirm",
        "ai_review_comment": DRAFT,
    }
    crs_mapping.carry_issued_wording(row, {"comment": WORDS, "comment_by": ""})
    assert row["comment"] == WORDS
    assert row["comment_by"] == ""
    assert "AI - engineer to confirm" not in row["comment_by"]
    view = crs_export.build_crs_view([_row(**row)], {"copy": crs_export.COPY_ISSUE})
    assert view["rows"][0]["comment"] == WORDS and view["rows_withheld_no_text"] == 0


def test_an_issued_comment_with_no_words_does_not_keep_the_drafts_byline():
    """Review of #1188: beside "Comment N was issued but its wording was not
    kept" the row must not still say "AI - engineer to confirm"."""
    row = {
        "comment": crs_mapping.AI_UNCONFIRMED_COMMENT,
        "comment_by": "AI - engineer to confirm",
        "ai_review_comment": DRAFT,
    }
    crs_mapping.carry_issued_wording(row, {"comment": "", "comment_by": "x"})
    assert row["comment"] == "" and row["comment_by"] == ""


def test_an_older_snapshot_byline_shows_the_display_name_not_the_user_id():
    """Audit rule 2026-09-30: a snapshot written before bylines printed names
    says "confirmed by eng-1"; it is shown as the user's display name."""
    row = {"comment": "waiting", "comment_by": "AI", "ai_review_comment": DRAFT}
    snap = {"comment": WORDS, "comment_by": "AI engineering check, confirmed by eng-1"}
    names = {"eng-1": "Eve Engineer"}
    crs_mapping.carry_issued_wording(row, snap, lambda ids: names)
    assert row["comment_by"] == "AI engineering check, confirmed by Eve Engineer"
    assert "eng-1" not in row["comment_by"]
    # no name on record: the byline is returned as stored, never invented
    plain = {"comment": "waiting", "comment_by": "AI", "ai_review_comment": DRAFT}
    crs_mapping.carry_issued_wording(plain, snap, lambda ids: {})
    assert plain["comment_by"] == "AI engineering check, confirmed by eng-1"
