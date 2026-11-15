"""The proof behind a "Proven by code" Pass or Fail of the one reviewer (owner, 12 Nov 2026; review R48e of #1804). ONE home, read by the calculator that
MAKES the line and by the exit (`agent_review_wording`) that ASKS AGAIN, so a flag on a line is never the proof: the texts and the values on the line are.

A code line is proven only when ALL of these hold, each recomputed here from what the line stores:
  1. its source is "code" (compared without case) and it carries the code's own markers;
  2. PAPER side: the quote is not empty; the observed value is a BARE number (`numparse.as_number`: a "min 85", "approx. 85" or "85 typ." is never compared as 85);
     the number, and its unit as the comparison read them, are STATED inside the quote by the code's own number reader (`numparse.value_in_text`: on number
     boundaries, so "5" is not in "15"); no bound or approximation word sits next to it in the quote; the page is a real page (an int of 1 or more);
  3. CLAUSE side: the quote is not empty and states the limit (both ends of a range) and its unit the same way;
  4. the comparison is made AGAIN (`comparison.compare` on the stored requirement and value) and gives the verdict the line stores;
  5. the quote sits with the fact's field label, on the same line or the label line directly above (`agent_review_pass_guards.belongs`, the rule the
     AI review's Pass guard uses); that needs the page, so the calculator asks it when it makes the line and the line carries the answer
     (`quotes_checked.paper` holds the label test, the found-on-page test and the value test together).
The approved checklist's lines have no limit to find in a clause (the approved entry is the clause): they need the code's markers, an approved rule id,
the value stated inside the paper quote, the label-and-value test on the page, and a real page.
Pure: no database, no model, no network. Words and ids only; no document text is logged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from . import agent_review_approved_code as approved
from . import agent_review_pass_guards as guards
from . import comparison, hold_reason, numparse, table_cell
from .reader_api import _fold

BY_CODE = (
    "decided by code"  # `agent_review_verdict.BY_CODE`; a test keeps the two equal
)
log = logging.getLogger(__name__)

SOURCE = "code"
COMPLIANT, NON_COMPLIANT = comparison.COMPLIANT, comparison.NON_COMPLIANT
PASS, FAIL = "Pass", "Fail"

#: A bound or approximation word, or sign, next to a number: the number is then not the value as written (a minimum of 85 is not 85).
_BOUND_WORDS = (
    r"min|max|minimum|maximum|approx|approximately|about|typ|typical|nominal|nom|circa|ca|up\s+to|over|under|below|above"
    r"|not\s+less\s+than|not\s+more\s+than|at\s+least|at\s+most|nlt|nmt|equal\s+to"
)
_BEFORE = re.compile(
    rf"(?:^|[\s(\[])(?:{_BOUND_WORDS})\.?\s*[:=]?\s*$|[<>~≤≥±≈=]\s*$", re.IGNORECASE
)
_AFTER = re.compile(
    rf"^[^.;\n]{{0,20}}?(?:\b(?:{_BOUND_WORDS})\b|\u00b1|\+/-)", re.IGNORECASE
)

REQUIREMENT_KEYS = (
    "requirement_type",
    "operator",
    "raw_value",
    "raw_unit",
    "value_low",
    "value_high",
)


def is_code_line(line: Mapping) -> bool:
    """A line that claims to be the calculator's: its source (without case), its kind, its approved-checklist marker or its `C-` id says so.
    Any one is enough, so a line cannot dodge the re-derivation by spelling its source another way."""
    return (
        str(line.get("source") or "").strip().casefold() == SOURCE
        or line.get("code_kind") is not None
        or line.get("approved_checklist") is not None
        or str(line.get("item_id") or "").strip().upper().startswith("C-")
    )


def stored_text(value: object) -> str:
    """A rule's number as it is stored: never re-formatted (10000.55 stays 10000.55, 1234567 stays 1234567)."""
    if isinstance(value, bool) or value is None:
        return ""
    return str(value).strip()


def limit_numbers(requirement: Mapping) -> list[str]:
    """The numbers a clause quote must state: the limit, or both ends of a range."""
    if (
        requirement.get("value_low") is not None
        and requirement.get("value_high") is not None
    ):
        return [
            stored_text(requirement["value_low"]),
            stored_text(requirement["value_high"]),
        ]
    return (
        [stored_text(requirement.get("raw_value"))]
        if requirement.get("raw_value") not in (None, "")
        else []
    )


