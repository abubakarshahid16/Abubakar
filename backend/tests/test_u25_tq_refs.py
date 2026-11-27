"""Another query a contractor's request NAMES is found by code and said on the page and the draft (lead-4's blind score of the owner's
approved answers, 27 Nov 2026: 4 of 7 point to another query already answered). Invented numbers only; no model, no network."""

from __future__ import annotations

from app import db
from app import technical_queries as tq
from app import technical_query_refs as refs
from tests.test_technical_queries import envelope
from tests.test_tq_g_feature_off import (  # noqa: F401 - storage: the autouse database fixture
    on,
    storage,
)

OLD = "ZQP-INVCON-INVCO-CFC-0005"


def _query(message_id: str, subject: str, body: str, owner: str = "u1"):
    item, _ = tq.import_message(
        {
            **envelope(message_id),
            "provider_thread_id": message_id,
            "subject": subject,
            "body": body,
        },
        owner,
        False,
        False,
    )
    return item


def test_numbers_in_a_text_are_read_once_each_with_or_without_their_prefix():
    found = refs.numbers_in(
        f"As answered in {OLD} and again in CFC-5; see also TQ-012 and {OLD.lower()}."
    )
    assert [(f["reference"], f["prefixed"]) for f in found] == [
        ("ZQP-INVCON-INVCO-CFC-5", True),
        ("CFC-5", False),
        ("TQ-12", False),
    ]


def test_a_named_query_held_here_is_listed_with_its_status_and_the_draft_line_says_see_it(
    monkeypatch,
):
    on(monkeypatch)
    old = _query(
        "m-old",
        f"{OLD} - PIP_Invented turning radius",
        "Please confirm the invented turning radius.",
    )
    new = _query("m-new", "ZQP-INVCON-INVCO-CFC-0009 - PIP_Invented layout",
                 f"Please confirm the invented layout. The turning radius was answered in {OLD}. Also see TQ-77.")  # fmt: skip
    got = tq.get(new["id"], "u1", False, False)
    by_ref = {r["reference"]: r for r in got["cross_refs"]}
    assert (
        by_ref["ZQP-INVCON-INVCO-CFC-5"]["held"]
        and by_ref["ZQP-INVCON-INVCO-CFC-5"]["query_id"] == old["id"]
    )
    assert by_ref["ZQP-INVCON-INVCO-CFC-5"]["status"] == old["status"]
    assert by_ref["TQ-77"] == {
        "reference": "TQ-77",
        "held": False,
        "query_id": None,
        "status": None,
        "subject": None,
    }
    assert (
        "ZQP-INVCON-INVCO-CFC-9" not in by_ref
    )  # the query's own number is never a cross-reference
    assert got["ready"]["cross_refs"] == got["cross_refs"]
    line = "The request names ZQP-INVCON-INVCO-CFC-5, held in this system: see it before replying."
    assert line in got["ready"]["marks"] and refs.mark(got["cross_refs"]) == line


def test_a_named_query_the_caller_may_not_see_is_said_to_be_held_never_named_or_linked(
    monkeypatch,
):
    on(monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u2','u2@example.test','V','x','x')"
        )
    _query(
        "m-other", f"{OLD} - PIP_Invented", "Please confirm.", owner="u2"
    )  # u1 may not see it
    new = _query(
        "m-mine",
        "ZQP-INVCON-INVCO-CFC-0010 - PIP_Invented",
        f"Please confirm; see {OLD}.",
    )
    [ref] = tq.get(new["id"], "u1", False, False)["cross_refs"]
    assert ref == {
        "reference": "ZQP-INVCON-INVCO-CFC-5",
        "held": True,
        "query_id": None,
        "status": None,
        "subject": None,
    }
