"""Two guards on a Pass of a rule WITHOUT numbers (order 13, W2 finding and review R39). Pure functions, no I/O, no model call.

A Pass of such a rule used to rest on two verified quotes and a second reader: the code compared no value and did not check that the
quote answers the rule's own FIELD or the rule's CONDITION. The guards run on EVERY Pass answer of such a rule, whatever the gate
decided (`agent_review_decide`), and on the second reader's own quotes (`agent_review_two_reader_run`); a line a guard objects to
carries `pass_guard = {"ok": False, "code", "why"}` and can end neither as "Proven by code: Pass" nor as "AI verdict: met"
(`agent_review_two_reader.textual_pass_agreed`, `is_candidate`, `agrees` read it). A guard only ever takes confidence away; a Fail,
a Query and a number rule (the code compares the figures) are never touched. The reasons state only what the code saw.

A. FIELD (`belongs`). The rule's field is the label's field and the item's field roles, in the registry's words
   (`agent_review_absence.field_words`: its label patterns and spellings; ALL of a spelling's words, no single shared word). A field the
   registry does not know needs every content word of its name. The verified quote's OWN line must carry them; or the line DIRECTLY ABOVE
   it must (never below), when that line is a short label line with no digit and the quote's own line carries no other known field's
   words. A single generic word (`GENERIC`: type, material, service, size, fluid, code, flow) counts only when the line is exactly that
   label. The AI's own field label is never evidence.
B. CONDITION. When the clause quote or the requirement holds a condition (`agent_review_verdict.is_conditional`, one home), the answer
   must carry a condition quote (`condition_quote`, `condition_page`) that is verified on its page, holds a content word of the
   condition itself (not just "service"), and is not the value quote nor overlaps it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from . import agent_bind
from . import agent_review_absence as absence
from . import agent_review_verdict as verdict
from .reader_api import _fold

CODE_FIELD_UNKNOWN = "pass_field_unknown"
CODE_FIELD_NOT_QUOTED = "pass_field_not_quoted"
CODE_CONDITION_NOT_QUOTED = "pass_condition_not_quoted"
CODES = (CODE_FIELD_UNKNOWN, CODE_FIELD_NOT_QUOTED, CODE_CONDITION_NOT_QUOTED)
FIELD_UNKNOWN_WHY = "the rule's field is not known to the code, so the quoted line could not be matched to it"
FIELD_LINE_WHY = "the field's words are not on the quoted line or the line above it"
CONDITION_NOT_QUOTED_WHY = (
    "the AI reviewer holds no verified quote for the condition the rule applies under"
)
CONDITION_WORD_WHY = "the quote given for the condition holds no word of the condition, or repeats the value quote"
#: a one-word label that names no field by itself (matched only as the whole label line)
GENERIC = frozenset({"type", "material", "service", "size", "fluid", "code", "flow"})
#: a label line above a value is short and has no digit
MAX_LABEL_WORDS = 6
_TRIGGERS = frozenset(
    {
        "if",
        "when",
        "where",
        "unless",
        "provided",
        "that",
        "in",
        "case",
        "except",
        "only",
        "otherwise",
        "for",
        "to",
    }
)
_HEADS = frozenset({"service", "duty"})


def field_names(item: Mapping) -> list[str]:
    """The rule's own field names: the label's field, then the item's field roles."""
    label = (
        item.get("rule_label") if isinstance(item.get("rule_label"), Mapping) else {}
    )
    names = [
        str(label.get("field") or "").strip(),
        *[str(r).strip() for r in item.get("field_roles") or []],
    ]
    return [n for n in dict.fromkeys(names) if n]


def _is_the_label(folded: str, text: str) -> bool:
    return folded.strip(" :.-") == text.strip()


def _hit(folded: str, words: absence.FieldWords) -> bool:
    """The folded line carries the field's words by the registry's patterns or spellings; a single generic word only as the whole line."""
    for p in words.patterns:
        m = p.search(folded)
        if m:
            text = m.group(0).strip()
            if text and not (
                len(text.split()) == 1
                and text in GENERIC
                and not _is_the_label(folded, text)
            ):
                return True
    for sp in words.spellings:
        generic_alone = (
            len(sp.split()) == 1 and sp in GENERIC and not _is_the_label(folded, sp)
        )
        if re.search(rf"(?<!\w){re.escape(sp)}(?!\w)", folded) and not generic_alone:
            return True
    return False


