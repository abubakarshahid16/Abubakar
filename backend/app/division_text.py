"""#141: where a standard's DIVISIONS (parts, appendices, annexes, chapters)
are, where each requirement sits, and what the model reads of a division.
Moved out of `ai_applicability` (names re-exported there). No standard or part
is named: the words are the structural words standards use for a top-level
division."""

from __future__ import annotations

import bisect
import re

from . import subject_scope

#: A division heading: the structural word, a short id (a number, or one to
#: four capitals with an optional "-A" letter), then the end of the line or a
#: title (`subject_scope._TITLE_REST`). The word is capitalised ("Part",
#: "PART"): a "part" inside a wrapped sentence is not a heading, and neither
#: is "Part 3 of this" (a lower-case word follows the id).
_DIVISION = re.compile(
    r"^(?:(?i:(?:non-?)?mandatory|normative|informative)\s+)?"
    r"(?:P(?i:art)|A(?i:ppendix|nnex)|C(?i:hapter))\s+"
    r"(?P<id>\d{1,3}[A-Z]?|[A-Z]{1,4}(?:-[A-Z]{1,2})?)(?![A-Za-z0-9])"
    + subject_scope._TITLE_REST
)
#: A contents-page entry: a heading with a title that ends in a page number.
_CONTENTS_TAIL = re.compile(r"[A-Za-z)]\s*[.\s]*\s\d{1,4}$")


def _page_lines(text: subject_scope.StandardText, lo: int, hi: int) -> list[int]:
    """The indices of the lines of the page that runs from `lo` to `hi`."""
    first = bisect.bisect_left(text.offsets, lo, hi=len(text.lines))
    last = bisect.bisect_left(text.offsets, hi, lo=first, hi=len(text.lines))
    return list(range(first, last))


#: A division heading is among this many first lines of its page.
_DIVISION_TOP = 5
#: How far into a division its scope clause is looked for (lines), and how
#: many words of the division the model reads.
_SCOPE_LOOK = 160
SCOPE_WORDS = 170
_SCOPE_LINE = re.compile(r"\bscope\b", re.IGNORECASE)


def divisions(text: subject_scope.StandardText) -> list[dict]:
    """The divisions of a standard and the lines that end them, in order:
    {"at" (offset in the folded text), "line" (index), "name", "heading"}.

    A division STARTS A PAGE: its heading is among the first lines of a page
    (`_DIVISION_TOP`), and that page holds no other heading-like line. EVERY
    other heading-like line - a wrapped cross-reference ("... see" / "Part
    X"), a heading below the top of a page, a page with two of them, a
    contents entry - ENDS the division it is in: it is a break (name None),
    and what follows it sits in no division until the next start, so it stays
    a check. A missed heading can therefore never lend the division before it
    to the next one's requirements. A running header, and a heading repeated
    for the division it is already in (a "(continued)" title), are neither."""
    out: list[dict] = []
    pages = [_page_lines(text, lo, hi) for lo, hi in text.page_bounds.values()]
    running = subject_scope._running_lines([[text.lines[i] for i in p] for p in pages])
    for indices in pages:
        first = indices[0] if indices else 0
        heads: list[tuple[int, tuple[str, str], bool]] = []
        for index in indices:
            line = text.lines[index]
            match = _DIVISION.match(line)
            if match is None or re.sub(r"\d+", "#", line) in running:
                continue
            listed = bool(line[match.end("id") :].strip()) and bool(
                _CONTENTS_TAIL.search(line)
            )
            # the division's name: its structural word and id ("appendix 9")
            word = line[: match.start("id")].split()[-1].casefold()
            heads.append((index, (word, match.group("id").upper()), listed))
        if not heads:
            continue
        top, _name, listed = heads[0]
        starts = (
            len({name for _i, name, _l in heads}) == 1
            and not listed
            and top - first < _DIVISION_TOP
        )
        for index, name, _listed in heads:
            if out and out[-1]["name"] == name:
                continue
            out.append(
                {
                    "at": text.offsets[index],
                    "line": index,
                    "name": name if starts and index == top else None,
                    "heading": text.lines[index],
                }
            )
    return out


