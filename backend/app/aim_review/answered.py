"""S4b, the whole-paper check of the general review (18 Nov 2026, after live; v3 the same night): after the second reader, every
sent line the AI alone decided (a Question, an AI opinion or a Not met, on a held rule or none) goes to the model with the whole
paper (cached, as for the judge), which checks each CLAIM of the comment that the paper lacks, leaves blank or only says
something, and each request, on every page (v2 asked whether the paper answers the WHOLE comment: a comment with one false claim
beside a right one was never answered, so nothing was taken off). Code checks every answer: the quote is found by code on that
page and is not the line's own evidence. Such a line stays in "All points" with the claim, the page and the quote (`ANSWERED`, a
not-sent note: an engineer checks it) and is never a comment. Code comparisons, provisional figures, values left open and lines
a reference paper checked are never offered. One call per `ANSWER_CHUNK` lines, each applied whole
or not at all; a failed or cut call applies nothing and the run's calls say so."""

from __future__ import annotations

import logging
import re

from . import ANSWERED, PROVISIONAL
from . import prompts as P
from .engine import StepFailed
from .references import NOTE_CHECKED as REFERENCE_CHECKED
from .steps import _dumps, paper_block
from .verify import norm, quote_in

log = logging.getLogger(__name__)

#: At most this many lines per call (a second call for more; the same step and run meter).
ANSWER_CHUNK = 80
#: Room for the compact answer (only the answered lines: n, page, quote).
ANSWER_MAX_TOKENS = 8000
#: The labels offered: what the AI alone decided (a code comparison is never offered).
OFFERED_LABELS = ("Question", "AI opinion", "Not met")
#: What the run's calls say when an answer was not applied (no model, no cost).
NOT_APPLIED = "whole-paper check not applied"
#: A claim that the paper LACKS a value or only says something: the line's own quote, holding that value on its own page, does
#: disprove it (valve copy of 18 Nov: the second reader said a filled row was blank; the only proof was the line's own quote).
ABSENCE = re.compile(
    r"\b(blank|empty|no value|has no|not (?:stated|given|shown|specified|provided|filled)|missing|left (?:blank|empty|open)|"
    r"only|lacks?|absent)\b",
    re.IGNORECASE,
)
#: A quote of the paper as code accepts it: words, at most this many.
QUOTE_WORDS = (3, 40)


def offered(lines: list[dict]) -> dict[int, dict]:
    """{line number: line} of the SENT lines the check may take off: a Question, an AI opinion or a Not met (any source), not
    compared by code, no provisional figure, no value left open, not checked against a reference paper."""
    from . import sendable
    from .engine import to_line

    out = {}
    for n, d in enumerate(lines, 1):
        parts = [x.strip() for x in str(d.get("code") or "").split(";")]
        if (
            sendable(to_line(n, d))
            and d.get("label") in OFFERED_LABELS
            and not d.get("code_compare")
            and not d.get("deferred")
            and not any(x.startswith(PROVISIONAL) for x in parts)
            # a line a reference paper checked rests on that paper, which this step never reads (the Schedule of the package)
            and not any(x.startswith(REFERENCE_CHECKED) for x in parts)
        ):
            out[n] = d
    return out


def s4b_answered(
    model, paper, lines: list[dict], lead: str, record: list | None = None
) -> int:
    """The whole-paper check on the offered lines (`offered`), in calls of at most `ANSWER_CHUNK` lines. Returns the number of
    lines taken off. `record` (the run's own list) gets every verdict as answered and what code did with it (`_recorded`): the
    local run record keeps it so a miss can be read later; it is never sent and never shown to a contractor."""
    pool = offered(lines)
    keys = list(pool)
    parts = [keys[i : i + ANSWER_CHUNK] for i in range(0, len(keys), ANSWER_CHUNK)]
    taken = 0
    for part in parts:
        shown = {n: pool[n] for n in part}
        out = _ask(model, paper, shown, lead)
        if out is None and record is not None:
            record.append({"lines": sorted(shown), "not_applied": True})
        if out is not None:
            taken += _apply(out, shown, paper, record)
    return taken


