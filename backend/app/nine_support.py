"""Support functions of the nine-role job (B5): the code roles 6 to 8's counts, the one step order's tier guard, the runner contexts the reviewer's
findings are decided in, the rule rows a finding is matched to, the chosen chapters as named parts, the earlier points, the rule books cut into
chapters and the reviewer's shared prefix. Split from `nine_job` only to keep that file under its size limit; nothing here decides a verdict
(every line still goes through the runner's one exit)."""

from __future__ import annotations

import json
from collections import Counter

from . import nine_call, nine_facts, nine_findings, nine_librarian
from .db import connect


def _role_result(*args, **kwargs):
    from .nine_job import RoleResult

    return RoleResult(*args, **kwargs)


def second_reviewer_role(ctx) -> object:
    """Role 6: today's two-reader step ran inside the asks (findings arrive as items, so they are candidates like any line). Its counts are
    read from the stored lines: a line's `second_opinion` is the second reader's stored answer (a mapping with `agree`), None when none was
    asked. Candidates are the lines `agent_review_two_reader.is_candidate` says could take a second reader."""
    from . import agent_review_two_reader as two

    candidates = asked = agreed = disagreed = 0
    for r in connect().execute(
        "SELECT line_json FROM agent_review_line WHERE run_id = ?", (ctx.run_id,)
    ):
        try:
            line = json.loads(r["line_json"] or "{}")
        except ValueError:
            continue
        second = line.get("second_opinion")
        candidates += bool(two.is_candidate(line) or isinstance(second, dict))
        if isinstance(second, dict) and second.get("agree") is not None:
            asked += 1
            agreed += bool(second["agree"])
            disagreed += not second["agree"]
    produced = {
        "candidates": candidates,
        "asked": asked,
        "agreed": agreed,
        "disagreed": disagreed,
    }
    if not asked:
        why = (
            "no line was a candidate for a second reader"
            if not candidates
            else "candidates existed but no second reader answered"
        )
        return _role_result("not_run", why, engine=None, produced=produced)
    return _role_result("ran", engine=None, produced=produced)


def code_role(ctx) -> object:
    """Roles 7 and 8: code, at every stored line. Counts only."""
    by = _lines_by_class(ctx.run_id)
    return _role_result(
        "ran", engine="code", produced={"lines": sum(by.values()), "by_class": dict(by)}
    )


def _lines_by_class(run_id: str) -> Counter:
    got: Counter = Counter()
    for r in connect().execute(
        "SELECT verdict_class FROM agent_review_line WHERE run_id = ?", (run_id,)
    ):
        got[r["verdict_class"] or "none"] += 1
    return got


def _covering_only_when_tier_resolved(built: list) -> list:
    """A finding that matched a rule covers it only when the match's tier RESOLVED to one a verdict may stand on. If the lookup failed the rule
    would get only an opinion where today's own ask could have been stronger: the finding then does not cover it (its clause page is
    withheld from the coverage decision, so `cover` emits it as an F- item and the rule goes to the batch path)."""
    import dataclasses

    from . import agent_review_verdict as verdict

    out = []
    for b in built:
        f = b.finding
        if f.matched_rule_id is not None and f.rule_tier not in verdict.USABLE_TIERS:
            b = dataclasses.replace(b, finding=dataclasses.replace(f, clause_page=None))
        out.append(b)
    return out


def _decide(ctx, runner, local, to_emit, pages) -> None:
    """Emit the reviewer's findings through the runner EXACTLY as `Runner.run` would work: the runner restored from the lines already stored,
    its step gate set, and on Claude inside `claude_approved.carrying(<the documents the run may declare>)` and `claude_spend.for_run(run)` (so a
    second reader's request is declared and metered like any other); on Local inside the local session. Without this a second reader is refused
    ("undeclared_documents") and no finding could reach the two-reader class."""
    from . import agent_claude, claude_approved, claude_spend
    from . import agent_review_run as run_mod

    runner.restore()
    if local is not None:
        runner.gate = run_mod.AppStepGate(float("inf"), 0.0)
        with local.session():
            nine_findings.decide_all(runner, to_emit, pages, runner.model)
        return
    runner.gate = run_mod.AppStepGate(
        run_mod.app_cap(), claude_spend.step_spent(agent_claude.STEP)
    )
    declared = {ctx.submittal} | {
        str(i["standard_document_id"])
        for i in ctx.plan.get("items") or []
        if i.get("standard_document_id")
    }
    with claude_approved.carrying(sorted(declared)), claude_spend.for_run(ctx.run_id):
        nine_findings.decide_all(runner, to_emit, pages, runner.model)


