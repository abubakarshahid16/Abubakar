"""CONTRACT CODE CHECKS (order 14, builder C, 19 Nov 2026): what code alone proves on a contract's own words, and the fixed contract
checklist that every contract review judges in addition to the checklist written from the standards.

Code checks (each line carries the page and a quote that verifies on that page; `lines`):
  amount_words   an amount or a percentage written in words and in figures in ONE quote ("Ten (10)", "five percent (5%)",
                 "<currency name> <words> (<code> <figures>)"): the two numbers differ, or the currency named in words is not the
                 currency of the code in brackets -> "Not met, proven by code".
  dates          a start date and an end date in one quote (unambiguous forms only: 3 March 2027, March 3, 2027, 2027-03-03; 03/04
                 gives no verdict): the end is before the start, or the start plus the duration stated between them is not the end
                 -> "Not met, proven by code".
  splits         percentages split with "/" in one bracket ("(60% X / 40% Y)"): a sentence that says "equally" with unequal parts
                 -> "Not met, proven by code"; parts that do not add up to 100 -> a Question.
  percent_values two different percentages stated as the same kind of statement (a cap: "not exceed", "not more than"; or a rate:
                 "equal to", "equivalent to") on the same base ("of the <base>") under the same clause heading: the same subject
                 words -> "Not met, proven by code"; one subject inside the other -> a Question. A percentage over 100 of a price
                 or invoice -> a Question.
  delay_cap      a rate per day or week, a stated maximum number of days or weeks and a stated cap, all percentages of one base under
                 one heading: rate x periods is not the cap -> a Question (the paper may mean them apart).
  schedules      the order of precedence against the list of Schedules the contract names as its parts: a ranked Schedule not
                 listed, or a listed Schedule not ranked, or one ranked twice -> "Not met, proven by code" (both lists read whole);
                 the listed Schedules the package does not hold -> ONE Question.
  terms          a term the contract defines in quotes ("Work", "COMPANY") used with a different capitalisation that is still
                 capitalised ("Company") -> a Question (never a verdict: the meaning may be the same).
A value left to the vendor (blank, By Contractor, TBA, TBD, *) has no figure and is never compared. Nothing guesses the AI's meaning:
code parses the paper's own words. Pure: no model, no network, no write. Hooked at ONE place: `engine._judge` adds
`checklist_items` and `engine._after_judge` adds `lines` (after every AI step, so no AI step rewrites a code line).
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from .. import contract_checks as CC
from .fail_words import PROVEN_FAIL
from .steps import KNOWLEDGE
from .verify import quote_in

log = logging.getLogger(__name__)

KIND = "contract"
CHECKLIST = (
    Path(__file__).resolve().parent.parent / "reference" / "contract_checklist.json"
)
TOPIC = "contract checked by code"
SOURCE = KNOWLEDGE  # the paper against itself: no held standard is the rule
READ_FROM = "verified quotes"
MAX_QUOTE = 420

IDS = {
    "amount_words": "C1",
    "dates": "C2",
    "splits": "C3",
    "percent_values": "C4",
    "delay_cap": "C5",
    "schedules": "C6",
    "terms": "C7",
}


def is_contract(identity: dict | None) -> bool:
    return str((identity or {}).get("kind") or "").strip().lower() == KIND


# ------------------------------------------------------------------------------------------------ the fixed checklist


@lru_cache(maxsize=1)
def checklist() -> dict:
    return json.loads(CHECKLIST.read_text(encoding="utf-8"))


def checklist_items(identity: dict | None) -> list[dict]:
    """The fixed contract checklist as judge items (same fields as the always-on items), for a contract only; [] otherwise.
    Not from a held standard: the judge's word is an AI opinion or a Question, never Met or Not met."""
    if not is_contract(identity):
        return []
    out = []
    for it in checklist()["items"]:
        check = it["check"]
        if it.get("code_part"):
            check += f" Code already compares: {it['code_part'].split(' (`')[0]}; do not repeat that comparison."
        out.append(
            {
                "id": it["id"],
                "topic": it["topic"],
                "what_to_check": check,
                "book": "",
                "clause": "",
                "page": None,
                "rule_quote": "",
                "applies_when": "the paper is a contract",
                "paper_fields": [],
                "paper_pages": [],
                "kind": "consistency" if it["decided_by"] != "judge" else "presence",
                "source": KNOWLEDGE,
                "stands_in_for": "the fixed contract checklist",
                "always_on": True,
                "context": "",
                "carries": [],
                "named_books": [],
            }
        )
    return out


