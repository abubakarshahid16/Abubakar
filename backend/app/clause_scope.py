"""Order 161 B: find the parts of a standard whose own words limit them.

`ai_applicability.divisions` knows a closed set of heading shapes and a part
that starts a page. This module widens WHAT IS READ, never what is decided:

- `candidate_starts` proposes lines that may open a part (a break the division
  finder made, or a line of the SHAPE "capitalised word, then an id"); the
  model reads each; one it is unsure of holds its requirements, one it does
  not confirm inherits the part before it (`downgrade`: it can only hold,
  never exclude, never rescue); a start found by shape or break can only HOLD,
  even when the model confirms it, because nothing checks it is a real part;
- `subclause_units` lists the sub-headings of one division that hold a wanted
  requirement, their extent taken from the standard's own headings;
- `screen_titles` asks the model which of those titles say the rules there are
  limited; CODE keeps only a title that is verbatim one it supplied, and says
  None when the read failed (so the caller counts it, never "none flagged").

No standard, part, material or layout is named and no word list decides:
a shape only proposes, the model reads, code verifies, an engineer decides.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable

from . import ai_task_runner, subject_scope
from .ai import output_limits

#: A candidate start is among this many first lines of its page, and is at
#: most this many words; a page with this many of them is a contents page.
_TOP = 5
_WORDS = 12
_CONTENTS_LEAST = 5
#: At most this many sub-heading titles go to the model in one read.
MAX_TITLES = 60

_ID = r"(?:\d+(?:[.\-][0-9A-Za-z]+)*|[IVXLC]{1,6}|[A-Z](?:-[0-9A-Z]+)*)"
#: The SHAPE of a heading: one or two capitalised words of 4+ letters, then an
#: id token. It proposes a line; it never decides what the line means.
_SHAPE = re.compile(r"^(?:[A-Z][A-Za-z]{3,}\s+){1,2}" + _ID + r"(?![A-Za-z0-9])")


def _page_indices(text: subject_scope.StandardText) -> list[list[int]]:
    out = []
    for lo, hi in text.page_bounds.values():
        first = bisect.bisect_left(text.offsets, lo, hi=len(text.lines))
        last = bisect.bisect_left(text.offsets, hi, lo=first, hi=len(text.lines))
        out.append(list(range(first, last)))
    return out


def _entry(text: subject_scope.StandardText, index: int, kind: str) -> dict:
    return {
        "at": text.offsets[index],
        "line": index,
        "heading": text.lines[index],
        "kind": kind,
    }


def candidate_starts(text: subject_scope.StandardText, divs: list[dict]) -> list[dict]:
    """Where a part may start that `ai_applicability.divisions` did not find:
    {"at", "line", "heading", "kind"} in text order. "break": every break the
    division finder made (name None). "shape": a line among the first lines of
    its page, short, no running header, no contents entry, of the shape
    `_SHAPE`, and not already a division."""
    known = {d["line"] for d in divs}
    out = {d["line"]: _entry(text, d["line"], "break") for d in divs if not d["name"]}
    pages = _page_indices(text)
    running = subject_scope._running_lines([[text.lines[i] for i in p] for p in pages])
    for indices in pages:
        found = []
        for index in indices[:_TOP]:
            line = text.lines[index]
            shape = _SHAPE.match(line)
            rest = line[shape.end() :] if shape else ""
            if (
                index in known
                or shape is None
                or len(line.split()) > _WORDS
                or re.sub(r"\d+", "#", line) in running
                or subject_scope._NOT_A_TITLE.search(rest)  # a contents entry
            ):
                continue
            found.append(index)
        if len(found) < _CONTENTS_LEAST:  # that many is a contents page
            out.update({i: _entry(text, i, "shape") for i in found})
    return [out[line] for line in sorted(out)]


def subclause_units(
    text: subject_scope.StandardText,
    div: dict,
    end: int | None,
    wanted_lines: Iterable[int],
    limit: int | None = MAX_TITLES,
) -> list[dict]:
    """The sub-headings of division `div` (lines up to `end`, the next start or
    break; None: the text's end) that hold at least one line of `wanted_lines`
    (line indexes of requirements): {"line", "at", "end" (offsets), "title"},
    at most `limit` (default `MAX_TITLES`; None: all), one per title. A unit
    runs from its heading to the next heading that closes it, as
    `StandardText.spans` reads the standard's own headings, never past the
    division."""
    stop = len(text.lines) if end is None else end
    cap = text.offsets[stop]
    wanted = sorted(set(wanted_lines))
    out: list[dict] = []
    for index in range(div["line"] + 1, stop):
        head = text.heads[index]
        if head is None or index in text.bare:
            continue
        at = text.offsets[index]
        # the extent that opens at this very heading
        span = next((s for s in text.spans(head) if s[0] == at), None)
        last = min(span[2], cap) if span else cap
        if not any(index <= w and text.offsets[w] < last for w in wanted):
            continue
        title = text.lines[index]
        if any(
            subject_scope._key(u["title"]) == subject_scope._key(title) for u in out
        ):
            continue
        out.append({"line": index, "at": at, "end": last, "title": title})
        if limit is not None and len(out) >= limit:
            break
    return out


SUBSCOPE_SCHEMA = {
    "type": "object",
    "required": ["titles"],
    "properties": {"titles": {"type": "array", "items": {"type": "string"}}},
}

SUBSCOPE_INSTRUCTION = """The TEXT is a list of sub-heading titles of one division
of an engineering standard, one title per line. Answer: titles - the titles
whose OWN words say that the rules under them are limited to one material,
product form, construction or grade, each copied exactly as written. Leave out
every title that names no such limit. Return an empty list when none does."""


SUBSCOPE_TASK = ai_task_runner.register(
    ai_task_runner.TaskSpec(
        name="subclause_scope",
        version="v1",
        instruction=SUBSCOPE_INSTRUCTION,
        schema=SUBSCOPE_SCHEMA,
        num_predict=output_limits.max_tokens_for(
            output_limits.ROUTE_CLAUSE_APPLICABILITY
        ),
    )
)


def screen_titles(units: list[dict], provider, run: dict) -> list[dict] | None:
    """The units whose title the model flagged as limited, verified by code:
    a returned title counts only when it is, letters and digits alone, one of
    the supplied titles; a title that is not (invented) is dropped on its own,
    it does not discard the valid ones of the same reply. None when the read
    failed (a reply that does not fit, a model error, a stopped model): the
    caller must count the requirements as not screened, never as screened with
    none flagged. Only the first `MAX_TITLES` units are offered; the gate
    counts the requirements under the rest."""
    from . import ai_applicability

    if not units:
        return []
    data = ai_applicability._read(
        SUBSCOPE_TASK, "\n".join(u["title"] for u in units[:MAX_TITLES]), provider, run
    )
    if data is None:
        return None
    returned = {subject_scope._key(t) for t in data.get("titles") or []}
    return [u for u in units[:MAX_TITLES] if subject_scope._key(u["title"]) in returned]


def downgrade(verdict: str | None) -> str:
    """What a region that no part start was confirmed for inherits from the
    part before it: an exclusion becomes a hold, a hold stays, the rest is
    kept. Code never excludes on an inherited reading."""
    return "held" if verdict in ("does_not_apply", "held") else "kept"
