"""A held datasheet check stores WHY it is held as a code from a closed set
(`hold_reason`, Part of #805 Cycle 2, owner order 10 Nov step 4), written where
the prose reason is written. No behaviour change: the stored prose is
byte-identical and the CRS is the same with or without the code. Invented
values only."""

from __future__ import annotations

import pytest

from app import crs_export, crs_mapping, db, deferred_value, hold_reason, review
from app import datasheet_checks as dc
from app.config import settings

DOC = "doc-hold"
RUN = "run-hold"
COND = {"role": "test_condition", "any": ["yes"]}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "hold.sqlite")
    monkeypatch.setattr(settings, "rule_auto_use_enabled", False)
    db.reset_connection()
    db.init_db()
    review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-11-10T00:00:00Z')",
            (DOC, "sheet.pdf", "sha-hold", "sheet.pdf"),
        )
    yield
    db.reset_connection()


def _fact(name, value, i, note=None):
    out = {
        "id": f"f{i}",
        "field_name": name,
        "field_label": name,
        "raw_value": value,
        "field_value": value,
        "raw_unit": None,
        "page": 2,
        "equipment_tag": None,
    }
    if note:
        out["value_note"] = note
    return out


def _item(item_id, condition=None, when_unknown=None):
    item = {
        "id": item_id,
        "text": "The body material is given",
        "rule": {"kind": "required", "field": "body_material"},
        "source": {"standard": "STD-1", "clause": "4.2"},
    }
    if condition:
        item["condition"] = condition
    if when_unknown:
        item["when_unknown"] = when_unknown
    return item


def _eval(item, roles):
    return dc.evaluate_item(item, roles, {}, None, dc.load_rules(), draft=True)


def _body(i, value):
    return _fact("body material", value, i)


def _cond(i, value):
    return _fact("test condition", value, i)


def _results(monkeypatch):
    """One invented result per code path, a decided one, and an 'other' hold."""
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", True)
    marked = _fact("body material", "CF8M", 6, note="TBA")
    deferred = deferred_value.hold_results(
        [_eval(_item("T-6"), {"body_material": [marked]})],
        [marked],
        dc.load_rules(),
        frozenset(),
    )
    other = {
        "id": "T-7",
        "text": "The set pressure is at most 10 barg",
        "rule": {
            "kind": "constant",
            "field": "set_pressure",
            "op": "<=",
            "value": 10,
            "unit": "barg",
        },
        "source": {"standard": "STD-1", "clause": "4.3"},
    }
    return [
        _eval(_item("T-1", COND), {}),
        _eval(
            _item("T-2", COND), {"test_condition": [_cond(1, "yes"), _cond(2, "no")]}
        ),
        _eval(_item("T-3", COND, "evaluate"), {}),
        _eval(_item("T-4"), {"body_material": [_body(3, "CF8M"), _body(4, "WCB")]}),
        _eval(_item("T-5"), {"body_material": [_body(5, "CF8M")]}),
        *deferred,
        _eval(other, {"set_pressure": [_fact("set pressure", "abc", 7)]}),
    ]


EXPECTED_CODE = {
    "T-1": hold_reason.APPLICABILITY_NOT_STATED,
    "T-2": hold_reason.APPLICABILITY_SEVERAL_VALUES,
    "T-3": hold_reason.APPLICABILITY_NOT_STATED_ABSENT,
    "T-4": hold_reason.FIELD_SEVERAL_VALUES,
    "T-5": None,  # decided (COMPLIANT): not held, no code
    "T-6": hold_reason.DEFERRED_MARKER,
    "T-7": hold_reason.OTHER,  # held for a reason with no named code: the fallback
}

_DRAFT = "DRAFT checklist, not signed off"
_BODY = f"The body material is given (STD-1 4.2; {_DRAFT})"
#: The prose each finding was stored with BEFORE the code existed (origin/main
#: 891e8917), copied byte for byte: (status, requirement, detail, severity).
BEFORE = {
    "T-1": (
        "NEEDS_ENGINEER_REVIEW",
        _BODY,
        "Could not be checked: whether it applies depends on the test condition, and the "
        "sheet does not state it.",
        "minor",
    ),
    "T-2": (
        "NEEDS_ENGINEER_REVIEW",
        _BODY,
        "Could not be checked: whether it applies depends on the test condition, and it has "
        "two different values on the sheet.",
        "minor",
    ),
    "T-3": (
        "NEEDS_ENGINEER_REVIEW",
        _BODY,
        "Could not be checked: the body material is not given, and whether it is needed "
        "depends on the test condition, which the sheet does not state.",
        "minor",
    ),
    "T-4": (
        "NEEDS_ENGINEER_REVIEW",
        _BODY,
        "Could not be checked: the body material has two different values on the sheet.",
        "minor",
    ),
    "T-5": (
        "COMPLIANT",
        _BODY,
        "Body material CF8M (page 2) is stated.",
        "observation",
    ),
    "T-6": (
        "NEEDS_ENGINEER_REVIEW",
        _BODY,
        "Could not be judged: the sheet marks a value this check rests on 'TBA', so it is "
        "deferred to the contractor. The numbers read COMPLIANT; engineer to confirm. "
        "Body material CF8M (page 2) is stated. The sheet marks this value 'TBA'.",
        "minor",
    ),
    "T-7": (
        "NEEDS_ENGINEER_REVIEW",
        f"The set pressure is at most 10 barg (STD-1 4.3; {_DRAFT})",
        "Could not be checked: the two values are not numbers on one scale and pressure "
        "basis.",
        "minor",
    ),
}


