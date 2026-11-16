"""CONTRACT CHECKS CT-01 to CT-03 (order 14 lane E, 16 Nov 2026): what code can decide on a contract's own text.

The checklist is `reference/contract_checks.json` (CT-01 to CT-08, AI DRAFT, ENGINEER TO CONFIRM). Code decides three items:
  CT-01 payment or progress stages add up to 100% and match the number of stages the contract states;
  CT-02 every labelled schedule, appendix, annex, exhibit or attachment the contract refers to is present (in the contract or in a
        held document of its package);
  CT-03 one named party gives each guarantee, warranty or bond.
`run_all(pages, package)` takes stored page texts ([(page number, text)], and {document id: pages} for the package) and returns
`Result`s. Every result carries the page and the paper's own line as its quote, verified on its page by the app's one quote check
(`compiled_rule_proof.quote_verified`); a result whose quote does not verify is never a finding, it goes to the engineer. The
checklist is a draft, so every result is INTERNAL ONLY: never a firm Pass or Fail on the contractor copy.

General rules only (CLAUDE.md rule 13): label words, percentage words and guarantee words are plain English vocabulary; nothing names
one paper's layout, field or spelling. Pure: no database, no model, no network, no write. The command and the gate rows are
`scripts/contract_checks.py`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CHECKLIST = Path(__file__).parent / "reference" / "contract_checks.json"
CONSISTENT, INCONSISTENT, ENGINEER = "consistent", "inconsistent", "engineer to check"
RULE_STATE = "AI draft, engineer to confirm"
CODES = ("CT-01", "CT-02", "CT-03")

Pages = list[tuple[int, str]]


@dataclass
class Quote:
    page: int
    text: str
    verified: bool = False


@dataclass
class Result:
    ct: str
    topic: str
    outcome: str
    value: str
    message: str
    quotes: list[Quote] = field(default_factory=list)
    absence_proven: bool = False  # every page was read and the thing is on none of them

    @property
    def is_row(self) -> bool:
        """A CRS candidate: a finding or a question. A consistent result is coverage, not a comment."""
        return self.outcome != CONSISTENT

    def to_json(self, show_text: bool = False) -> dict:
        return {
            "ct": self.ct,
            "topic": self.topic,
            "outcome": self.outcome,
            "value": self.value,
            "message": self.message,
            "pages": sorted({q.page for q in self.quotes}),
            "quotes_verified": all(q.verified for q in self.quotes),
            "quotes": [
                {
                    "page": q.page,
                    "verified": q.verified,
                    **({"text": q.text} if show_text else {}),
                }
                for q in self.quotes
            ],
            "absence_proven": self.absence_proven,
            "rule": RULE_STATE,
            "internal_only": True,
        }


# ------------------------------------------------------------------------------------------------ shared


def checklist() -> dict:
    return json.loads(CHECKLIST.read_text(encoding="utf-8"))


def verified(quote: str, page_text: str) -> bool:
    """THE quote check of the app: the words stand on the cited page's stored text."""
    from .compiled_rule_proof import quote_verified

    return quote_verified(quote, page_text)


def quote(pages: Pages, page: int, text: str) -> Quote:
    on = dict(pages).get(page, "")
    return Quote(page, " ".join(text.split()), verified(text, on))


def lines_of(pages: Pages) -> list[tuple[int, str]]:
    """(page, line) for every non-empty line, in reading order."""
    return [(p, ln.strip()) for p, t in pages for ln in t.splitlines() if ln.strip()]


def whole(pages: Pages) -> bool:
    """Every page from 1 to the last has stored text: an absence on all of them is shown."""
    nos = [p for p, _t in pages]
    return (
        bool(nos)
        and nos == list(range(1, len(nos) + 1))
        and all(t.strip() for _p, t in pages)
    )


def _finish(r: Result) -> Result:
    """A result whose quote does not stand on its page decides nothing, either way: it goes to the engineer."""
    if r.outcome in (INCONSISTENT, CONSISTENT) and not all(
        q.verified for q in r.quotes
    ):
        r.outcome = ENGINEER
        r.message += " A quote did not verify on its page, so code does not decide."
    return r