@lru_cache(maxsize=1)
def _all_fields() -> tuple[tuple[str, absence.FieldWords], ...]:
    roles = absence.registry()["roles"]
    out = []
    for role in sorted(roles):
        words = absence.field_words([(role, "registry")])
        if words is not None:
            out.append((role, words))
    return tuple(out)


#: words a label line may add to the field's own words: a unit column header
UNIT_HEADERS = frozenset({"unit", "units", "uom"})
NEGATIONS = frozenset(
    {"not", "no", "non", "without", "never", "none", "nor", "neither", "nil"}
)


def _label_only(folded: str, names: list[str]) -> bool:
    """The line is ONLY the field's label: its longest registry match (or all content words of a field the registry does not know)
    and nothing else but punctuation, a parenthesised unit or a unit column header. A row that holds a text value is not a label line."""
    words = absence.field_words([(n, "rule label") for n in names])
    if words is not None:
        found = [m.group(0) for p in words.patterns for m in p.finditer(folded)]
        found += [
            sp
            for sp in words.spellings
            if re.search(rf"(?<!\w){re.escape(sp)}(?!\w)", folded)
        ]
        if not found:
            return False
        rest = folded.replace(max(found, key=len).strip(), " ", 1)
    else:
        want = agent_bind.content_words(" ".join(n.replace("_", " ") for n in names))
        have = agent_bind.content_words(folded)
        return bool(want) and want <= have and have - want <= UNIT_HEADERS
    rest = re.sub(r"\([^)]*\)", " ", rest)
    return all(t in UNIT_HEADERS for t in re.findall(r"[a-z0-9]+", rest))


def _carries(folded: str, names: list[str]) -> bool:
    words = absence.field_words([(n, "rule label") for n in names])
    if words is not None:
        return _hit(folded, words)
    want = agent_bind.content_words(" ".join(n.replace("_", " ") for n in names))
    if len(want) == 1 and next(iter(want)) in GENERIC:
        return _is_the_label(folded, next(iter(want)))
    return bool(want) and want <= agent_bind.content_words(folded)


def _other_field_words(folded: str, names: list[str]) -> bool:
    """The line carries the words of a registry field that is NOT the rule's own."""
    own = absence.field_words([(n, "rule label") for n in names])
    own_role = own.role if own is not None else None
    return any(role != own_role and _hit(folded, w) for role, w in _all_fields())


def _page_lines(page_text: Any) -> list[tuple[int, int, str]]:
    """(start, end, folded) of every non-empty page line in the folded page text (lines joined by one space, as `_fold` does)."""
    out, pos = [], 0
    for raw in str(page_text or "").splitlines():
        folded = _fold(raw)
        if folded:
            out.append((pos, pos + len(folded), folded))
            pos += len(folded) + 1
    return out


def _own_and_above(page_text: Any, quote: Any) -> tuple[list[str], str | None]:
    """(the folded lines the verified quote lies on, the folded line directly above the first of them or None)."""
    q = _fold(str(quote or "")).strip()
    pieces = _page_lines(page_text)
    i = " ".join(p[2] for p in pieces).find(q) if q else -1
    if i < 0:
        return [], None
    hit = [k for k, (a, b, _f) in enumerate(pieces) if a < i + len(q) and i < b]
    above = pieces[hit[0] - 1][2] if hit[0] > 0 else None
    return [pieces[k][2] for k in hit], above


def belongs(
    item: Mapping, quote: Any, page_text: Any
) -> tuple[bool, str | None, str | None]:
    """(ok, reason code, reason): the strict test of guard A. Not established = not ok, with the reason in plain words."""
    names = field_names(item)
    if not names:
        return False, CODE_FIELD_UNKNOWN, FIELD_UNKNOWN_WHY
    own, above = _own_and_above(page_text, quote)
    if own and any(_carries(line, names) for line in own):
        return True, None, None
    if (
        own
        and above
        and not re.search(r"\d", above)
        and len(above.split()) <= MAX_LABEL_WORDS
        and _carries(above, names)
        and _label_only(above, names)
        and not any(_other_field_words(line, names) for line in own)
    ):
        return True, None, None
    return False, CODE_FIELD_NOT_QUOTED, FIELD_LINE_WHY