def _bound_next_to(quote: str, number: str) -> bool:
    """A bound or approximation word or sign directly before or after the number's place in the quote."""
    wanted = numparse.as_number(number)
    for n in numparse.find_numbers(numparse.fold(quote)):
        if n.value is not None and n.value == wanted and not n.joined:
            text = numparse.fold(quote)
            if _BEFORE.search(text[: n.start]) or _AFTER.match(text[n.end :]):
                return True
    return False


def number_stated(number: object, quote: object) -> bool:
    """The quote states the number as its own token: the code's number reader finds it, and no letter or digit is glued to it on either side ("85" is not in
    "x85", "PN85" or "85x"). A glued unit ("85dB") is therefore not found: a Query, never a proof."""
    wanted = numparse.as_number(number)
    if wanted is None:
        return False
    text = numparse.fold(quote)
    for n in numparse.find_numbers(text):
        before = text[n.start - 1 : n.start] if n.start else ""
        after = text[n.end : n.end + 1]
        if (
            n.value == wanted
            and not n.joined
            and not before.isalnum()
            and not after.isalnum()
        ):
            return True
    return False


def unit_stated(unit: object, quote: object) -> bool:
    """The quote states the unit as its own token: not the start of a longer unit or a basis mark ("bar" is not in "bar(g)", "barg" or "bar/h"). Case is kept
    ("mPa" is not "MPa"). The unit's own brackets ("dB(A)") are part of the token."""
    u = stored_text(unit)
    if not u:
        return True
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(u)}(?![A-Za-z0-9(/])", str(quote or ""))
        is not None
    )


def states(number: object, unit: object, quote: object) -> bool:
    """The quote states the number and, when there is one, its unit, each as its own token."""
    return number_stated(number, quote) and unit_stated(unit, quote)


def paper_reason(observed: Mapping | None, quote: object) -> str | None:
    """Why the paper quote does not prove the observed value, in words; None when it does."""
    raw = stored_text((observed or {}).get("raw_value"))
    if not stored_text(quote):
        return "the paper has no quote for this value"
    if numparse.as_number(raw) is None:
        return "the value is written with words or a qualifier (a minimum, a maximum, approximate, typical, a range), so it was not compared as a bare number"
    if not states(raw, (observed or {}).get("raw_unit"), quote):
        return (
            "the value and its unit are not both stated inside the quote from the paper"
        )
    if _bound_next_to(str(quote), raw):
        return "the quote gives the value with a bound or approximation word, so it was not compared as a bare number"
    return None


def clause_reason(requirement: Mapping | None, quote: object) -> str | None:
    """Why the clause quote does not prove the limit, in words; None when it does."""
    req = requirement or {}
    if not stored_text(quote):
        return "the rule has no quote from its clause"
    numbers = limit_numbers(req)
    if not numbers or not all(states(n, req.get("raw_unit"), quote) for n in numbers):
        return "the limit and its unit are not both stated inside the quote from the clause"
    return None


DIRECTION_WHY = "the clause's wording does not show the direction of the limit"
_SENSE = {
    ">=": "lower",
    ">": "lower",
    "min": "lower",
    "<=": "upper",
    "<": "upper",
    "max": "upper",
    "=": "equal",
}
#: words that follow a figure and give its direction ("90 dB(A) maximum", "5 bar or more"): the one small list this module adds to the comparator
#: vocabulary of `claims` (which reads only what stands BEFORE a figure).
_AFTER_DIRECTION = (
    (
        re.compile(
            r"^\s*(?:[a-z\u00b0%()/0-9.]{1,12}\s+)?(?:or\s+(?:less|lower|fewer|below)|maximum|max\.?)\b",
            re.IGNORECASE,
        ),
        "upper",
    ),
    (
        re.compile(
            r"^\s*(?:[a-z\u00b0%()/0-9.]{1,12}\s+)?(?:or\s+(?:more|higher|greater|above)|minimum|min\.?)\b",
            re.IGNORECASE,
        ),
        "lower",
    ),
)
_RANGE_WORD = re.compile(r"\bbetween\s*$", re.IGNORECASE)
_RANGE_JOIN = re.compile(
    r"^\s*(?:\S{0,12}\s+)?(?:and|to|-|\u2013|\u2014)\s", re.IGNORECASE
)