# ------------------------------------------------------------------------------------------------ CT-01 stages add to 100%

_PERCENT_AFTER = re.compile(r"\s*(?:%|per\s*cent\b|percent\b)", re.I)
_STAGE_WORDS = re.compile(
    r"\b(?:milestones?|stages?|instal+ments?|advance|down\s*payment|retention|progress|payments?|payable|paid|invoic\w*)\b",
    re.I,
)
_RATE_WORDS = re.compile(  # a percentage that is a rate, a cap or a charge is not a payment stage
    r"\b(?:interest|liquidated|damages|penalt\w*|liabilit\w*|caps?|limited|exceed\w*|per\s+(?:week|day|month|annum|year)"
    r"|each\s+(?:week|day|month)|tax\w*|vat|insurance|discount\w*|escalation)\b",
    re.I,
)
_COUNT_CLAIM = re.compile(
    r"\b(?:in|by|through)\s+(?P<n>\w+)\s+(?:\(\s*\d+\s*\)\s+)?(?:equal\s+)?(?P<what>instal+ments?|stages?|milestones?|payments)\b",
    re.I,
)
_COUNT_WORDS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        ]
    )
}
MAX_GAP = 2  # non-stage lines allowed inside one schedule (a heading or a wrapped line)


def percents(line: str) -> list[float]:
    """The values in `line` printed as percentages (`numparse` reads every number; code adds only those followed by % or percent)."""
    from . import numparse

    return [
        n.value
        for n in numparse.find_numbers(line)
        if n.value is not None and _PERCENT_AFTER.match(line, n.end)
    ]


def is_stage_line(line: str) -> bool:
    return (
        bool(percents(line))
        and bool(_STAGE_WORDS.search(line))
        and not _RATE_WORDS.search(line)
    )


_CLAUSE_NUMBER = re.compile(r"^\s*(?P<num>\d+(?:\.\d+)+)\.?\s")


def numbered_schedules(pages: Pages) -> list[list[tuple[int, str]]]:
    """Sibling numbered clauses that each state ONE percentage ("7.2.1.1 Twenty percent (20%) of ...", 7.2.1.2, ...): one
    schedule per parent number. Kept only when every sibling under that parent states one percentage and the siblings are
    numbered 1 to n without a gap (a parent that also holds clauses of another kind is not a schedule)."""
    by_parent: dict[str, list[tuple[int, int, str, int]]] = {}
    for page, line in lines_of(pages):
        m = _CLAUSE_NUMBER.match(line)
        if not m:
            continue
        parent, _dot, last = m.group("num").rpartition(".")
        members = by_parent.setdefault(parent, [])
        if any(n == int(last) for n, _p, _l, _k in members):
            continue  # the number again: a wrapped cross-reference ("... Sub-Article / 7.2.2.2 and upon ..."), not a clause
        members.append((int(last), page, line, len(percents(line))))
    out = []
    for members in by_parent.values():
        numbers = [n for n, _p, _l, _k in members]
        if (
            len(members) >= 2
            and numbers == list(range(1, len(members) + 1))
            and all(k == 1 for _n, _p, _l, k in members)
        ):
            out.append([(p, ln) for _n, p, ln, _k in members])
    return out


def schedules(pages: Pages) -> list[list[tuple[int, str]]]:
    """Payment schedules: sibling numbered clauses of one percentage each (`numbered_schedules`), then runs of stage lines in
    reading order, at most MAX_GAP other lines apart, outside those clauses; a run of two or more is one payment schedule."""
    numbered = numbered_schedules(pages)
    taken = {(p, ln) for run in numbered for p, ln in run}
    runs, current, gap = [], [], 0
    for page, line in lines_of(pages):
        if (page, line) in taken:
            continue
        if is_stage_line(line):
            current.append((page, line))
            gap = 0
        elif current:
            gap += 1
            if gap > MAX_GAP:
                runs.append(current)
                current, gap = [], 0
    if current:
        runs.append(current)
    return numbered + [r for r in runs if len(r) >= 2]


