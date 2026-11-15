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

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from . import (
    crs_completeness,
    nine_call,
    nine_chapters,
    nine_checklist,
    nine_context,
    nine_facts,
    nine_findings,
    nine_librarian,
    nine_reader,
    nine_record,
    nine_resume,
    nine_reviewer,
    nine_support,
    nine_writer,
)
from .db import connect

log = logging.getLogger(__name__)
second_reviewer_role = nine_support.second_reviewer_role
code_role = nine_support.code_role
_lines_by_class = nine_support._lines_by_class
_covering_only_when_tier_resolved = nine_support._covering_only_when_tier_resolved
_decide = nine_support._decide
_rule_rows = nine_support._rule_rows
_chapter_texts = nine_support._chapter_texts
_earlier_points = nine_support._earlier_points
_book_inputs = nine_support._book_inputs
_prefix = nine_support._prefix
_guarded_ask = nine_resume.guarded_ask  # kept under its old names for the tests
_handover_save = nine_resume.handover_save
_handover_load = nine_resume.handover_load
WRITER_QUESTION = nine_writer.WRITER_QUESTION
WRITER_SYSTEM = nine_writer.WRITER_SYSTEM


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
    should_stop: Callable[[], bool] = lambda: (
        False
    )  # the job's cancellation, asked before every paid call and between roles
    cancel_exc: type[BaseException] = (
        RuntimeError  # what stops the job (the caller's own cancellation exception)
    )

    def check_stop(self) -> None:
        if self.should_stop():
            raise self.cancel_exc()


# ------------------------------------------------------------------------------------------------ what the adapters read


def _jobs():
    from . import agent_review_jobs

    return agent_review_jobs


NO_DECISION = "no engine decision is stored for this run, so no model was asked"


def _engine(ctx: RoleContext) -> str:
    """The run's engine as the call seam derives it: "claude", "local", or "none" (no stored decision: default deny, no model is asked)."""
    return nine_call.engine_of_run(ctx.run_id)


def _choice(ctx: RoleContext) -> str:
    from . import review_engine

    return (review_engine.stored(connect(), ctx.run_id) or {}).get(
        "choice"
    ) or "automatic"


def _scope(ctx: RoleContext) -> frozenset[str]:
    """The access of the user who started the review (the same rebuild the job itself uses)."""
    from . import review_jobs

    row = (
        connect()
        .execute("SELECT created_by FROM jobs WHERE review_run_id = ?", (ctx.run_id,))
        .fetchone()
    )
    return review_jobs._scope_of(row["created_by"] if row else None)


def _paper_pages(ctx: RoleContext) -> dict[int, str]:
    if "pages" not in ctx.store:
        from . import agent_review_request

        ctx.store["pages"] = dict(
            agent_review_request.DbPages(connect(), ctx.submittal).pages
        )
    return ctx.store["pages"]


def _seam_kwargs(ctx: RoleContext | None = None) -> dict:
    """The lane (`send`, `env`) and, with a context, the job's cancel check: the seam stops a call BEFORE its reservation and its send when the
    job was cancelled (the role then sees a refused call and the loop raises the cancellation before the next role)."""
    send, env = (
        _jobs().lane()
    )  # (None, None) in the app: the real lane through `agent_claude`; tests put a fake model here
    return {
        "send": send,
        "env": env,
        **({"should_stop": ctx.should_stop} if ctx is not None else {}),
    }


def _usd_of(role_no: int, run_id: str) -> float | None:
    return nine_record.role_calls(run_id, role_no)[1]


# ------------------------------------------------------------------------------------------------ role 1: the Reader


