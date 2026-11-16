"""The words a reader sees on the AI reviewer's CRS (order 13, owner 12 Nov 2026). Pure functions and constants; no I/O, no model call.

ONE module for every fixed sentence of the main sheet, and ONE table of plain phrases (`WHY_PHRASES`, `WHY_PATTERNS`,
`CODE_PHRASES`) that turns what a line stores (a guard reason, a reason code, a model's own sentence) into words with no code
word in them. Nothing here decides a verdict: the line already carries it. A reason that has no phrase here is never printed
raw; it prints `UNKNOWN_WHY`.

Words that must not stand on a cell a reader sees (`BANNED`): an item id (`S-EQ-04`, `R-...`), a reason code (`not_met`, any
word_with_underscores), a model id, and the words gate, lane, guard, tier, verdict class, quote check, reason code. The paper's
own quotes and the rule's own words are not scrubbed: they are the document's, not ours.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from . import agent_review_absence as absence
from .agent_review_two_reader import DISAGREE_ONE_FOUND
from .agent_review_verdict import (
    CONDITIONAL_WHY,
    DEFERRED_WHY,
    DISAGREE_WHY,
    NO_VALUE_WHY,
    NOT_STATED_WHY,
    SILENCE_WHY,
    TABLE_NOTE_WHY,
    UNVERIFIED_CLAUSE_WHY,
    UNVERIFIED_PAPER_WHY,
)
from .clause_check_rank import is_safety

# ---------------------------------------------------------------- the four Status words, their order, the priority rule

STATUS_FAIL, STATUS_AI, STATUS_QUERY, STATUS_PASS = (
    "Fail",
    "AI opinion",
    "Query",
    "Pass",
)
#: The fifth Status word (owner order 13, point 10): two AI readers reached the same verdict independently. Internal copy only.
STATUS_AI_VERDICT = "AI verdict"
STATUSES = (STATUS_FAIL, STATUS_AI_VERDICT, STATUS_AI, STATUS_QUERY, STATUS_PASS)
HIGH, MEDIUM, LOW = "High", "Medium", "Low"
#: Internal copy row order: Fail, AI verdict (not met), AI opinion (not met), Query, AI verdict (met), AI opinion (met), Pass
#: (owner, 12 Nov, order 13 point 10).
(
    ORDER_FAIL,
    ORDER_AI_VERDICT_NOT_MET,
    ORDER_AI_NOT_MET,
    ORDER_QUERY,
    ORDER_AI_VERDICT_MET,
    ORDER_AI_MET,
    ORDER_PASS,
) = range(7)
#: The sheet of the lines that are not item rows (same Item No scheme), and what each kind is called there.
OTHER_SHEET = "Not reviewed or not applicable"  # Excel: 31 characters at most
KIND_NOT_APPLICABLE = "Does not apply"
KIND_NOT_REVIEWED = "Not reviewed"
KIND_UNAPPROVED = "Rule not yet approved"
KIND_NOT_HELD = "Not checked: rule book not held"
KIND_NOT_CHECKED_HERE = "Not checked on this paper"
OTHER_KINDS = (
    KIND_NOT_APPLICABLE,
    KIND_NOT_REVIEWED,
    KIND_UNAPPROVED,
    KIND_NOT_CHECKED_HERE,
    KIND_NOT_HELD,
)
#: Order 14 lane B (owner, 16 Nov 2026: "drop noise rows, merge repeats, move 'N rules not matched' to a coverage note"). A line or point
#: that carries no finding is NOT a comment: it is listed apart, counted and named, never dropped (the completeness rule still holds).
NOT_A_COMMENT_SHEET = "Not a comment"  # the AI run file's sheet of every line that is not a comment row (Excel: 31 characters at most)
KIND_NOTHING_TO_CHANGE = "Checked, nothing to change"  # met (proven, two readers or one reader): the engineer ticks it, no comment
KIND_COVERAGE = "Coverage note"  # "N rules of a book could not be matched to a field": one coverage note, not a comment
KIND_IN_COMMENT = "Part of comment {n}"  # the same field or topic as comment n: its clause and page are listed on that comment
KIND_MET_NOT_CONFIRMED = "AI says met, not confirmed: engineer to tick"  # quote not found or readers disagree; nothing open or missing
NOT_A_COMMENT_KINDS = (KIND_NOTHING_TO_CHANGE, KIND_MET_NOT_CONFIRMED, KIND_COVERAGE)
#: Words that say there is nothing to do ("no correction needed", "found none", "could not be read" and their plain variants). A model's
#: own sentence is shown without them (`drop_noise`); our own fixed words never use them.
NOISE = re.compile(
    r"\b(?:no corrections? (?:is |are |was |were )?(?:needed|required)"
    r"|found none|none (?:was |were )?found"
    r"|(?:could|can) ?not be read|couldn'?t be read|can'?t be read)\b[^.;!?]*[.;!?]?",
    re.IGNORECASE,
)


def priority_rule(statuses) -> str:
    """THE Priority sentence, built from the Statuses a reviewer can write (the AI reviewer: all five; the normal reviewer: four)."""
    verdict = STATUS_AI_VERDICT in statuses
    not_met = (
        "AI verdict (not met) and AI opinion (not met)"
        if verdict
        else "AI opinion (not met)"
    )
    blank = (
        "AI verdict (met), AI opinion (met) and Pass"
        if verdict
        else "AI opinion (met) and Pass"
    )
    return (
        f"Priority is set by one rule. Fail = High. {not_met} = High when the rule is mandatory, "
        f"otherwise Medium. Query = Medium when the rule is mandatory, otherwise Low. {blank} = blank. "
        "Mandatory means a held "
        "rule that is not marked as a recommendation ('should'); a checklist item has no stored strength and counts as not "
        "mandatory."
    )


PRIORITY_RULE = priority_rule(STATUSES)
#: The normal reviewer never writes the two-reader class: its sentence names the four Statuses it can write.
NORMAL_STATUSES = tuple(x for x in STATUSES if x != STATUS_AI_VERDICT)
PRIORITY_RULE_NORMAL = priority_rule(NORMAL_STATUSES)

#: The sentence of an "AI verdict" line says WHICH route earned it, each sentence true: the independent second-reader step, or the
#: always-on route (owner, 12 Nov): a verdict one AI reader gave, checked and agreed by a second AI reader that SAW the first answer.
#: The owner's words (12 Nov 2026) open the sentence of an "AI verdict" line; then the route clause, each true; then the engineer.
OWNER_MET = "Met (AI, two readers agree, quotes verified)"
OWNER_NOT_MET = "Not met (AI, two readers agree, quotes verified)"
ROUTE_INDEPENDENT = "reached independently by two AI readers"
ROUTE_CHECKED = (
    "one AI reader's verdict, checked by a second AI reader that saw the first answer"
)
VERDICT_PREFIX_INDEPENDENT = f"{OWNER_MET}: {ROUTE_INDEPENDENT}, engineer to confirm."
VERDICT_PREFIX_CHECKED = f"{OWNER_MET}: {ROUTE_CHECKED}, engineer to confirm."


ABSENCE_CHECK_SEARCHED = (
    "the code searched for this field and found no value on any page"
)
ABSENCE_OPENER = "Not stated (AI, two readers agree)"


def absence_verdict_sentence(item: str, clause_quote: str) -> str:
    """ONE home of the sentence of an "AI verdict: not stated" line (lead, 12 Nov 2026, from the owner's rule). It never says the paper
    side is "quotes verified": there is no paper quote, the readers found nothing. The clause quote is the verified one. The line has
    this word only when the code itself searched (R49 F2), so the code-check clause is always the searched one."""
    ask = f' The rule requires: "{clause_quote}".' if clause_quote else ""
    return f"{ABSENCE_OPENER}: two AI readers each read every page of the paper and found no {item}.{ask} Code check: {ABSENCE_CHECK_SEARCHED}. Engineer to confirm."


def absence_cell(line: Mapping, item: str) -> str:
    """The CRS cell of an "AI verdict: not stated" line: `absence_verdict_sentence` with the line's verified clause quote."""
    quote = plain(" ".join(str(line.get("clause_quote") or "").split())[:300])
    return absence_verdict_sentence(item or "value for this item", quote)


def decisions_rows(dec: Mapping) -> list[tuple[str, str]]:
    """The Notes rows of the one decisions count (`wording.decisions_of`): the total, and the absence decisions apart when there are any."""
    rows = [
        (
            "Decisions",
            f"Decisions: {dec['total']} = code Pass/Fail {dec['code']} + two-reader verdicts {dec['two_reader']}",
        )
    ]
    if dec["not_stated"]:
        rows.append(
            (
                "Decisions, of which",
                f"of which: not stated on the paper {dec['not_stated']}",
            )
        )
    return rows


def verdict_prefix(independent: bool, met: bool = True) -> str:
    """ONE home of the first sentence of an "AI verdict" met / not met line: the owner's words, the route clause, "engineer to confirm"."""
    head = OWNER_MET if met else OWNER_NOT_MET
    return f"{head}: {ROUTE_INDEPENDENT if independent else ROUTE_CHECKED}, engineer to confirm."


AI_VIEW_PREFIX = "The AI reviewer's view, not proven: the requirement is "
AI_VIEW_MET = (
    AI_VIEW_PREFIX + "met."
)  # the scorer reads this to tell an AI "met" from a comment
GENERATED_BY = "Generated by AI, to be confirmed by a {company} engineer"
DEFAULT_COMPANY = "COMPANY"
COMMENT_BY = "AI reviewer"

# ---------------------------------------------------------------- the one table of plain phrases

UNKNOWN_WHY = "it could not be confirmed"
_ABSENCE_UNCONFIRMED = (
    "the AI reviewer did not find it, but that could not be confirmed"
)
#: absence code (`agent_review_absence.ABSENCE_WHY` key) -> plain phrase. Every key must be here (a test reads them all).
ABSENCE_PLAIN: dict[str, str] = {
    "absence_not_a_rule": "it is not a held rule, so an absence could not be confirmed",
    "absence_rule_not_found": _ABSENCE_UNCONFIRMED,
    "absence_advice": "the rule is a recommendation, so a missing statement is not a failure",
    "absence_not_binding": "the rule does not say shall or must, so a missing statement is not a failure",
    "absence_conditional": "the rule holds only under a condition, which the AI reviewer could not settle from the paper",
    "absence_exception": "the rule has an exception that may apply",
    "absence_field_unknown": _ABSENCE_UNCONFIRMED,
    "absence_field_ambiguous": "the rule names several fields, so it is not clear which one to look for",
    "absence_no_field_list": "this kind of paper has no fixed field list, so an absence could not be confirmed",
    "absence_not_carried": "the item may belong in another paper",
    "absence_page_unreadable": "a page has no readable text, so an absence could not be confirmed",
    "absence_field_read": "the paper names the item, so it may be stated",
    "absence_field_words_on_page": "the field's words stand on a page of the paper, so it may be stated",
    "absence_value_deferred": DEFERRED_WHY,
    "absence_clause_weak": "the quoted rule text is too short or could not be found, so an absence could not be confirmed",
    "absence_no_second_opinion": "no second AI reader confirmed the absence",
    "absence_second_disagreed": "the second AI reader did not agree with the first reader",
    "absence_second_same_model": "no independent second AI reader confirmed the absence",
}
#: Lane D's reason text for a second reader cut off by its token limit, keyed by its exact words (the constant lives in
#: `agent_review_wording.CUT_OFF_WHY` once lane D is merged; a test keeps the two equal).
CUT_OFF_WHY = (
    "the second AI reader's answer was cut off, so the two readers did not agree"
)
WHY_PHRASES: dict[str, str] = {
    SILENCE_WHY: "the AI reviewer found the paper silent on this, which could not be confirmed",
    CONDITIONAL_WHY: "the rule holds only under a condition, which the AI reviewer could not settle from the paper",
    TABLE_NOTE_WHY: "the rule is a table row or a note whose conditions may lie outside the quoted text",
    DEFERRED_WHY: "the paper leaves the value open",
    UNVERIFIED_PAPER_WHY: "the quoted paper text could not be found on the page",
    UNVERIFIED_CLAUSE_WHY: "the quoted rule text could not be found in the rule book",
    NOT_STATED_WHY: "the AI reviewer's own words say the paper leaves this out",
    NO_VALUE_WHY: "only the field name was quoted, with nothing after it",
    DISAGREE_WHY: "the two AI readers disagreed",
    # lane D's CUT_OFF_WHY (agent_review_wording, on o14/D-pump): the second reader was cut off, it never said the opposite
    CUT_OFF_WHY: "the second AI reader's answer was cut off, so the two readers did not agree",
    **{absence.ABSENCE_WHY[k]: v for k, v in ABSENCE_PLAIN.items() if k in absence.ABSENCE_WHY},
}  # fmt: skip
#: A reason with a part that changes (a verdict colour, a page number, an error text): matched by its start or its words.
WHY_PATTERNS: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), v)
    for p, v in (
        (r"^not asked: too long for the local model", "Not asked: too long for the local model. Not reviewed"),
        (r"^not all of the paper could be asked", "Not all of the paper could be asked; it was not found in the part that was. Not reviewed"),
        (r"^AI call failed", "the AI reviewer gave no answer"),
        (r"answer cut off", "the AI reviewer's answer was cut off"),
        (r"^no answer from the AI", "the AI reviewer gave no answer"),
        (r"^second opinion disagreed", "the two AI readers disagreed"),
        (r"^not shown on the sheet", "the AI reviewer did not find it, but that could not be confirmed"),
        (r"clause quote is too short|is the clause heading", "the quoted rule text is too short to rely on"),
        (r"no figure with its unit", "no figure with its unit stands in both quotes, so nothing could be compared"),
        (r"^the field's words are not on the quoted line", "the words of the rule's field are not on the quoted line or the line above it"),
        (r"^the rule's field is not known to the code", "the rule's field is not known to the code, so the quoted line could not be matched to it"),
        (r"^the quote given for the condition holds no word", "the quote given for the condition holds no word of the condition, or repeats the value quote"),
        (r"^the AI reviewer holds no verified quote for the condition", "the paper is not quoted for the condition the rule applies under"),
        (r"^the AI did not give pass or fail", "the AI reviewer did not reach a view"),
        (r"^(?:the )?rule is (?:also )?not AI approved", "the rule has not been approved yet"),
        (r"^no second opinion", "no second AI reader confirmed it"),
        (r"marks this value as not final", DEFERRED_WHY),
        (r"^field words unknown", "the paper could not be checked for an open value"),
        (r"^the AI judged the rule not applicable", "the AI reviewer judged the rule not applicable to this paper"),
    )
)  # fmt: skip
#: A reason code (the AI's closed list, or code's own) -> the plain words.
CODE_PHRASES = {
    "not_met": "not met",
    "met": "met",
    "absent": "not found",
    "absent_pages_not_named": "not found",
    "sheet_silent": "the AI reviewer found the paper silent",
    "needs_drawing_or_calc": "a drawing or a calculation is needed",
    "unclear_clause": "the rule text is unclear",
    "value_deferred": "the value is left open",
    "pass_field_not_quoted": "the field's words are not on the quoted line or the line above it",
    "pass_field_unknown": "the rule's field is not known",
    "pass_condition_not_quoted": "the condition the rule applies under is not quoted",
    "ai_call_failed": "the AI reviewer gave no answer",
    "not_asked_too_long": "not asked: too long for the local model",
    "not_applicable": "does not apply",
    "verdict_and_reason_differ": "the answer was not consistent",
    "other": "other",
}  # fmt: skip

