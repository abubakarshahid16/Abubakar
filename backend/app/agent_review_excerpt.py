"""Fit the question to the local window instead of refusing it (the local AI reviewer, 12 Nov 2026, measured on a 5-page valve datasheet).

The first real local run asked nothing: every request carried the whole of pages 1 to 4 (about 5,600 tokens by the repo's fail-safe estimate)
with 3 items and their clause text, against an 8,192-token window. This module builds what an item NEEDS from the stored page text, in
pure functions (no model, no I/O, no layout of any one datasheet):

  * `label_lines`   the lines of a page that carry the item's field words (`field_roles` and the rule label's field), by content words.
  * `windows_for`   an ordered list of windows for ONE item: first the label excerpts (the label line, a stated number of lines
                    above and below it, and the page's notes block when a label line points to a note), then every other part of every
                    page in overlapping line windows, so that asking them ALL covers the whole paper. A window is a `{page: text}` of
                    only the pages and line ranges it holds, with "..." marking a gap.
  * `trim_clause`   the one clause around the requirement, not the section.

ABSENCE NEEDS FULL COVERAGE. The runner (`agent_review_local_run`) asks the windows one after another; the item is decided at the first
window that holds an answer; "not found" is a claim about the paper only when EVERY window of EVERY page was asked and none was
discarded. Otherwise the line says "not all of the paper could be asked". Quotes are still verified by code against the FULL stored page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import agent_review_verdict as verdict
from . import context_budget
from .agent_bind import content_words

LINES_AROUND = 8  # lines above and below a label line, shrunk when the budget is short
OVERLAP_LINES = 4  # lines a later window repeats from the one before: a table row of up to ROW_LINES_WHOLE lines is whole in one window
ROW_LINES_WHOLE = OVERLAP_LINES + 1
NOTE_LINES = (
    10  # lines of the page's notes block added when a label line points to a note
)
MAX_CLAUSE_CHARS = 1400
_NOTE_POINTER = re.compile(r"\(\s*\d+\s*\)|\bnotes?\s*\d|\bsee\s+note|\*")
_NOTE_HEAD = re.compile(r"^\s*notes?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Window:
    """One thing asked about an item: `pages` is what is SHOWN (page -> text), `label` says it is a label excerpt (else a coverage window)."""

    pages: dict[int, str]
    label: bool

    def is_full(self, full: Mapping[int, str]) -> bool:
        """Does this window show every page of the paper, every line whole? Only then is a reading of it a reading of the paper."""
        return (
            not self.label
            and {n: t for n, t in full.items() if (t or "").strip()} == self.pages
        )


def field_words(item: Mapping) -> frozenset[str]:
    """The words of the field the item asks about: its field roles and its rule label's field, as content words."""
    label = (
        item.get("rule_label") if isinstance(item.get("rule_label"), Mapping) else {}
    )
    roles = " ".join(str(r).replace("_", " ") for r in item.get("field_roles") or [])
    return content_words(f"{roles} {str(label.get('field') or '').replace('_', ' ')}")


def label_lines(lines: list[str], want: frozenset[str]) -> list[int]:
    """Indexes of the lines that carry the field words: all of them when there are one or two, all but one otherwise. None when no line does."""
    if not want:
        return []
    need = len(want) if len(want) <= 2 else len(want) - 1
    return [i for i, ln in enumerate(lines) if len(want & content_words(ln)) >= need]


def _ranges(hits: list[int], around: int, n: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for i in hits:
        lo, hi = max(0, i - around), min(n, i + around + 1)
        if spans and lo <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))
    return spans


def _render(lines: list[str], spans: list[tuple[int, int]]) -> str:
    out: list[str] = []
    for k, (lo, hi) in enumerate(spans):
        if lo > 0 and (k == 0 or lo > spans[k - 1][1]):
            out.append("...")
        out.extend(lines[lo:hi])
    if spans and spans[-1][1] < len(lines):
        out.append("...")
    return "\n".join(out)


def _tokens(text: str) -> int:
    return context_budget.estimate_tokens(text)


def _label_window(
    pages: Mapping[int, str], want: frozenset[str], budget: int
) -> Window | None:
    """The label excerpt over all pages, shrunk (fewer lines around) until its estimated tokens fit `budget`; None when no label line is found
    or it cannot be made to fit."""
    split = {n: t.splitlines() for n, t in pages.items() if (t or "").strip()}
    hits = {n: label_lines(ls, want) for n, ls in split.items()}
    if not any(hits.values()):
        return None
    for around in range(LINES_AROUND, -1, -2):
        shown: dict[int, str] = {}
        for n, ls in split.items():
            if not hits[n]:
                continue
            spans = _ranges(hits[n], around, len(ls))
            if any(
                _NOTE_POINTER.search(ls[i]) for i in hits[n]
            ):  # the label points to a note: the page's notes block comes too
                head = next(
                    (i for i, ln in enumerate(ls) if _NOTE_HEAD.match(ln)), None
                )
                if head is not None:
                    spans = _ranges(
                        sorted(
                            {
                                *(s for sp in spans for s in range(sp[0], sp[1])),
                                *range(head, min(len(ls), head + NOTE_LINES)),
                            }
                        ),
                        0,
                        len(ls),
                    )
            shown[n] = _render(ls, spans)
        if sum(_tokens(t) for t in shown.values()) <= budget:
            return Window(shown, True)
    return None


