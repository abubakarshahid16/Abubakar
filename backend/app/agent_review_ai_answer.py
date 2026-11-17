"""The AI reviewer's OWN answer on a line that code did not prove (owner, 17 Nov 2026, order 14 item LP0). Pure functions, no I/O.

The owner's words: "Show the AI's own answer instead of a Query: 'Pass / Fail (AI, rule not approved, engineer to confirm)' with
standard, clause, page and quote. 'Does not apply (AI, engineer to confirm)' goes in a separate tick-to-confirm section. Plain Pass and
Fail only for code-proven rows. Do not count AI rows as decisions in the score."

THE ONE HOME of those words. Every writer takes them from here: the page's points (`review_points.ai_point`: the pill and the answer
line), the paper's one CRS file (`crs_one`, which prints the points' pill), and the AI run's own file (`crs_ai_workbook._paper_shows`,
`crs_comments._status_words`). The answer scorer reads them back through `says_met` / `is_label` (`tools.answer_key_score`).

WHAT IT CHANGES: WORDS ONLY. The line's class, rank, tile, priority, action and comment grouping stay exactly as they were, so a line
the gate made a question is still counted open, still a question for the engineer, never a decision (`agent_review_wording.decisions_of`
counts code Pass/Fail and two-reader verdicts only; the proposed review code counts the engineer's decisions only). What changes is
that such a line no longer hides the AI reader's own answer behind a bare "Query": it shows that answer, labelled as the AI's.

WHICH LINES (`label`): a line of the AI reviewer (a rule or a checklist item) whose reader answered met (Pass) or not met (Fail) and that
is NOT proven by code (the class "Proven by code" keeps its plain Pass / Fail), NOT a two-reader verdict (its own words, "Met (AI, two
readers agree, quotes verified)"), NOT "needs a drawing or a calculation", NOT a line with no answer (an error, a reader's own Query),
and NOT a line on a rule book the run does not hold (a book not held is never guessed: it stays a question, gate G7). A "does not apply"
without its proof (`agent_review_wording.not_applicable_question`) is "Does not apply (AI, engineer to confirm)", in its own section.
The rule check's own AI-written rows (AI clause review, AI engineering check, ...) store no verdict, so they are always a QUESTION
(PR #1882), never "Pass / Fail (AI, ...)": their line is `rule_check_question`, "Question (AI, not settled, <why>)", with its rule's
approval words looked up by the finding's requirement id (`rule_labels.usable_tier`, ONE lookup, `rule_check_why`). A line two AI readers disagree on is never in a Met / Not met tile: its class
is a question (`crs_ai_workbook.status_of`), its Class cell says "AI readers disagree, engineer to decide". Every other cell of an AI row
that says met / not met in our own words (a reason code, the second reader's verdict) carries "(AI, engineer to confirm)" (`marked`).

HONESTY (CLAUDE.md rule 4). The middle words say truly why the answer is not a plain Pass or Fail, read from the line's STORED tier
only (`final_cap` writes it; for the rule check's rows, the looked-up tier), never from a default that claims a fact: "rule not
approved" (not AI approved; a label that needs a person), "rule approved by AI only" (AI approved), "not proven by code" (approved by
the owner or an engineer, or an item of the app's approved checklist), "rule not sorted yet" (no label), "rule approval not recorded"
(no tier stored, or no requirement id to look it up by). When the second AI reader DISAGREED, no
reader's answer is shown as the answer: "AI readers disagree (first: Pass, second: Fail), engineer to decide". The page is printed with
`agent_review_crs.page_words` (a page hint says so); the quote only when code found it on the page, else "quote not found by code".
"""

from __future__ import annotations

from collections.abc import Mapping

from .agent_review_verdict import (
    AI_TIER,
    ENGINEER_TIER,
    FAIL,
    OWNER_TIER,
    PASS,
    RULE_NOT_APPROVED,
    TIER_NOT_APPROVED,
)

