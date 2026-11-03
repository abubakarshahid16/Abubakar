"""Standards by role and document kind (owner order 3 Nov): a procedure or study is not checked against equipment design
standards; the left-out count is in the run note; method standards still needed are named once; off changes nothing.
Invented documents and an invented table."""

from __future__ import annotations

import pytest

from app import applicability, db, kind_rules, kind_standards
from app.config import settings
from tests.test_754_required_vs_cited import _psv
from tests.test_1474_kind_chooses_rules import _set_kind
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401

TABLE = {
    "kinds_apply": {
        "datasheet": ["equipment design", "general"],
        "procedure": ["process/method", "general"],
        "study": ["process/method", "general"],
    },
    "method_standards": {"procedure": ["SAEP-901", "IEC 99999-1"]},
    "standards": {
        "SAES-Z-100": "equipment design",
        "SAES-Z-200": "equipment design",
        "SAEP-901": "process/method",
        "SAES-Z-300": "general",
    },
}


def _entry(sid, name):
    return {"id": sid, "filename": f"{name}.pdf", "identifier": name}


LIBRARY = [
    _entry("d1", "SAES-Z-100"),
    _entry("d2", "SAES-Z-200"),
    _entry("d3", "SAES-Z-300"),
    _entry("d4", "SAES-Z-999"),
]


def _selected(method="referenced"):
    return {
        sid: {"method": method, "identifier": None, "reason": "named"}
        for sid in ("d1", "d2", "d3", "d4")
    }


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", True)


@pytest.fixture
def kind(monkeypatch):
    holder = {"kind": "procedure", "state": "confirmed", "guess": False}
    monkeypatch.setattr(
        kind_rules,
        "_lookup",
        lambda document_id: (holder["kind"], holder["state"], holder["guess"]),
    )
    return holder


def test_a_procedure_leaves_out_equipment_design_standards_and_counts_them(on, kind):
    selected = _selected()
    result = kind_standards.apply(selected, "doc", LIBRARY, TABLE)
    assert result["count"] == 2 and result["identifiers"] == [
        "SAES-Z-100",
        "SAES-Z-200",
    ]
    assert (
        result["note"]
        == "2 standards left out: equipment design standards do not apply to a procedure"
    )
    assert [s for s, r in selected.items() if r.get("excluded_by_scope")] == [
        "d1",
        "d2",
    ]
    assert applicability.is_included(selected["d3"]) and applicability.is_included(
        selected["d4"]
    )  # general, unmapped
    assert not applicability.is_included(selected["d1"])


def test_a_datasheet_keeps_equipment_design_standards(on, kind):
    kind["kind"] = "datasheet"
    selected = _selected()
    assert kind_standards.apply(selected, "doc", LIBRARY, TABLE) is None
    assert not any(r.get("excluded_by_scope") for r in selected.values())


def test_a_manual_choice_a_guessed_or_unknown_kind_and_the_switch_off_leave_everything_in(
    monkeypatch, kind
):
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", False)
    selected = _selected()
    assert kind_standards.apply(selected, "doc", LIBRARY, TABLE) is None
    assert not any(r.get("excluded_by_scope") for r in selected.values())
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", True)
    manual = _selected(method="manual")
    kind_standards.apply(manual, "doc", LIBRARY, TABLE)
    assert not any(r.get("excluded_by_scope") for r in manual.values())
    for state, k, guess in (
        ("suggested", "procedure", True),
        ("needs_engineer", "unknown", False),
    ):
        kind.update(kind=k, state=state, guess=guess)
        again = _selected()
        assert kind_standards.apply(again, "doc", LIBRARY, TABLE) is None
        assert not any(r.get("excluded_by_scope") for r in again.values())


def test_method_standards_that_are_not_held_are_named_once_and_held_ones_are_not(
    on, kind
):
    held = [*LIBRARY, _entry("d5", "SAEP-901")]
    result = kind_standards.apply(_selected(), "doc", held, TABLE)
    assert result["needed"] == ["IEC 99999-1"]
    line = kind_standards.needed_line("procedure", result["needed"])
    assert line.startswith("Standard needed: IEC 99999-1") and "SAEP-901" not in line
    assert kind_standards.needed_line("procedure", []) is None


def test_select_drops_a_referenced_equipment_design_standard_for_a_procedure_and_persists_why(
    on,
    kind,
    monkeypatch,
    temp_storage,  # noqa: F811
):
    std = _doc(
        "std_z100", "SAES-Z-100.pdf", "COMPANY_STANDARD", document_number="SAES-Z-100"
    )
    sub = _psv()
    _set_kind(sub, "procedure", "confirmed")
    monkeypatch.setattr(kind_standards, "table", lambda path=None: TABLE)
    monkeypatch.setattr(
        applicability,
        "_match_referenced",
        lambda library, referenced: {
            std: {
                "method": applicability.METHOD_REFERENCED,
                "identifier": "SAES-Z-100",
                "reason": "named",
            }
        },
    )
    result = applicability.select(
        sub, allowed_document_ids=_scope(std, sub), persist=False
    )
    row = next(r for r in result["selected"] if r["standard_document_id"] == std)
    assert (
        row["included"] is False
        and row["excluded_by_scope"]
        == "equipment design standards do not apply to a procedure"
    )
    assert [
        r["standard_document_id"] for r in result["selected"] if r["included"]
    ] == []


def test_the_run_note_says_what_was_left_out_and_what_is_still_needed_once(
    on,
    kind,
    monkeypatch,
    temp_storage,  # noqa: F811
):
    std = _doc(
        "std_z100", "SAES-Z-100.pdf", "COMPANY_STANDARD", document_number="SAES-Z-100"
    )
    sub = _psv()
    monkeypatch.setattr(kind_standards, "table", lambda path=None: TABLE)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('run-1', ?, 'completed', 't', 't')",
            (sub,),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, selection_reason, selection_method,"
            " confidence, included, exclusion_reason, created_at) VALUES ('a1','run-1',?,'named','referenced',0.9,0,"
            " 'equipment design standards do not apply to a procedure','t')",
            (std,),
        )
    note = kind_standards.note_for_run(sub, _scope(std, sub))
    assert (
        note["roles_left_out"]
        == "1 standard left out: equipment design standards do not apply to a procedure"
    )
    assert note["standard_needed"].startswith("Standard needed: SAEP-901, IEC 99999-1")
    out = kind_rules.lines(
        {"requirement_split": {"kind_rules": {"blocked": False, "mark": None, **note}}}
    )
    assert [x["line"] for x in out] == [note["roles_left_out"], note["standard_needed"]]


def test_with_the_switch_off_the_note_is_exactly_what_it_was(
    monkeypatch,
    kind,
    temp_storage,  # noqa: F811
):
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", False)
    assert kind_standards.note_for_run("doc", frozenset()) is None
    assert (
        kind_rules.lines(
            {"requirement_split": {"kind_rules": {"blocked": False, "mark": None}}}
        )
        == []
    )