def _coverage_windows(pages: Mapping[int, str], budget: int) -> list[Window]:
    """Every line of every page, in order, in windows of at most `budget` estimated tokens: whole pages are packed together while they fit
    (a short paper is ONE window); a page longer than the budget is cut by lines, each cut repeating OVERLAP_LINES of the one before."""
    out: list[Window] = []
    group: dict[int, str] = {}
    used = 0
    for n in sorted(pages):
        text = pages[n] or ""
        cost = _tokens(text) + 1
        if cost <= budget:
            if group and used + cost > budget:
                out.append(Window(group, False))
                group, used = {}, 0
            group[n], used = text, used + cost
            continue
        if group:
            out.append(Window(group, False))
            group, used = {}, 0
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            j, spent = i, 0
            while j < len(lines) and (
                j == i or spent + _tokens(lines[j]) + 1 <= budget
            ):
                spent += _tokens(lines[j]) + 1
                j += 1
            out.append(Window({n: _render(lines, [(i, j)])}, False))
            if j >= len(lines):
                break
            i = max(i + 1, j - OVERLAP_LINES)
    if group:
        out.append(Window(group, False))
    return out


def windows_for(item: Mapping, pages: Mapping[int, str], budget: int) -> list[Window]:
    """The windows to ask for ONE item, in order: its label excerpt first (when a label line is found and it fits), then the coverage
    windows of the whole paper. Asking all of them covers every line of every page."""
    found = _label_window(pages, field_words(item), budget)
    return ([found] if found else []) + _coverage_windows(pages, budget)


@dataclass(frozen=True)
class ClauseText:
    """What goes to the model for one clause. `sent` is the text; `conditions` is what the CODE read in the WHOLE clause before any trimming
    (every line with a condition or exception word, every NOTE block): the condition guards read it whatever was sent; `shortened` says
    the text sent is less than the clause; `fits` is False when the minimum that may be sent (the requirement, every condition line, every
    NOTE) is longer than `MAX_MINIMUM_CHARS`: the item is then not asked, never asked with the exception missing."""

    sent: str
    conditions: str
    shortened: bool
    fits: bool


MAX_MINIMUM_CHARS = 6000
_NOTE_LINE = re.compile(r"^\s*notes?\b", re.IGNORECASE)


def trim_clause(
    text: str, requirement: str | None, limit: int = MAX_CLAUSE_CHARS
) -> ClauseText:
    """The clause for the model: the whole of it when it is at most `limit` characters; else the REQUIREMENT lines, EVERY line that carries a
    condition or exception word (`agent_review_verdict.is_conditional`, the one vocabulary) and EVERY NOTE block of the clause, then the
    nearest lines around the requirement up to `limit`. The code reads the conditions of the WHOLE clause first (`conditions`)."""
    lines = text.splitlines()
    notes: set[int] = set()
    head = next((i for i, ln in enumerate(lines) if _NOTE_LINE.match(ln)), None)
    if head is not None:
        notes = set(
            range(head, len(lines))
        )  # a NOTE block runs to the end of the clause
    cond = {i for i, ln in enumerate(lines) if verdict.is_conditional(ln)}
    conditions = "\n".join(lines[i] for i in sorted(cond | notes))
    if len(text) <= limit:
        return ClauseText(text, conditions, False, True)
    anchor = (requirement or "").strip()[:60].lower()
    req = {i for i, ln in enumerate(lines) if anchor and anchor in ln.lower()}
    if (
        not req and anchor
    ):  # the requirement may wrap across lines: the line holding its first words
        req = {next((i for i, ln in enumerate(lines) if anchor[:20] in ln.lower()), 0)}
    keep = req | cond | notes
    if sum(len(lines[i]) + 1 for i in keep) > MAX_MINIMUM_CHARS:
        return ClauseText("", conditions, True, False)
    centre = min(req) if req else 0
    used = sum(len(lines[i]) + 1 for i in keep)
    for d in range(1, len(lines)):
        for i in (centre - d, centre + d):
            if (
                0 <= i < len(lines)
                and i not in keep
                and used + len(lines[i]) + 1 <= limit
            ):
                keep.add(i)
                used += len(lines[i]) + 1
        if used >= limit:
            break
    spans = [(i, i + 1) for i in sorted(keep)]
    return ClauseText(_render(lines, _merge(spans)), conditions, True, True)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in spans:
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def fit_budget(
    window_tokens: int, out_tokens: int, margin: int, fixed: Callable[[], int] | int
) -> int:
    """Estimated tokens left for the page excerpt: the window, less the output limit, the margin and everything else in the request."""
    other = fixed() if callable(fixed) else int(fixed)
    return max(0, window_tokens - out_tokens - margin - other)