#: The owner's words, one constant each (a test reads them).
WHY_NOT_APPROVED = "rule not approved"
WHY_AI_ONLY = "rule approved by AI only"
WHY_NOT_PROVEN = "not proven by code"
WHY_NOT_RECORDED = "rule approval not recorded"
WHY_NOT_SORTED = "rule not sorted yet"
WHYS = (WHY_NOT_APPROVED, WHY_AI_ONLY, WHY_NOT_PROVEN, WHY_NOT_RECORDED, WHY_NOT_SORTED)
DISAGREE_LABEL = (
    "AI readers disagree (first: {first}, second: {second}), engineer to decide"
)
LABEL = "{answer} (AI, {why}, engineer to confirm)"
NOT_APPLICABLE_LABEL = "Does not apply (AI, engineer to confirm)"
#: Lead's decision (17 Nov 2026, with PR #1882): an AI answer is shown only beside a paper quote code verified; without one the line is a
#: question in these words (the AI reader's own reasoning stays in its labelled column).
NO_QUOTE_LABEL = (
    "AI view without a verified quote of the value from the paper: engineer to check"
)
QUOTE_FOUND = "found on the page by code"
QUOTE_LOOKED = (
    "where the AI reader looked; found on the page by code, it does not show the value"
)
QUOTE_NOT_FOUND = "quote not found by code"
NO_BOOK = "no held rule book linked"
BOOK_HIDDEN = "rule book not shown (not one you may read)"
BOOK_NO_NAME = "rule book name not recorded"
NO_CLAUSE = "clause not named"
NO_PAGE = "page not recorded"
DISAGREE_CLASS = "AI readers disagree, engineer to decide"
#: The mark of a met / not met in our own words on an AI row's other cells (`marked`).
AI_MARK = "(AI, engineer to confirm)"
_MET_WORDS = frozenset({"met", "not met", "not_met"})
#: The answers this module can give, as they open a label (the scorer reads them back: `is_label`).
ANSWERS = (PASS, FAIL)


def _why(line: Mapping) -> str:
    """Why the answer is the AI's and not a plain Pass / Fail, from the line's STORED tier only (see the module words)."""
    tier = line.get("tier")
    if line.get("rule_tier") == RULE_NOT_APPROVED or tier == TIER_NOT_APPROVED:
        return WHY_NOT_APPROVED
    if tier == AI_TIER:
        return WHY_AI_ONLY
    if tier in (OWNER_TIER, ENGINEER_TIER) or line.get("checklist") is True:
        return (
            WHY_NOT_PROVEN  # approved by a person, or the app's own approved checklist
        )
    return WHY_NOT_RECORDED


def rule_check_why(requirement_id: object, cache: dict | None = None) -> str:
    """THE middle words of a rule-check AI row, from its rule's tier looked up by the finding's requirement id (`rule_labels.usable_tier`):
    owner / engineer -> "not proven by code"; AI approved -> "rule approved by AI only"; no label -> "rule not sorted yet"; any other
    reason (needs a person, one pass only, quote not found, refused, declined) -> "rule not approved"; no requirement id, or a lookup
    that cannot be made -> "rule approval not recorded". `cache`: one lookup per requirement id."""
    import sqlite3

    from . import rule_labels
    from .db import connect

    key = str(requirement_id or "").strip()
    if not key:
        return WHY_NOT_RECORDED
    if cache is not None and key in cache:
        return cache[key]
    try:
        got = rule_labels.usable_tier(connect(), requirement_id=key)
    except sqlite3.Error:
        got = None
    if got is None:
        why = WHY_NOT_RECORDED
    elif got.tier in (OWNER_TIER, ENGINEER_TIER):
        why = WHY_NOT_PROVEN
    elif got.tier == AI_TIER:
        why = WHY_AI_ONLY
    elif got.reason in (rule_labels.NOT_LABELLED, rule_labels.NO_LABEL_TABLE):
        why = WHY_NOT_SORTED
    else:
        why = WHY_NOT_APPROVED
    if cache is not None:
        cache[key] = why
    return why