def count_claims(pages: Pages) -> list[tuple[int, int, str]]:
    """(stated number, page, line) for each sentence that says the price is paid in N instalments, stages or milestones."""
    from . import numparse

    out = []
    for page, line in lines_of(pages):
        for m in _COUNT_CLAIM.finditer(line):
            word = m.group("n").lower()
            n = _COUNT_WORDS.get(word)
            if n is None:
                v = numparse.as_number(word)
                n = int(v) if v is not None and float(v).is_integer() else None
            if n:
                out.append((n, page, line))
    return out


def _schedule_result(pages: Pages, run: list[tuple[int, str]]) -> Result:
    values = [percents(line) for _p, line in run]
    quotes = [quote(pages, p, line) for p, line in run]
    where = sorted({p for p, _l in run})
    if any(len(v) != 1 for v in values):
        return Result(
            "CT-01",
            f"payment schedule p{where[0]}",
            ENGINEER,
            f"{len(run)} stage lines",
            "A stage line states more than one percentage; code does not choose which is the stage's share.",
            quotes,
        )
    total = sum(v[0] for v in values)
    shown = " + ".join(f"{v[0]:g}" for v in values) + f" = {total:g}%"
    pages_word = ", ".join(str(p) for p in where)
    if abs(total - 100.0) < 1e-9:
        return _finish(
            Result(
                "CT-01",
                f"payment schedule p{where[0]}",
                CONSISTENT,
                shown,
                f"The {len(run)} payment stages on page {pages_word} add up to 100%.",
                quotes,
            )
        )
    return _finish(
        Result(
            "CT-01",
            f"payment schedule p{where[0]}",
            INCONSISTENT,
            shown,
            f"The {len(run)} payment stages on page {pages_word} add up to {total:g}%, not 100%.",
            quotes,
        )
    )


def check_stages(pages: Pages) -> list[Result]:
    found = schedules(pages)
    out = [_schedule_result(pages, run) for run in found]
    stages = sum(len(r) for r in found)
    for n, page, line in count_claims(pages):
        q = [quote(pages, page, line)]
        topic = f"number of stages p{page}"
        if not found:
            absent = whole(pages)
            out.append(
                _finish(
                    Result(
                        "CT-01",
                        topic,
                        ENGINEER,
                        f"{n} stated, 0 found",
                        f"Page {page} says the price is paid in {n} parts; no stage with a percentage is on any of the "
                        f"{len(pages)} pages read{'' if absent else ' (not every page has text)'}. The stages may be in a part not held.",
                        q,
                        absent,
                    )
                )
            )
        elif len(found) > 1:
            out.append(
                Result(
                    "CT-01",
                    topic,
                    ENGINEER,
                    f"{n} stated, {len(found)} schedules found",
                    f"Page {page} states {n} parts and the contract holds {len(found)} payment schedules; "
                    "code does not choose which one is meant.",
                    q,
                )
            )
        elif stages != n:
            out.append(
                _finish(
                    Result(
                        "CT-01",
                        topic,
                        INCONSISTENT,
                        f"{n} stated, {stages} found",
                        f"Page {page} states {n} parts; the payment schedule lists {stages} stages.",
                        q + [quote(pages, p, ln) for p, ln in found[0]],
                    )
                )
            )
        else:
            out.append(
                Result(
                    "CT-01",
                    topic,
                    CONSISTENT,
                    f"{n} stated, {stages} found",
                    f"Page {page} states {n} parts and the payment schedule lists {stages}.",
                    q,
                )
            )
    return out


# ------------------------------------------------------------------------------------------------ CT-02 every attachment present

