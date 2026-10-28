"""Order 302.4: the engineer's step on a rule card. Invented rules only; no database file, no model."""

from __future__ import annotations

import sqlite3

import pytest

from app import datasheet_checks as dc
from app import rule_card_versions as rcv

TYPE = "Pressure Safety Valve"
TESTED_CARD = "PSV-24"  # a compare rule with a numeric clause and written cases
NEEDS_CARD = "PSV-05"  # waits for a standard we do not hold
RULES = dc.load_rules()


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def _seen(conn, card_id=TESTED_CARD):
    card = rcv.current(conn, TYPE, card_id, RULES)
    return {"version": card["version"], "seen_hash": card["content_hash"]}


def _approve(conn, card_id=TESTED_CARD, actor="eng-1", **seen):
    seen = seen or _seen(conn, card_id)
    return rcv.decide(
        conn, TYPE, card_id, rcv.APPROVED, actor=actor, rules=RULES, **seen
    )


def test_a_fresh_tested_card_is_tested_not_approved(conn):
    card = rcv.whole(conn, TYPE, TESTED_CARD, RULES)
    assert (card["state"], card["version"], card["decision"]) == ("tested", 1, None)
    assert card["why"] == "tested, not yet approved"


def test_approve_locks_the_exact_content_and_records_who_and_when(conn):
    done = _approve(conn)
    assert (
        done["decision"] == "approved"
        and done["decided_by"] == "eng-1"
        and done["decided_at"].endswith("Z")
    )
    card = rcv.whole(conn, TYPE, TESTED_CARD, RULES)
    assert (card["state"], card["decided_by"]) == ("approved", "eng-1")


def test_a_second_decision_on_the_same_content_is_refused(conn):
    seen = _seen(conn)
    _approve(conn, **seen)
    with pytest.raises(rcv.Conflict):
        rcv.decide(
            conn, TYPE, TESTED_CARD, rcv.REJECTED, actor="eng-2", rules=RULES, **seen
        )
    assert rcv.whole(conn, TYPE, TESTED_CARD, RULES)["decided_by"] == "eng-1"


def test_a_stale_screen_writes_nothing(conn):
    with pytest.raises(rcv.Conflict):
        rcv.decide(
            conn,
            TYPE,
            TESTED_CARD,
            rcv.APPROVED,
            version=1,
            seen_hash="0" * 64,
            actor="eng-1",
            rules=RULES,
        )
    assert conn.execute("SELECT COUNT(*) FROM rule_card_versions").fetchone()[0] == 0


def test_nobody_signed_in_writes_nothing(conn):
    with pytest.raises(rcv.CardError):
        _approve(conn, actor="")
    assert conn.execute("SELECT COUNT(*) FROM rule_card_versions").fetchone()[0] == 0


def test_a_card_that_needs_a_standard_we_do_not_hold_cannot_be_approved(conn):
    assert rcv.whole(conn, TYPE, NEEDS_CARD, RULES)["state"] == "draft"
    with pytest.raises(rcv.CardError, match="only a tested card"):
        _approve(conn, NEEDS_CARD)


def test_an_edit_is_a_new_version_with_no_decision_and_the_approval_no_longer_applies(
    conn,
):
    _approve(conn)
    before = rcv.whole(conn, TYPE, TESTED_CARD, RULES)
    edited = rcv.edit(
        conn,
        TYPE,
        TESTED_CARD,
        {"severity": "minor"},
        actor="eng-2",
        rules=RULES,
        **_seen(conn),
    )
    assert edited["version"] == 2 and edited["decision"] is None
    assert edited["state"] == "tested"  # tested again at once, but NOT approved
    assert (
        edited["item"]["severity"] == "minor" and before["item"]["severity"] != "minor"
    )
    rows = conn.execute(
        "SELECT version, decision FROM rule_card_versions ORDER BY version"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (1, "approved"),
        (2, None),
    ]  # the earlier approval stays in the history