#: The rule check's AI-written row (#1882: no stored verdict, always a question): the lead of its line, with its rule's approval words.
RULE_CHECK_QUESTION = "Question (AI, not settled, {why})"


def rule_check_question(requirement_id: object, cache: dict | None = None) -> str:
    """THE lead of a rule-check AI-written row's line (`rule_check_why`): a question, never a Pass / Fail."""
    return RULE_CHECK_QUESTION.format(why=rule_check_why(requirement_id, cache))


def is_question(line: Mapping) -> bool:
    """An AI opinion line (stored "AI thinks") that is a question on every page and file (`crs_ai_workbook.status_of`): its two readers
    disagree, or it holds no paper quote code verified (an AI answer is shown only beside one)."""
    from . import agent_review_wording as wording

    return wording.is_opinion(line) and (
        bool(disagreement(line)) or not line_quotes(line)[0]
    )


def is_ai_row(line: Mapping) -> bool:
    """A line that is neither proven by code nor a two-reader verdict: its met / not met is one AI reader's."""
    from . import agent_review_wording as wording

    return line.get("verdict_class") not in (
        wording.CLASS_PROVEN,
        wording.CLASS_TWO_READERS,
    )


def marked(text: object, ai_row: bool = True) -> object:
    """A cell that says met / not met in our own words on an AI row, marked as the AI's ("met (AI, engineer to confirm)"); any other
    text, or a decision's row (`ai_row` False), unchanged."""
    t = " ".join(str(text or "").split())
    return f"{t} {AI_MARK}" if ai_row and t.lower() in _MET_WORDS else text


def disagreement(line: Mapping) -> tuple[str, str] | None:
    """(first, second): the answers of two AI readers who DISAGREED on the line, else None. The second reader said no to the first
    (`agent_run_second.disagreed`), or the independent second reader reached the opposite verdict (`agent_review_two_reader.stored`). A
    second answer cut off by its token limit is not a disagreement in words: it never said the opposite."""
    from . import agent_review_two_reader as two
    from . import agent_run_second

    first = line.get("ai_verdict")
    if first not in ANSWERS:
        return None
    other = FAIL if first == PASS else PASS
    if agent_run_second.disagreed(line.get("second_opinion")):
        return first, other
    second = two.stored(line)
    said = {two.V_MET: PASS, two.V_NOT_MET: FAIL}.get((second or {}).get("verdict"))
    return (first, other) if said == other else None


def label(line: Mapping) -> str | None:
    """THE label of the AI's own answer on one stored line as every reader sees it (after `crs_ai_words.read_now`), or None when the line
    has none to show (see the module words: WHICH LINES)."""
    from . import agent_review_wording as wording
    from . import crs_ai_words as words

    if line.get("source") not in ("rule", "skill"):
        return None
    if words.book_not_held(
        line
    ):  # a rule book not held is never guessed (G7): it stays a question
        return None
    if wording.not_applicable_question(line):
        return NOT_APPLICABLE_LABEL
    answer = line.get("ai_verdict")
    if answer not in ANSWERS or line.get("error"):
        return None
    cls = line.get("verdict_class")
    if cls not in (
        wording.CLASS_OPINION,
        wording.CLASS_UNAPPROVED,
        wording.CLASS_QUERY,
    ):
        return None  # proven by code (plain Pass / Fail), two readers, not applicable, not reviewed, not checked here
    if (
        wording.is_two_reader(line)
        or wording.is_not_checked_here(line)
        or wording.is_not_reviewed(line)
    ):
        return None
    evidence, _looked = line_quotes(line)
    if not evidence:  # no paper quote code verified: no answer is shown as Pass / Fail
        return NO_QUOTE_LABEL
    if got := disagreement(line):  # one reader's answer is never shown as THE answer
        return DISAGREE_LABEL.format(first=got[0], second=got[1])
    return LABEL.format(answer=answer, why=_why(line))


