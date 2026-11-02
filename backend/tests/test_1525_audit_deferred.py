"""#1525 follow-up: the audit's Pass count must say which Passes are on a
contractor-deferred value ('By Contractor' / TBA), which owner decision D2
makes Query - the same count the bench (#1471) shows. Invented findings."""

from __future__ import annotations

from tools import crs_bench

from app import deferred_pass, review_audit, review_audit_detail


def _f(i, status, finding):
    return {"id": f"f{i}", "compliance_status": status, "finding": finding}


FINDINGS = [
    _f(1, "COMPLIANT", "Set pressure 340 psig meets the limit."),
    _f(2, "COMPLIANT", "Set pressure By Contractor meets the limit."),
    _f(3, "COMPLIANT", "Material TBA meets the limit."),
    _f(4, "NON_COMPLIANT", "Back pressure TBA exceeds the limit."),
    _f(5, "NEEDS_ENGINEER_REVIEW", "Value by contractor."),
    _f(6, "NON_COMPLIANT", "Rating By Contractor below the limit."),
]


def test_the_audit_counts_passes_on_a_deferred_value_apart():
    rules = review_audit._rules_section(FINDINGS)
    assert rules["pass_on_deferred"] == 2
    assert rules["pass_on_deferred_note"].startswith("2 of 3 Pass")


def test_the_audit_and_the_bench_use_one_test():
    assert crs_bench._deferred_pass is deferred_pass.is_deferred_pass
    assert sum(map(deferred_pass.is_deferred_pass, FINDINGS)) == 2


def test_no_pass_gives_zero_with_its_boundary():
    rules = review_audit._rules_section([FINDINGS[3]])
    assert rules["pass_on_deferred"] == 0
    assert (
        rules["pass_on_deferred_note"]
        == "0 of 0 Pass rows are on a contractor-deferred value"
    )


def test_the_note_is_in_the_rendered_rules_section_and_not_listed_as_unrecorded(
    monkeypatch,
):
    import inspect

    src = inspect.getsource(review_audit)
    assert "pass_on_deferred_note" in src.split("## 4. Rules", 1)[1][:600]
    monkeypatch.setattr(
        review_audit_detail,
        "_nothing_read_gate",
        lambda *_: {"gate": "nothing-read guard", "count": None},
    )
    counts = {"wrong": None, "untrue": None, "pass_on_deferred": 0}
    steps = {"CHECKLIST": {"counts": {}}}
    gates = review_audit_detail.gates_section({}, {}, [], counts, steps)
    assert "pass_on_deferred" not in gates["not_recorded_on_the_run"]