def _rule_rows(plan: dict) -> list[dict]:
    """The rule rows a finding is matched to ({id, standard_document_id, source_text}), from the plan's own items and clause cache: a rule the
    review is asked to apply, with the clause words it was stored with. A rule not asked of this paper is not a candidate."""
    cache = plan.get("cache") or {}
    rows = []
    for item in plan.get("items") or []:
        iid = str(item.get("item_id") or "")
        if not iid.startswith("R-"):
            continue
        ref = cache.get(str(item.get("clause_quote_ref") or f"Q-{iid}")) or {}
        if ref.get("text") and ref.get("standard_document_id"):
            rows.append(
                {
                    "id": iid.removeprefix("R-"),
                    "standard_document_id": ref["standard_document_id"],
                    "source_text": ref["text"],
                    "rule_version_id": item.get(
                        "rule_version_id"
                    ),  # the rule's CURRENT tier is looked up by this
                }
            )
    return rows


def _page_cuts(
    pages: tuple[int, ...], pages_of_book: dict[int, str], lo: int, hi: int, limit: int
) -> list[tuple[tuple[int, ...], int, int]]:
    """Cut the character range [lo, hi) of the joined pages (joined with one line break) into pieces of whole pages that are each at most `limit`
    characters (a page that is alone over the limit is a piece of its own): [(pages, char_from, char_to)] in order. Offsets are into the joined text."""
    start, at = {}, 0
    for n in pages:
        text = pages_of_book.get(n)
        if text is None:
            continue
        start[n] = (at, at + len(text))
        at += len(text) + 1
    cuts: list[tuple[tuple[int, ...], int, int]] = []
    now: list[int] = []
    first = lo

    def close() -> None:
        base = start[
            now[0]
        ][
            0
        ]  # a piece's own joined text begins at its first page: its offsets are relative to that
        cuts.append((tuple(now), first - base, min(start[now[-1]][1], hi) - base))

    for n in pages:
        if n not in start:
            continue
        a, b = max(start[n][0], lo), min(start[n][1], hi)
        if b <= a:
            continue
        if now and b - first > limit:
            close()
            now, first = [], a
        if not now:
            first = a
        now.append(n)
    if now:
        close()
    return cuts


def _chapter_texts(chosen, cuts, max_chars: int | None = None) -> list:
    """The chosen chapters in reading order as NAMED parts (book, pages, character range into the joined stored text of those pages): the seam
    loads the stored words itself. A part whose words cannot be located in the joined pages goes whole-pages (no range). With `max_chars` a part longer
    than that is cut on page boundaries into several parts (each its own request), numbered `part n of m` of its chapter; the first part keeps the
    chapter's own number when nothing is cut."""
    from . import agent_review_standards, nine_reviewer

    conn = connect()
    books: dict[str, dict[int, str]] = {}
    out = []
    for book, ch in chosen:
        pages_of_book = books.setdefault(
            book, dict(agent_review_standards.read_book(conn, book).pages)
        )
        pieces = []  # (pages, char_from, char_to, chars, original part number, original parts of) per piece of this chapter, in order
        cut_any = False
        for p in ch.parts:
            pages = tuple(range(p.page_from, p.page_to + 1))
            joined = "\n".join(pages_of_book[n] for n in pages if n in pages_of_book)
            body = cuts[book].text(ch.chapter_id, p.part_no)
            at = joined.find(body)
            located = at >= 0
            lo, hi = (
                (at, at + len(body)) if located else (0, len(joined))
            )  # what the seam will really send: the range, or the whole pages
            if max_chars is not None and hi - lo > max_chars:
                got = _page_cuts(pages, pages_of_book, lo, hi, max_chars)
                if len(got) > 1:
                    cut_any = True
                    pieces += [
                        (
                            pg,
                            a if located else None,
                            b if located else None,
                            b - a,
                            p.part_no,
                            p.part_of,
                        )
                        for pg, a, b in got
                    ]
                    continue
            pieces.append(
                (
                    pages,
                    at if located else None,
                    at + len(body) if located else None,
                    hi - lo,
                    p.part_no,
                    p.part_of,
                )
            )
        for k, (pg, lo, hi, chars, no, of) in enumerate(pieces, 1):
            out.append(
                nine_reviewer.ChapterText(
                    book,
                    ch.chapter_id,
                    k if cut_any else no,
                    len(pieces) if cut_any else of,
                    pg,
                    chars,
                    lo,
                    hi,
                )
            )  # a chapter that was cut is renumbered 1..m of m, so every piece is its own part
    return out


def _earlier_points(scope: frozenset[str]):
    """The earlier revision's points as `nine_context.follow_up` reads them (point id, field, the stored word, the engineer's decision), taken from
    that paper's own page list; none when the starter may not read it. The value is not kept on a point, so `still_open` stays "cannot tell"."""
    from . import access
    from . import review_points_service as svc

    def points(document_id: str):
        if document_id not in scope:
            return ()
        got = svc.assemble(
            document_id, access.AccessScope(user_id=None, allowed_document_ids=scope)
        )
        return [
            {
                "point_id": p["id"],
                "field": p.get("name"),
                "value": None,
                "status_word": p.get("pill"),
                "engineer_decision": (p.get("decision") or {}).get("state"),
            }
            for p in got["points"]
        ]

    return points