def reader_role(ctx: RoleContext) -> RoleResult:
    """Role 1: every page into the fact sheet through `nine_reader.read_paper` (every model call goes through `nine_call.ask`, role 1).
    Pictures only on Claude. The sheet is stored per run (`nine_facts.store`); nothing is written to `submittal_facts`."""

    conn = connect()
    engine = _engine(ctx)
    if engine == "none":
        return RoleResult("not_run", NO_DECISION)
    pages = _paper_pages(ctx)
    stored = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM submittal_facts WHERE submittal_document_id = ?",
            (ctx.submittal,),
        )
    ]
    got = nine_reader.read_paper(
        run_id=ctx.run_id, paper_id=ctx.submittal, pages=pages, stored_facts=stored, engine=engine,
        equipment_type=getattr(ctx.kind, "equipment_type", None), pages_total=max([*pages, 0]), pictures=engine == "claude",
        conn=conn, **_seam_kwargs(ctx),
    )  # fmt: skip
    nine_facts.store(conn, got.sheet, got.produced)
    ctx.store["fact_sheet"] = got.sheet
    return RoleResult(
        got.state,
        got.why,
        engine=engine,
        models=tuple(got.sheet.models),
        produced=got.produced,
    )


# ------------------------------------------------------------------------------------------------ role 2: the project context


def _usable_documents(ctx: RoleContext, engine: str) -> frozenset[str]:
    """THE ONE answer to "which documents may this run use?", for roles 2 and 3 (B1's seam applies the same two rules to every block): the access
    of the user who started the review (rule 5), narrowed by the list shown before the start WHERE ONE WAS STORED. A start that sends nothing
    stores no list (it restricts only what is SENT to Claude): on a Local run the usable documents are then everything the starter may read;
    on Claude a missing list means none (default deny)."""
    from . import review_shown

    scope = _scope(ctx)
    listed = review_shown.shown_ids(connect(), ctx.run_id)
    if listed is not None:
        return scope & listed
    return scope if engine == "local" else frozenset()


def context_role(ctx: RoleContext) -> RoleResult:
    """Role 2: `nine_context.run`. Code finds the project's papers and admits each one (shown list, the starter's access, the engine
    choice; a contract never under Automatic); a model, through `nine_call.ask`, may only NAME a standard or an override with a page
    quote that code finds. Nothing held: no call, a note with the five "not available" lines.

    WHAT IS PASSED ON: the note holds words of OTHER documents, so it is NOT handed to the reviewer as one block under the
    paper's id; it goes to the reviewer as one derived block PER SOURCE document (tokens only), and role 4 records how many."""
    from . import (
        applicability,
    )

    conn = connect()
    engine, scope = _engine(ctx), _scope(ctx)
    if engine == "none":
        return RoleResult("not_run", NO_DECISION)
    shown = _usable_documents(ctx, engine)
    mine = conn.execute(
        "SELECT * FROM document_classification WHERE document_id = ?", (ctx.submittal,)
    ).fetchone()
    project = (mine["project"] if mine else None) or None
    rows = (
        [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM document_classification WHERE project = ?", (project,)
            )
        ]
        if project
        else []
    )
    papers = nine_context.find_papers(conn, ctx.submittal, scope, shown)
    new_values = {
        f.field_label: f.value
        for f in getattr(ctx.store.get("fact_sheet"), "facts", ())
    }
    library = applicability._library(frozenset(scope))
    note, tally = nine_context.run(
        ctx.run_id, project=project, papers=papers, paper_row=dict(mine) if mine else {}, rows=rows, earlier_points=_earlier_points(scope),
        new_values=new_values, library=library, engine=_choice(ctx), ask=nine_context.seam_ask(ctx.run_id, **_seam_kwargs(ctx)),
    )  # fmt: skip
    ctx.store["context_note"] = note
    produced = nine_context.produced(note, tally)
    parts = nine_context.context_blocks(
        note, tally
    )  # one derived block per SOURCE document and column shape
    ctx.store["context_blocks"] = parts.blocks
    produced["context_parts"] = len(parts.blocks)
    produced["context_rows_not_passed"] = parts.not_passed
    held = sum(1 for p in papers if p.accessible and p.shown)
    state, why = (
        ("ran", None)
        if (held or not papers)
        else (
            "ran_partly",
            "no project paper could be read (see the not available lines)",
        )
    )
    return RoleResult(
        state, why, engine=engine if tally.windows else "code", produced=produced
    )


