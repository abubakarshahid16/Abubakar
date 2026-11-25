"""THE PAPER MAP: how the judge reads a paper too long for one call, without judging any piece blind (owner's standing lesson,
25 Nov 2026 23:15: "the model did not have the full context of the document and could not decide well"). Behind
`settings.aim_paper_map_enabled` (OFF): off, a long paper is judged window by window as before, and the run says so.

Used ONLY when the paper does not fit one call (`paper.windows` gives more than one window, on Claude or on the local model,
whose smaller window comes from the same function). A paper that fits is judged whole, exactly as before.

THE MAP (`build`, `text`) is made by CODE from every page, no model: per page its headings, its tags and other identifiers,
how many table rows it holds, and the values the app's own reader finds there (`claims.extract_measurements`), each with its
page. Every judge call gets the map AND the full text of the pages its items cite (`plan`): the item's own paper pages, else
the pages where code finds its paper fields, with one page either side. An item that names no page and whose fields code finds
nowhere is judged on every part of the paper in turn, each part with the map. An item whose cited pages do not show what it
needs says so and names the page the map shows; it is asked again on that page, then on every part it was not given (`judge`),
so "the paper shows it on no page" is said only after every page was read.

THE RECORD: every judge call says what it read, "whole paper" or "map + pages N-M" (or, switch off, "page window N-M, no map"):
`identity.judge_seen`, in call order. No text is logged; the map itself is paper text sent like the paper, to the same model."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings

#: Per page, at most this many entries of each kind, each at most `ENTRY_CHARS` characters (the map stays a map).
MAX_HEADINGS, MAX_TAGS, MAX_VALUES, ENTRY_CHARS = 8, 12, 12, 70
#: One page either side of an item's cited pages (a table or a clause runs over a page break).
NEIGHBOURS = 1
WHOLE = "whole paper"

_HEADING = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*\.?|[A-Z]\.|(?:ARTICLE|SECTION|SCHEDULE|PART|APPENDIX|ANNEX)\s+\w+)\s+\S.*)$"
)
_CAPS = re.compile(r"^[^a-z]*[A-Z]{3}[^a-z]*$")
_TAG = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_CELLS = re.compile(r"\t| {2,}|\|")

MAP_LINE = """THIS IS A LONG PAPER of %(count)d pages. Above are its MAP, made by code from every page (headings, tags, table rows and
values read on each page, with the page), and the FULL TEXT of pages %(pages)s. Judge each item on the full pages given, and
quote only from them; use the map to know what stands on the other pages. If what an item needs is not on the full pages given,
reply for it {"id": "C..", "not_here": true, "page": the page the map shows it on, or null} and nothing else: it is asked again
with that page.
"""


def on() -> bool:
    return bool(settings.aim_paper_map_enabled)


def _short(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= ENTRY_CHARS else s[: ENTRY_CHARS - 1] + "~"


def _page_entry(text: str) -> dict:
    from app import claims

    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    heads = [
        _short(ln)
        for ln in lines
        if len(ln.strip()) <= 90 and (_HEADING.match(ln) or _CAPS.match(ln))
    ]
    tags = sorted(
        {
            m.group(0)
            for m in _TAG.finditer(text or "")
            if any(c.isdigit() for c in m.group(0))
        }
    )
    rows = sum(
        1
        for ln in lines
        if len([c for c in _CELLS.split(ln.strip()) if c.strip()]) >= 3
    )
    values = []
    for ln in lines:
        for m in claims.extract_measurements(ln):
            label = (
                ln.split(m.raw_value)[0].strip(" :=-\t") if m.raw_value in ln else ""
            )
            values.append(
                _short(f"{label[-40:]}: {m.raw_value} {m.raw_unit}".strip(": "))
            )
    return {"headings": heads[:MAX_HEADINGS], "tags": tags[:MAX_TAGS], "table_rows": rows,
            "values": list(dict.fromkeys(values))[:MAX_VALUES]}  # fmt: skip


def build(paper) -> dict[int, dict]:
    """The map: {page: {"headings", "tags", "table_rows", "values"}}, every page of the paper, code only."""
    return {n: _page_entry(t) for n, t in sorted(paper.pages.items())}


def text(m: dict[int, dict]) -> str:
    out = [
        "PAPER MAP (made by code from every page; each entry is the paper's own words, cut at a mark ~):"
    ]
    for n, e in sorted(m.items()):
        parts = [f"headings: {' | '.join(e['headings'])}" if e["headings"] else "",
                 f"tags: {', '.join(e['tags'])}" if e["tags"] else "",
                 f"table rows: {e['table_rows']}" if e["table_rows"] else "",
                 f"values: {' | '.join(e['values'])}" if e["values"] else ""]  # fmt: skip
        out.append(
            f"page {n}: "
            + (
                "; ".join(p for p in parts if p)
                or "no heading, tag, table or value read"
            )
        )
    return "\n".join(out) + "\n\n"


def tokens(s: str) -> int:
    from app import agent_general_review

    return agent_general_review.tokens_of(s)


def page_cost(paper, n: int) -> int:
    return (
        tokens(paper.pages.get(n) or "") + 20
    )  # the window walker's own cost of a page (`window_pages`)


def room(paper, windows: list[list[int]], map_text: str) -> int:
    """The tokens of paper text one call may carry besides the map: the largest window the caller allows, less the map."""
    largest = max((sum(page_cost(paper, n) for n in w) for w in windows), default=0)
    return max(
        largest - tokens(map_text),
        max((page_cost(paper, n) for n in paper.pages), default=0),
    )


def pages_text(pages) -> str:
    """ "3-5, 9": the pages read, as ranges."""
    nums, out = sorted(set(pages)), []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def seen(pages) -> str:
    return f"map + pages {pages_text(pages)}"


def cited_pages(item: dict, paper) -> list[int]:
    """The pages an item cites (its own paper pages), else the pages where code finds one of its paper fields; with neighbours.
    [] when it names none and code finds none."""
    have = set(paper.pages)
    own = {
        int(p)
        for p in item.get("paper_pages") or []
        if isinstance(p, int) and p in have
    }
    if not own:
        fields = [
            str(f).strip().lower()
            for f in item.get("paper_fields") or []
            if len(str(f).strip()) >= 4
        ]
        own = {
            n
            for n, t in paper.pages.items()
            if any(f in (t or "").lower() for f in fields)
        }
    return sorted(
        {m for n in own for m in range(n - NEIGHBOURS, n + NEIGHBOURS + 1) if m in have}
    )


@dataclass
class Call:
    items: list[dict]
    pages: list[int]

    @property
    def seen(self) -> str:
        return seen(self.pages)


def _fit(paper, pages: list[int], limit: int) -> list[int]:
    """The pages in order up to `limit` tokens (at least the first): an item whose own pages alone exceed one call."""
    out, used = [], 0
    for n in pages:
        if out and used + page_cost(paper, n) > limit:
            break
        out.append(n)
        used += page_cost(paper, n)
    return out


def parts(paper, limit: int) -> list[list[int]]:
    """The paper in parts of at most `limit` tokens (for an item code cannot place): the same walker as the windows."""
    from app import agent_general_review

    return agent_general_review.window_pages(paper.pages, int(limit), 1)


def plan(
    paper, items: list[dict], windows: list[list[int]], batch: int, map_text: str
) -> list[Call]:
    """The judge calls of a long paper: items grouped by their cited pages (at most `batch` items, the pages within the room);
    an item code cannot place is asked on every part of the paper."""
    limit = room(paper, windows, map_text)
    placed = sorted(
        ((cited_pages(it, paper), it) for it in items),
        key=lambda p: (p[0][:1] or [10**9], p[1]["id"]),
    )
    calls: list[Call] = []
    loose = [it for pages, it in placed if not pages]
    for pages, it in ((p, it) for p, it in placed if p):
        pages = _fit(paper, pages, limit)
        last = (
            calls[-1]
            if calls and calls[-1].pages and len(calls[-1].items) < batch
            else None
        )
        union = sorted(set(last.pages) | set(pages)) if last else pages
        if last and sum(page_cost(paper, n) for n in union) <= limit:
            last.items.append(it)
            last.pages = union
        else:
            calls.append(Call([it], pages))
    for part in parts(paper, limit) if loose else []:
        calls += [Call(loose[k : k + batch], part) for k in range(0, len(loose), batch)]
    return calls


def again(paper, named, asked: set[int], windows, map_text: str) -> list[list[int]]:
    """A later round for an item whose pages did not show what it needs: the page it named (with neighbours), else every part
    of the paper it was not given whole."""
    have = set(paper.pages)
    if isinstance(named, int) and named in have and named not in asked:
        return [
            sorted(
                {
                    m
                    for m in range(named - NEIGHBOURS, named + NEIGHBOURS + 1)
                    if m in have
                }
            )
        ]
    return [
        p for p in parts(paper, room(paper, windows, map_text)) if not set(p) <= asked
    ]


def _shared(pairs, batch: int) -> list[Call]:
    """Items asked again on the same pages share calls (at most `batch` items each)."""
    by_pages: dict[tuple, list[dict]] = {}
    for it, pages in pairs:
        by_pages.setdefault(tuple(pages), []).append(it)
    return [
        Call(its[k : k + batch], list(p))
        for p, its in by_pages.items()
        for k in range(0, len(its), batch)
    ]


def _collect(calls, results, answers, errors, asked, scope) -> dict[str, object]:
    """Each call's answers onto its items (the model's own label first: `_scope_unverified`), its errors, the pages each item
    was given whole; returns {item id: the page it named} for an item that said its pages do not show it."""
    from . import steps as S

    named: dict[str, object] = {}
    for c, got in zip(calls, results, strict=True):
        if got is None:
            continue
        if got[0] == "failed":
            for it in c.items:
                errors.setdefault(it["id"], str(got[1]))
            continue
        rows = S._rows(got[1])
        for it in c.items:
            asked[it["id"]] |= set(c.pages)
            for j in rows.get(it["id"]) or []:
                answers[it["id"]].append(
                    S._scope_unverified(j, bool(S._scope_line(scope)))
                )
                if j.get("not_here"):
                    named[it["id"]] = j.get("page")
    return named


def _again_calls(items, answers, named, asked, paper, windows, map_text) -> list[Call]:
    """The next round: every item whose answers so far all say "not here", on the page it named (`named`), else on every part
    it was not given whole."""
    from . import steps as S

    pairs = [(it, p) for it in items if answers[it["id"]] and all(j.get("not_here") for j in answers[it["id"]])
             for p in again(paper, named.get(it["id"]), asked[it["id"]], windows, map_text)]  # fmt: skip
    return _shared(pairs, S.JUDGE_BATCH)


def judge(
    model,
    paper,
    checklist: dict,
    text_: object,
    *,
    items,
    windows,
    lead,
    cancelled=None,
    progress=None,
    scope=None,
):
    """The judge on a long paper by the map: (lines, stop), the same lines and the same code checks as `steps.s4_judge`, and
    `scope["judge_seen"]` lists what each call read."""
    from . import disciplines as D
    from . import parallel
    from . import steps as S

    books = {b["alias"]: b for b in checklist.get("books") or []}
    map_text = text(build(paper))
    head = S._scope_line(scope) + D.judge_head(scope)
    answers: dict[str, list[dict]] = {it["id"]: [] for it in items}
    errors: dict[str, str] = {}
    asked: dict[str, set[int]] = {it["id"]: set() for it in items}
    record: list[str] = []
    calls = plan(paper, items, windows, S.JUDGE_BATCH, map_text)
    stop = ""
    for rnd in (1, 2, 3):
        if not calls:
            break
        reqs = [S._batch_request(paper, c.items, books, text_, map_text + S.paper_block(paper, c.pages),
                                 MAP_LINE % {"count": len(paper.pages), "pages": pages_text(c.pages)} + head, lead)
                for c in calls]  # fmt: skip
        results, stop = parallel.run_calls(
            model, reqs, workers=S.JUDGE_PARALLEL, cancelled=cancelled
        )
        record += [
            c.seen for c, got in zip(calls, results, strict=True) if got is not None
        ]
        named = _collect(calls, results, answers, errors, asked, scope)
        if stop or rnd == 3:
            break
        # round 2: the page the item named; round 3: every part it was not given whole (only then "on no page" is true)
        calls = _again_calls(
            items, answers, named if rnd == 1 else {}, asked, paper, windows, map_text
        )
    if isinstance(scope, dict):
        scope["judge_seen"] = record
    if progress is not None:
        progress(100, "judge")
    lines = [
        ln
        for it in items
        for ln in S._lines_of(
            it, answers[it["id"]], paper, books, errors.get(it["id"], ""), True
        )
    ]
    return lines, stop


def window_jobs(
    paper, batches, windows, books, text_, scope, lead
) -> list[tuple[list[dict], dict]]:
    """The judge's (batch, request) pairs for a paper that fits (one window) or a long one with the map switched off (window
    by window), in window then batch order (the one-at-a-time order); records what each call reads (`judge_seen`)."""
    from . import disciplines as D
    from . import prompts as P
    from . import steps as S

    windowed, jobs, record = len(windows) > 1, [], []
    discipline = D.judge_head(scope)  # "" = the general judge
    for win in windows or [sorted(paper.pages)]:
        cached = S.paper_block(paper, win if windowed else None)
        line = P.WINDOW_LINE % {
            "first": win[0],
            "last": win[-1],
            "count": len(paper.pages),
        }
        head = (line if windowed else "") + S._scope_line(scope) + discipline
        jobs += [
            (b, S._batch_request(paper, b, books, text_, cached, head, lead))
            for b in batches
        ]
        record += [
            f"page window {pages_text(win)}, no map" if windowed else WHOLE
        ] * len(batches)
    if isinstance(scope, dict):
        scope["judge_seen"] = record
    return jobs