LABEL_WORDS = ("schedule", "appendix", "annex", "exhibit", "attachment", "enclosure")
DEPTH = {
    "schedule": 0,
    "appendix": 1,
    "annex": 1,
    "attachment": 1,
    "exhibit": 2,
    "enclosure": 2,
}
_LABEL = re.compile(
    r"(?i:\b(?P<word>"
    + "|".join(LABEL_WORDS)
    + r")\b)\s*[\"'\u201c\u201d\u2018\u2019]?\s*"
    r"(?P<label>[IVXL]{1,6}|[A-Z]|\d{1,3})(?![A-Za-z0-9])"
)
#: the words between a part and the higher part it belongs to: "Attachment III, to Schedule W", "Exhibit I of this Annex 2"
_BELONGS = re.compile(
    r"[\"'\u201c\u201d\u2018\u2019]?[\s,]*(?:(?:of|to|in|under)\s+(?:this\s+|the\s+)?)?$",
    re.I,
)
LIST_SPAN = 4  # the opening lines read for a list of parts: HEADING_LINES times this
LIST_OTHERS = 2  # other labels of the same kind that make the opening a list (one alone is a wrapped reference)
HEADING_LINES = (
    3  # the first non-empty lines of a package document that name what it is
)

Key = tuple[str, str]  # (label word, label): ("appendix", "F")
Part = tuple[
    Key, "Key | None"
]  # a part and the higher part it belongs to, when the text says


def labels(line: str) -> list[tuple[str, str, int]]:
    """(word, label, position) of every labelled reference in the line: 'Appendix F', 'SCHEDULE "K"', 'Attachment VII'."""
    return [
        (m.group("word").lower(), m.group("label"), m.start())
        for m in _LABEL.finditer(line)
    ]


def parts(line: str) -> list[tuple[Part, int]]:
    """Every labelled part of the line with the higher part it belongs to, when the next label is a higher one joined by
    'of', 'to', 'in', 'under' or a comma ('Attachment III, to SCHEDULE W' is Attachment III of Schedule W)."""
    found = list(_LABEL.finditer(line))
    out = []
    for i, m in enumerate(found):
        key = (m.group("word").lower(), m.group("label"))
        parent = None
        if i + 1 < len(found):
            nxt = found[i + 1]
            up = (nxt.group("word").lower(), nxt.group("label"))
            if DEPTH[up[0]] < DEPTH[key[0]] and _BELONGS.fullmatch(
                line[m.end() : nxt.start()]
            ):
                parent = up
        out.append(((key, parent), m.start()))
    return out


def _heading_part(line: str) -> Part | None:
    """The part a line starts with, when the line starts with one."""
    found = parts(line)
    if found and not line[: found[0][1]].strip(" \t\"'\u201c\u201d\u2018\u2019"):
        return found[0][0]
    return None


BODY_LOOKAHEAD, BODY_WORDS = (
    6,
    6,
)  # a part's heading is followed, before the next labelled line, by a sentence of its own


def _has_body(lines: list[tuple[int, str]], starts: list, i: int) -> bool:
    """The heading at line i is followed by body text: a line of BODY_WORDS or more words before the next line that starts with
    a label. A list of schedules (labels with their titles on the next line, or a numbered order of precedence) has none."""
    for j in range(i + 1, min(len(lines), i + 1 + BODY_LOOKAHEAD)):
        if starts[j]:
            return False
        if len(re.findall(r"[^\W\d_]+", lines[j][1])) >= BODY_WORDS:
            return True
    return False


def headings(pages: Pages) -> dict[Part, int]:
    """Parts present in the paper: a line that starts with a label AND is followed by body text of its own (`_has_body`). A
    line of a list of parts (two label lines in a row on one page, or labels with only their titles between them) refers to
    the parts; it does not hold them."""
    lines = lines_of(pages)
    starts = [_heading_part(ln) for _p, ln in lines]
    out: dict[Part, int] = {}
    for i, (page, _ln) in enumerate(lines):
        here = starts[i]
        if not here:
            continue
        near = [
            starts[j]
            for j in (i - 1, i + 1)
            if 0 <= j < len(starts) and starts[j] and lines[j][0] == page
        ]
        if any(n[0][0] == here[0][0] and n[0] != here[0] for n in near):
            continue  # a line of a list
        if not _has_body(lines, starts, i):
            continue  # a title in a list, not a part
        out.setdefault(here, page)
    return out


