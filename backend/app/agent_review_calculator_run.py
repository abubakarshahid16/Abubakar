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
from . import agent_review_calculator_cells as cells_mod
from . import agent_review_pass_guards as guards
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
    from . import agent_review_rule_choice as rule_choice

    return {
        k: v
        for k, v in stored.items()
        if not v.get("error")
        and str(v.get("source") or "").strip().casefold() != calc.SOURCE
        and not rule_choice.is_group_line(
            v
        )  # a rule choice's group line is not a plan item either
    }


def step_job(run_id: str, submittal: str, kind, plan: dict, tier_lookup) -> list[dict]:
    """`step` as the review job calls it: the job's own database connection, and its `store_line` as the place the lines are kept before the first reader call."""
    from . import agent_review_jobs
    from .db import connect

    return step(
        connect(),
        run_id,
        submittal,
        kind,
        plan,
        store=lambda line, trace: agent_review_jobs.store_line(run_id, line, trace),
        tier_lookup=tier_lookup,
    )


def finish(plan: dict, runner) -> tuple[list[dict], dict]:
    """The lines of a finished (or stopped) run, the runner's then the calculator's, and the counts of both with the calculator's summary."""
    from . import agent_review_run as runner_mod

    lines = (
        [
            runner.lines[k]
            for i in plan["items"]
            if (k := str(i["item_id"])) in runner.lines
        ]
        if runner
        else []
    )
    lines += plan.get("extra_lines") or []  # the rule choice's group lines
    lines += plan.get("code_lines") or []
    return lines, counts_with(runner_mod.counts_of(lines, runner), plan)


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
    item: dict,
    requirement: dict,
    facts: list[dict],
    sheet: str | None,
    why: Counter | None = None,
) -> list[dict]:
    """The facts that answer this rule: not blank, the SAME quantity words as the rule's field, and no refusal of the classic pairing
    (`match_rules.refusal`: unit dimension, equipment domain, table input, compound term, qualifier ...). Never a guess: none, no pair.
    `why` (a Counter) takes the reason of every fact that did not pair, in words, so a run that pairs nothing says why."""
    from . import match_rules, subject_pairing

    why = Counter() if why is None else why
    # the label's own field first, then the item's roles (the Pass guard's reading)
    names = guards.field_names(item)
    field = names[0] if names else None
    wanted = subject_pairing.quantity_words(field, sheet)
    if not wanted:
        why["the rule names no field the code can match"] += 1
        return []
    out = []
    for f in facts:
        if (
            subject_pairing.quantity_words(
                f.get("field_name") or f.get("field_label"), sheet
            )
            != wanted
        ):
            continue
        if f.get("is_blank"):
            why["the value on the paper is blank"] += 1
        elif (refused := match_rules.refusal(requirement, f, sheet=sheet)) is not None:
            why[f"refused by the pairing: {str(refused)[:40]}"] += 1
        else:
            out.append(f)
    if not out and not any(k.startswith(("refused", "the value")) for k in why):
        why["no value on the paper has this rule's quantity words"] += 1
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


def _tables(conn, submittal: str) -> dict:
    """page -> the stored table rows of that page (`pages.tables_json`)."""
    from . import table_cell

    return {
        r["page_no"]: table_cell.tables_of(r["tables_json"])
        for r in conn.execute(
            "SELECT page_no, tables_json FROM pages WHERE document_id = ?", (submittal,)
        )
    }