# ---------------------------------------------------------------- words a reader must not see

_ID = (
    r"\b(?:S-[A-Z]{1,6}-\d+|S-\d+|R-\d+|R-[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}[0-9a-f]*)\b"
)


def _model_ids() -> list[str]:
    """The model ids the app knows: the price table of `claude_spend` and every `*_model` setting that looks like an id."""
    from . import claude_spend
    from .config import settings

    ids = set(claude_spend.PRICES)
    for key, value in settings.model_dump().items():
        if (
            key.endswith("_model")
            and isinstance(value, str)
            and len(value) > 3
            and not value.endswith((".onnx", ".pt"))
        ):
            ids.add(value)
    return sorted(ids, key=len, reverse=True)


_FAMILIES = (
    r"(?:claude|sonnet|opus|haiku|gpt|qwen|llama|ollama|mistral|gemma|gemini)[\w.:/-]*"
)
BANNED = re.compile(
    r"(?:" + _ID + r"|\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b|\bgate\b(?!\s+valves?)|\blane\b|\bguard\b|\btier\b"
    r"|verdict[\s_-]*class|quote[\s_-]*check|reason[\s_-]*code|\bmodel[\s_-]*id\b|\b" + _FAMILIES + r"|"
    + "|".join(re.escape(m) for m in _model_ids()) + r")",
    re.IGNORECASE,
)  # fmt: skip
_ID_RE = re.compile(_ID)
_SNAKE = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def has_banned(text: object) -> bool:
    """True when the text carries a code word a reader must not see."""
    return bool(BANNED.search(str(text or "")))