def quote_words(evidence: str | None, looked: str | None = None) -> str:
    """The quote part of the answer line: a quote only when code found it on the page, else "quote not found by code"."""
    if evidence:
        return f'quote: "{evidence}" ({QUOTE_FOUND})'
    if looked:
        return f'quote: "{looked}" ({QUOTE_LOOKED})'
    return QUOTE_NOT_FOUND


def clause_words(line: Mapping) -> str:
    """The clause part of the answer line: the clause the line shows; a clause code moved off the line (`crs_ai_words.
    mark_clause_unconfirmed`, read as a question by `firm_clause` when the line was a firm "not met") says it was not checked or not
    confirmed, with why; else "clause not named"."""
    from . import crs_ai_words as words

    shown = " ".join(str(line.get("clause") or "").split())
    if shown:
        return f"clause {shown}"
    moved = " ".join(str(line.get(words.CLAUSE_UNCONFIRMED_KEY) or "").split())
    if moved:
        from . import firm_clause  # merge round 19a: #1875 moved not_checked_words here; lazy to avoid a cycle

        return (
            firm_clause.not_checked_words(line)
            or f"clause {moved} not confirmed by code: the rule's words are not in it"
        )
    return NO_CLAUSE


def sentence(
    answer_label: str,
    *,
    book: str | None,
    clause: str,
    page: str | None,
    evidence: str | None,
    looked: str | None = None,
    hidden: bool = False,
    linked: bool = False,
) -> str:
    """THE answer line: the label, then the standard, the clause (`clause_words`), the page as printed (`agent_review_crs.page_words`: a
    page hint says so) and the quote (each said, never left out). `hidden`: the viewer may not read the linked rule book (CLAUDE.md rule
    5), so it is neither named nor its clause shown; decided from the viewer's readable books only. `linked`: a held book is linked, so a
    blank name is "rule book name not recorded", never "not shown"."""
    name = " ".join(str(book or "").split())
    book_words = (
        BOOK_HIDDEN if hidden else (name or (BOOK_NO_NAME if linked else NO_BOOK))
    )
    where = ", ".join(
        (
            book_words,
            NO_CLAUSE if hidden else clause,
            f"page {page}" if page else NO_PAGE,
        )
    )
    sep = ". " if answer_label == NO_QUOTE_LABEL else ": "
    return f"{answer_label}{sep}{where}; {quote_words(evidence, looked)}."


def line_quotes(line: Mapping) -> tuple[str | None, str | None]:
    """(evidence, looked) of a stored line, the same split the page makes (`review_points.ai_point`): a paper quote code verified is
    evidence, unless the line says the paper does not state the value (`crs_ai_actions.silent_row`), when it is where the reader looked."""
    from . import crs_ai_actions as actions

    q = line.get("quotes_checked") or {}
    quote = (
        " ".join(str(line.get("paper_quote") or "").split())
        if isinstance(q, Mapping) and q.get("paper")
        else ""
    )
    if not quote:
        return None, None
    if actions.silent_row(line) or actions.absence_proof(line):
        return None, quote
    return quote, None


def line_sentence(line: Mapping) -> str | None:
    """The answer line of a stored line (the AI run's own file), or None when the line has no AI answer to show."""
    from .agent_review_crs import line_page_words

    got = label(line)
    if got is None:
        return None
    evidence, looked = line_quotes(line)
    return sentence(
        got,
        book=line.get("standard"),
        clause=clause_words(line),
        page=line_page_words(line),
        evidence=evidence,
        looked=looked,
        linked=bool(line.get("standard_document_id")),
    )


