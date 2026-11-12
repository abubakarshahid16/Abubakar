"""The calculator STEP of the AI review job (owner, 12 Nov 2026, STATE section 37; `ONE-REVIEWER.md`, PR 3).

Behind `AI_REVIEW_CALCULATOR_ENABLED` (default off). Off: `step` returns at once, before any read, so the job's requests, lines and files are byte-for-byte
what they were. On: BEFORE the first reader call, for a datasheet, the old rule check's code comparisons are made as lines of THIS run:

  1. the paper's STORED datasheet facts are read (`datasheets.list_facts`); none stored: the step says so and makes no line (the reader's own field list
     is a later PR); the facts are the classic reading's, the same ones its comparison used;
  2. each numeric rule item of the run's list is PAIRED with the facts of the same quantity (`subject_pairing.quantity_words` equality, then
     `match_rules.refusal`: the classic pairing's own refusals); no pair, no line: the reader handles absence;
  3. every pair is compared by `agent_review_calculator.numeric_line` (`comparison.compare`), and the approved checklist's results come from
     `checklist_scope.evaluate` (the classic step's own call) through `agent_review_calculator.checklist_lines`;
  4. each line goes through the SAME exit as a model line (`agent_review_wording.final_cap`: tier from the current label table, the proof asked again) and is
     STORED at once (`store`), before any reader call: a run that stops early keeps them; a resumed run writes the same ids again (an upsert).

The step is code only: no model call, no spend, the same on the Claude lane and the local one. It NEVER fails the run: an error is logged by its type and
recorded on the run ("the calculator did not run: <reason>"), never an empty "all fine". Returns the final lines; the job's CRS and counts include them
(`plan["code_lines"]`, `plan["calculator"]`).
"""

from __future__ import annotations

import logging
from collections import Counter

from . import (
    agent_review_calculator as calc,
)
from . import (
    agent_review_wording as wording,
)
from .agent_review_request import ClauseCache, DbPages
from .config import settings

log = logging.getLogger(__name__)

NOT_RUN = "the calculator did not run"


def enabled() -> bool:
    return bool(settings.ai_review_calculator_enabled)


def runner_done(stored: dict) -> dict:
    """The stored lines the runner may resume from: a code line has no plan item, so the runner never re-caps it."""
    return {
        k: v
        for k, v in stored.items()
        if not v.get("error") and v.get("source") != calc.SOURCE
    }


def counts_with(counts: dict, plan: dict) -> dict:
    """The run's counts plus the calculator's summary (nothing added with its setting off)."""
    if plan.get("calculator"):
        counts["calculator"] = plan["calculator"]
    return counts


def _note(reason: str) -> dict:
    return {"ran": False, "reason": f"{NOT_RUN}: {reason}", "lines": 0}


def _numeric_items(items: list[dict]) -> list[dict]:
    """The rule items a code comparison can judge: a limit (comparator and value) or a range, from a stored rule row (source "rule")."""
    out = []
    for it in items:
        if it.get("source") == "skill" or it.get("rule_kind") not in ("limit", "range"):
            continue
        has_limit = it.get("comparator") and it.get("value") is not None
        has_range = it.get("value_low") is not None and it.get("value_high") is not None
        if has_limit or has_range:
            out.append(it)
    return out


def pair(
    item: dict, requirement: dict, facts: list[dict], sheet: str | None
) -> list[dict]:
    """The facts that answer this rule: not blank, the SAME quantity words as the rule's field, and no refusal of the classic pairing
    (`match_rules.refusal`: unit dimension, equipment domain, table input, compound term, qualifier ...). Never a guess: none, no pair."""
    from . import match_rules, subject_pairing

    field = (item.get("field_roles") or [None])[0]
    wanted = subject_pairing.quantity_words(field, sheet)
    if not wanted:
        return []
    out = []
    for f in facts:
        if (
            f.get("is_blank")
            or subject_pairing.quantity_words(
                f.get("field_name") or f.get("field_label"), sheet
            )
            != wanted
        ):
            continue
        if match_rules.refusal(requirement, f, sheet=sheet) is None:
            out.append(f)
    return out


def step(
    conn,
    run_id: str,  # noqa: ARG001 - the job's signature
    submittal: str,
    kind,
    plan: dict,
    *,
    store,
    tier_lookup,
) -> list[dict]:
    """Make, finish and STORE the calculator's lines; set `plan["calculator"]` (what ran, in words and counts). Setting off: `[]` and nothing else."""
    if not enabled():
        return []
    try:
        lines, summary = _run(
            conn, submittal, kind, plan, store=store, tier_lookup=tier_lookup
        )
    except Exception as exc:  # noqa: BLE001 - the calculator never fails the review; the run says it did not run
        log.warning("calculator: did not run (%s)", type(exc).__name__)
        lines, summary = [], _note(f"an error ({type(exc).__name__})")
    plan["calculator"] = summary
    plan["code_lines"] = lines
    return lines


def _run(conn, submittal, kind, plan, *, store, tier_lookup) -> tuple[list[dict], dict]:
    from . import (
        checklist_scope,
        classification,
        datasheets,
        degraded_read,
        match_rules,
    )

    if not (kind.known and kind.kind == "datasheet"):
        return [], _note("the paper is not a datasheet")
    facts = datasheets.list_facts(
        submittal, allowed_document_ids=frozenset({submittal})
    )
    if not facts:
        return [], _note("no datasheet value is stored for this paper yet")
    pages = DbPages(conn, submittal).pages
    cache = ClauseCache(plan.get("cache"))
    stored = classification.of_document(submittal) or {}
    sheet = match_rules.sheet_kind(
        facts, stored.get("equipment_type") or kind.equipment_type
    )
    made: list[dict] = []
    considered = paired = 0
    for item in _numeric_items(plan.get("items") or []):
        considered += 1
        req = {
            **calc.requirement_from_item(item),
            "field": (item.get("field_roles") or [None])[0],
            "subject": (item.get("field_roles") or [None])[0],
        }
        for fact in pair(item, req, facts, sheet):
            paired += 1
            line = calc.numeric_line(
                item, req, fact, submittal_facts=facts, page_text=pages.get(fact.get("page")),
                clause_quote=cache.text(item.get("rule_quote_ref")), clause_text=cache.text(item.get("clause_quote_ref")),
            )  # fmt: skip
            made.append(
                wording.final_cap(line, item, tier_lookup, paper_kind=kind.kind)
            )
    results = degraded_read.hold(
        checklist_scope.evaluate(facts, stored, pages), submittal
    )
    for line in calc.checklist_lines(results, page_texts=pages):
        made.append(wording.final_cap(line, line, tier_lookup, paper_kind=kind.kind))
    for (
        line
    ) in made:  # stored BEFORE the first reader call: a run that stops early keeps them
        store(line, None)
    by_class = Counter(ln.get("verdict_class") for ln in made)
    return made, {
        "ran": True,
        "lines": len(made),
        "facts": len(facts),
        "rules_considered": considered,
        "pairs": paired,
        "by_class": dict(by_class),
        "reasons": dict(
            Counter(
                ln.get("reason_code") for ln in made if ln.get("verdict") == "Query"
            )
        ),
    }
