"""Order 139 part 2, spec d: permanent numbers and decisions when rows merge.

One comment per datasheet field means a field's clauses, which were rows of
their own (each maybe numbered and confirmed by an engineer), are now ONE row
keyed on the field. Here, on `main._crs_content` over a seeded run:

  * an issued per-clause number now inside a field row is not carried
    forward beside it as a second row;
  * the field row names the numbers it replaces (both copies), so the number
    an engineer confirmed is never silently dropped;
  * the field row is the engineer's only when EVERY clause was confirmed
    before (#986: decided only when all its findings are);
  * a machine draft's number (not issued) is not printed again;
  * a rejected field row's number is withdrawn.

Synthetic sheet only (invented fields and clauses, no client text), via
`test_review_screen`'s world.
"""
from __future__ import annotations

import uuid

from app import access, comparison, crs_mapping, crs_numbers, db, main, submittal_review
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

FIELD = "Design pressure"


def _scope(scope):
    return access.AccessScope(user_id="eng-1", allowed_document_ids=scope)


def _add_blanks(run, clauses=("4.1", "6.2"), field=FIELD) -> list[str]:
    """Two (or more) findings: the same datasheet field left blank, raised by
    different clauses - one field row since order 139 part 2."""
    conn = db.connect()
    base = dict(conn.execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? LIMIT 1", (run,)).fetchone())
    fact = conn.execute("SELECT id FROM submittal_facts WHERE field_label = ?",
                        (field,)).fetchone()["id"]
    ids = []
    for clause in clauses:
        row = {**base, "id": str(uuid.uuid4()), "compliance_status": "MISSING_INFORMATION",
               "fact_id": fact, "contractor_page": 1, "standard_clause": clause,
               "requirement_id": None, "matched_phrase": field.lower(),
               "requirement_source_text": f"{clause} The {field.lower()} shall be stated ({clause}).",
               "contractor_evidence_text": "", "confirmed_by": None, "engineer_comment": None,
               "approval_status": "pending"}
        marks = ",".join("?" for _ in row)
        conn.execute(f"INSERT INTO review_findings ({','.join(row)}) VALUES ({marks})",
                     tuple(row.values()))
        ids.append(row["id"])
    conn.commit()
    return ids


def _member_keys(run, scope, ids) -> list[str]:
    """Each finding's per-clause key - what its own row was numbered under
    before rows were one per field."""
    findings = [f for f in submittal_review.list_run_findings(run, allowed_document_ids=scope)
                if f["id"] in ids]
    comparison.attach_crs_context(findings)
    by_id = {f["id"]: crs_mapping.finding_member_key(f) for f in findings}
    return [by_id[i] for i in ids]


def _old_number(sub, run, key, *, issued=True) -> str:
    """A number an earlier per-clause row held (issued = an engineer's)."""
    crs_scope, label = main._crs_scope_of(sub)
    record = crs_numbers.assign(crs_scope, label, [key], document_id=sub, review_run_id=run,
                                snapshots={key: {"comment": "an earlier per-clause comment"}},
                                user_id="eng-1", issued=issued)
    return record[key]["ref"]


def _field_row(rows):
    [row] = [r for r in rows if r.get("row_kind") == crs_mapping.ROW_KIND_MISSING_INFORMATION]
    return row


def test_a_field_row_stands_on_both_clauses(world):  # noqa: F811
    _sub, run, scope = world
    ids = _add_blanks(run)
    rows, *_ = main._crs_content(run, _scope(scope))
    row = _field_row(rows)
    assert sorted(row["finding_ids"]) == sorted(ids)
    assert row["comment"].startswith(f"Contractor to provide {FIELD}.\n")
    assert "Supporting clauses (2):" in row["comment"]


def test_an_issued_per_clause_number_is_not_carried_forward_twice(world):  # noqa: F811
    sub, run, scope = world
    ids = _add_blanks(run)
    first, _second = _member_keys(run, scope, ids)
    ref = _old_number(sub, run, first)
    rows, *_ = main._crs_content(run, _scope(scope))
    carried = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_CARRIED_FORWARD]
    assert carried == [], "the clause is inside the field row: no second row for it"
    assert ref in _field_row(rows)["comment"]