# ------------------------------------------------------------------------------------------------ role 3: the Librarian


def librarian_role(ctx: RoleContext) -> RoleResult:
    """Role 3: the reading list by code (`nine_librarian.plan_reading`: books from the chosen rules, chapters cut by `nine_chapters`, a rank,
    a budget, "chosen, not read" with the reason); one optional model call sees only chapter TITLES and can only ADD chapters (through
    `nine_call.ask`, role 3). A book outside the starter's access is counted, never named."""
    from . import (
        nine_chapters,
    )

    conn = connect()
    engine, scope = _engine(ctx), _scope(ctx)
    if engine == "none":
        return RoleResult("not_run", NO_DECISION)
    items = list(ctx.plan.get("items") or [])
    book_ids = list(
        dict.fromkeys(
            str(i["standard_document_id"])
            for i in items
            if i.get("standard_document_id")
        )
    )
    shown = _usable_documents(ctx, engine)
    budget = (
        nine_chapters.LOCAL_CALL_TOKENS
        if engine == "local"
        else nine_chapters.CLAUDE_CALL_TOKENS
    )
    inputs, cuts = _book_inputs(conn, book_ids, scope, budget)
    refs = [
        nine_librarian.RuleRef(
            str(i["standard_document_id"]), i.get("clause"), i.get("clause_page"), n
        )
        for n, i in enumerate(items, 1)
        if i.get("standard_document_id")
    ]
    note = ctx.store.get("context_note")
    context = [
        nine_librarian.ClauseRef(s.book_id, None)
        for s in getattr(note, "standards", ())
        if s.held and s.book_id
    ]
    reading = nine_librarian.plan_reading(
        ctx.run_id, inputs, rules=refs, context=context, equipment_words=[str(getattr(ctx.kind, "equipment_type", "") or "")],
        shown=shown, allowed=scope, engine=engine, wanted_not_listed=len([b for b in book_ids if b not in scope]),
    )  # fmt: skip

    title_ask = nine_librarian.seam_ask(ctx.run_id, **_seam_kwargs(ctx))
    reading = nine_librarian.extend_with_model(
        reading, inputs, title_ask, engine=engine
    )
    ctx.store["reading"], ctx.store["cuts"] = reading, cuts
    produced = nine_librarian.produced(reading)
    refused = nine_librarian.model_step_refusal(
        title_ask
    )  # the optional title step: refused or failed is said, never "ran"
    if refused:
        produced["model_step"] = refused
    unread = produced["chapters_not_read"]
    if refused and not unread:
        return RoleResult(
            "ran_partly",
            f"the reading list was chosen by code; the model's title step did not run ({refused})",
            engine=engine,
            produced=produced,
        )
    return RoleResult("ran_partly" if unread else "ran", ("some chapters were chosen but not read: " + ", ".join(unread)) if unread else None,
                      engine=engine, produced=produced)  # fmt: skip


# ------------------------------------------------------------------------------------------------ role 4: the Reviewer


def _chosen_chapters(ctx: RoleContext) -> tuple[list, dict]:
    """The chosen (book, chapter) pairs and the cut books: from the reading list in memory, or - after a restart that skipped role 3 - from what
    role 3 handed over (the chosen pairs; the books are cut again by code, no model)."""
    reading, cuts = ctx.store.get("reading"), ctx.store.get("cuts") or {}
    if reading is not None:
        return [
            (b.book_id, i.chapter)
            for b in reading.books
            if b.on_shown_list
            for i in b.items
            if i.chosen
        ], cuts
    pairs = ctx.store.get("chosen")
    if not pairs:
        return [], cuts
    scope, engine = _scope(ctx), _engine(ctx)
    budget = (
        nine_chapters.LOCAL_CALL_TOKENS
        if engine == "local"
        else nine_chapters.CLAUDE_CALL_TOKENS
    )
    _inputs, cuts = _book_inputs(
        connect(), list(dict.fromkeys(b for b, _c in pairs)), scope, budget
    )
    return [
        (b, cuts[b].chapter(c))
        for b, c in pairs
        if b in cuts and cuts[b].chapter(c) is not None
    ], cuts