def _ask(model, paper, shown: dict, lead: str) -> dict | None:
    rows = [{"n": n, "field": d.get("field") or "", "page": d.get("page"), "comment": d.get("comment") or ""}
            for n, d in shown.items()]  # fmt: skip
    try:
        out = model.ask(
            step="aim_answered",
            model=lead,
            system="",
            cached=paper_block(paper),
            prompt=P.ANSWERED_TASK % {"comments": "\n".join(_dumps(x) for x in rows)},
            carries=_carries(paper, shown),
            max_tokens=ANSWER_MAX_TOKENS,
        )
    except (
        StepFailed
    ) as exc:  # nothing of a failed or cut answer is applied; the run's calls say why
        code = str(exc).split(":", 1)[-1].strip().split(" ", 1)[0]
        _note(
            model,
            f"{NOT_APPLIED}: {'answer too long' if code == 'stop_max_tokens' else code}",
        )
        log.info("general review: the whole-paper check was not applied (%s)", code)
        return None
    return out if isinstance(out, dict) else None


def _carries(paper, shown: dict) -> set[str]:
    """The paper and every book whose words the shown lines hold (their rule book, the books an always-on line names)."""
    out = {paper.paper_id}
    for d in shown.values():
        out |= {str(d["book_document_id"])} if d.get("book_document_id") else set()
        out |= {
            str(b.get("id"))
            for b in d.get("named_books") or []
            if isinstance(b, dict) and b.get("id")
        }
    return out


def _note(model, words: str) -> None:
    from .engine import CallRecord

    meter = getattr(model, "meter", None)
    if meter is not None and hasattr(meter, "calls"):
        meter.calls.append(
            CallRecord(
                step="aim_answered", model="code", prompt_chars=0, ok=False, code=words
            )
        )


def answer_reason(a: dict, shown: dict, paper) -> str | None:
    """Code's check of ONE answer: the line was offered in this call; the page is a page of the paper; the quote has no "..." part,
    is `QUOTE_WORDS` words long and is found by code on THAT page; and it is not the line's own evidence (on the line's own page,
    holding or held in the line's own quote). The note words, or None (refused: the line stays sent)."""
    n, page, quote = a.get("n"), a.get("page"), str(a.get("quote") or "").strip()
    if not isinstance(n, int) or isinstance(n, bool) or n not in shown:
        return None
    if not isinstance(page, int) or isinstance(page, bool) or page not in paper.pages:
        return None
    words = len(quote.split())
    if "..." in quote or "…" in quote or not QUOTE_WORDS[0] <= words <= QUOTE_WORDS[1]:
        return None
    if not quote_in(quote, paper.pages.get(page, "")):
        return None
    own, said = norm(str(shown[n].get("quote") or "")), norm(quote)
    claim = " ".join(str(a.get("claim") or "").split())[:120]
    if (
        page == shown[n].get("page")
        and own
        and (own in said or said in own)
        and not ABSENCE.search(claim)
    ):
        return None  # the line's own evidence (its quote, on its own page) is no answer: a value conflict is never dropped
    what = f'what it says ("{claim}")' if claim else "it"
    return f'{ANSWERED}: the paper covers {what} on page {page}: "{quote[:300]}"; an engineer to check'


def _apply(out: dict, shown: dict, paper, record: list | None = None) -> int:
    """One call's answer, whole: each accepted answer adds the not-sent note to its line (once)."""
    verdicts = out.get("verdicts")
    taken = 0
    for a in (
        verdicts if isinstance(verdicts, list) else []
    ):  # one verdict per comment; only "answered": true is checked
        why = (
            answer_reason(a, shown, paper)
            if isinstance(a, dict) and a.get("answered") is True
            else None
        )
        if record is not None and isinstance(a, dict):
            record.append(_recorded(a, bool(why)))
        if why:
            d = shown.pop(a["n"])
            d["code"] = "; ".join(x for x in (d.get("code"), why) if x)
            taken += 1
    return taken


def _recorded(a: dict, taken: bool) -> dict:
    """One verdict as the local run record keeps it: the line, the answer, the claim, page and quote it gave (paper words, cut to
    300 characters with no mark: a record for the team, never a sheet) and whether code took the line off."""
    return {
        "n": a.get("n") if isinstance(a.get("n"), int) else None,
        "answered": a.get("answered") if isinstance(a.get("answered"), bool) else None,
        "claim": " ".join(str(a.get("claim") or "").split())[:120],
        "page": a.get("page") if isinstance(a.get("page"), int) else None,
        "quote": str(a.get("quote") or "")[:300],
        "taken_off": taken,
    }
