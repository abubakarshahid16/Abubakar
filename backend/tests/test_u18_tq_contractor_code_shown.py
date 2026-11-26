"""A query whose contractor no rule names yet says the contractor CODE printed in its reference number instead of "not set" (lead-4,
26 Nov 2026: all 33 queries said "contractor not set" while 32 carried the code). The code is read, never a guessed name, and fills no
field. Invented subjects only."""

from __future__ import annotations

from app.technical_queries import contractor_code_of, import_message, list_queries

from .test_technical_queries import envelope, temp_storage  # noqa: F401 - the fixture is used by name


def test_the_list_carries_the_code_from_the_number_and_never_fills_the_contractor():
    item, _ = import_message({**envelope("cc-1"), "subject": "Fw: 99999-INVCO-OWNR-TQ-00012 - PRO_Invented question"}, "u1", False, False)
    rows = {r["id"]: r for r in list_queries("u1", True, False)}
    assert rows[item["id"]]["contractor_code"] == "INVCO"
    assert rows[item["id"]]["contractor_name"] is None  # a code is not a name: nothing is filled
    assert contractor_code_of("A plain subject with no reference") is None
