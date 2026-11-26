"""G2 (lead-4, 26 Nov 2026; audit of the 9 live reviews): a Question that asks to confirm, or raises a concern about, a value the
paper is said to state must show that value as a code-verified quote. With no verified quote at ANY of its places the claim is
unproven: the comment is open ("Missing information") and its ask starts with `VALUE_NOT_SHOWN`; it is never shown as if the
paper stated it. A comment with one verified place keeps its card. Invented values only."""

from __future__ import annotations

import re

import pytest

from app import aim_review_card as card_mod
from app import aim_review_contractor


def _q(
    ask: str,
    quote: str = "",
    unverified: bool = False,
    field: str = "Design temperature",
) -> dict:
    return {
        "n": 1, "label": "Question", "shown_label": "Question", "ask": ask, "quote": quote, "quote_unverified": unverified,
        "field": field, "comment": "Confirm the invented value.", "code_note": "", "topic": "invented topic", "page": 3,
        "standard": "STD-X", "clause": "4.1", "source": "held standard",
    }  # fmt: skip


@pytest.mark.parametrize(
    "members, unshown",
    [
        ([_q("confirm")], True),  # no quote at all
        (
            [_q("concern", "Design temperature 150 C", unverified=True)],
            True,
        ),  # a quote code could not find
        (
            [_q("confirm", "Design temperature")],
            True,
        ),  # only the field's own label: no value
        ([_q("confirm", "Design temperature 150 C")], False),  # a verified value
        (
            [_q("concern", "Design temperature 150 C"), _q("concern", unverified=True)],
            False,
        ),  # one place verified
        ([_q("open")], False),  # already open: nothing claimed
    ],
)
def test_a_value_is_unshown_only_when_no_place_has_a_verified_quote(members, unshown):
    assert card_mod.value_not_shown(members) is unshown


def test_the_card_of_an_unshown_value_is_missing_information_and_says_so():
    members = [_q("confirm")]
    got = card_mod.card({"n": 1}, members)
    assert got["severity"] == card_mod.MISSING
    assert got["we_ask"].startswith(card_mod.VALUE_NOT_SHOWN)
    assert got["we_ask"].endswith(
        "Confirm the invented value."
    )  # the engineer still reads the AI's words after it


def test_a_verified_value_keeps_its_card_unchanged():
    members = [_q("concern", "Design temperature 150 C")]
    got = card_mod.card({"n": 1}, members)
    assert (
        got["severity"] == card_mod.CHECK
        and got["we_ask"] == "Confirm the invented value."
    )


def test_the_comment_asks_open_when_its_value_is_unshown():
    assert card_mod.card({"n": 1}, [_q("concern")])["ask"] == "open"
    assert "ask" not in card_mod.card(
        {"n": 1}, [_q("concern", "Design temperature 150 C")]
    )  # its own ask stands


def test_the_new_sentence_carries_no_internal_words_for_the_contractor_copy():
    for pattern, _what in aim_review_contractor.INTERNAL:
        assert not re.search(pattern, card_mod.VALUE_NOT_SHOWN)


def test_the_sentence_claims_neither_no_quote_nor_a_quote_that_was_not_found():
    """Review N3: it is said both when no quote exists and when code could not find the quote on the page, so it says neither."""
    s = card_mod.VALUE_NOT_SHOWN
    assert (
        s == "We could not find this value on the page; please state it or point to it."
    )
    assert "not shown" not in s and "any page" not in s


def test_without_the_rule_the_card_is_as_before():
    members = [_q("confirm")]
    got = card_mod.card({"n": 1}, members, rules=())
    assert got["we_ask"] == "Confirm the invented value." and "ask" not in got
    assert (
        got["severity"] != card_mod.MISSING
        or card_mod.point_severity(members[0]) == card_mod.MISSING
    )


# A SIGNED review keeps the wording it was signed with (lead-4, 26 Nov 2026): the rule is applied to a signed review only when its
# sign-off recorded it. Invented papers and values only (`test_aim_sheet_rule`'s run).
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, make_run  # noqa: E402
from tests.test_crs_endpoint import temp_db  # noqa: E402,F401 - fixture
from tests.test_g_signoff import CODE, client  # noqa: E402

BASE = f"/api/reviews/papers/{PAPER}/general"


def _asks(c) -> list[str]:
    page = c.get(f"{BASE}?run_id={RUN}").json()
    return [cm["we_ask"] for cm in page["comments"]]


@pytest.fixture
def every_value_unshown(temp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(card_mod, "value_not_shown", lambda members: True)
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(RUN)
    return client(PAPER, BOOK)


def _sign(c):
    assert c.post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code == 200
    assert (
        c.post(f"{BASE}/signoff", json={"run_id": RUN, "review_code": CODE}).status_code
        == 200
    )


def test_a_review_signed_under_the_rule_keeps_its_wording(every_value_unshown):
    c = every_value_unshown
    before = _asks(c)
    assert before and all(
        a.startswith(card_mod.VALUE_NOT_SHOWN) for a in before
    )  # unsigned: the rule applies
    _sign(c)
    assert _asks(c) == before  # signed under the rule: the same wording after sign-off


def test_a_review_signed_before_the_rule_keeps_its_old_wording(every_value_unshown):
    from app import aim_review_store, db

    c = every_value_unshown
    _sign(c)
    import json

    with (
        db.connect() as conn
    ):  # a sign-off made before the rule existed: no card rules (its other counts stay)
        row = conn.execute(
            f"SELECT id, counts_json FROM {aim_review_store.SIGNOFFS} WHERE run_id = ?",
            (RUN,),
        ).fetchone()
        counts = json.loads(row["counts_json"])
        assert counts.pop("card_rules") == list(
            card_mod.CARD_RULES
        )  # a sign-off made now records them
        conn.execute(
            f"UPDATE {aim_review_store.SIGNOFFS} SET counts_json = ? WHERE id = ?",
            (json.dumps(counts), row["id"]),
        )
    after = _asks(c)
    assert after and not any(card_mod.VALUE_NOT_SHOWN in a for a in after)
    page = c.get(f"{BASE}?run_id={RUN}").json()
    assert page["signoff"]["state"] == "signed"
