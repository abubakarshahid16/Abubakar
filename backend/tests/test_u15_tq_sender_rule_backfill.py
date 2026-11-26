"""A saved sender rule (address or domain) fills the blank contractor / department of the queries ALREADY held, as a code rule does
(lead-4, 26 Nov 2026: every held query kept "contractor not set" after a rule was saved). Only blanks; a value set is kept. Invented."""

from __future__ import annotations

from app import db
from app.technical_queries import import_message, set_routing_rule

from .test_technical_queries import (  # noqa: F401 - the fixture is used by name
    _routed_envelope,
    temp_storage,
)


def _row(query_id):
    with db.connect() as conn:
        r = conn.execute("SELECT contractor_name, department, routing_source FROM technical_queries WHERE id=?", (query_id,)).fetchone()
    return tuple(r)


def test_a_domain_rule_saved_later_fills_held_queries_and_keeps_what_is_set():
    held, _ = import_message(_routed_envelope("h1", "clerk@invented-maker.test"), "u1", False, False)
    other, _ = import_message(_routed_envelope("h2", "someone@elsewhere.test"), "u1", False, False)
    set_by_hand, _ = import_message(_routed_envelope("h3", "chief@invented-maker.test", department="Kept Dept"), "u1", False, False)
    assert _row(held["id"])[0] is None
    set_routing_rule("domain", "invented-maker.test", "Invented Maker", "Piping", "u1", True)
    contractor, department, source = _row(held["id"])
    assert (contractor, department) == ("Invented Maker", "Piping") and source.startswith("rule:")
    assert _row(other["id"])[:2] == (None, None)  # a different sender is left alone
    assert _row(set_by_hand["id"])[:2] == ("Invented Maker", "Kept Dept")  # only the blank field is filled