def test_an_edit_that_breaks_the_cases_sends_the_card_back_to_draft(conn):
    _approve(conn)
    edited = rcv.edit(
        conn, TYPE, TESTED_CARD, {"op": ">="}, actor="eng-2", rules=RULES, **_seen(conn)
    )
    assert edited["state"] == "draft" and edited["why"] == "a case failed"
    with pytest.raises(rcv.CardError, match="only a tested card"):
        _approve(conn)


def test_an_approval_does_not_survive_a_change_of_the_committed_card(conn):
    _approve(conn)
    moved = {
        **RULES,
        "checklists": {
            **RULES["checklists"],
            TYPE: {
                **RULES["checklists"][TYPE],
                "items": [
                    {**i, "severity": "minor"} if i["id"] == TESTED_CARD else i
                    for i in RULES["checklists"][TYPE]["items"]
                ],
            },
        },
    }
    card = rcv.whole(conn, TYPE, TESTED_CARD, moved)
    assert card["decision"] is None and card["state"] == "tested"
    # an unedited card follows the committed card: the new words, not the stored copy of the old ones
    assert card["item"]["severity"] == "minor" and not card["baseline_changed"]


def test_a_rejected_card_stays_rejected_and_an_edit_starts_again(conn):
    rcv.decide(
        conn, TYPE, TESTED_CARD, rcv.REJECTED, actor="eng-1", rules=RULES, **_seen(conn)
    )
    assert rcv.whole(conn, TYPE, TESTED_CARD, RULES)["state"] == "rejected"
    edited = rcv.edit(
        conn,
        TYPE,
        TESTED_CARD,
        {"text": "A new wording."},
        actor="eng-1",
        rules=RULES,
        **_seen(conn),
    )
    assert edited["state"] == "tested" and edited["decision"] is None


def test_approve_needs_a_clause_number(conn):
    card_id = next(i["id"] for i in RULES["checklists"]["Pressure Vessel"]["items"])
    assert not rcv.clause_is_a_number(
        RULES["checklists"]["Pressure Vessel"]["items"][0]
    )
    seen = {
        k: v
        for k, v in rcv.current(conn, "Pressure Vessel", card_id, RULES).items()
        if k in ("version",)
    }
    seen["seen_hash"] = rcv.current(conn, "Pressure Vessel", card_id, RULES)[
        "content_hash"
    ]
    with pytest.raises(rcv.CardError, match="clause number"):
        rcv.decide(
            conn,
            "Pressure Vessel",
            card_id,
            rcv.APPROVED,
            actor="eng-1",
            rules=RULES,
            **seen,
        )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"op": "=="}, "the comparison is one of"),
        ({"left": "no such box"}, "not a box"),
        ({"values": ["x"]}, "cannot be edited on a compare rule"),
        ({"text": "  "}, "cannot be empty"),
        ({"severity": "high"}, "critical, major or minor"),
        ({"clause": ""}, "cannot be empty"),
        ({}, "nothing changed"),
    ],
)
def test_an_edit_outside_what_the_rule_allows_is_refused(conn, changes, message):
    with pytest.raises(rcv.CardError, match=message):
        rcv.edit(
            conn, TYPE, TESTED_CARD, changes, actor="eng-1", rules=RULES, **_seen(conn)
        )
    assert conn.execute("SELECT COUNT(*) FROM rule_card_versions").fetchone()[0] == 0


def test_a_number_edit_must_be_a_number(conn):
    card = next(
        i["id"]
        for i in RULES["checklists"][TYPE]["items"]
        if i["rule"]["kind"] == "above_by"
    )
    with pytest.raises(rcv.CardError, match="must be a number"):
        rcv.edit(
            conn,
            TYPE,
            card,
            {"percent": "10"},
            actor="eng-1",
            rules=RULES,
            **_seen(conn, card),
        )


def test_the_listing_counts_states_against_the_types_own_cards(conn):
    _approve(conn)
    listing = rcv.listing(conn, RULES)[TYPE]
    assert listing["total"] == len(listing["cards"]) == 47
    assert listing["counts"] == {"draft": 2, "tested": 44, "approved": 1, "rejected": 0}
    assert sum(listing["counts"].values()) == listing["total"]
