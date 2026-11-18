"""S4b, the whole-paper check of the general review (18 Nov 2026, after live): before a comment that rests on NO held rule book
is sent, the model reads the whole paper once more (cached, as for the judge) and names the comments the paper already answers,
or states the opposite of, on some page. Code checks every answer: the quote is found by code on that page. Such a line stays in
"All points" with the page and the quote (`ANSWERED`, a not-sent note) and is never a comment. Held-standard lines, code
comparisons, provisional figures and values left open are never offered. One call per `ANSWER_CHUNK` lines, each applied whole
or not at all; a failed or cut call applies nothing and the run's calls say so."""

from __future__ import annotations

import logging

from . import ANSWERED, PROVISIONAL
from . import prompts as P
from .engine import StepFailed
from .steps import HELD, _dumps, paper_block
from .verify import quote_in

log = logging.getLogger(__name__)

#: At most this many lines per call (a second call for more; the same step and run meter).
ANSWER_CHUNK = 80
#: Room for the compact answer (only the answered lines: n, page, quote).
ANSWER_MAX_TOKENS = 8000
#: The labels offered: a question or an opinion on no held rule; never a verdict.
OFFERED_LABELS = ("Question", "AI opinion")
#: What the run's calls say when an answer was not applied (no model, no cost).
NOT_APPLIED = "whole-paper check not applied"
#: A quote of the paper as code accepts it: words, at most this many.
QUOTE_WORDS = (3, 40)


def offered(lines: list[dict]) -> dict[int, dict]:
    """{line number: line} of the SENT lines the check may take off: no held standard, a Question or an AI opinion, not compared
    by code, no provisional figure, no value left open."""
    from . import sendable
    from .engine import to_line

    out = {}
    for n, d in enumerate(lines, 1):
        parts = [x.strip() for x in str(d.get("code") or "").split(";")]
        if (
            sendable(to_line(n, d))
            and d.get("source") != HELD
            and d.get("label") in OFFERED_LABELS
            and not d.get("code_compare")
            and not d.get("deferred")
            and not any(x.startswith(PROVISIONAL) for x in parts)
        ):
            out[n] = d
    return out


def s4b_answered(model, paper, lines: list[dict], lead: str) -> int:
    """The whole-paper check on the offered lines (`offered`), in calls of at most `ANSWER_CHUNK` lines. Returns the number of
    lines taken off."""
    pool = offered(lines)
    keys = list(pool)
    parts = [keys[i : i + ANSWER_CHUNK] for i in range(0, len(keys), ANSWER_CHUNK)]
    taken = 0
    for part in parts:
        shown = {n: pool[n] for n in part}
        out = _ask(model, paper, shown, lead)
        if out is not None:
            taken += _apply(out, shown, paper)
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
            carries={paper.paper_id},
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
    is `QUOTE_WORDS` words long and is found by code on THAT page. The note words, or None (refused: the line stays sent)."""
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
    return f'{ANSWERED}: the paper answers it on page {page}: "{quote[:300]}"'


def _apply(out: dict, shown: dict, paper) -> int:
    """One call's answer, whole: each accepted answer adds the not-sent note to its line (once)."""
    answers = out.get("answered")
    taken = 0
    for a in answers if isinstance(answers, list) else []:
        why = answer_reason(a, shown, paper) if isinstance(a, dict) else None
        if why:
            d = shown.pop(a["n"])
            d["code"] = "; ".join(x for x in (d.get("code"), why) if x)
            taken += 1
    return taken