def package_part(pages: Pages) -> list[Part]:
    """What a held package document is: the deepest labels on its first heading lines, each with the next higher label there as
    the part it belongs to ('SCHEDULE K' then 'ATTACHMENT I' is Attachment I of Schedule K; 'EXHIBIT I, ATTACHMENT III, SCHEDULE K'
    is Exhibit I of Attachment III)."""
    page_one = [ln for p, ln in lines_of(pages) if p == (pages[0][0] if pages else 1)]
    first = page_one[:HEADING_LINES]
    found = [
        (w, lab) for ln in first if _heading_part(ln) for w, lab, _i in labels(ln)
    ]  # heading lines only, not a mention
    if not found:
        return []
    opening = [_heading_part(ln) for ln in page_one[: HEADING_LINES * LIST_SPAN]]
    for w, lab in found:
        others = {h[0][1] for h in opening if h and h[0][0] == w and h[0][1] != lab}
        if len(others) >= LIST_OTHERS:
            return []  # the paper opens with a list of parts of one kind: it names them, it is none of them
    deepest = max(DEPTH[w] for w, _l in found)
    higher = [k for k in found if DEPTH[k[0]] < deepest]
    parent = max(higher, key=lambda k: DEPTH[k[0]]) if higher else None
    return list(dict.fromkeys((k, parent) for k in found if DEPTH[k[0]] == deepest))


def _name(part: Part) -> str:
    (w, lab), parent = part
    return f"{w.capitalize()} {lab}" + (
        f" of {parent[0].capitalize()} {parent[1]}" if parent else ""
    )


AMBIGUOUS = "held under several higher parts"
UNNAMED = "higher part not named"


def _present_for(
    ref: Part, present: dict[Part, str], own: Part | None = None
) -> str | None:
    """Where the referred part is present, or AMBIGUOUS, or None. A reference that names its higher part matches only a
    present part of that higher part (or one whose higher part is not stated). A reference that names none, in a paper that
    is one part of the contract, matches only the paper's own sub-part or a sibling under the paper's own higher part (in
    Schedule K, "Attachment II" is Schedule K's, never another schedule's). In a paper that is no part (the agreement), the
    one held part with that label; with that label held under several higher parts code does not choose: AMBIGUOUS."""
    key, parent = ref
    found = [(p, where) for (k, p), where in present.items() if k == key]
    if parent is not None:
        return next((w for p, w in found if p is None or p == parent), None)
    if own is not None:
        family = {x for x in (own[0], own[1]) if x is not None}
        return next((w for p, w in found if p in family), None)
    if not found:
        return None
    if DEPTH[key[0]] > 0:
        return UNNAMED  # a sub-part with no higher part, in a paper that is no part: whose it is is not said
    return found[0][1] if len({p for p, _w in found}) == 1 else AMBIGUOUS


def _inside(ref: Part, own: Part | None) -> bool:
    """A reference to this paper's own contents: the paper is a whole contract (no part label), or the reference names this
    paper's part as its higher part. A sibling or higher part (another Schedule referred to from Schedule K) is outside: a
    package of parts does not have to hold it. A sub-part whose higher part the text does not name ("Thereof, Appendix C",
    "listed in Attachment I") may belong to any part of the contract, so code does not call it missing from THIS paper:
    the engineer reads it."""
    if own is None:
        return True
    _key, parent = ref
    return parent == own[0]


