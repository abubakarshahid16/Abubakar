"""S4c, the second reader (owner's top rule: "a second model attacks"; 18 Nov 2026 after live: one checklist judged twice flipped
31% of its items, mostly AI opinion <-> Question). Before a FINDING the AI alone decided is sent (Not met, AI opinion: nothing
code compared), a second reader judges the same item at the same place BLIND: it sees the checklist item, the clause words, the
field and the page, never the first reader's label or comment. Code decides:
  agree    = the second reader also finds a fault (Not met or AI opinion) and its quote is found by code on a page of the paper;
             the line is sent as it is, with the note `TWO_READERS_AGREE`;
  disagree = anything else (another label, no answer for the line, a quote code cannot find): the line is sent as a QUESTION to
             be checked, with BOTH readers' words, and the note `READERS_DIFFER`; never dropped (no find is lost), never Met.
A comparison by code (any result), a Question and a Met are never offered. One call per `READ_CHUNK` lines, the paper cached as for
the judge; each call applied whole or not at all (a failed call changes nothing and the run's calls say so)."""

from __future__ import annotations

import logging

from app.crs_completeness import CUT_MARK

from . import PROVISIONAL, READERS_DIFFER, TWO_READERS_AGREE
from . import prompts as P
from .engine import StepFailed
from .references import NOTE_CHECKED as REFERENCE_CHECKED
from .steps import _dumps, paper_block
from .verify import quote_in

log = logging.getLogger(__name__)

#: The labels of a finding the AI alone decided: these need a second reader before they are sent.
OFFERED_LABELS = ("Not met", "AI opinion")
#: A second reader's label that agrees there is a fault.
FAULT = frozenset({"Not met", "AI opinion"})
READ_CHUNK = 60
#: A differing line's words at most this long; a longer text is cut WITH the cut mark (the first reader's words stay on the line).
COMMENT_MAX = 900
READ_MAX_TOKENS = 8000
NOT_APPLIED = "second reader not applied"


def offered(lines: list[dict]) -> dict[int, dict]:
    """{line number: line} of the SENT findings the AI alone decided: Not met or AI opinion, nothing compared by code, no
    provisional figure, the value not left open."""
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


def s4c_second_read(model, paper, lines: list[dict], checklist: dict, lead: str) -> int:
    """The second reader on the offered lines (`offered`), in calls of at most `READ_CHUNK`. Returns the number that disagree."""
    pool = offered(lines)
    items = {
        it.get("id"): it
        for it in (checklist or {}).get("items") or []
        if isinstance(it, dict)
    }
    keys = list(pool)
    differ = 0
    for part in (keys[i : i + READ_CHUNK] for i in range(0, len(keys), READ_CHUNK)):
        shown = {n: pool[n] for n in part}
        out = _ask(model, paper, shown, items, lead)
        if out is not None:
            differ += _apply(out, shown, paper)
    return differ


def _row(n: int, d: dict, items: dict) -> dict:
    it = items.get(d.get("item_id")) or {}
    return {"n": n, "topic": it.get("topic") or d.get("topic") or "", "what_to_check": it.get("what_to_check") or "",
            "standard": d.get("standard") or "", "clause": d.get("clause") or "", "rule_quote": it.get("rule_quote") or "",
            "field": d.get("field") or "", "page": d.get("page")}  # fmt: skip


def _ask(model, paper, shown: dict, items: dict, lead: str) -> dict | None:
    carries = {paper.paper_id} | {
        str(d["book_document_id"]) for d in shown.values() if d.get("book_document_id")
    }
    try:
        out = model.ask(
            step="aim_second_read",
            model=lead,
            system="",
            cached=paper_block(paper),
            prompt=P.SECOND_READ_TASK
            % {"items": "\n".join(_dumps(_row(n, d, items)) for n, d in shown.items())},
            carries=carries,
            max_tokens=READ_MAX_TOKENS,
        )
    except (
        StepFailed
    ) as exc:  # nothing of a failed answer is applied; the run's calls say why
        code = str(exc).split(":", 1)[-1].strip().split(" ", 1)[0]
        _note(model, f"{NOT_APPLIED}: {code}")
        log.info("general review: the second reader was not applied (%s)", code)
        return None
    return out if isinstance(out, dict) else None


def _note(model, words: str) -> None:
    from .engine import CallRecord

    meter = getattr(model, "meter", None)
    if meter is not None and hasattr(meter, "calls"):
        meter.calls.append(
            CallRecord(
                step="aim_second_read",
                model="code",
                prompt_chars=0,
                ok=False,
                code=words,
            )
        )


def agrees(read: dict | None, paper) -> bool:
    """The second reader also finds a fault, on a quote code finds on the page it names (else on any page)."""
    if not isinstance(read, dict) or read.get("label") not in FAULT:
        return False
    quote, page = str(read.get("quote") or ""), read.get("page")
    if not quote.strip() or "..." in quote:
        return False
    if (
        isinstance(page, int)
        and not isinstance(page, bool)
        and quote_in(quote, paper.pages.get(page, ""))
    ):
        return True
    return any(quote_in(quote, t) for t in paper.pages.values())


def _apply(out: dict, shown: dict, paper) -> int:
    """One call's answer, whole: every offered line gets a verdict (a line with no answer counts as a disagreement)."""
    reads = {r.get("n"): r for r in out.get("reads") or [] if isinstance(r, dict)}
    differ = 0
    for n, d in shown.items():
        read = reads.get(n)
        if agrees(read, paper):
            d["code"] = "; ".join(x for x in (d.get("code"), TWO_READERS_AGREE) if x)
            continue
        second = str((read or {}).get("label") or "no answer")
        why = str((read or {}).get("reason") or "")[:200]
        first = d.get("label") or ""
        words = (f"To be checked: the two readers differ. First reader ({first}): {d.get('comment') or ''} "
                 f"Second reader ({second}): {why or 'no reason given'}")  # fmt: skip
        d["comment"] = (
            words if len(words) <= COMMENT_MAX else words[: COMMENT_MAX - 1] + CUT_MARK
        )  # a cut is marked
        d["code"] = "; ".join(
            x
            for x in (
                d.get("code"),
                f"{READERS_DIFFER}: first {first}, second {second}",
            )
            if x
        )
        d["label"] = "Question"  # never dropped, never a verdict
        differ += 1
    return differ