def reviewer_role(ctx: RoleContext) -> RoleResult:
    """Role 4: the chosen chapters against the paper (`nine_reviewer.review`, every call through `nine_call.ask`), then the findings join
    (`nine_findings.process`) and go through TODAY'S runner (`decide_all`: `Runner.decide`, the two-reader step, `final_cap`): the one exit.
    No reading list, nothing chosen, a failed or empty reviewer: the role says so and role 5 asks EVERY item (never weaker than today's)."""
    from . import agent_review_standards

    chosen, cuts = _chosen_chapters(ctx)
    if not chosen:
        ctx.flags["reviewer_failed"] = True
        return RoleResult(
            "not_run",
            "no chapter was chosen to read, so nothing was reviewed against a chapter",
        )
    engine = _engine(ctx)
    if engine == "none":
        ctx.flags["reviewer_failed"] = True
        return RoleResult("not_run", NO_DECISION)
    pages = _paper_pages(ctx)
    groups = nine_reviewer.group_chapters(_chapter_texts(chosen, cuts))
    prefix, no_context = _prefix(ctx, pages)
    ran = nine_reviewer.review(
        ctx.run_id,
        prefix,
        groups,
        engine=engine,
        no_context_available=no_context,
        ask=nine_resume.guarded_ask(ctx),
        should_stop=ctx.should_stop,
        **_seam_kwargs(),
    )
    ctx.check_stop()  # a cancel during the reviewer's calls ends the job here, never reads as "no finding"
    if not ran.ok:
        ctx.flags["reviewer_failed"] = True
        return RoleResult("not_run", "the reviewer gave no usable finding (" + (", ".join(sorted(set(ran.errors))) or "nothing found") + ")", engine=engine, produced={"groups": ran.groups, "failed": ran.failed})  # fmt: skip
    jobs = _jobs()
    local = None
    if engine == "local":
        from . import agent_review_local

        local = agent_review_local.engine_for(ctx.run_id)
    runner = ctx.holder["runner"] = jobs._make_runner(
        ctx.run_id, ctx.submittal, ctx.kind, ctx.plan, local
    )
    built = nine_findings.process(
        ran.raw, paper_pages=pages, books=agent_review_standards.BookPages(), rules=_rule_rows(ctx.plan),
        plan_items={str(i["item_id"]): i for i in ctx.plan.get("items") or []}, tier_lookup=jobs._tier_lookup(ctx.kind),
    )  # fmt: skip
    # THE ONE step order (B4's `cover`): the findings to emit (a finding that matched a rule it does not cover stays an F- item of its own) and the
    # coverage; emit the first list with `decide_all`, then role 5 asks `Coverage.to_ask` through today's batch path
    built = _covering_only_when_tier_resolved(built)
    to_emit, coverage = nine_checklist.cover(
        ctx.plan.get("items") or [], built, reviewer_ok=True
    )
    _decide(ctx, runner, local, to_emit, pages)
    ctx.store["coverage"] = coverage
    ctx.store["findings"] = [b.finding for b in to_emit]
    produced = {
        "groups": ran.groups,
        "answered": ran.answered,
        "failed": ran.failed,
        "raw_findings": len(ran.raw),
        "findings": len(to_emit),
        "findings_kept": sum(b.underlying for b in to_emit),
        "context_parts_passed": len(ctx.store.get("context_blocks") or ()),
        **{
            f"fact_{k}": v
            for k, v in (ctx.store.get("digest_counts") or {}).items()
            if k in ("rows_tagged", "rows_untagged", "rows_cut_for_size")
        },  # how many fact rows the reviewer was given and how many did not fit a derived block
    }
    return RoleResult("ran_partly" if ran.partly else "ran", "some chapter groups were not read" if ran.partly else None, engine=engine, produced=produced)  # fmt: skip