#: reasons built by `wording.reader_query_words` from a reason CODE (no model text): said as they are
_SAID_AS_THEY_ARE = (
    "the sheet does not state this",
    "needs a drawing or a calculation to judge",
    "the AI could not decide",
    "the AI gave no answer",
)


def _one_why(raw: str) -> str | None:
    if raw.startswith(_SAID_AS_THEY_ARE):
        return raw

    if raw.startswith(
        DISAGREE_ONE_FOUND
    ):  # built by code from a page number it verified (`absence_disagree_why`): said as it is
        return raw
    for known, phrase in WHY_PHRASES.items():
        if raw == known.rstrip("."):
            return phrase
    for pattern, phrase in WHY_PATTERNS:
        if pattern.search(raw):
            return phrase
    return None


def _pieces(raw: str) -> list[str]:
    """A reason of several parts as its parts: a known whole reason first (some contain a ';' themselves), the rest split at ';'."""
    out: list[str] = []
    rest = raw
    while rest:
        known = next(
            (k.rstrip(".") for k in WHY_PHRASES if rest.startswith(k.rstrip("."))), None
        )
        if known is None:
            head, _, rest = rest.partition(";")
            if head.strip():
                out.append(head.strip())
            continue
        out.append(known)
        rest = rest[len(known) :].lstrip("; ")
    return out