def test_grouped_row_lists_the_earlier_comments_it_replaces(world):  # noqa: F811
    sub, run, scope = world
    ids = _add_blanks(run)
    first, second = _member_keys(run, scope, ids)
    refs = [_old_number(sub, run, first), _old_number(sub, run, second)]
    for copy in ("internal", "issue"):
        rows, *_ = main._crs_content(run, _scope(scope), copy)
        row = _field_row(rows)
        assert row["replaces_refs"] == refs
        assert row["comment"].endswith(
            f"\nReplaces earlier comments {refs[0]}, {refs[1]} (now one comment per field).")
    # The old numbers stay in their table, Open, never reused.
    crs_scope, _label = main._crs_scope_of(sub)
    stored = crs_numbers.lookup(crs_scope, [first, second])
    assert [stored[k]["status"] for k in (first, second)] == [crs_numbers.OPEN] * 2


def test_grouped_row_is_confirmed_only_when_every_member_was(world):  # noqa: F811
    sub, run, scope = world
    ids = _add_blanks(run)
    first, second = _member_keys(run, scope, ids)
    ref = _old_number(sub, run, first)
    rows, *_ = main._crs_content(run, _scope(scope))
    row = _field_row(rows)
    assert row["engineer_confirmed"] is False, "one of two clauses confirmed is not the row"
    assert row["comment"].endswith(f"Replaces earlier comment {ref} (now one comment per field).")
    _old_number(sub, run, second)
    rows, *_ = main._crs_content(run, _scope(scope))
    assert _field_row(rows)["engineer_confirmed"] is True


def test_a_machine_draft_number_is_not_printed_again(world):  # noqa: F811
    sub, run, scope = world
    ids = _add_blanks(run)
    first, _second = _member_keys(run, scope, ids)
    draft = _old_number(sub, run, first, issued=False)
    rows, *_ = main._crs_content(run, _scope(scope))
    row = _field_row(rows)
    assert draft not in row["comment"] and "replaces_refs" not in row
    assert row["engineer_confirmed"] is False


def test_rejected_field_row_number_is_withdrawn(world):  # noqa: F811
    sub, run, scope = world
    ids = _add_blanks(run)
    first, _second = _member_keys(run, scope, ids)
    old = _old_number(sub, run, first)
    rows, *_ = main._crs_content(run, _scope(scope))
    field_key = _field_row(rows)["crs_row_key"]
    crs_scope, label = main._crs_scope_of(sub)
    crs_numbers.assign(crs_scope, label, [field_key], document_id=sub, review_run_id=run,
                       user_id="eng-1")
    with db.connect() as conn:
        conn.executemany("UPDATE review_findings SET approval_status = 'rejected' WHERE id = ?",
                         [(i,) for i in ids])
    _rows, meta, *_ = main._crs_content(run, _scope(scope))
    assert {field_key, first} <= set(meta["rejected_row_keys"])
    main._mint_crs_numbers(run, _scope(scope))
    stored = crs_numbers.lookup(crs_scope, [field_key, first])
    assert stored[field_key]["status"] == crs_numbers.WITHDRAWN
    assert stored[first]["status"] == crs_numbers.WITHDRAWN
    assert crs_numbers.parse_ref(old), "the old number is kept (never reused), withdrawn"


def test_a_member_key_still_on_the_sheet_is_never_withdrawn(world):  # noqa: F811
    """Two findings with one subject (the same clause words, field and value),
    one rejected: the other still stands on the field row, so neither the
    row's number nor that clause's earlier number is withdrawn."""
    sub, run, scope = world
    [kept] = _add_blanks(run, ("4.1",))
    [rejected] = _add_blanks(run, ("4.1",))
    [member] = _member_keys(run, scope, [kept])
    assert _member_keys(run, scope, [rejected]) == [member]
    _old_number(sub, run, member)
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET approval_status = 'rejected' WHERE id = ?",
                     (rejected,))
    rows, meta, *_ = main._crs_content(run, _scope(scope))
    row = _field_row(rows)
    assert row["finding_ids"] == [kept]
    assert row["comment_key"] not in meta["rejected_row_keys"]
    assert member not in meta["rejected_row_keys"]
    main._mint_crs_numbers(run, _scope(scope))
    crs_scope, _label = main._crs_scope_of(sub)
    assert crs_numbers.lookup(crs_scope, [member])[member]["status"] == crs_numbers.OPEN
