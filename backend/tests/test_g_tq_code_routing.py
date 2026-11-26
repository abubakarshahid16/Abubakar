"""The contractor and the department of a technical query come from the codes in its document number, through admin maps set once; the
sender's domain is the fallback; only blank fields are filled, now and for the queries already held (lead-4 and the planner, 26 Nov 2026:
all 33 queries of the first import showed "Unknown contractor"). Invented numbers, codes and names only."""

from __future__ import annotations

import pytest

from app.technical_queries import (
    get,
    import_message,
    list_routing_rules,
    set_routing_rule,
)
from app.technical_query_subject import parse

from .test_technical_queries import envelope, temp_storage  # noqa: F401 - the fixture is used by name

SUBJECT = "RE: 12345-ABC-OWN-TQ-00007 - PRO_Invented_title"


def _import(mid, subject=SUBJECT, sender="person@vendor.example", contractor=None):
    data = envelope(mid)
    # its own thread: a shared thread would join the queries
    data.update(
        subject=subject,
        from_address=sender,
        contractor_name=contractor,
        attachments=[],
        provider_thread_id=mid,
    )
    return import_message(data, "u1", False, False)[0]


def test_the_contractor_code_is_read_from_the_number_by_code():
    assert parse(SUBJECT)["contractor_code"] == "ABC"
    assert (
        parse("ABC-TQ-7 - PRO_x")["contractor_code"] is None
    )  # a number without project, contractor and company names no contractor


def test_a_code_rule_names_the_contractor_and_a_discipline_rule_the_department():
    set_routing_rule("contractor_code", "abc", "Invented Contractor", None, "u1", True)
    set_routing_rule("discipline", "PRO", None, "Process", "u1", True)
    item = get(_import("c1")["id"], "u1", False, False)
    assert (
        item["contractor_name"] == "Invented Contractor"
        and item["department"] == "Process"
    )
    assert item["routing_source"].startswith("code:")
    kinds = {r["match_type"] for r in list_routing_rules()}
    assert {"contractor_code", "discipline"} <= kinds


def test_the_sender_domain_fills_what_the_number_does_not():
    set_routing_rule(
        "domain", "vendor.example", "Domain Contractor", "Domain Dept", "u1", True
    )
    set_routing_rule("discipline", "PRO", None, "Process", "u1", True)
    item = get(
        _import("c2")["id"], "u1", False, False
    )  # no contractor-code rule for ABC
    assert (
        item["contractor_name"] == "Domain Contractor"
        and item["department"] == "Process"
    )


def test_a_rule_fills_the_blanks_of_queries_already_held_and_never_overwrites_a_set_value():
    blank = _import("c3")
    kept = _import(
        "c4", subject="RE: 12345-ABC-OWN-TQ-00008 - PRO_Other", contractor="Set By Hand"
    )
    set_routing_rule("contractor_code", "ABC", "Invented Contractor", None, "u1", True)
    assert (
        get(blank["id"], "u1", False, False)["contractor_name"] == "Invented Contractor"
    )
    assert get(kept["id"], "u1", False, False)["contractor_name"] == "Set By Hand"


def test_a_bad_code_or_an_empty_rule_is_refused():
    with pytest.raises(ValueError):
        set_routing_rule("contractor_code", "A", "X", None, "u1", True)
    with pytest.raises(ValueError):
        set_routing_rule("discipline", "PRO", None, None, "u1", True)
    with pytest.raises(PermissionError):
        set_routing_rule("contractor_code", "ABC", "X", None, "u1", False)