def why_phrase(text: object) -> str:
    """A stored reason in plain words: the table first, then the patterns, then each part of a reason joined by '; ', else
    `UNKNOWN_WHY`. Never the raw text."""
    raw = _clean(text).rstrip(".")
    if not raw:
        return ""
    if (whole := _one_why(raw)) is not None:
        return whole
    parts = [_one_why(p) for p in _pieces(raw)]
    known = list(dict.fromkeys(p for p in parts if p))
    return "; ".join(known) if known else UNKNOWN_WHY


def code_phrase(code: object) -> str:
    """A reason code in plain words (`CODE_PHRASES`); an unknown code is its words with spaces, never with underscores."""
    raw = _clean(code)
    return CODE_PHRASES.get(raw) or raw.replace("_", " ")


def plain(text: object) -> str:
    """A model's own text for a reader: ids removed, reason codes in words, and every sentence that still holds a code word
    dropped. '' when nothing is left. Numbers are not touched here (the caller's number check is `numparse`)."""
    raw = _clean(text)
    if not raw:
        return ""
    raw = _ID_RE.sub("", raw)
    raw = _SNAKE.sub(lambda m: code_phrase(m.group(0)), raw)
    keep = [s for s in _SENTENCES.split(raw) if s.strip() and not has_banned(s)]
    return drop_noise(" ".join(" ".join(keep).split()))