def check_attachments(
    pages: Pages, package: dict[str, Pages] | None = None, complete: bool = False
) -> list[Result]:
    """CT-02. Evidence that a part is present: a held package document whose first heading lines name it, or the paper's
    own first heading lines. A heading INSIDE the paper counts only when the caller says the papers are the whole contract
    (`complete`): in a real contract a list of schedules, an order of precedence or a reference at the start of a line looks
    like a heading. A missing part is a firm finding only with `complete`; otherwise the contract's parts may be files not
    given here: "not in the papers given", and the engineer checks the whole contract. Code never calls a part missing from
    a contract it has not seen whole."""
    present = {k: f"page {p}" for k, p in headings(pages).items()} if complete else {}
    own = package_part(pages)
    own = (
        own[0] if own else None
    )  # the part this paper is ('Schedule K'); None for a whole contract
    for k in package_part(pages):
        present.setdefault(k, "this paper")
    for doc, doc_pages in (package or {}).items():
        for k in package_part(doc_pages):
            present.setdefault(k, f"held document {doc}")
    refs: dict[Part, list[tuple[int, str]]] = {}
    lines = lines_of(pages)
    for n, (page, line) in enumerate(lines):
        head = _heading_part(line)
        # the higher part may stand on the next line ("listed in Attachment I of" / "Schedule W."): read the two lines
        # together, keep the references that start on this line
        following = (
            lines[n + 1][1] if n + 1 < len(lines) and lines[n + 1][0] == page else ""
        )
        for part, at in parts(f"{line} {following}" if following else line):
            if at >= len(line):
                continue
            if head == part and present.get(head) == f"page {page}":
                continue  # the heading itself is not a reference
            refs.setdefault(part, []).append((page, line))
    out: list[Result] = []
    by_part: dict[Part, Result] = {}
    scope = f"the {len(pages)} pages of this paper" + (
        f" and {len(package)} held package documents" if package else ""
    )
    for part, where in sorted(refs.items(), key=lambda kv: _name(kv[0])):
        first_per_page = list({p: (p, ln) for p, ln in reversed(where)}.values())[::-1]
        quotes = [quote(pages, p, ln) for p, ln in sorted(first_per_page)]
        on = ", ".join(str(p) for p in sorted({p for p, _l in where}))
        at = _present_for(part, present, own)
        if at in (AMBIGUOUS, UNNAMED):
            out.append(
                Result(
                    "CT-02",
                    _name(part),
                    ENGINEER,
                    at,
                    f"{_name(part)} is referred to on page {on} without its higher part, and held documents carry that "
                    "label under a higher part: the engineer checks which one is meant.",
                    quotes,
                )
            )
        elif at:
            out.append(
                Result(
                    "CT-02",
                    _name(part),
                    CONSISTENT,
                    f"present ({at})",
                    f"{_name(part)} is referred to on page {on} and is present ({at}).",
                    quotes,
                )
            )
        elif not _inside(part, own):
            out.append(
                Result(
                    "CT-02",
                    _name(part),
                    ENGINEER,
                    "not held",
                    f"{_name(part)} is referred to on page {on}. It is a part of the contract outside "
                    f"{_name(own)} (or its higher part is not named), and it is not in {scope}: the engineer checks it "
                    "in the whole contract.",
                    quotes,
                )
            )
        elif not complete:
            out.append(
                Result(
                    "CT-02",
                    _name(part),
                    ENGINEER,
                    "not in the papers given",
                    f"{_name(part)} is referred to on page {on}; it is not in {scope}. These may not be the whole "
                    "contract: the engineer checks it in the whole contract.",
                    quotes,
                    whole(pages),
                )
            )
        else:
            out.append(
                _finish(
                    Result(
                        "CT-02",
                        _name(part),
                        INCONSISTENT,
                        "not present",
                        f"{_name(part)} is referred to on page {on}; it is not in {scope}.",
                        quotes,
                        whole(pages),
                    )
                )
            )
        by_part[part] = out[-1]
    return _fold_into_parent(by_part, out)


def _fold_into_parent(by_part: dict[Part, Result], out: list[Result]) -> list[Result]:
    """One comment per missing part (G4): a missing sub-part whose higher part is itself missing with the same outcome is said
    inside the higher part's comment ('Schedule W is not held; Attachment III of it is referred to on page 2'), with its quotes."""
    keep = []
    for r in out:
        part = next(p for p, x in by_part.items() if x is r)
        (_key, parent) = part
        up = next(
            (x for (k, _pp), x in by_part.items() if parent and k == parent), None
        )
        if (
            up is not None
            and up is not r
            and r.outcome != CONSISTENT
            and up.outcome == r.outcome
        ):
            pages_of = ", ".join(str(q.page) for q in r.quotes)
            up.message += f" {_name(part)} is referred to on page {pages_of} too."
            up.value += f"; also {_name(part)}"
            up.quotes += [q for q in r.quotes if q not in up.quotes]
            continue
        keep.append(r)
    return keep