def division_of(
    requirement: dict, text: subject_scope.StandardText, divs: list[dict]
) -> dict | None:
    """The division a requirement sits in, or None when it sits before the
    first one, after a break, or cannot be placed: where its sentence sits in
    the text first, else its page (a division starts a page) - a page that
    holds a break is in none."""
    at = text.place(requirement)
    if at is None:
        bounds = text.page_bounds.get(subject_scope._page_of(requirement))
        if bounds is None or bounds[1] <= bounds[0]:
            return None
        if any(d["name"] is None and bounds[0] <= d["at"] < bounds[1] for d in divs):
            return None
        at = bounds[1] - 1
    inside = [d for d in divs if d["at"] <= at]
    return inside[-1] if inside and inside[-1]["name"] is not None else None


#: The heading and the lines right after it: always read.
_OPENING = 4


def scope_passage(text: subject_scope.StandardText, div: dict, end: int | None) -> str:
    """What the model reads of a division: its heading and the lines right
    after it, then its OWN scope clause - the first line naming "scope" in the
    division's first clause (before a second sub-clause heading) - up to the
    next sub-clause heading, at most `SCOPE_WORDS` words, never past the
    division's end (`end`: the next start or break). A scope line of a later
    sub-clause is never read as the division's: with none in the first
    clause, the first clause is read instead, to the same limits (a limit
    written under "General", or after a preamble, is still in front of the
    model; the word "scope" only picks where to start, it decides nothing)."""
    stop = len(text.lines) if end is None else end
    first = div["line"]
    opening = min(first + _OPENING, stop)
    scope_at = None
    subs = 0
    clause_end = min(first + _SCOPE_LOOK, stop)
    for i in range(first + 1, clause_end):
        # the heading first: a scope line of the SECOND sub-clause is not the
        # division's own
        if subject_scope._heading(text.lines[i]) is not None:
            subs += 1
            if subs > 1:
                clause_end = i
                break
        if _SCOPE_LINE.search(text.lines[i]):
            scope_at = i
            break
    words: list[str] = " ".join(text.lines[first:opening]).split()
    if scope_at is not None:
        for i in range(max(scope_at, opening), stop):
            if i > scope_at and subject_scope._heading(text.lines[i]) is not None:
                break
            if len(words) >= SCOPE_WORDS:
                break
            words.extend(text.lines[i].split())
    else:
        for line in text.lines[opening:clause_end]:
            if len(words) >= SCOPE_WORDS:
                break
            words.extend(line.split())
    return " ".join(words[:SCOPE_WORDS])


def _line_at(text: subject_scope.StandardText, at: int) -> int:
    """The index of the line that holds offset `at`."""
    return bisect.bisect_right(text.offsets, at) - 1


def _tops(text: subject_scope.StandardText, divs: list[dict]) -> list[dict]:
    """The starts that can open a part, in order: the named divisions, every
    break `divisions` makes, and the candidate starts `clause_scope` proposes
    (a shape, never a word list: a candidate only proposes, the model reads)."""
    from . import clause_scope

    tops = {
        d["line"]: {**d, "kind": "division" if d["name"] else "break"} for d in divs
    }
    for c in clause_scope.candidate_starts(text, divs):
        tops.setdefault(c["line"], {**c, "name": None, "kind": "candidate"})
    return [tops[line] for line in sorted(tops)]


def _requirement_at(requirement: dict, text, tops: list[dict]):
    """(offset, is it exact) of a requirement, or (None, False) when it cannot
    be placed: its sentence is not found and its page is unknown or holds a
    break (the page end is used only when no break could split the page)."""
    at = text.place(requirement)
    if at is not None:
        return at, True
    bounds = text.page_bounds.get(subject_scope._page_of(requirement))
    if bounds is None or bounds[1] <= bounds[0]:
        return None, False
    if any(t["kind"] == "break" and bounds[0] <= t["at"] < bounds[1] for t in tops):
        return None, False
    return bounds[1] - 1, False


def _page_at(text: subject_scope.StandardText, at: int) -> int | None:
    return next((p for p, (lo, hi) in text.page_bounds.items() if lo <= at < hi), None)


def _end_line(text: subject_scope.StandardText, end: int) -> int | None:
    """The line an extent that ends at offset `end` stops before (None: the
    text's end)."""
    line = bisect.bisect_left(text.offsets, end, hi=len(text.lines))
    return None if line >= len(text.lines) else line


def _new_unit(sid, text, tops: list[dict], k: int, prev: dict | None) -> dict:
    """The unit that starts at `tops[k]`: a division, or a candidate start
    (`prev`: the named division before it, whose verdict it may inherit)."""
    top = tops[k]
    return {
        "key": (sid, top["line"]),
        "text": text,
        "div": top,
        "end": tops[k + 1]["line"] if k + 1 < len(tops) else None,
        "page": _page_at(text, top["at"]),
        "count": 0,
        "weight": 0,
        "prev": prev,
        "kind": "division" if top["kind"] == "division" else "candidate",
    }


