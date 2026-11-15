"""THE NINE-ROLE JOB (design B5): the order of the nine roles inside the SAME job, run row and line table, with a stored row per role.

`run_roles` is called by `agent_review_dispatch.run` ONLY when `AGENT_REVIEW_NINE_ROLES_ENABLED` is on (off: this module is not even
imported and today's `_ask` runs, byte for byte). Order (A.3): calculator lines first (the caller's `calculator_run.step_job`, already
done) -> 1 Reader -> 2 Project context -> 3 Librarian -> 4 Reviewer (its join is part of it) -> 5 Checklist (today's batch path, asked
only for the required items the reviewer did not cover) -> 6 Second reviewer (today's two-reader step, inside the same ask) -> 7 Code and
8 Decision rule (code, at every stored line: recorded here from the stored lines) -> 9 Writer (the ONE sheet: `crs_completeness` checks
N points = N lines = N rows, and the result is stored with the run).

  * Nine rows are written at the start, all "not run: not reached"; each role updates its own row (`nine_record`, B1's module).
  * A role that FAILS is recorded "not run: failed (<error type>)" and the run goes on by the table of A.3: role 4 failing, stopped or
    reading nothing makes role 5 ask EVERY required item (never weaker than today's review).
  * RESUME: a role whose row says "ran" is not run again, so nothing is paid twice (a role's own stored answers are reused by that role).
  * A role's budget or a cap reached is "ran partly" with what was not read; later roles still run inside their own budgets.
  * A cancellation (`agent_review_jobs._Cancelled`) and anything that is not an `Exception` is never swallowed.

This module decides nothing: lines are stored only through the one exit (`store_line` -> `Runner.decide` -> `final_cap`); no class or
word is written here. No model call is made here: every role that asks a model does it through `nine_call` (B1).
"""

from __future__ import annotations

import importlib
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from . import crs_completeness
from .db import connect
from .nine_contract import NOT_REACHED, ROLE_NAMES

log = logging.getLogger(__name__)
#: the roles that are run in order by a module of their own: role number -> (module, function); each takes a `RoleContext`
ROLE_MODULES = {
    1: "nine_reader",
    2: "nine_context",
    3: "nine_librarian",
    4: "nine_reviewer",
}


@dataclass
class RoleResult:
    state: str  # ran | ran_partly | not_run
    why: str | None = None  # required unless "ran"
    engine: str | None = None  # claude | local | code
    models: tuple[str, ...] = ()
    calls: int = 0
    usd: float | None = None
    produced: dict = field(default_factory=dict)  # counts and ids only


@dataclass
class RoleContext:
    run_id: str
    submittal: str
    kind: object
    plan: dict
    holder: dict
    ask: Callable[
        [str, str, object, dict, dict], None
    ]  # today's `agent_review_jobs._ask`
    store: dict = field(
        default_factory=dict
    )  # what one role hands the next (fact sheet, note, reading list, findings): in memory
    flags: dict = field(default_factory=dict)  # e.g. reviewer_failed


# ------------------------------------------------------------------------------------------------ the roles that are code or today's path


def _lines_by_class(run_id: str) -> Counter:
    got: Counter = Counter()
    for r in connect().execute(
        "SELECT verdict_class FROM agent_review_line WHERE run_id = ?", (run_id,)
    ):
        got[r["verdict_class"] or "none"] += 1
    return got


def checklist_role(ctx: RoleContext) -> RoleResult:
    """Role 5: today's batch path. Asked only for the required items the reviewer did not cover; when the reviewer failed, was stopped
    or found nothing, EVERY item is asked (never weaker than today's). The module `nine_checklist` (B4) names the items to skip."""
    items = list(ctx.plan.get("items") or [])
    asked = items
    findings = ctx.store.get("findings") or []
    if findings and not ctx.flags.get("reviewer_failed"):
        try:
            skip = set(
                importlib.import_module("app.nine_checklist").covered_item_ids(
                    ctx.store
                )
            )
            asked = [i for i in items if i.get("id") not in skip]
        except (ImportError, AttributeError):  # no coverage module: ask everything
            asked = items
    ctx.plan["items"] = asked
    if asked:
        ctx.ask(ctx.run_id, ctx.submittal, ctx.kind, ctx.plan, ctx.holder)
    ctx.plan["items"] = items
    return RoleResult(
        "ran",
        engine=None,
        produced={
            "required": len(items),
            "mentioned": len(items) - len(asked),
            "asked": len(asked),
        },
    )