# ------------------------------------------------------------------------------------------------ CT-03 one name per guarantee

_PARTY = re.compile(  # 'Alpha Ltd (the "Owner")', 'Beta Co. (hereinafter called CONTRACTOR)': a role needs 'the', quotes or 'hereinafter'
    r"(?P<name>[A-Z][\w&'.,-]*(?:\s+(?:[A-Z][\w&'.,-]*|&|and|of))*?)\s*\(\s*(?P<intro>(?:hereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?)?"
    r"(?:the\s+)?)(?P<q>[\"“']?)(?P<role>[A-Z][A-Za-z]+)[\"”']?\s*\)"
)
_LEAD_WORDS = {"between", "and", "by", "the", "this", "with", "of"}
#: used only when the contract defines no party: plain words for a contract's parties
ROLE_WORDS = (
    "Contractor",
    "Supplier",
    "Vendor",
    "Seller",
    "Owner",
    "Company",
    "Purchaser",
    "Buyer",
    "Employer",
    "Client",
    "Guarantor",
    "Bank",
    "Subcontractor",
    "Manufacturer",
)
_GUARANTEE = re.compile(
    r"\b(?:(?P<q>(?:[a-z]+[\s-]+){0,2}?)(?P<noun>guarantees?|bonds?|security|securities)\b|(?P<warr>warrant(?:s|y|ies|ed)?)\b)",
    re.I,
)
_QUALIFIERS = {
    "performance",
    "bank",
    "advance",
    "payment",
    "parent",
    "company",
    "corporate",
    "retention",
    "bid",
    "tender",
    "warranty",
    "maintenance",
    "on-demand",
    "demand",
}
_SENTENCE_END = re.compile(r"(?<=[.;])\s+")
_CLAUSE_LINE = re.compile(
    r"\n(?=[ \t]*(?:\d+(?:\.\d+)+|[A-Z]\.\d+|\d+\.)\s)"
)  # a new line that starts a numbered clause


def sentences(text: str) -> list[str]:
    """The page's sentences: a numbered clause starts a new one (a heading line does not run into it), then '.' and ';' end one."""
    return [
        s
        for chunk in _CLAUSE_LINE.split(text)
        for s in _SENTENCE_END.split(" ".join(chunk.split()))
        if s
    ]


def parties(pages: Pages) -> dict[str, str]:
    """{alias: party} for each party the contract defines as 'Name (the Role)': the full name and the role both name the party.
    An abbreviation ('Material Take Off (MTO)') is not a party: the role needs 'the', quotes or 'hereinafter'."""
    out: dict[str, str] = {}
    for _p, text in pages:
        for m in _PARTY.finditer(" ".join(text.split())):
            if not (m.group("intro").strip() or m.group("q")):
                continue
            words = m.group("name").split()
            while words and words[0].lower().strip(",") in _LEAD_WORDS:
                words = words[1:]
            role = m.group("role")
            name = " ".join(words).strip(" ,")
            if not name or name == role or len(name) < 3:
                continue
            out.setdefault(role, role)
            out.setdefault(name, role)
    if not out:
        out = {w: w for w in ROLE_WORDS}
    return out


def _kind(m: re.Match) -> str:
    if m.group("warr"):
        return "warranty"
    noun = m.group("noun").lower()
    noun = {"guarantees": "guarantee", "bonds": "bond", "securities": "security"}.get(
        noun, noun
    )
    quals = [
        w for w in re.split(r"[\s-]+", (m.group("q") or "").lower()) if w in _QUALIFIERS
    ]
    if noun == "security" and not quals:
        return ""  # 'security' alone is not a guarantee word (site security, security of data)
    return " ".join([*quals, noun])