def place(requirements: list[dict], pages_of) -> tuple[dict, dict, set]:
    """Where each requirement sits: ({key: unit} - one per division and per
    candidate start -, {id(requirement): (unit key, line or None)}, {ids of the
    requirements that cannot be placed}). A requirement before the first start
    sits in no part."""
    units: dict[tuple, dict] = {}
    where: dict[int, tuple] = {}
    unplaced: set[int] = set()
    for sid in dict.fromkeys(r.get("standard_document_id") for r in requirements):
        mine = [r for r in requirements if r.get("standard_document_id") == sid]
        text = subject_scope.StandardText(pages_of(sid)) if sid else None
        if text is None:
            unplaced.update(id(r) for r in mine)
            continue
        tops = _tops(text, divisions(text))
        mine_units: list[dict] = []
        for k in range(len(tops)):
            named = [u for u in mine_units if u["kind"] == "division"]
            prev = named[-1] if named else None
            mine_units.append(_new_unit(sid, text, tops, k, prev))
        starts = [t["at"] for t in tops]
        for r in mine:
            at, exact = _requirement_at(r, text, tops)
            if at is None:
                unplaced.add(id(r))
                continue
            k = bisect.bisect_right(starts, at) - 1
            if k >= 0:
                mine_units[k]["count"] += 1
                line = _line_at(text, at) if exact else None
                where[id(r)] = (mine_units[k]["key"], line)
        for unit in mine_units:
            unit["weight"] += unit["count"]
            if unit["kind"] == "candidate" and unit["count"] and unit["prev"]:
                unit["prev"]["weight"] += unit["count"]
        units.update({u["key"]: u for u in mine_units})
    return units, where, unplaced


def sub_units(unit: dict, flagged: list[dict]) -> list[dict]:
    """The units for the flagged sub-headings of a division (`flagged`: the
    units `clause_scope.screen_titles` verified; "end" is an offset)."""
    text = unit["text"]
    return [
        {
            "key": (*unit["key"], f["line"]),
            "text": text,
            "div": {"line": f["line"], "heading": f["title"], "at": f["at"]},
            "end": _end_line(text, f["end"]),
            "page": _page_at(text, f["at"]),
            "count": 0,
            "kind": "subpart",
            "parent": unit,
        }
        for f in flagged
    ]


def sub_of(subs: list[dict], where: dict) -> dict[int, list[tuple]]:
    """Every flagged sub-part each requirement sits in (by its line), the
    outermost first; sets the requirement count of each sub-part, which counts
    a requirement of an inner sub-part for the outer ones too."""
    out: dict[int, list[tuple]] = {}
    for rid, (key, line) in where.items():
        inside = [
            s
            for s in subs
            if line is not None
            and s["parent"]["key"] == key
            and s["div"]["line"] <= line
            and (s["end"] is None or line < s["end"])
        ]
        if inside:
            by_line = sorted(inside, key=lambda s: s["div"]["line"])
            out[rid] = [s["key"] for s in by_line]
    for sub in subs:
        sub["count"] = sum(1 for keys in out.values() if sub["key"] in keys)
    return out


def unscreened(
    unit: dict, where: dict, skipped: list | None, *, screened: bool = True
) -> tuple[set[int], set[int]]:
    """(failed, by_page): the requirements of `unit` whose sub-headings were not
    screened. `failed` - HELD, the screen did not carry them: `skipped` is the
    sub-headings left out of the screen (None: all of the unit's, as when no
    screen ran or it failed). `by_page` - kept but counted, a requirement that
    is not a failed read: placed only by its page (no line, so never screened
    by heading) while the screen ran, or in a part whose sub-headings are never
    screened (`screened=False`: a candidate start)."""
    text = unit["text"]
    mine = {rid: ln for rid, (key, ln) in where.items() if key == unit["key"]}
    if not screened:
        return set(), set(mine)
    failed = {
        rid
        for rid, ln in mine.items()
        if skipped is None
        or (
            ln is not None
            and any(s["line"] <= ln and text.offsets[ln] < s["end"] for s in skipped)
        )
    }
    return failed, {rid for rid, ln in mine.items() if ln is None} - failed