# ------------------------------------------------------------------------------------------------ shared

_SPACE = re.compile(r"\s+")


def flat(text: str) -> str:
    return _SPACE.sub(" ", str(text or "")).strip()


def _quote(flat_page: str, start: int, end: int) -> str:
    return flat_page[max(0, start) : end].strip(" ,;")


def _line(
    check: str,
    n: int,
    label: str,
    page: int,
    quote: str,
    comment: str,
    field: str,
    compare: dict | None = None,
    note: str = "",
) -> dict:
    return {
        "item_id": IDS[check],
        "finding_no": n,
        "label": label,
        "field": field,  # code's own short words: never cut
        "page": page,
        "quote": quote,
        "quote_unverified": "",
        "comment": comment,  # never cut (completeness rule 3): the whole sentence or nothing
        "standard": "",
        "clause": "",
        "source": SOURCE,
        "topic": TOPIC,
        "code": "; ".join(x for x in (f"contract code: {check}", note) if x),
        "numbers": None,
        "code_compare": compare,
        "deferred": False,
        "ask": "concern",
    }


def _firm(check, n, page, quote, sentence, field, paper_value, rule_value, why) -> dict:
    return _line(
        check,
        n,
        "Not met",
        page,
        quote,
        f"{PROVEN_FAIL}: {sentence}",
        field,
        {
            "read_from": READ_FROM,
            "result": "fail",
            "operator": "==",
            "paper_value": paper_value,
            "rule_value": rule_value,
            "why": why,
        },
    )


_WORD = re.compile(r"[A-Za-z]+")


def _question(
    check, n, page, quote, sentence, field, compare: dict | None = None
) -> dict:
    return _line(check, n, "Question", page, quote, sentence, field, compare)


# ------------------------------------------------------------------------------------------------ schedules


#: a line of this many words or more that ENDS a sentence ('.' or ':') between two Schedule lines is a body sentence: the list
#: ended. A long title that wraps (no full stop) does not end it (review B2).
LIST_BREAK_WORDS = 10


def _schedule_list(pages: dict[int, str]) -> list[tuple[str, int, str]]:
    """The Schedules the contract lists as its parts: (label, page, the line) of every line that STARTS with a Schedule label and is
    not an item of a numbered list (its line, or the line before it, is not a list number), in the longest run of three or more
    such lines with no body sentence (LIST_BREAK_WORDS words or more, ending with '.' or ':') between them. A layout reading:
    what it misses is never a proof (`check_schedules` asks, never says Not met)."""
    lines = CC.lines_of(sorted(pages.items()))
    runs, cur = [], []
    for i, (page, ln) in enumerate(lines):
        part = CC._heading_part(ln)
        if not part or part[0][0] != "schedule":
            if (
                cur
                and len(_WORD.findall(ln)) >= LIST_BREAK_WORDS
                and ln.rstrip().endswith((".", ":"))
            ):
                runs.append(cur)
                cur = []
            continue
        prev = lines[i - 1][1] if i else ""
        if re.fullmatch(r"\d{1,2}\.", prev.strip()) or re.match(r"^\d{1,2}\.\s", ln):
            continue  # an item of the order of precedence (a numbered list)
        cur.append((part[0][1], page, ln))
    if cur:
        runs.append(cur)
    best = max(runs, key=len) if runs else []
    return best if len(best) >= 3 else []