_CLAUSE_NO = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|\([a-z0-9]{1,3}\)|[a-z]\))\s*", re.I)
_GIVES = re.compile(
    r"\s+(?:shall|will|must|hereby|agrees\s+to|undertakes\s+to)?\s*(?:also\s+)?"
    r"(?:provides?|furnish(?:es)?|gives?|issues?|warrants?|guarantees?|submits?|delivers?|posts?|procures?|maintains?|extends?)\b",
    re.I,
)


GIVER_GAP = 5  # words between the giving verb and the guarantee word ("furnish a bank guarantee": 2)


def giver(sentence: str, start: int, names: dict[str, str]) -> str | None:
    """The party that gives the guarantee: the sentence's subject (after its clause number) followed by a giving verb, before the
    guarantee word ('The Supplier warrants ...', 'CONTRACTOR shall furnish a performance bond'). A party named anywhere else
    (the one it benefits, the one who obtains it from others) is not the giver: then None, and the engineer reads it. The
    verb must govern the guarantee word: at most GIVER_GAP words between them ('provide the installation ... to maintain
    the vendor's warranty' gives work, not the warranty)."""
    body = _CLAUSE_NO.sub("", sentence, count=1)
    body = re.sub(r"^the\s+", "", body, flags=re.I)
    at = start - (len(sentence) - len(body))  # the guarantee word's place in `body`
    for alias, party in sorted(names.items(), key=lambda kv: -len(kv[0])):
        for spelt in dict.fromkeys((alias, alias.upper())):
            verb = _GIVES.match(body, len(spelt)) if body.startswith(spelt) else None
            if not verb or verb.end() - len(verb.group(0).split()[-1]) > at:
                continue  # no giving verb, or it comes after the word
            if len(body[verb.end() : max(at, verb.end())].split()) <= GIVER_GAP:
                return party
    return None


def check_guarantees(pages: Pages) -> list[Result]:
    names = parties(pages)
    by_kind: dict[str, list[tuple[str | None, int, str]]] = {}
    for page, text in pages:
        for sentence in sentences(text):
            for m in _GUARANTEE.finditer(sentence):
                kind = _kind(m)
                if kind:
                    by_kind.setdefault(kind, []).append(
                        (giver(sentence, m.start(), names), page, sentence)
                    )
    out = []
    for kind, seen in sorted(by_kind.items()):
        givers = sorted({g for g, _p, _s in seen if g})
        named = [(g, p, s) for g, p, s in seen if g]
        if not givers:
            out.append(
                Result(
                    "CT-03",
                    kind,
                    ENGINEER,
                    "no party named",
                    f"The {kind} is mentioned on page {', '.join(str(p) for p in sorted({p for _g, p, _s in seen}))}; "
                    "no sentence names the party that gives it.",
                    [quote(pages, p, s) for _g, p, s in seen[:2]],
                )
            )
        elif len(givers) == 1:
            out.append(
                Result(
                    "CT-03",
                    kind,
                    CONSISTENT,
                    givers[0],
                    f"The {kind} is given by one party: {givers[0]}.",
                    [quote(pages, p, s) for _g, p, s in named[:1]],
                )
            )
        else:
            first = list({g: (g, p, s) for g, p, s in reversed(named)}.values())[::-1]
            out.append(
                _finish(
                    Result(
                        "CT-03",
                        kind,
                        INCONSISTENT,
                        " / ".join(givers),
                        f"The {kind} is given by {len(givers)} different parties: {', '.join(givers)}.",
                        [quote(pages, p, s) for _g, p, s in first],
                    )
                )
            )
    return out


# ------------------------------------------------------------------------------------------------ all checks


def run_all(
    pages: Pages, package: dict[str, Pages] | None = None, complete: bool = False
) -> list[Result]:
    """Every check code decides. `complete`: the caller knows `pages` and `package` are the WHOLE contract (only then is
    a part missing from them a firm finding, CT-02)."""
    return (
        check_stages(pages)
        + check_attachments(pages, package, complete)
        + check_guarantees(pages)
    )