def _sense_before(prefix: str) -> str | None:
    """The direction a comparator phrase at the END of `prefix` gives: the repo's one comparator vocabulary (`claims.comparator_ending`)."""
    from . import claims

    return _SENSE.get(claims.comparator_ending(prefix.strip()) or "")


def direction_reason(requirement: Mapping | None, quote: object) -> str | None:
    """Why the clause quote does not show the DIRECTION of the stored limit; None when it does. The stored comparator (at least, at most, equal) or
    range must agree with a direction word the quote carries next to the limit's figure: before it (claims' comparator vocabulary) or after it.
    No word, or the opposite one, is a reason. A range needs "between" before the first end, or a joining "and" / "to" / dash before the second."""
    req = requirement or {}
    text, numbers = numparse.fold(str(quote or "")), limit_numbers(req)
    if not numbers:
        return DIRECTION_WHY
    found = [
        n for n in numparse.find_numbers(text) if n.value is not None and not n.joined
    ]
    spots = [
        next((n for n in found if n.value == numparse.as_number(x)), None)
        for x in numbers
    ]
    if any(spot is None for spot in spots):
        return DIRECTION_WHY
    if len(numbers) == 2:
        first, second = sorted(spots, key=lambda n: n.start)
        joined = _RANGE_WORD.search(text[: first.start]) or _RANGE_JOIN.match(
            text[first.end : second.start] + " "
        )
        return None if joined else DIRECTION_WHY
    want = _SENSE.get(str(req.get("operator") or ""))
    spot = spots[0]
    got = _sense_before(text[: spot.start])
    if got is None:
        after = text[spot.end :]
        got = next((sense for rx, sense in _AFTER_DIRECTION if rx.match(after)), None)
    return None if want is not None and got == want else DIRECTION_WHY


SUBJECT_WHY = "the clause's wording does not make the field the subject of the limit"


_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\s+|\n+")
#: what may stand directly before a lone field word that is the subject itself ("the pressure", "of pressure"); any other word there is a qualifier that makes it
#: another field ("test pressure", "relief valve pressure")
_BEFORE_HEAD = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "at",
        "to",
        "and",
        "or",
        "that",
        "whose",
        "with",
        "no",
        "any",
        "each",
        "its",
        "this",
        "all",
    }
)


def _sentence_before_figure(quote: object, numbers: list[str]) -> str | None:
    """The folded words of the SAME sentence (or table line) that states the limit, up to its figure: the first sentence or line of the quote that holds the limit's number."""
    wanted = [numparse.as_number(x) for x in numbers]
    for seg in _SENTENCE_BREAK.split(str(quote or "")):
        text = numparse.fold(seg)
        spots = [
            n
            for n in numparse.find_numbers(text)
            if n.value is not None and n.value in wanted and not n.joined
        ]
        if spots:
            return text[: min(n.start for n in spots)]
    return None


def subject_reason(
    rule_field: object, requirement: Mapping | None, quote: object
) -> str | None:
    """Why the clause quote is not ABOUT the rule's field, in words; None when it is. In the SAME sentence (or table line) as the limit's figure, before it,
    the rule's own field stands as a whole phrase: the approved field list's own words for it (`agent_review_pass_guards`), no other approved field of the
    list in that sentence, and a field of one common word only as the subject itself ("the pressure shall not exceed"), never as the end of a longer name
    ("test pressure", "relief valve pressure"). "Noise level is reported separately. Valve body shall not exceed 90" is about the valve body."""
    from . import agent_bind

    field = str(rule_field or "").replace("_", " ").strip()
    sent = _sentence_before_figure(quote, limit_numbers(requirement or {}))
    words = agent_bind.content_words(field)
    if not (field and words and sent):
        return SUBJECT_WHY
    if not guards._carries(sent, [field]) or guards._other_field_words(sent, [field]):
        return SUBJECT_WHY
    if len(words) == 1 and len(field.split()) == 1:  # one word as written
        tokens = re.findall(r"[a-z0-9]+", sent)
        lone = [i for i, t in enumerate(tokens) if agent_bind.content_words(t) == words]
        if not any(i == 0 or tokens[i - 1] in _BEFORE_HEAD for i in lone):
            return SUBJECT_WHY
    return None


