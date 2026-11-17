"""Order 14 live proof LP1 (17 Nov 2026): a FIRM "not met" never stands without a clause code checked.

A firm "not met" (proven by code, two AI readers agree, or one AI reader's "not met") cites the clause of the rule book it rests on
(CLAUDE.md rule 4: no claim without a resolving citation; gate G5). When the line shows no clause - the clause it carried was moved
off because code did not confirm it or could not check it (`crs_ai_words.mark_clause_unconfirmed`), the rule book is not held, or
it never named one - the line is a QUESTION for the engineer with its reason, never a firm row with no clause. It only makes a line
less confident; a "met" is left as it is (made a question it would become a new comment row). Applied once, at the one reading of
stored lines (`crs_ai_words.read_now`), and honoured by `agent_review_wording.classify` (`held_class`), so every reader of the line
(page, run file, team file, counts, gates) sees the same question. Pure: no model, no network."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

#: The key a held line carries: the reason the engineer reads (the words of `WHY`).
HELD_KEY = "firm_without_clause"
WHY = (
    "{cause}; a firm finding needs a clause code checked, so this line ({was}) is a question: the engineer confirms the clause "
    "before it is a finding"
)
NO_CLAUSE = "the finding names no clause of the rule book"
NOT_HELD = "the rule book is not held"


def _was() -> dict[int, str]:
    """The firm "not met" row orders of the run file (`crs_ai_words`) -> what the line said."""
    from . import crs_ai_words as words

    return {
        words.ORDER_FAIL: "not met, proven by code",
        words.ORDER_AI_VERDICT_NOT_MET: "not met, two AI readers agree",
        words.ORDER_AI_NOT_MET: "not met in the AI reviewer's view",
    }


def not_checked_words(line: Mapping) -> str:
    """The words a line marked "not checked" (`crs_ai_words.mark_clause_unconfirmed`) shows after its book's page; "" for any other
    line. Moved here from `crs_ai_words` (LP1, to keep that file within 800 lines); read by `cause` and `agent_review_crs.against`."""
    from . import crs_ai_words as words
    from .agent_review_standards import CLAUSE_BEFORE

    doubt = line.get(words.CLAUSE_UNCHECKED_KEY)
    if not doubt:
        return ""
    said = (
        words.CLAUSE_NOT_CHECKED_BEFORE
        if doubt == CLAUSE_BEFORE
        else words.CLAUSE_NOT_CHECKED
    )
    return said.format(clause=line.get(words.CLAUSE_UNCONFIRMED_KEY) or "")


def cause(line: Mapping) -> str:
    """Why the line shows no clause, or "" when it shows one (a book not held never shows its clause: `crs_ai_words.mark_not_held`)."""
    from . import crs_ai_words as words

    if line.get(words.NOT_HELD_KEY):
        return NOT_HELD
    if " ".join(str(line.get("clause") or "").split()):
        return ""
    moved = " ".join(str(line.get(words.CLAUSE_UNCONFIRMED_KEY) or "").split())
    if not moved:
        return NO_CLAUSE
    return not_checked_words(line) or words.CLAUSE_NOT_CONFIRMED.replace(
        "clause", f"clause {moved}", 1
    )


def held_class(line: Mapping) -> dict | None:
    """The class `agent_review_wording.classify` gives a held line (a question with the held reason); None for any other line."""
    why = line.get(HELD_KEY)
    if not why:
        return None
    from .agent_review_wording import CLASS_QUERY, WORD_QUERY

    return {
        "verdict_label": WORD_QUERY,
        "verdict_class": CLASS_QUERY,
        "not_proven_reason": str(why),
    }


def held_count(lines: Iterable[Mapping]) -> int:
    """How many of the lines are held as a question by `hold` (the run summary's own group, LP1)."""
    return sum(1 for ln in lines if ln.get(HELD_KEY))


def hold(lines: Iterable[Mapping]) -> list[dict]:
    """The lines with every firm "not met" that shows no clause made a question (`HELD_KEY` holds the reason; a proven Fail's verdict
    becomes Query, decided by the engineer, as `crs_ai_words._proven_not_held` does). Every other line unchanged. Idempotent."""
    from .agent_review_verdict import BY_ENGINEER, FAIL, PASS, QUERY
    from .crs_ai_workbook import status_of

    was_of = _was()
    out = []
    for ln in lines:
        got = None if ln.get(HELD_KEY) else status_of(ln)
        why = cause(ln) if got is not None and got[1] in was_of else ""
        if not why:
            out.append(dict(ln))
            continue
        held = {**ln, HELD_KEY: WHY.format(cause=why, was=was_of[got[1]])}
        if held.get("verdict") in (PASS, FAIL):
            held.update(verdict=QUERY, decided_by=BY_ENGINEER)
        out.append({**held, **held_class(held)})
    return out
