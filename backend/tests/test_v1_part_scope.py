"""Owner 3 Nov 13:50: the Part/Appendix scope check also narrows rulebook version 1 requirements. Invented only."""

from __future__ import annotations

from app import equipment_scope, rule_part_scope, scope_ledger, v1_part_scope
from app.config import settings
from app.rule_part_scope import OUTSIDE_EQUIPMENT_SCOPE, Scope

REQS = [
    {
        "id": "r-in",
        "standard_document_id": "std-1",
        "page": 3,
        "clause": "4.1",
        "source_text": "In.",
    },
    {
        "id": "r-out",
        "standard_document_id": "std-1",
        "page": 9,
        "clause": "A.1",
        "source_text": "Out.",
    },
    {
        "id": "r-unknown",
        "standard_document_id": "std-1",
        "page": 5,
        "clause": "5.1",
        "source_text": "Unk.",
    },
]


def fake(conn, rule, equipment_type):
    quote = rule["quote"]
    if quote == "Out.":
        return Scope(
            "OUTSIDE",
            OUTSIDE_EQUIPMENT_SCOPE,
            "Part A (page 9) is written for other equipment",
        )
    if quote == "Unk.":
        return Scope("UNKNOWN", "scope_not_established", "code cannot place the rule")
    return Scope("STANDARD", None, "the standard's own scope")


def setup(monkeypatch, on=True):
    monkeypatch.setattr(settings, "v1_part_scope_enabled", on)
    monkeypatch.setattr(rule_part_scope, "of_rule", fake)
    monkeypatch.setattr(v1_part_scope, "connect", lambda: None)


def test_off_every_requirement_is_read(monkeypatch):
    setup(monkeypatch, on=False)
    left = []
    assert v1_part_scope.gate(REQS, "Pressure Vessel", left) == REQS and left == []


def test_on_only_the_requirement_outside_its_part_scope_is_left_out_and_counted(
    monkeypatch,
):
    setup(monkeypatch)
    left = []
    kept = v1_part_scope.gate(REQS, "Pressure Vessel", left)
    assert [r["id"] for r in kept] == ["r-in", "r-unknown"]  # unknown scope stays in
    assert [i["requirement"]["id"] for i in left] == ["r-out"]
    assert left[0]["code"] == v1_part_scope.CODE and "Part A" in left[0]["detail"]


def test_no_equipment_type_leaves_everything_in(monkeypatch):
    setup(monkeypatch)
    left = []
    assert v1_part_scope.gate(REQS, None, left) == REQS and left == []


def test_the_review_gate_calls_it_and_the_ledger_knows_the_reason(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(equipment_scope, "submittal_kind", lambda _s: None)
    left = []
    kept, _result = equipment_scope.gate_for_run(
        REQS, {"equipment_type": "Pressure Vessel"}, [], "sub", {}, left
    )
    assert "r-out" not in [r["id"] for r in kept]
    assert v1_part_scope.CODE in scope_ledger.REASONS


def test_the_gate_reuses_the_threads_connection_and_never_closes_it(monkeypatch):
    """`db.connect()` hands back the thread's one shared connection, so it is not opened here and must not be closed
    here: closing it would break every later query on the thread."""
    setup(monkeypatch)
    opened = []

    class Shared:
        closed = False

        def close(self):
            self.closed = True

    shared = Shared()
    monkeypatch.setattr(v1_part_scope, "connect", lambda: opened.append(1) or shared)
    v1_part_scope.gate(REQS, "Pressure Vessel", [])
    assert opened == [1] and shared.closed is False
    from app import db

    assert db.connect() is db.connect()  # the same shared object every call