# ------------------------------------------------------------------------------------------------ the roles that are code or today's path


def checklist_role(ctx: RoleContext) -> RoleResult:
    """Role 5: today's batch path. Asked only for the required items the reviewer did not cover; when the reviewer failed, was stopped
    or found nothing, EVERY item is asked (never weaker than today's). The module `nine_checklist` (B4) names the items to skip."""
    items = list(ctx.plan.get("items") or [])
    findings = ctx.store.get("findings") or []
    coverage = (
        ctx.store.get("coverage") if not ctx.flags.get("reviewer_failed") else None
    ) or nine_checklist.plan(
        items, findings, reviewer_ok=not ctx.flags.get("reviewer_failed")
    )
    asked = coverage.to_ask
    # The batch path gets the WHOLE plan: the runner asks only the items that have no line yet, and every item the reviewer covered has its
    # line already (stored by role 4). Shortening the plan would hide those items from the runner's exit and `_finish`, which then cannot
    # find the rule of a stored line (its tier would read "not approved"). The plan is never changed here.
    if asked:
        ctx.ask(ctx.run_id, ctx.submittal, ctx.kind, ctx.plan, ctx.holder)
    return RoleResult(
        "ran",
        engine=None,
        produced={
            "required": len(items),
            "mentioned": len(items) - len(asked),
            "asked": len(asked),
        },
    )