#: Order 14 (lane A's answer to lane B, 16 Nov 2026): a code check against a limit that is an AI draft. Never Pass or Fail; a Query.
AI_DRAFT = "AI draft, engineer to confirm"
_COMPARED = ("COMPLIANT", "NON_COMPLIANT")


def ai_draft_words(line: Mapping) -> str:
    """The words of an AI-draft check (`line["ai_draft"]` is True): "code compared the stated value with a limit that is an AI draft"
    ONLY when code really compared (`compare.code_said` COMPLIANT or NON_COMPLIANT); otherwise nothing was compared and only the
    check's own detail is said. '' for any other line."""
    if line.get("ai_draft") is not True:
        return ""
    why = _clean(
        line.get("why")
    )  # lane A: the bare detail is compare.reason; "why" already begins with AI_DRAFT
    detail = _clean((line.get("compare") or {}).get("reason")) or (
        why[len(AI_DRAFT) :] if why.startswith(AI_DRAFT) else why
    )
    detail = detail.strip(" :.")
    said = str((line.get("compare") or {}).get("code_said") or "").upper()
    if said in _COMPARED:
        return (
            f"{AI_DRAFT}: code compared the stated value with a limit that is an AI draft"
            + (f"; {detail}." if detail else ".")
        )
    return f"{AI_DRAFT}: {detail}." if detail else f"{AI_DRAFT}."


#: Order 14 lane G: what the contract's edition cutoff says of the held edition of a cited book (`standard_editions.against_cutoff`),
#: in the owner's words. Keyed by lane G's own status sentences; an unknown status is "not known", never a guess.
EDITION_WORDS = {
    "held edition binds": "binds",
    "held edition is later than the cutoff: for information only": "later, for information only",
    "held edition is older than the one that binds": "older than the edition that binds",
    "cannot tell: the date reaches into the cutoff": "cannot tell",
    "edition not known": "not known",
}


def edition_words(result: Mapping | None) -> str:
    """ "edition: binds" (and the edition that binds, and lane G's caveat, when it gives them) for one book's cutoff result."""
    if not result:
        return "edition: not known"
    out = "edition: " + EDITION_WORDS.get(_clean(result.get("status")), "not known")
    binding, held = _clean(result.get("binding")), _clean(result.get("held"))
    if binding and binding != held:
        out += f" (the edition that binds: {binding})"
    if caveat := _clean(result.get("caveat")):
        out += f"; {caveat}"
    return out