def _numeric_lines(
    items, facts, sheet, pages, tables, cache, kind, tier_lookup, unpaired, submittal
) -> tuple[list[dict], int, int]:
    """The numeric lines, PER TAG GROUP: a rule is paired with the facts of one group and compared with that group's facts only."""
    made, considered, paired = [], 0, 0
    counts = cells_mod.page_tag_counts(facts)
    count = max((k for k in pages if isinstance(k, int)), default=None)
    for item in _numeric_items(items):
        considered += 1
        field = (guards.field_names(item) or [None])[0]
        req = {**calc.requirement_from_item(item), "field": field, "subject": field}
        for gfacts in cells_mod.groups(facts).values():
            cells = cells_mod.cells_of(gfacts, tables, counts)
            for fact in pair(item, req, gfacts, sheet, unpaired):
                paired += 1
                line = calc.numeric_line(
                    item, req, fact, submittal_facts=gfacts, page_text=pages.get(fact.get("page")),
                    clause_quote=cache.text(item.get("rule_quote_ref")), clause_text=cache.text(item.get("clause_quote_ref")),
                    page_count=count, cell=cells.get(str(fact.get("id"))), document_id=submittal,
                )  # fmt: skip
                if fact.get("settled_note"):
                    line["settled_note"] = fact["settled_note"]
                made.append(
                    wording.final_cap(line, item, tier_lookup, paper_kind=kind.kind)
                )
    return made, considered, paired


def _checklist_lines(
    facts, stored, pages, tables, submittal, kind, tier_lookup, presence
) -> list[dict]:
    """The approved checklist, PER TAG GROUP; a group-level result (no fact) is named by its group."""
    from . import checklist_scope, degraded_read
    from .agent_review_checklist_books import ChecklistBooks
    from .db import connect

    books = ChecklistBooks(connect())  # each book and clause read once per run
    made = []
    counts = cells_mod.page_tag_counts(facts)
    for key, gfacts in cells_mod.groups(facts).items():
        results = degraded_read.hold(
            checklist_scope.evaluate(gfacts, stored, pages), submittal
        )
        results = [
            {**r, "equipment_tag": r.get("equipment_tag") or key} for r in results
        ]
        presence.update(calc.presence_counts(results))
        for line in calc.checklist_lines(
            results,
            page_texts=pages,
            cells=cells_mod.cells_of(gfacts, tables, counts),
            document_id=submittal,
            books=books,
        ):
            made.append(
                wording.final_cap(line, line, tier_lookup, paper_kind=kind.kind)
            )
    return made


def _run(conn, submittal, kind, plan, *, store, tier_lookup) -> tuple[list[dict], dict]:
    from . import classification, datasheets, match_rules

    if not (kind.known and kind.kind == "datasheet"):
        return [], _note("the paper is not a datasheet")
    raw = datasheets.list_facts(submittal, allowed_document_ids=frozenset({submittal}))
    if not raw:
        return [], _note("no datasheet value is stored for this paper yet")
    pages, tables = DbPages(conn, submittal).pages, _tables(conn, submittal)
    settled = [
        cells_mod.settle(f, raw, tables) for f in raw
    ]  # a hold that was only other tags' values is lifted, in words
    facts, lifted = [f for f, _ in settled], Counter(w for _, w in settled if w)
    stored = classification.of_document(submittal) or {}
    sheet = match_rules.sheet_kind(
        facts, stored.get("equipment_type") or kind.equipment_type
    )
    unpaired: Counter = Counter()
    made, considered, paired = _numeric_lines(
        plan.get("items") or [],
        facts,
        sheet,
        pages,
        tables,
        ClauseCache(plan.get("cache")),
        kind,
        tier_lookup,
        unpaired,
        submittal,
    )
    presence: Counter = Counter()
    made += _checklist_lines(
        facts, stored, pages, tables, submittal, kind, tier_lookup, presence
    )
    for (
        line
    ) in made:  # stored BEFORE the first reader call: a run that stops early keeps them
        store(line, None)
    return made, {
        "ran": True,
        "lines": len(made),
        "facts": len(facts),
        "groups": len(cells_mod.groups(facts)),
        "holds_lifted": sum(lifted.values()),
        "rules_considered": considered,
        "pairs": paired,
        "not_paired": dict(unpaired),
        "presence_checked": presence["presence_checked"],
        "presence_stated": presence["presence_stated"],
        "presence_missing": presence["presence_missing"],
        "by_class": dict(Counter(ln.get("verdict_class") for ln in made)),
        "reasons": dict(
            Counter(
                ln.get("reason_code") for ln in made if ln.get("verdict") == "Query"
            )
        ),
    }