def writer_role(ctx: RoleContext) -> RoleResult:
    """Role 9, the Writer: the ONE sheet (`crs_one`), one comment per field, worst first, checked by `crs_completeness`; on Claude the AI
    wording of each comment, locked by code (`nine_writer`); otherwise the code's words, said so. The contractor file is never reworded."""
    engine = nine_call.engine_of_run(ctx.run_id)
    ctx.check_stop()
    produced, why = nine_writer.write(
        ctx.run_id,
        ctx.submittal,
        engine,
        ask=nine_resume.guarded_ask(ctx),
        **_seam_kwargs(ctx),
    )
    got = crs_completeness.record_after_run(ctx.run_id)
    if got is None:
        return RoleResult("not_run", "the sheet could not be checked", engine="code")
    team = got["team"]
    produced |= {
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
    return RoleResult("ran" if why is None else "ran_partly", why, engine="claude" if engine == "claude" and produced.get("sheet_by") != "code" else "code", produced=produced)  # fmt: skip
    # the record names the engine that really wrote: the writer is off in this version (`sheet_by` code), so it says code, never claude


def default_roles() -> dict[int, Callable[[RoleContext], RoleResult]]:
    return {
        1: reader_role,
        2: context_role,
        3: librarian_role,
        4: reviewer_role,
        5: checklist_role,
        6: second_reviewer_role,
        7: code_role,
        8: code_role,
        9: writer_role,
    }


class RealRecord:
    """B1's `nine_record` behind the four calls the job makes. Calls, cost and models follow the call rows there (written by the seam),
    never this job's own numbers."""

    @staticmethod
    def ensure_schema() -> None:
        nine_record.ensure_schema()

    @staticmethod
    def begin_run(run_id: str) -> None:
        nine_record.start_run(
            run_id
        )  # nine rows, all "not run: not reached" (idempotent)

    @staticmethod
    def role_state(run_id: str, n: int) -> str | None:
        row = (
            connect()
            .execute(
                "SELECT state, finished_at FROM agent_review_role WHERE run_id = ? AND role_no = ?",
                (run_id, n),
            )
            .fetchone()
        )
        return row["state"] if row is not None and row["finished_at"] else None

    @staticmethod
    def role_started(run_id: str, n: int) -> None:
        nine_record.role_start(run_id, n, "code")

    @staticmethod
    def role_finished(
        run_id: str, n: int, *, state, why, engine, models, produced
    ) -> None:
        nine_record.role_end(
            run_id,
            n,
            state,
            why=why,
            produced=produced,
            models=tuple(models),
            engine=engine,
        )


def _record():
    return RealRecord()


#: the roles that are today's own path (checklist, second reader, code, decision rule): an error in them is today's error
TODAYS_PATH = (5, 6, 7, 8)


def flat(produced: dict) -> dict:
    """The record keeps counts, ids and short codes only (`nine_record._counts_only`): a dict becomes one count per sub-key
    ("chapters_not_read.over the reading budget": 3), a dict of reasons becomes a count per reason, a long text is dropped."""
    out: dict = {}
    for key, value in produced.items():
        if isinstance(value, dict):
            counts = (
                value
                if all(
                    isinstance(v, int) and not isinstance(v, bool)
                    for v in value.values()
                )
                else Counter(str(v) for v in value.values())
            )
            for sub, n in counts.items():
                out[f"{key}.{sub}"[: nine_record.MAX_STRING]] = n
        elif isinstance(value, str) and len(value) > nine_record.MAX_STRING:
            continue
        else:
            out[key] = value
    return out


def failure_detail(exc: BaseException) -> dict:
    """What the record keeps of a role that FAILED, so the sheet can word it without a value or a document word: the error's type name, a reason code
    from the closed list `nine_call.FAILURE_REASONS` (`other` for any error that does not carry one), and, where the error names them, the
    template (or derived block) NAME and the declared cell kind. Stored in the role's `produced` as `failure_error`, `failure_reason`,
    `failure_template`, `failure_cell_kind` (the last two only when known)."""
    reason = getattr(exc, "reason", "other")
    out = {
        "failure_error": type(exc).__name__,
        "failure_reason": reason if reason in nine_call.FAILURE_REASONS else "other",
    }
    for key, attr in (
        ("failure_template", "template"),
        ("failure_cell_kind", "cell_kind"),
    ):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            out[key] = value[: nine_record.MAX_STRING]
    return out


def _execute_role(
    n: int, ctx: RoleContext, fn, record, reraise: tuple[type[BaseException], ...]
) -> None:
    if (
        record.role_state(ctx.run_id, n) == "ran"
    ):  # RESUME: a role that ran is not run again, so nothing is paid twice; what it handed over is reloaded
        nine_resume.reload(ctx, n)
        return
    record.role_started(ctx.run_id, n)
    try:
        result = fn(ctx)
    except reraise:
        raise
    except Exception as exc:
        if (
            n in TODAYS_PATH
        ):  # today's batch path and its code roles behave EXACTLY as today (retry, poison): never swallowed here
            raise
        log.warning("nine roles: role %s failed (%s)", n, type(exc).__name__)
        result = RoleResult(
            "not_run", f"failed ({type(exc).__name__})", produced=failure_detail(exc)
        )
        if n == 4:
            ctx.flags["reviewer_failed"] = True
    if n == 4 and result.state == "not_run":
        ctx.flags["reviewer_failed"] = True
    if result.state != "ran" and not result.why:
        result.why = "no reason recorded"  # a role that did not fully run always carries a reason
    record.role_finished(
        ctx.run_id, n, state=result.state, why=result.why, engine=result.engine, models=list(result.models), produced=flat(result.produced),
    )  # fmt: skip
    nine_resume.hand_over(ctx, n)


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
    should_stop=None,
) -> RoleContext:
    """Run the nine roles in order (see the module words). `ask` is today's `agent_review_jobs._ask`; `reraise` are the exceptions that
    must stop the job (the caller passes its cancellation); a BaseException that is not an Exception always propagates."""
    record = record or _record()
    record.ensure_schema()
    record.begin_run(run_id)
    ctx = RoleContext(
        run_id,
        submittal,
        kind,
        plan,
        holder,
        ask,
        should_stop=should_stop or (lambda: nine_resume.job_cancelled(run_id)),
        cancel_exc=reraise[0] if reraise else RuntimeError,
    )
    table = {**default_roles(), **(roles or {})}
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        ctx.check_stop()  # a cancellation is honoured before every role, and before every paid call inside roles 4 and 9
        _execute_role(n, ctx, table[n], record, reraise)
    return ctx