def recompute(requirement: Mapping, observed: Mapping) -> str | None:
    """The comparison made again on the stored requirement and value: COMPLIANT or NON_COMPLIANT, else None."""
    try:
        got = comparison.compare(
            {k: requirement.get(k) for k in REQUIREMENT_KEYS},
            {
                "raw_value": observed.get("raw_value"),
                "raw_unit": observed.get("raw_unit"),
                "is_blank": False,
            },
            submittal_facts=None,
        )
    except Exception as exc:  # noqa: BLE001 - a comparison that cannot be redone proves nothing
        log.warning(
            "code proof: the comparison could not be made again (%s)",
            type(exc).__name__,
        )
        return None
    status = got.get("status")
    return (
        status
        if status in (COMPLIANT, NON_COMPLIANT) and not got.get(hold_reason.KEY)
        else None
    )


NEAR_CHARS = 80


def value_near_label(label: object, value: object, text: object) -> bool:
    """The checklist's results carry the value and its label, not the cell's text. The value counts as FOUND only when the label occurs ONCE on the page,
    and the value is the ONE number that follows it on its line within `NEAR_CHARS` (by the code's number reader, on number boundaries: "5" is not in
    "15 bar"). A label that repeats (a column per case), or a second value in the window, is ambiguous: not found. A text value must be a whole word there."""
    lab = _fold(str(label or ""))
    if not (lab and str(value or "").strip() and str(text or "").strip()):
        return False
    seen = [
        (line, at)
        for _s, _e, line in guards._page_lines(text)
        for at in [m.start() for m in re.finditer(re.escape(lab), line)]
    ]
    if len(seen) != 1:
        return False
    line, at = seen[0]
    window = line[at + len(lab) : at + len(lab) + NEAR_CHARS]
    wanted = numparse.as_number(value)
    if wanted is None:
        return numparse.value_in_text(value, window)
    nums = [
        n for n in numparse.find_numbers(window) if n.value is not None and not n.joined
    ]
    if len(nums) != 1 or nums[0].value != wanted:
        return False
    return not window[
        nums[0].end : nums[0].end + 1
    ].isalpha()  # "316" is not the start of "316L"


def _real_page(line: Mapping) -> bool:
    """A page of the paper: an int of 1 or more, within the page count the line records (the calculator writes it from the paper's own pages)."""
    page, count = line.get("paper_page"), line.get("paper_page_count")
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (page, count))
    return ints and 1 <= page <= count


def _verdict_matches(line: Mapping, status: str | None) -> bool:
    cmp = line.get("compare")
    meets = line.get("verdict") == PASS
    return bool(
        status is not None
        and line.get("verdict") in (PASS, FAIL)
        and isinstance(cmp, Mapping)
        and cmp.get("decided") is True
        and cmp.get("verdict") == ("meets" if meets else "does_not_meet")
        and (status == COMPLIANT) == meets
    )


def _flags(line: Mapping) -> Mapping:
    got = line.get("quotes_checked")
    return got if isinstance(got, Mapping) else {}


def context_of(page_text: object, quote: object) -> str:
    """The lines the quote lies on and the line directly above the first of them, as the page holds them: what the exit needs to ask the label test again."""
    own, above = guards._own_and_above(page_text, quote)
    return "\n".join(([above] if above else []) + own)


def _db_page_text(document_id: str, page: int) -> str | None:
    """The stored text of one page of one document (a document is never edited in place: its id is its revision)."""
    from .db import connect

    row = (
        connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (document_id, page),
        )
        .fetchone()
    )
    return row["text"] if row is not None else None


#: Where the exit reads a page from. One place, so a test can give it a page without a database.
PAGE_SOURCE: list = [_db_page_text]


def page_text_of(line: Mapping) -> str | None:
    """The page the line names, read again from the store by the document id and page ON the line. None when the line names none, or it cannot be read."""
    doc, page = line.get("paper_document_id"), line.get("paper_page")
    if not (
        isinstance(doc, str)
        and doc
        and isinstance(page, int)
        and not isinstance(page, bool)
        and page >= 1
    ):
        return None
    try:
        text = PAGE_SOURCE[0](doc, page)
    except Exception as exc:  # noqa: BLE001 - a page that cannot be read again proves nothing
        log.warning(
            "code proof: the page could not be read again (%s)", type(exc).__name__
        )
        return None
    return text if isinstance(text, str) and text.strip() else None


