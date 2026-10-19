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
import json
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest

from app import comparison, review_tiers
from app.api import run_summary

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


def _code_strings(path: Path) -> set[str]:
    """Every string literal in the module's code, docstrings left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
    }


def test_review_tiers_keeps_no_rule_literal_of_its_own():
    rule_words = {
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
    # the data's own key names (e.g. "needs_you") are how it is read, not rules
    own = (_code_strings(Path(T.__file__)) - set(RULES)) & rule_words
    assert not own, f"review_tiers.py keeps rule literals of its own: {sorted(own)}"


def test_the_table_is_not_vacuous():
    cases = TABLE["cases"]
    assert len(cases) >= 30
    told = {c["expected"]["reason"] for c in cases}
    assert set(RULES["reasons"]) <= told
    statuses = {finding_of(c["finding"]).get("compliance_status") for c in cases}
    assert set(RULES["status_tiers"]) <= statuses
    assert {r["removed"] for r in TABLE["removed"]} == {True, False}
    assert TABLE["disagreements"] and TABLE["counts"]