def _rank_line(pages: dict[int, str], page: int, label: str) -> str:
    for ln in pages.get(page, "").splitlines():
        found = CC.labels(ln)
        if found and found[0][0] == "schedule" and found[0][1] == label:
            return flat(ln)
    return ""


def check_schedules(pages: dict[int, str], held: set[str] | None = None) -> list[dict]:
    """The order of precedence against the list of Schedules, and the listed Schedules against the package; Schedules matched by
    their label (letter or number), never by title words. Every line is a QUESTION: the two lists are read by a layout rule, and
    an absence from a parsed list is not a comparison of two verified values (review B2: a wrapped title once cut the list).
    `held`: the labels of the Schedules the package holds and a recorded link ties to the paper; None = not known (no line)."""
    ranks = [
        (r, k, p)
        for r, k, p in CC.precedence_list(sorted(pages.items()))
        if k[0] == "schedule"
    ]
    listed = _schedule_list(pages)
    out = []
    if len(ranks) >= 3 and len(listed) >= 3:
        names = {lab for lab, _p, _l in listed}
        lo, hi = min(p for _l, p, _x in listed), max(p for _l, p, _x in listed)
        list_pages = f"{lo}" if lo == hi else f"{lo}-{hi}"
        ranked: dict[str, list[tuple[int, int]]] = {}
        for r, (_w, lab), p in ranks:
            ranked.setdefault(lab, []).append((r, p))
        for lab, places in ranked.items():
            q = _rank_line(pages, places[0][1], lab)
            if not q or not quote_in(q, pages[places[0][1]]):
                continue
            if lab not in names:
                out.append(
                    _question(
                        "schedules", len(out) + 1, places[0][1], q,
                        f"Schedule {lab} is ranked {places[0][0]} in the order of precedence (page {places[0][1]}), but it was "
                        f"not found in the list of Schedules on page {list_pages} ({', '.join(sorted(names))}); please confirm "
                        "it is a part of the contract and add it to the list, or remove it from the order.",
                        "order of precedence against the list of Schedules",
                    )
                )  # fmt: skip
            if len(places) > 1:
                out.append(
                    _question(
                        "schedules", len(out) + 1, places[0][1], q,
                        f"Schedule {lab} appears more than once in the order of precedence (ranks "
                        f"{', '.join(str(r) for r, _p in places)}); please confirm its one rank.",
                        "order of precedence",
                    )
                )  # fmt: skip
        for lab, page, ln in listed:
            q = flat(ln)
            if lab in ranked or not quote_in(q, pages[page]):
                continue
            out.append(
                _question(
                    "schedules", len(out) + 1, page, q,
                    f"Schedule {lab} is listed as a part of the contract (page {page}), but it was not found in the order of "
                    f"precedence (page {ranks[0][2]}); please confirm its rank.",
                    "list of Schedules against the order of precedence",
                )
            )  # fmt: skip
    if held is not None and listed:
        missing = [(lab, page, ln) for lab, page, ln in listed if lab not in held]
        if missing:
            lab, page, ln = missing[0]
            q = flat(ln)
            if quote_in(q, pages[page]):
                out.append(
                    _question(
                        "schedules", len(out) + 1, page, q,
                        f"Schedules {', '.join(m[0] for m in missing)} are named as parts of the contract but are not held in "
                        "this contract package, so they could not be checked; please provide them.",
                        "listed Schedules held in the package",
                    )
                )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ defined terms

_DEF = re.compile(
    r"(?:referred\s+to\s+(?:collectively\s+|individually\s+)?as\s+(?:the\s+)?|\(\s*(?:the\s+)?|\bor\s+)"
    r"[\"“](?P<term>[A-Z][A-Za-z\-]*(?:\s+[A-Z][A-Za-z\-]*){0,4})[\"”]"
)