def second_reviewer_role(ctx: RoleContext) -> RoleResult:
    """Role 6: today's two-reader step ran inside the checklist's ask (findings arrive as items, so they are candidates like any line).
    Its counts are read from the stored lines."""
    challenged = agreed = 0
    for r in connect().execute(
        "SELECT line_json FROM agent_review_line WHERE run_id = ?", (ctx.run_id,)
    ):
        text = r["line_json"] or ""
        if '"two_reader"' in text:
            challenged += 1
            agreed += '"agrees": true' in text
    if not challenged:
        return RoleResult(
            "not_run", "no line was a candidate for a second reader", engine=None
        )
    return RoleResult(
        "ran", engine=None, produced={"challenged": challenged, "agreed": agreed}
    )


def code_role(ctx: RoleContext) -> RoleResult:
    """Roles 7 and 8: code, at every stored line. Counts only."""
    by = _lines_by_class(ctx.run_id)
    return RoleResult(
        "ran", engine="code", produced={"lines": sum(by.values()), "by_class": dict(by)}
    )


def writer_role(ctx: RoleContext) -> RoleResult:
    """Role 9: the ONE sheet, never a second one. `crs_completeness` checks that the points, the stored lines and the rows of both
    files agree and stores the result with the run; the comments are `crs_comments`' (one per field). An AI wording of a comment goes
    through `nine_sheet.apply_wordings` (the lock); this version words by code: it says "ran partly" and why."""
    got = crs_completeness.record_after_run(ctx.run_id)
    if got is None:
        return RoleResult("not_run", "the sheet could not be checked", engine="code")
    team = got["team"]
    produced = {
        "points": team["page"],
        "database_lines": team["database"]["total"],
        "comments_rows": team["rows_in_file"],
    }
    if not (team["ok"] and got["contractor"]["ok"]):
        return RoleResult(
            "ran_partly",
            "the file is incomplete and will not be given out: " + team["sentence"],
            engine="code",
            produced=produced,
        )
    return RoleResult(
        "ran_partly",
        "comments worded by code: no AI wording was asked",
        engine="code",
        produced=produced,
    )


# ------------------------------------------------------------------------------------------------ the runner of one role


def _module_role(n: int) -> Callable[[RoleContext], RoleResult]:
    def run(ctx: RoleContext) -> RoleResult:
        try:
            mod = importlib.import_module(f"app.{ROLE_MODULES[n]}")
        except ImportError:
            return RoleResult(
                "not_run", f"{ROLE_NAMES[n]} is not built in this version", engine=None
            )
        return mod.run(ctx)

    return run


def default_roles() -> dict[int, Callable[[RoleContext], RoleResult]]:
    return {
        **{n: _module_role(n) for n in ROLE_MODULES},
        5: checklist_role,
        6: second_reviewer_role,
        7: code_role,
        8: code_role,
        9: writer_role,
    }


def _record():
    return importlib.import_module("app.nine_record")


def _execute_role(
    n: int, ctx: RoleContext, fn, record, reraise: tuple[type[BaseException], ...]
) -> None:
    if (
        record.role_state(ctx.run_id, n) == "ran"
    ):  # RESUME: a role that ran is not run again, so nothing is paid twice
        return
    record.role_started(ctx.run_id, n)
    try:
        result = fn(ctx)
    except reraise:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded by type (never text), the run goes on by the table of A.3
        log.warning("nine roles: role %s failed (%s)", n, type(exc).__name__)
        result = RoleResult("not_run", f"failed ({type(exc).__name__})")
        if n == 4:
            ctx.flags["reviewer_failed"] = True
    if n == 4 and result.state == "not_run":
        ctx.flags["reviewer_failed"] = True
    if result.state != "ran" and not result.why:
        result.why = "no reason recorded"  # a role that did not fully run always carries a reason
    record.role_finished(
        ctx.run_id, n, state=result.state, why=result.why, engine=result.engine, models=list(result.models), calls=result.calls,
        usd=result.usd, produced=result.produced,
    )  # fmt: skip


def run_roles(
    run_id: str,
    submittal: str,
    kind,
    plan: dict,
    holder: dict,
    ask,
    *,
    record=None,
    roles: dict | None = None,
    reraise: tuple[type[BaseException], ...] = (),
) -> RoleContext:
    """Run the nine roles in order (see the module words). `ask` is today's `agent_review_jobs._ask`; `reraise` are the exceptions that
    must stop the job (the caller passes its cancellation); a BaseException that is not an Exception always propagates."""
    record = record or _record()
    record.ensure_schema()
    record.begin_run(run_id, reason=NOT_REACHED)
    ctx = RoleContext(run_id, submittal, kind, plan, holder, ask)
    table = {**default_roles(), **(roles or {})}
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        _execute_role(n, ctx, table[n], record, reraise)
    return ctx