#: What a part or sub-part that was NOT READ is held for, and the summary count
#: of the requirements held for it.
_NOT_READ = {
    "scope": "the model did not read this part's scope sentence (unavailable, "
    "timed out, or an invalid reply)",
    "beyond": "this part's scope sentence was not read: the run's limit on parts "
    "read was reached",
    "screen": "the model did not screen the sub-headings of this part for a limit "
    "of their own (unavailable, timed out, an invalid reply, or the run's limit "
    "was reached)",
}
NOT_READ_COUNTS = {
    "scope": "requirements_held_scope_not_read",
    "construction": "requirements_held_construction_not_read",
    "beyond": "requirements_beyond_limit",
    "screen": "requirements_subparts_not_screened",
}


def not_read_rec(unit: dict, why: str, scope: dict | None = None) -> dict:
    """The decision for a unit nothing was read for (`why`: a key of
    `NOT_READ_COUNTS`): HELD for the engineer, never compared and never a pass.
    `scope` is the scope reading when only the construction step failed."""
    status = "beyond" if why == "beyond" else "unread" if why != "screen" else "read"
    return {
        "status": status,
        "verdict": "held",
        "not_read": why,
        "scope": scope,
        "unit": unit,
    }


def _not_read_item(requirement: dict, rec: dict, standard_labels: dict) -> dict:
    """The ledger item for a requirement of a part that was not read. The
    detail names the part's heading and the standard, and quotes the standard's
    scope sentence only where it was read (as every other hold does)."""
    sid = requirement.get("standard_document_id")
    unit, why = rec["unit"], rec["not_read"]
    head = f"{unit['div']['heading']} of {standard_labels.get(sid) or sid}"
    page = f" (page {unit['page']})" if unit["page"] is not None else ""
    if why == "construction":
        scope = rec["scope"]
        reason = (
            f"applies only to {scope['construction'].strip()}: "
            f'"{scope["quote"].strip()}"; the model did not read whether this '
            "equipment is of that construction (unavailable, timed out, or an "
            "invalid reply)"
        )
        detail = f"{head}{page} {reason}"
    else:
        detail = f"{head}{page}: {_NOT_READ[why]}"
    return {
        "requirement": requirement,
        "code": "applicability_unsure",
        "detail": f"{detail}; an engineer decides",
        "decided_by": "code:scope-not-read",
    }


def crashed_item(requirement: dict, error_type: str) -> dict:
    """The ledger item for a requirement when the whole part-scope step stopped
    on an unexpected error: HELD like any part that was not read. The detail
    carries the error's TYPE only, never its message or any document text."""
    return {
        "requirement": requirement,
        "code": "applicability_unsure",
        "detail": f"the part-scope step stopped on an unexpected error ({error_type}); "
        "an engineer decides",
        "decided_by": "code:scope-not-read",
    }


def ledger_item(
    requirement: dict, rec: dict, standard_labels: dict, model: str
) -> dict:
    """The ledger item for a requirement of a decided part. The detail quotes
    only the standard's own sentence and the datasheet's stated line."""
    if rec.get("not_read"):
        return _not_read_item(requirement, rec, standard_labels)
    sid = requirement.get("standard_document_id")
    scope, unit = rec["scope"], rec["unit"]
    head = f"{unit['div']['heading']} of {standard_labels.get(sid) or sid}"
    page = f" (page {unit['page']})" if unit["page"] is not None else ""
    if scope.get("limited") == "yes":
        construction, quote = scope["construction"].strip(), scope["quote"].strip()
        said = f'{head} applies only to {construction}: "{quote}"{page}'
        tail = (
            "; the datasheet does not settle whether this equipment is of that "
            "construction - an engineer decides"
        )
    else:
        said = (
            f"{head}{page}: the model could not tell whether this part is "
            "limited by its own scope to one construction"
        )
        tail = "; an engineer decides"
    code = "applicability_unsure"
    if rec["verdict"] == "does_not_apply":
        code = "outside_division_scope"
        tail = (
            f'; the datasheet states "{rec["line"]}, another material of that '
            "family (the model read the scope sentence and the stated line; code decided)"
        )
    elif rec.get("via"):
        tail = (
            f'; this clause follows the heading "{rec["via"]}", which could not be '
            "confirmed as the start of a new part - an engineer decides"
        )
    elif rec.get("line"):  # a start found by shape: held, never excluded
        tail = (
            f'; the datasheet states "{rec["line"]}, but this heading was found by '
            "its shape and is not confirmed as the start of a part - "
            "an engineer decides"
        )
    return {
        "requirement": requirement,
        "code": code,
        "detail": said + tail,
        "decided_by": f"ai:{model}+code",
    }