def defined_terms(pages: dict[int, str]) -> dict[str, tuple[int, str]]:
    """{term as defined: (page, quote)} for every capitalised term the paper defines in quotes after 'referred to as' or an
    opening bracket ('(the "Work")', '"Work" or "WORK"')."""
    out: dict[str, tuple[int, str]] = {}
    for page in sorted(pages):
        fp = flat(pages[page])
        for m in _DEF.finditer(fp):
            term = m.group("term").strip()
            if len(term) < 3:
                continue
            out.setdefault(term, (page, _quote(fp, m.start(), m.end())))
    return out


def check_terms(pages: dict[int, str]) -> list[dict]:
    """ONE Question for the paper: each defined term written in another capitalised form, with its count; the quote and page are
    those of the first such use. Never a verdict (the meaning may be the same)."""
    terms = defined_terms(pages)
    forms: dict[str, set[str]] = {}
    for t in terms:
        forms.setdefault(t.casefold(), set()).add(t)
    found = []  # (page, at, used, flat page, allowed forms, count)
    for low, allowed in forms.items():
        rx = re.compile(
            r"(?<![A-Za-z])"
            + r"\s+".join(re.escape(w) for w in low.split())
            + r"(?![A-Za-z])",
            re.I,
        )
        odd: list[tuple[int, int, str, str]] = []
        for page in sorted(pages):
            fp = flat(pages[page])
            for m in rx.finditer(fp):
                used = " ".join(m.group(0).split())
                if used in allowed or not used[0].isupper() or used.islower():
                    continue
                if m.start() > 0 and fp[m.start() - 1] in '"\u201c':
                    continue  # a definition or a quoted mention
                odd.append((page, m.start(), used, fp))
        if odd:
            found.append((*odd[0], allowed, len(odd)))
    for page, at, used, fp, _allowed, _n in found:
        quote = _quote(fp, max(0, at - 40), at + len(used) + 30)
        quote = quote[quote.find(" ") + 1 :] if at >= 40 else quote
        if quote_in(quote, pages[page]):
            break
    else:
        return []
    said = "; ".join(
        f"{' / '.join(sorted(al))} written '{u}' {n} time(s) (first on page {p})"
        for p, _a, u, _f, al, n in found
    )
    return [
        _question(
            "terms", 1, page, quote,
            f"Defined terms are written in other forms: {said}; please use the defined form or confirm the same meaning.",
            "defined terms used in another form",
        )
    ]  # fmt: skip


# ------------------------------------------------------------------------------------------------ all


def lines(
    pages: dict[int, str], identity: dict | None, held: set[str] | None = None
) -> list[dict]:
    """Every code line of a contract, in check order; [] for any other kind. A check that fails on a paper adds no line and
    never stops the review."""
    if not is_contract(identity):
        return []
    from . import (
        contract_numbers as N,  # the number checks (their own module: size limit)
    )

    out: list[dict] = []
    for fn in (
        N.check_amount_words,
        N.check_dates,
        N.check_splits,
        N.check_percent_values,
        N.check_delay_cap,
        check_terms,
        lambda p: check_schedules(p, held),
    ):
        try:
            out += fn(pages)
        except Exception as exc:  # noqa: BLE001 - a parse fault of one check never stops the review: logged, no line
            log.info("contract code: a check failed (%s)", type(exc).__name__)
    return out


def held_labels(
    conn, paper_id: str, shown: frozenset[str] = frozenset()
) -> set[str] | None:
    """The labels of the Schedules the package holds and a recorded link ties to the paper (`references.held_schedules`)."""
    try:
        from .references import held_schedules

        linked, _other = held_schedules(conn, paper_id, shown)
        return {lab for (w, lab) in linked if w == "schedule"}
    except Exception as exc:  # noqa: BLE001 - not known: no package line (logged)
        log.info("contract code: held Schedules not read (%s)", type(exc).__name__)
        return None


def add_lines(conn, state, paper, allowed_books=frozenset()) -> int:
    """THE hook (`engine._after_judge`, last): the contract's code lines appended to the decided lines. Returns how many."""
    new = lines(
        paper.pages,
        state.identity,
        held_labels(conn, state.paper_id, frozenset(allowed_books)),
    )
    state.decided.extend(new)
    return len(new)