def _book_inputs(
    conn, book_ids: list[str], scope: frozenset[str], budget: int
) -> tuple[list, dict]:
    """The rule books inside the starter's access, each read once and cut into chapters (a book outside the access is counted by the
    caller, never named)."""
    from . import agent_review_standards, nine_chapters

    inputs, cuts = [], {}
    for b in book_ids:
        if b not in scope:
            continue
        book = agent_review_standards.read_book(conn, b)
        pages = sorted((n, t) for n, t in book.pages.items() if (t or "").strip())
        cut = nine_chapters.cut(b, pages, max_tokens=budget, scanned=book.ocr)
        cuts[b] = cut
        inputs.append(
            nine_librarian.BookInput(
                b, cut, why=("holds a rule chosen for this paper",)
            )
        )
    return inputs, cuts


def _roles_by_book(plan: dict) -> dict[str, set[str]]:
    """{rule book id: the field roles of the rules asked from it}: what a chapter of that book is read for."""
    out: dict[str, set[str]] = {}
    for item in plan.get("items") or []:
        book = item.get("standard_document_id")
        if book:
            out.setdefault(str(book), set()).update(
                str(r) for r in item.get("field_roles") or []
            )
    return out


#: the most paper text ONE reviewer request carries. A paper whose pages come to more is read in page windows (each request carries one window and
#: one chapter group; a window starts one page back), because the whole paper plus a chapter group would pass the seam's per-request ceiling and
#: every request would be refused (`request_too_large`)
PAPER_WINDOW_CHARS = 40_000


def paper_windows(
    pages: dict[int, str], limit: int = PAPER_WINDOW_CHARS
) -> list[list[int]]:
    """The paper's pages as windows of consecutive pages of at most `limit` characters (one page alone may be over it), each starting one page
    back. A paper that fits is ONE window holding every page: the request is then built exactly as before."""
    numbers = sorted(int(n) for n in pages)
    if sum(len(pages[n]) for n in numbers) <= limit:
        return [numbers]
    out: list[list[int]] = []
    i = 0
    while i < len(numbers):
        window, used, j = [], 0, i
        while j < len(numbers) and (
            not window or used + len(pages[numbers[j]]) <= limit
        ):
            window.append(numbers[j])
            used += len(pages[numbers[j]])
            j += 1
        out.append(window)
        if j >= len(numbers):
            break
        i = max(i + 1, j - 1)
    return out


#: what one request carries beyond the chapters: the labels and the question (characters, a margin)
REQUEST_OVERHEAD_CHARS = 3_000
#: a request never gives the chapters less than this, however large the shared part is
MIN_CHAPTER_CHARS = 15_000


def chapter_budget(ctx, pages: dict[int, str]) -> int:
    """How many characters of chapter text one reviewer request may carry: the per-request ceiling (`nine_call.MAX_REQUEST_CHARS`) less what every
    request already carries (the paper's pages, the fact digest at its largest one block per kind, the blank list, the project context) and a margin."""
    shared = (
        max(sum(len(pages[n]) for n in w) for w in paper_windows(pages)) if pages else 0
    )
    sheet = ctx.store.get("fact_sheet")
    if sheet is not None:
        tagged, untagged, _left = nine_facts.digest_rows(sheet, pages)
        blank, _b = nine_facts.blank_rows(sheet)
        cap = nine_call.MAX_DERIVED_CHARS
        shared += (
            min(nine_facts._cost(tagged), cap)
            + min(nine_facts._cost(untagged), cap)
            + nine_facts._cost(blank)
        )
    shared += sum(
        nine_facts._cost(b.items) for b in ctx.store.get("context_blocks") or ()
    )
    return max(
        nine_call.MAX_REQUEST_CHARS - shared - REQUEST_OVERHEAD_CHARS, MIN_CHAPTER_CHARS
    )


def request_groups(ctx, pages: dict[int, str], chosen, cuts) -> list:
    """The chapter groups of the reviewer's requests: chapters cut on page boundaries to the per-request budget and packed by characters up to it. Records
    the plan (the budget and how many parts the cutting added) in `ctx.store["request_plan"]` for the role's record."""
    from . import nine_reviewer

    budget = chapter_budget(ctx, pages)
    texts = _chapter_texts(chosen, cuts, max_chars=budget)
    ctx.store["request_plan"] = {
        "chapter_budget_chars": budget,
        "paper_windows": len(paper_windows(pages)),
        "chapter_parts_added_by_cutting": len(texts)
        - sum(len(ch.parts) for _b, ch in chosen),
    }
    return nine_reviewer.group_chapters(texts, limit_chars=budget)


