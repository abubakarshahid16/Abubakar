"""PF4 (#884): every applicable rule of a run accounted for, in exactly one
state - checked, sent to the engineer, not checked - with the denominator
stated, checklist-covered rules apart, and "does not apply" outside it.

Read from the run's own scope ledger (#677). Invented runs only.
"""
from __future__ import annotations

from app import clause_coverage as cov
from app import db, scope_ledger
from tests.test_crs_endpoint import _client, _run, _submittal, temp_db  # noqa: F401 - fixture
from tests.test_w5_677_scope_ledger import review_run  # noqa: F401 - fixture


def _ledger(run_id: str, codes: list[str]) -> None:
    decisions = [scope_ledger.decision({"id": f"req-{n}"}, code) for n, code in enumerate(codes)]
    scope_ledger.store(run_id, decisions)


def _get(client, run_id):
    r = client.get(f"/api/reviews/runs/{run_id}/coverage")
    assert r.status_code == 200, r.text
    return r.json()


def test_every_ledger_reason_has_one_pf4_state():
    assert set(scope_ledger.REASONS) <= set(cov.STATE_OF)
    assert set(cov.STATE_OF.values()) <= {*cov.STATES, cov.DOES_NOT_APPLY}


def test_each_rule_is_in_exactly_one_state_out_of_the_applicable_ones():
    doc = _submittal()
    run = _run(doc)
    _ledger(run, ["compared", "compared", "missing_information", "not_applicable",
                  "needs_engineer", "needs_other_document",
                  "row_label_not_on_sheet", "applicability_unsure",
                  "covered_by_checklist",
                  "definition", "other_equipment"])
    body = _get(_client(doc), run)
    assert body["recorded"] is True and body["adds_up"] is True
    # order 260.1: only the two COMPARED rules are checked; "the sheet has no value" is not
    # checked, and "the comparison found it does not apply" is outside the denominator
    assert body["counts"] == {"checked": 2, "engineer": 2, "not_checked": 3,
                              "covered_by_checklist": 1, "does_not_apply": 3}
    # the denominator: in scope minus "does not apply", checklist-covered included
    assert body["applicable"] == 8 and body["checked_share"] == 25.0
    assert body["line"] == (
        "2 of 8 applicable requirement(s) checked (25.0%), 2 sent to the engineer, "
        "3 not checked; 1 covered by a checklist (not proof the whole standard was "
        "checked); 3 do not apply")
    states = {r["requirement_id"]: r["state"] for r in body["rows"]}
    assert len(states) == 11 and states["req-4"] == "engineer" and states["req-7"] == "not_checked"


def test_a_checklist_covered_rule_says_it_is_not_proof_of_the_whole_standard():
    doc = _submittal()
    run = _run(doc)
    _ledger(run, ["covered_by_checklist"])
    row = _get(_client(doc), run)["rows"][0]
    assert row["state"] == "covered_by_checklist" and row["note"] == cov.CHECKLIST_NOTE
    assert row["reason"] == "the review checklist for this equipment type governs its standard"


def test_a_run_with_no_ledger_says_so_never_zero():
    doc = _submittal()
    body = _get(_client(doc), _run(doc))
    assert (body["recorded"], body["applicable"], body["counts"]) == (False, None, None)
    assert body["line"] == cov.NO_LEDGER


def test_an_unknown_reason_is_counted_not_checked_never_dropped():
    doc = _submittal()
    run = _run(doc)
    scope_ledger.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO review_scope_decisions (review_run_id, requirement_id, state,"
                     " reason_code, reason, decided_by, created_at)"
                     " VALUES (?, 'r1', 'applies_not_checked', 'a_new_reason', 'new', 'code', 'now')",
                     (run,))
    body = _get(_client(doc), run)
    assert body["counts"]["not_checked"] == 1 and body["applicable"] == 1


def test_clause_and_standard_only_where_the_caller_may_read_the_standard():
    doc = _submittal()
    run = _run(doc)
    _ledger(run, ["compared"])
    _submittal("std-1", "std.pdf")
    with db.connect() as conn:
        conn.execute("INSERT INTO standard_requirements (id, standard_document_id, clause,"
                     " requirement_text, created_at, updated_at)"
                     " VALUES ('req-0', 'std-1', '6.2', 'x', 'now', 'now')")
    assert _get(_client(doc), run)["rows"][0]["clause"] is None          # standard not granted
    row = _get(_client(doc, "std-1"), run)["rows"][0]
    assert (row["clause"], row["standard_document_id"]) == ("6.2", "std-1")


def test_a_stranger_gets_404_and_the_route_writes_nothing():
    doc = _submittal()
    run = _run(doc)
    assert _client("other").get(f"/api/reviews/runs/{run}/coverage").status_code == 404
    _get(_client(doc), run)
    tables = {r["name"] for r in db.connect().execute("SELECT name FROM sqlite_master")}
    assert "review_scope_decisions" not in tables


# ------------------------------------------- PF4 step 1: stored with the run

def test_summarise_is_the_routes_arithmetic():
    decisions = [scope_ledger.decision({"id": f"r{n}"}, code) for n, code in enumerate(
        ["compared", "needs_engineer", "row_label_not_on_sheet", "covered_by_checklist", "definition"])]
    s = cov.summarise(decisions)
    assert s["counts"] == {"checked": 1, "engineer": 1, "not_checked": 1,
                           "covered_by_checklist": 1, "does_not_apply": 1}
    assert (s["applicable"], s["checked_share"], s["adds_up"]) == (4, 25.0, True)
    assert s["line"].startswith("1 of 4 applicable requirement(s) checked (25.0%)")
    assert cov.summarise([])["line"] == "0 applicable requirements in this run (0 do not apply)"


def test_the_run_stores_the_coverage_the_route_reports(review_run):
    """PF4 step 1: at run end the run keeps its clause coverage (counts, the
    denominator, the line) from the same decisions the ledger holds, so the
    PF1 scorer reads it from a database copy and the route can never say a
    different number (rule 8)."""
    from app import comparison
    run, _ids, scope = review_run
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    stored = comparison.run_outcome(run, allowed_document_ids=scope)["clause_coverage"]
    assert stored == result["clause_coverage"]
    route = cov.for_run(run, allowed_document_ids=scope)
    assert (stored["counts"], stored["applicable"], stored["line"]) == (
        route["counts"], route["applicable"], route["line"])
    assert stored["adds_up"] is True and stored["applicable"] == 2       # 5 in scope, 3 do not apply
    assert stored["counts"]["checked"] == 1 and stored["counts"]["not_checked"] == 1