def _cell_ok(line: Mapping, label: str, text: str) -> bool:
    """A located cell, asked again against the re-read page: the quote starts with the label cell, the label is that cell or a part of a compound label,
    and each of the two cells' words stands on the page."""
    cell_label, quote = (
        str(line.get("cell_label") or ""),
        str(line.get("paper_quote") or ""),
    )
    names = [_fold(cell_label), *[_fold(x) for x in table_cell.label_parts(cell_label)]]
    rest = _fold(quote)[len(_fold(cell_label)) :].strip()
    flat = _fold(text)
    return bool(
        label and cell_label and _fold(label) in names and _fold(quote).startswith(_fold(cell_label)) and rest
        and _fold(cell_label) in flat and rest in flat
    )  # fmt: skip


def paper_ok(line: Mapping) -> bool:
    """The paper side asked again from the page's own stored text, never from a flag or a context carried on the line: the quote is found on the page the
    line names; its field label stands on the quote's own line or the label line directly above it (`agent_review_pass_guards.belongs`, the Pass guard's
    rule), or, for a located cell, the label is the row's own cell."""
    label, text = str(line.get("field") or "").strip(), page_text_of(line)
    if not (label and text):
        return False
    if isinstance(line.get("cell_ref"), Mapping):
        return _cell_ok(line, label, text)
    quote = line.get("paper_quote")
    if not (stored_text(quote) and _fold(str(quote)) in _fold(text)):
        return False
    return guards.belongs({"field_roles": [label]}, quote, text)[0]


def numeric_proven(line: Mapping) -> bool:
    checked = _flags(line)
    req, obs = line.get("proof_requirement"), line.get("proof_fact")
    if not (isinstance(req, Mapping) and isinstance(obs, Mapping)):
        return False
    return bool(
        checked.get("paper") is True
        and checked.get("clause") is True
        and _real_page(line)
        and paper_reason(obs, line.get("paper_quote")) is None
        and paper_ok(line)
        and clause_reason(req, line.get("clause_quote")) is None
        and direction_reason(req, line.get("clause_quote")) is None
        and subject_reason(line.get("rule_field"), req, line.get("clause_quote"))
        is None
        and _verdict_matches(line, recompute(req, obs))
    )


def checklist_paper_ok(line: Mapping) -> bool:
    """A checklist line's paper side asked again from the re-read page: a located cell as for a numeric line, else the value stands next to its label there."""
    text = page_text_of(line)
    if not text:
        return False
    if isinstance(line.get("cell_ref"), Mapping):
        return _cell_ok(
            line, str(line.get("field") or "").strip(), text
        ) and number_stated(line.get("paper_value"), line.get("paper_quote"))
    return value_near_label(line.get("field"), line.get("paper_quote"), text)


def checklist_proven(line: Mapping) -> bool:
    checked = _flags(line)
    value = stored_text(line.get("paper_quote"))
    cmp = line.get("compare")
    return bool(
        line.get("approved_checklist") is True
        and line.get("rule_id") in approved.approved_check_ids()
        and line.get("rule_id")
        not in approved.presence_only_ids()  # a check that only asks a field be stated compares no value
        and checked.get("clause") is True
        and stored_text(line.get("clause_quote"))
        and value
        and _real_page(line)
        and checklist_paper_ok(line)
        and line.get("verdict") in (PASS, FAIL)
        and isinstance(cmp, Mapping)
        and cmp.get("decided") is True
        and cmp.get("verdict")
        == ("meets" if line.get("verdict") == PASS else "does_not_meet")
    )


def line_proven(line: Mapping) -> bool:
    """The exit's ask: a code line is a proven Pass or Fail only when it is proven again here; its source must be "code" without case."""
    if (
        line.get("decided_by") != BY_CODE
        or str(line.get("source") or "").strip().casefold() != SOURCE
    ):
        return False
    return (
        checklist_proven(line)
        if line.get("code_kind") == "checklist"
        else numeric_proven(line)
        if line.get("code_kind") == "numeric"
        else False
    )