def condition_terms(*texts: Any) -> set[str]:
    """The content words of the conditions the detector (`verdict._CONDITIONAL`, one home) finds in the texts: for a conditional
    word the words after it up to the next punctuation; for a "for / in / to ... service" form the words of the form itself. The bare
    trigger words and the heads "service" and "duty" are not terms."""
    terms: set[str] = set()
    for text in texts:
        t = str(text or "")
        for m in verdict._CONDITIONAL.finditer(t):
            span = m.group(0)
            if re.match(r"(?:for|in|to)\s", span, re.IGNORECASE):
                words = span
            else:
                words = " ".join(
                    re.split(r"[.;:,()]", t[m.end() :], maxsplit=1)[0].split()[:8]
                )
            terms |= {
                w
                for w in agent_bind.content_words(words)
                if w not in _TRIGGERS and w not in _HEADS
            }
    return terms


def _spans(page_text: Any, quote: Any) -> list[tuple[int, int]]:
    q, fp = _fold(str(quote or "")).strip(), _fold(str(page_text or ""))
    out, i = [], fp.find(q) if q else -1
    while i >= 0:
        out.append((i, i + len(q)))
        i = fp.find(q, i + 1)
    return out


def _negated(quote: str, terms: set[str]) -> bool:
    """A negation word within five words before, or three after, a word of the condition ("not expected to be sour")."""
    tokens = re.findall(r"[a-z0-9']+", _fold(quote))
    for i, tok in enumerate(tokens):
        if terms & agent_bind.content_words(tok) and any(
            t in NEGATIONS or t.endswith("n't") for t in tokens[max(0, i - 5) : i + 4]
        ):
            return True
    return False


def condition_ok(answer: Mapping, pages: Mapping[int, str], terms: set[str]) -> bool:
    """The condition quote is verified on its page, holds a word of the condition, and is not the value quote nor overlaps it."""
    cq = answer.get("condition_quote")
    ok, _why = verdict.check_paper_quote(cq, answer.get("condition_page"), pages)
    if not (ok and terms and terms & agent_bind.content_words(str(cq))):
        return False
    if _negated(
        str(cq), terms
    ):  # a quote saying the condition does NOT hold is no quote of the condition
        return False
    vq, fc, fv = (
        answer.get("paper_quote"),
        _fold(str(cq)).strip(),
        _fold(str(answer.get("paper_quote") or "")).strip(),
    )
    if fc == fv or fc in fv or fv in fc:
        return False
    cp, vp = (
        verdict._page_no(answer.get("condition_page")),
        verdict._page_no(answer.get("paper_page")),
    )
    if cp is not None and cp == vp:
        a, b = _spans(pages.get(cp), cq), _spans(pages.get(vp), vq)
        if any(x[0] < y[1] and y[0] < x[1] for x in a for y in b):
            return False
    return True


def verdict_of(
    item: Mapping, answer: Mapping, pages: Mapping[int, str], requirement: str | None
) -> dict | None:
    """The guards' result for one Pass answer: None for a number rule (not this guard's), {"ok": True}, or {"ok": False, "code", "why"}."""
    if verdict.is_number_item(item):
        return None
    page = verdict._page_no(answer.get("paper_page"))
    ok, code, why = belongs(
        item, answer.get("paper_quote"), pages.get(page) if page else None
    )
    if not ok:
        return {"ok": False, "code": code, "why": why}
    if verdict.is_conditional(answer.get("clause_quote"), requirement):
        terms = condition_terms(answer.get("clause_quote"), requirement)
        if not (answer.get("condition_quote") and condition_ok(answer, pages, terms)):
            quoted = bool(answer.get("condition_quote"))
            return {
                "ok": False,
                "code": CODE_CONDITION_NOT_QUOTED,
                "why": CONDITION_WORD_WHY if quoted else CONDITION_NOT_QUOTED_WHY,
            }
    return {"ok": True}


def check(
    item: Mapping, answer: Mapping, pages: Mapping[int, str], requirement: str | None
) -> tuple[str, str] | None:
    """(reason code, reason) when a Pass of a rule without numbers must not stand, else None."""
    got = verdict_of(item, answer, pages, requirement)
    return None if got is None or got["ok"] else (str(got["code"]), str(got["why"]))