def _blank(paper_id: str, rows: list, roles: set | None) -> list:
    """The blank-fields block (one line list), narrowed to the chapter's fields when `roles` are given, and cut to one derived block if it came to more."""
    keep = [r for r in rows if not roles or r[1] in roles]
    keep, _cut = nine_facts.fit_rows(keep)
    block = nine_facts.blank_block(paper_id, keep)
    return [block] if block else []


def _with_cache(blocks: list) -> list:
    import dataclasses

    if blocks:
        blocks[-1] = dataclasses.replace(blocks[-1], cache=True)
    return blocks


def _prefix(ctx, pages: dict[int, str], groups: list | None = None):
    """The reviewer's prefixes and groups for a paper in ONE window (exactly `_prefix_core`), or, for a paper over `PAPER_WINDOW_CHARS`, for each
    window in turn: the groups are repeated once per window (as they are once per part of the digest) and the prefix of each repeat carries only
    that window's pages. What a request really sent is read from its answer, so a quote from a page outside its window is never verified by it."""
    windows = paper_windows(pages)
    if len(windows) == 1:
        return _prefix_core(ctx, pages, groups, windows[0])
    plans, expanded, no_context = [], [], True
    for w in windows:
        pre, grp, none = _prefix_core(ctx, pages, groups, w)
        no_context = no_context and none
        for k, g in enumerate(grp):
            plans.append(pre(k, g) if callable(pre) else pre)
            expanded.append(g)
    return (lambda i, _g: plans[i]), expanded, no_context


def _prefix_core(ctx, pages: dict[int, str], groups: list | None, window: list[int]):
    """(what the reviewer sends before each chapter group, the groups to send, whether NO context could be passed). The shared part is the paper's pages
    (named), the fact-sheet digest (derived blocks, the paper their only source) and the project context as ONE derived block PER SOURCE document.

    When the digest fits one derived block (30,000 characters) it is shared by every request (cached). When it does not, each request carries only the
    facts of the fields the rules asked from THAT chapter's book are about, and if even those do not fit one block the chapter is sent once per PART of
    the rows (on page boundaries). Nothing is dropped without a count: `ctx.store["digest_counts"]` holds the rows, the parts and what never went."""
    base = [nine_call.Block("paper", ctx.submittal, (int(n),)) for n in window]
    context = list(ctx.store.get("context_blocks") or ())
    sheet = ctx.store.get("fact_sheet")
    groups = list(groups or [])
    if sheet is None:
        return _with_cache([*base, *context]), groups, not context
    tagged, untagged, left = nine_facts.digest_rows(sheet, pages)
    blank, blank_left = nine_facts.blank_rows(sheet)
    left.update(blank_left)
    total = len(tagged) + len(untagged)
    counts = {
        "rows": total,
        "rows_blank": len(blank),
        "parts": 1,
        "never_sent": 0,
        "left_out_reasons": dict(left),
    }
    ctx.store["digest_counts"] = counts
    if nine_facts.digest_fits(tagged, untagged):
        return (
            _with_cache(
                [
                    *base,
                    *nine_facts.rows_blocks(sheet.paper_id, tagged, untagged),
                    *_blank(sheet.paper_id, blank, None),
                    *context,
                ]
            ),
            groups,
            not context,
        )
    by_book = _roles_by_book(ctx.plan)
    expanded, plans, sent = [], [], set()
    for g in groups or [[]]:
        roles = (
            nine_facts.codes_of(
                set().union(*(by_book.get(c.book_id, set()) for c in g))
            )
            if g
            else set()
        )
        parts, _lost = nine_facts.digest_parts(
            sheet.paper_id, tagged, untagged, roles or None
        )
        for part in parts or [[]]:
            expanded.append(g)
            plans.append(
                _with_cache(
                    [*base, *part, *_blank(sheet.paper_id, blank, roles), *context]
                )
            )
            sent.update(str(row[0]) for b in part for row in b.items)
    never = [r for r in (*tagged, *untagged) if str(r[0]) not in sent]
    all_roles = (
        nine_facts.codes_of(set().union(*by_book.values())) if by_book else set()
    )
    why = Counter(
        "field not asked from any chapter's book"
        if (all_roles and r[1] not in all_roles)
        else "over the size limit of a derived block"
        for r in never
    )
    counts.update(
        parts=max(len(plans) // max(len(groups), 1), 1),
        requests=len(plans),
        never_sent=len(never),
    )
    counts["left_out_reasons"] = {**left, **dict(why)}
    return (lambda i, _g: plans[i]), expanded, not context