def drop_noise(text: object) -> str:
    """The text without the words that say there is nothing to do (`NOISE`, up to the end of their clause); the next word starts with
    a capital when a sentence now starts with it. '' when nothing is left. The finding itself is never in those words: a row that says
    only that is not a comment (`crs_comments.not_a_comment`)."""
    raw = _clean(text)
    if not NOISE.search(raw):
        return raw
    out = " ".join(NOISE.sub(" ", raw).split()).strip(" ;,")
    return out[:1].upper() + out[1:] if out else ""


def comment_by(discipline: object) -> str:
    """'AI reviewer, <discipline>', or 'AI reviewer' when the discipline is not known."""
    d = _clean(discipline)
    return f"{COMMENT_BY}, {d}" if d else COMMENT_BY


def generated_by(company: object) -> str:
    return GENERATED_BY.format(company=_clean(company) or DEFAULT_COMPANY)


def priority(status: str, line: Mapping, order: int | None = None) -> str:
    """THE priority rule (`PRIORITY_RULE`). Mandatory = a rule line that is not a recommendation."""
    mandatory = line.get("source") == "rule" and line.get("rule_kind") != "advice"
    if status == STATUS_FAIL:
        return HIGH
    if (status == STATUS_AI and order == ORDER_AI_NOT_MET) or (
        status == STATUS_AI_VERDICT and order == ORDER_AI_VERDICT_NOT_MET
    ):
        return HIGH if mandatory else MEDIUM
    if status == STATUS_QUERY:
        return MEDIUM if mandatory else LOW
    return ""


#: The AI reviewer's own Priority rule (U5, P6): from the FINDING, never from the reader's free guess.
PRIORITY_RULE_AI = (
    "Priority is set by one rule. Fail (proven by code) = High. For an AI opinion (not met), an AI verdict (not met) and a Query: "
    "High when the rule is mandatory ('shall') and its clause is about safety (the closed safety vocabulary); Medium when the rule is "
    "mandatory; otherwise Low. A point that has no clause has no priority. AI opinion (met), AI verdict (met) and Pass = blank. "
    "Mandatory means a held rule that is not marked as a recommendation ('should'), or an item of the engineer's approved checklist (an entry that states its own strength, 'should' or advice, is not mandatory)."
)


def priority_ai(status: str, line: Mapping, order: int | None = None) -> str:
    """THE AI reviewer's priority (`PRIORITY_RULE_AI`). The normal reviewer keeps `priority`."""
    if status == STATUS_FAIL:
        return HIGH
    not_met = (status == STATUS_AI and order == ORDER_AI_NOT_MET) or (
        status == STATUS_AI_VERDICT and order == ORDER_AI_VERDICT_NOT_MET
    )
    if not (not_met or status == STATUS_QUERY):
        return ""
    text = _clean(line.get("clause_quote") or line.get("requirement"))
    if not (text or _clean(line.get("clause"))):
        return ""
    # mandatory: a held rule, or an item of the engineer's approved checklist ("skill"), that is not marked as advice (a "should")
    # an entry that states its own strength is believed: a "should" / recommendation / advice is not mandatory
    advice = (
        line.get("rule_kind") == "advice"
        or line.get("recommendation")
        or (
            str(line.get("strength") or "").lower()
            in ("should", "recommendation", "advice")
        )
    )
    mandatory = line.get("source") in ("rule", "skill") and not advice
    if mandatory and is_safety(text):
        return HIGH
    return MEDIUM if mandatory else LOW


__all__ = [
    "BANNED",
    "EDITION_WORDS",
    "KIND_COVERAGE",
    "KIND_IN_COMMENT",
    "KIND_MET_NOT_CONFIRMED",
    "KIND_NOTHING_TO_CHANGE",
    "NOISE",
    "NORMAL_STATUSES",
    "NOT_A_COMMENT_KINDS",
    "NOT_A_COMMENT_SHEET",
    "OTHER_SHEET",
    "PRIORITY_RULE",
    "PRIORITY_RULE_AI",
    "PRIORITY_RULE_NORMAL",
    "STATUSES",
    "UNKNOWN_WHY",
    "WHY_PHRASES",
    "ai_draft_words",
    "code_phrase",
    "comment_by",
    "drop_noise",
    "edition_words",
    "generated_by",
    "has_banned",
    "plain",
    "priority",
    "priority_ai",
    "why_phrase",
]
