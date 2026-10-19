"""Order 133 (117a item 4): one truth for the review tiers.

The rules' data has one home, `backend/app/reference/review_tiers.json`, and the
logic is pinned by one case table, `contracts/fixtures/review_tier_cases.json`,
which the screen's `crs/tiers.parity.test.ts` runs too. So a change to one side
fails until the other side and the table agree. Known disagreements (D1, D2) are
pinned with each side's own answer and fail here if the answers become equal:
a fix moves the case into `cases`. Display only. Invented data.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest

from app import comparison, review_tiers
from app.api import run_summary
from app.schemas import ReviewFinding

T = review_tiers
REPO = Path(__file__).resolve().parents[2]
TABLE = json.loads(
    (REPO / "contracts" / "fixtures" / "review_tier_cases.json").read_text(
        encoding="utf-8"
    )
)
RULES = json.loads(T.RULES_PATH.read_text(encoding="utf-8"))


def facts_of(name: str) -> review_tiers.RunFacts:
    raw = TABLE["facts"][name]
    library = raw["library_standard_ids"]
    return T.RunFacts(
        pages_not_read=frozenset(raw["pages_not_read"]),
        reader_timed_out_pages=frozenset(raw["reader_timed_out_pages"]),
        missing_standards=tuple(raw["missing_standards"]),
        library_standard_ids=None if library is None else frozenset(library),
    )


def finding_of(over: dict) -> dict:
    return {**TABLE["base_finding"], **over}


def answer(expected: dict) -> tuple:
    return expected["tier"], expected["label"], expected["reason"]


def by_name(rows: list[dict]):
    return pytest.mark.parametrize("case", rows, ids=[r["name"] for r in rows])


@by_name(TABLE["cases"])
def test_every_shared_case_tiers_as_the_table_says(case):
    got = T.tier_of(finding_of(case["finding"]), facts_of(case["facts"]))
    assert got == answer(case["expected"])


@by_name(TABLE["disagreements"])
def test_a_known_disagreement_stays_pinned_until_it_is_fixed(case):
    got = T.tier_of(finding_of(case["finding"]), facts_of(case["facts"]))
    assert got == answer(case["python"])
    assert answer(case["python"]) != answer(case["screen"]), (
        f"{case['id']}: the answers became equal: move the case to cases"
    )


@by_name(TABLE["removed"])
def test_a_removed_finding_is_in_no_tier(case):
    tier = T.tier_of(finding_of(case["finding"]), facts_of("full"))[0]
    assert (tier == T.REMOVED) is case["removed"]


@by_name(TABLE["counts"])
def test_counts_follow_the_table(case):
    findings = [
        finding_of({"id": str(i), **over}) for i, over in enumerate(case["findings"])
    ]
    counts = T.summarise(findings, facts_of(case["facts"]))["counts"]
    assert {k: counts[k] for k in case["expected"]} == case["expected"]
    assert counts["total"] == len(findings)


def _literals(field: str) -> list[str]:
    annotation = run_summary.TierRow.model_fields[field].annotation
    literal = next(
        a for a in (annotation, *get_args(annotation)) if get_origin(a) is Literal
    )
    return list(get_args(literal))


def test_the_api_literals_are_the_rule_data():
    assert _literals("tier") == RULES["tiers"]
    assert _literals("label") == RULES["labels"]
    assert _literals("reason") == RULES["reasons"]


def test_the_screens_pairing_guess_is_comparisons_own():
    assert RULES["pairing_guess"] == {
        "always": [comparison.METHOD_FIELD_NAME],
        "held": {
            "match_method": comparison.METHOD_MODEL_CHOICE,
            "compliance_status": comparison.NEEDS_ENGINEER_REVIEW,
        },
    }


def test_one_predicate_per_unsettled_reason_and_no_other():
    assert set(T.PREDICATES) == set(RULES["unsettled_order"])
    assert len(RULES["unsettled_order"]) == len(set(RULES["unsettled_order"]))
    assert set(RULES["reasons"]) == {
        *RULES["unsettled_order"],
        RULES["fallback_reason"],
        RULES["missing_information"]["not_in_library_reason"],
    }


def _is_rules_key_read(node: ast.Constant, parent: ast.AST | None) -> bool:
    """`RULES["key"]` or `RULES.get("key")`: a top-level key name of the data,
    used to read it. Any other use of the same word is a literal of its own."""
    if not isinstance(node.value, str) or node.value not in RULES:
        return False
    if isinstance(parent, ast.Subscript) and parent.slice is node:
        return isinstance(parent.value, ast.Name) and parent.value.id == "RULES"
    return (
        isinstance(parent, ast.Call)
        and node in parent.args
        and isinstance(parent.func, ast.Attribute)
        and parent.func.attr == "get"
        and isinstance(parent.func.value, ast.Name)
        and parent.func.value.id == "RULES"
    )


def _code_strings(source: str) -> set[str]:
    """Every string literal in the module's code, docstrings and reads of the
    data by its top-level key name (`RULES["needs_you"]`) left out."""
    tree = ast.parse(source)
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    parents = {
        id(child): node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
        and not _is_rules_key_read(node, parents.get(id(node)))
    }


RULE_WORDS = {
    *RULES["tiers"],
    *RULES["labels"],
    *RULES["reasons"],
    *RULES["tier_c_statuses"],
    *RULES["status_tiers"],
    RULES["missing_information"]["status"],
    *RULES["phrases"].values(),
    RULES["fold"]["pattern"],
    RULES["rule_not_proven_trust_label"],
    RULES["safety_tick_status"],
    RULES["removed"]["approval_status"],
    *RULES["count_keys"].values(),
}


def _own_rule_literals(source: str) -> set[str]:
    return _code_strings(source) & RULE_WORDS


def test_review_tiers_keeps_no_rule_literal_of_its_own():
    own = _own_rule_literals(Path(T.__file__).read_text(encoding="utf-8"))
    assert not own, f"review_tiers.py keeps rule literals of its own: {sorted(own)}"


def test_the_fence_lets_through_only_a_read_of_the_data_by_its_key():
    """A count key written out by hand fails the fence even where it is also
    a top-level key name of the data ("needs_you")."""
    source = Path(T.__file__).read_text(encoding="utf-8")
    assert "needs_you" in RULES and "needs_you" in RULES["count_keys"].values()
    assert not _own_rule_literals(
        'x = RULES["needs_you"]\ny = RULES.get("needs_you")\n'
    )
    assert _own_rule_literals(source + '\ncounts = {"needs_you": 0}\n') == {"needs_you"}
    assert _own_rule_literals(source + '\nn = counts["needs_you"]\n') == {"needs_you"}
    assert _own_rule_literals(source + '\nn = row.get("needs_you")\n') == {"needs_you"}


def _status_words(rules: dict) -> set[str]:
    """Every compliance-status word the data names: under a key that says
    "status" (an engineer's approval_status is not one), and the keys of
    `status_tiers`."""
    words: set[str] = set()

    def walk(node, under_status: bool = False):
        if isinstance(node, dict):
            for key, value in node.items():
                is_status = "status" in key and "approval" not in key
                if is_status and isinstance(value, dict):
                    words.update(value)
                walk(value, under_status or (is_status and not isinstance(value, dict)))
        elif isinstance(node, list):
            for item in node:
                walk(item, under_status)
        elif isinstance(node, str) and under_status:
            words.add(node)

    walk(rules)
    return words


def _compliance_statuses() -> set[str]:
    annotation = ReviewFinding.model_fields["compliance_status"].annotation
    literal = next(
        a for a in (annotation, *get_args(annotation)) if get_origin(a) is Literal
    )
    return set(get_args(literal))


def test_every_status_the_rule_data_names_is_a_status_the_backend_stores():
    named = _status_words(RULES)
    assert {
        *RULES["status_tiers"],
        *RULES["tier_c_statuses"],
        RULES["missing_information"]["status"],
        RULES["safety_tick_status"],
        RULES["pairing_guess"]["held"]["compliance_status"],
    } <= named
    assert RULES["removed"]["approval_status"] not in named
    unknown = named - _compliance_statuses()
    assert not unknown, (
        f"the rule data names statuses the backend never stores: {unknown}"
    )


@pytest.mark.parametrize(
    "where",
    [
        lambda r: r["tier_c_statuses"].append("BOGUS"),
        lambda r: r["status_tiers"].update(BOGUS={"tier": "A", "label": "Met"}),
        lambda r: r["missing_information"].update(status="BOGUS"),
        lambda r: r.update(safety_tick_status="BOGUS"),
        lambda r: r["pairing_guess"]["held"].update(compliance_status="BOGUS"),
    ],
    ids=["tier_c", "status_tiers", "missing", "safety_tick", "pairing_held"],
)
def test_the_status_check_sees_a_bogus_status_in_each_place(where, monkeypatch):
    rules = copy.deepcopy(RULES)
    where(rules)
    monkeypatch.setattr(T, "RULES", rules)
    assert "BOGUS" in _status_words(T.RULES) - _compliance_statuses()


def _unique_cases(cases: list[dict]) -> set[str]:
    """(finding, facts, expected) triples, each counted once."""
    return {
        json.dumps([c["finding"], c["facts"], c["expected"]], sort_keys=True)
        for c in cases
    }


def test_the_table_is_not_vacuous():
    cases = TABLE["cases"]
    unique = _unique_cases(cases)
    assert len(unique) >= 30
    assert len(unique) == len(cases), "a case repeats another's input and answer"
    told = {c["expected"]["reason"] for c in cases}
    assert set(RULES["reasons"]) <= told
    statuses = {finding_of(c["finding"]).get("compliance_status") for c in cases}
    assert set(RULES["status_tiers"]) <= statuses
    assert {r["removed"] for r in TABLE["removed"]} == {True, False}
    assert TABLE["disagreements"] and TABLE["counts"]