#: The AI run file's words for a row whose paper quote code did not verify (`crs_ai_workbook._paper_shows`).
NO_VERIFIED_QUOTE = (
    "The AI reviewer holds no verified quote from the paper for this point."
)


def lead(line: Mapping, out: str, status: str, met: bool) -> str:
    """The paper part of an AI run-file row, opened by the AI's own answer (`crs_ai_workbook._paper_shows`): a row of an AI opinion or a
    question with an answer leads with its label (and says "Quote not found by code." in place of the no-verified-quote sentence); an AI
    opinion with no label (a rule book not held) keeps the older words "The AI reviewer's view, not proven: the requirement is ..."."""
    from . import crs_ai_words as words

    answer = label(line) if status in (words.STATUS_AI, words.STATUS_QUERY) else None
    if answer:
        quote = f"{QUOTE_NOT_FOUND[:1].upper()}{QUOTE_NOT_FOUND[1:]}."
        return f"{answer}. {quote if out == NO_VERIFIED_QUOTE else out}"
    if status == words.STATUS_AI:
        return f"{words.AI_VIEW_PREFIX}{'met' if met else 'not met'}. {out}"
    return out


#: The class words of a point with an AI answer (the team file's column "Class"): never the plain "Not met" / "Met" of a decision.
AI_CLASS = "{tile} (AI, engineer to confirm)"


def class_words(tile_words: str, point: Mapping) -> str:
    """THE "Class" cell of a point (`crs_one`): the tile's own words for a point code proved, two readers agreed, a question or a point
    with no AI answer; for a point that shows the AI's own answer (`ai_label`) on the Not met / Met tiles, those words marked as the
    AI's ("Not met (AI, engineer to confirm)"); on a rule not yet approved, its kind ("Rule not yet approved"), never "Does not apply"."""
    if not point.get("ai_label"):
        return tile_words
    if str(point["ai_label"]).startswith("AI readers disagree (first: "):
        return DISAGREE_CLASS
    if point["ai_label"] == NO_QUOTE_LABEL and point.get("tile") in ("not_met", "met"):
        return "Questions for you"  # never reached by a stored line (`is_question`): said as a question if it ever is
    if point.get("tile") in ("not_met", "met"):
        return AI_CLASS.format(tile=tile_words)
    if point.get("rank") == 8 and point.get("other_kind"):
        return str(point["other_kind"])
    return tile_words


def plain_class(text: object) -> str:
    """The tile words a "Class" cell stands for (the scorer's one reading of it): the AI mark taken off."""
    from . import crs_ai_words as words

    t = " ".join(str(text or "").split())
    if t == DISAGREE_CLASS:
        return "Questions for you"  # a disagreement is a question, in both files
    for tile in ("Not met", "Met"):
        if t == AI_CLASS.format(tile=tile):
            return tile
    return (
        "Does not apply" if t == words.KIND_UNAPPROVED else t
    )  # the tile of a rule not yet approved


def is_label(text: object) -> bool:
    """Is `text` (a pill or a cell) one of this module's labels? The scorer reads an AI row back with it, never as a decision."""
    t = " ".join(str(text or "").split())
    return (
        t in (NOT_APPLICABLE_LABEL, NO_QUOTE_LABEL)
        or t.startswith("AI readers disagree (first: ")
        or any(
            t.startswith(LABEL.format(answer=a, why=w)) for a in ANSWERS for w in WHYS
        )
    )


def answer_of(text: object) -> str | None:
    """PASS, FAIL or None: the answer a label carries (the scorer's one reading of it)."""
    t = " ".join(str(text or "").split())
    for a in ANSWERS:
        if is_label(t) and t.startswith(f"{a} (AI, "):
            return a
    return None


def says_met(text: object) -> bool:
    """Does a run-file comment cell carry the AI's own "met" label (the scorer's test of an AI met row: no comment, no pass)?"""
    t = " ".join(str(text or "").split())
    return any(LABEL.format(answer=PASS, why=w) in t for w in WHYS)