def _stored(monkeypatch) -> dict[str, dict]:
    dc.store(RUN, DOC, _results(monkeypatch), pages_read={2: "read"})
    rows = (
        db.connect()
        .execute("SELECT * FROM review_findings WHERE review_run_id = ?", (RUN,))
        .fetchall()
    )
    return {
        dict(r)["requirement_source_text"].split(":")[0].split()[-1]: dict(r)
        for r in rows
    }


def _id(result):
    return result["rule_id"]


# ------------------------------------------------------------ written where the prose is


def test_each_hold_path_carries_its_own_code_on_the_result(monkeypatch):
    got = {_id(r): r.get(hold_reason.KEY) for r in _results(monkeypatch)}
    assert got == {**EXPECTED_CODE, "T-5": None, "T-7": None}


def test_without_the_deferral_switch_no_deferral_code_is_written(monkeypatch):
    marked = _fact("body material", "CF8M", 6, note="TBA")
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", False)
    plain = deferred_value.hold_results(
        [_eval(_item("T-6"), {"body_material": [marked]})],
        [marked],
        dc.load_rules(),
        frozenset(),
    )
    assert plain[0]["status"] == "COMPLIANT" and hold_reason.KEY not in plain[0]


def test_a_decided_result_carries_no_code():
    result = _eval(_item("T-5"), {"body_material": [_body(5, "CF8M")]})
    assert result["status"] == "COMPLIANT" and hold_reason.KEY not in result


# ------------------------------------------------------------ stored on the finding


def test_store_writes_each_code_to_the_finding(monkeypatch):
    stored = _stored(monkeypatch)
    assert {k: v[hold_reason.COLUMN] for k, v in stored.items()} == EXPECTED_CODE
    for finding in stored.values():
        assert hold_reason.of(finding) == finding[hold_reason.COLUMN]


def test_every_stored_code_is_in_the_closed_set(monkeypatch):
    codes = {v[hold_reason.COLUMN] for v in _stored(monkeypatch).values()} - {None}
    assert codes and codes <= hold_reason.CODES


def test_a_not_held_status_stores_no_code_even_if_the_result_carried_one():
    result = {hold_reason.KEY: hold_reason.FIELD_SEVERAL_VALUES}
    assert hold_reason.stored(result, "COMPLIANT") is None
    assert (
        hold_reason.stored(result, "NEEDS_ENGINEER_REVIEW")
        == hold_reason.FIELD_SEVERAL_VALUES
    )
    assert (
        hold_reason.stored({hold_reason.KEY: "made_up"}, "NEEDS_ENGINEER_REVIEW")
        == "other"
    )


def test_the_reader_returns_only_codes_of_the_closed_set():
    assert hold_reason.of({"hold_reason_code": "deferred_marker"}) == "deferred_marker"
    assert hold_reason.of({"hold_reason_code": None}) is None
    assert hold_reason.of({}) is None  # a finding written before the column
    assert hold_reason.of({"hold_reason_code": "made_up"}) is None


def test_an_old_findings_table_gains_the_column(monkeypatch):
    with db.connect() as conn:
        conn.execute("ALTER TABLE review_findings DROP COLUMN hold_reason_code")
    review.ensure_schema()
    columns = {r[1] for r in db.connect().execute("PRAGMA table_info(review_findings)")}
    assert hold_reason.COLUMN in columns


# ------------------------------------------------------------ no behaviour change


def test_the_stored_prose_is_byte_identical_to_before(monkeypatch):
    stored = _stored(monkeypatch)
    assert set(stored) == set(BEFORE)
    for rule_id, (status, requirement, detail, severity) in BEFORE.items():
        f = stored[rule_id]
        assert f["compliance_status"] == status
        assert f["requirement"] == requirement
        assert (
            f["requirement_source_text"] == f"Datasheet check {rule_id}: {requirement}"
        )
        assert f["finding"] == f"Datasheet check: {detail}"
        assert f["ai_rationale"] == f"Datasheet check {rule_id}: {detail}"
        assert f["required_action"] == (
            "None." if status == "COMPLIANT" else "Engineer to check."
        )
        assert f["severity"] == severity
        assert f["reason_code"] is None  # the #921 column is untouched


def test_the_crs_is_the_same_with_and_without_the_code(monkeypatch):
    findings = list(_stored(monkeypatch).values())
    assert any(f[hold_reason.COLUMN] for f in findings)
    without = [
        {k: v for k, v in f.items() if k != hold_reason.COLUMN} for f in findings
    ]
    shuffled = [{**f, hold_reason.COLUMN: hold_reason.OTHER} for f in findings]
    rows = crs_mapping.build_crs_rows(findings, [], "sheet.pdf")
    assert rows  # the held checks do reach the CRS, so the comparison is not of nothing
    assert rows == crs_mapping.build_crs_rows(without, [], "sheet.pdf")
    assert rows == crs_mapping.build_crs_rows(shuffled, [], "sheet.pdf")
    meta = {"project": "EXAMPLE PROJECT", "review_run_id": RUN}
    assert crs_export.build_crs_view(rows, meta) == crs_export.build_crs_view(
        crs_mapping.build_crs_rows(without, [], "sheet.pdf"), meta
    )
