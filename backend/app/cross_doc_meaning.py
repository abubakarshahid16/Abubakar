"""THE CROSS-DOCUMENT CHECK, LANE 2: MEANING MISMATCHES FOUND BY AI, SHOWN ONLY AS A QUESTION TO THE ENGINEER (order 14, planner
25 Nov 2026 23:35 (b) item 1; builder H). OFF by default (CROSS_DOC_MEANING_ENABLED).

WHAT IS ASKED. The pairs lane 1 cannot decide by code (`cross_doc.pairs`): one field of one tag that the paper and another
readable paper naming the tag both state, where at least one value is words and code cannot settle it: words that differ as words
("carbon steel" / "CS"), or a number against words. Two numbers are NEVER asked, whatever code decided: numbers are compared by
code, not by the AI, and a pair code refused (gauge against absolute, units of different quantities) stays refused.

THE MODEL. Only the local model, through the app's one local transport (`reasoning_provider.OllamaProvider` ->
`model_transport`): nothing leaves the machine and no new outbound path exists. The model is this lane's own setting
(CROSS_DOC_MEANING_MODEL, a 14B-class model by default; a 35B-class name is refused, owner 25 Nov 2026). The answer's shape is
forced by a JSON schema and checked by code. A Claude-lane run bars the local engine (`local_engine_bar`): then nothing is asked
and the run says so. Claude is not wired here: that would be a new step on the Claude lane and needs its own line in rule 1.

WHAT IS SHOWN. A pair the model calls a conflict becomes a Question to the ENGINEER: on "All points" only, never sent to the
contractor (`aim_review.ENGINEER_QUESTION`), never Pass or Fail. Both quotes are found by code on their own pages before the
question is written; a pair whose quote code cannot find is not asked. The comment holds only the two papers' own words, pages
and a plain question; the model's reason and its name are in the team-only note (the AI mark, `aim_review_gate.AI_MARK`). A pair the model calls
the same, or cannot tell, is no line. When the model did not answer, ONE line on "All points" says the check was not run and why
(`aim_review.NOT_JUDGED`): a failed AI step is shown, never silent. Rule 5 as lane 1: the other paper's name and words are hidden
from a viewer who may not open it.
"""

from __future__ import annotations

import json
import logging

from . import cross_doc, tag_cross
from .aim_review_gate import AI_MARK

log = logging.getLogger(__name__)

ITEM_ID = "X3"
TOPIC = "cross-document check: meaning"
SOURCE = f"the papers of one package against each other ({AI_MARK})"
NOTE_MEANING = f"{tag_cross.NOTE}: meaning"
NOTE_NOT_RUN = f"{tag_cross.NOTE}: meaning not run"
STEP = "cross-doc-meaning"
PROMPT_VERSION = "h1"
#: At most this many pairs per review, and per call (a 14B-class model's context holds a batch whole: no blind cutting).
MAX_PAIRS = 40
BATCH = 10
NUM_CTX = 8192
NUM_PREDICT = 1500
VERDICTS = ("conflict", "same", "unclear")

SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "why": {"type": "string"},
                },
                "required": ["n", "verdict", "why"],
            },
        }
    },
    "required": ["answers"],
}

SYSTEM = (
    "You compare statements about ONE equipment item taken from two papers of the same project. For each numbered pair, say "
    'whether the two statements say the same thing ("same"), say things that cannot both be true for that item ("conflict"), '
    'or you cannot tell from the words alone ("unclear"). An abbreviation, a synonym, a more specific grade of the same thing, '
    'or a value with more detail is "same". Answer only from the two statements; do not guess. Give a one-sentence reason in '
    'plain words for each. Answer as JSON: {"answers": [{"n": 1, "verdict": "conflict", "why": "..."}]}.'
)


def lane_on() -> bool:
    from .config import settings

    return bool(getattr(settings, "cross_doc_meaning_enabled", False))


def model_name() -> str:
    from .config import settings

    return str(getattr(settings, "cross_doc_meaning_model", "") or "").strip()


class NotRun(Exception):
    """The model did not give a usable answer: the plain reason (never document text)."""


def _provider():
    name = model_name()
    if not name:
        raise NotRun("no local model is set for this check")
    if "35b" in name.lower():
        raise NotRun("the 35B model is not used (owner, 25 Nov 2026)")
    from .reasoning_provider import OllamaProvider

    return OllamaProvider(name, timeout=900.0)


def candidates(
    found: list[cross_doc.Pair], pages: dict[str, dict[int, str]]
) -> list[cross_doc.Pair]:
    """The pairs code cannot decide (see the module note), both quotes found by code on their pages, at most MAX_PAIRS."""
    out = []
    for p in found:
        if p.verdict == "agree" or p.numeric:
            continue  # two numbers are code's, whatever code decided (gauge against absolute is never compared, nor guessed)
        a, b = p.mine, p.theirs
        if cross_doc.proven(
            a.quote, a.page, pages.get(a.doc_id, {})
        ) and cross_doc.proven(b.quote, b.page, pages.get(b.doc_id, {})):
            out.append(p)
    return out[:MAX_PAIRS]


def _prompt(batch: list[cross_doc.Pair]) -> str:
    rows = []
    for n, p in enumerate(batch, 1):
        rows.append(
            f'{n}. Item {p.mine.tag}, {p.mine.field}.\n   Paper 1 says: "{p.mine.quote}"\n   Paper 2 says: "{p.theirs.quote}"'
        )
    return "Pairs:\n" + "\n".join(rows)


def ask(
    provider, batch: list[cross_doc.Pair]
) -> tuple[dict[int, tuple[str, str]], str]:
    """({pair number: (verdict, why)}, the model the engine reported) from one call. Raises NotRun on any refusal, a cut answer or a broken shape."""
    from .reasoning_provider import Packet, ProviderRefused

    packet = Packet(
        prompt=_prompt(batch),
        system=SYSTEM,
        num_ctx=NUM_CTX,
        num_predict=NUM_PREDICT,
        json_schema=SCHEMA,
        step=STEP,
        prompt_version=PROMPT_VERSION,
    )
    try:
        resp = provider.reason(packet)
    except ProviderRefused as exc:
        raise NotRun(f"the local model did not answer ({type(exc).__name__})") from None
    if resp.truncated:
        raise NotRun("the local model's answer was cut off at its limit")
    if resp.schema_errors:
        raise NotRun("the local model's answer had the wrong shape")
    try:
        answers = json.loads(resp.text).get("answers") or []
    except (ValueError, AttributeError):
        raise NotRun("the local model's answer was not JSON") from None
    out: dict[int, tuple[str, str]] = {}
    for a in answers:
        n, verdict = a.get("n"), str(a.get("verdict") or "")
        if (
            isinstance(n, int)
            and 1 <= n <= len(batch)
            and verdict in VERDICTS
            and n not in out
        ):
            out[n] = (
                verdict,
                " ".join(str(a.get("why") or "").replace(";", ",").split()),
            )
    return out, resp.model_tag


def _row(
    n: int,
    start: int,
    *,
    field: str,
    page,
    quote: str,
    comment: str,
    note: str,
    named: list,
) -> dict:
    return {
        "line_no": start + n,
        "item_id": ITEM_ID,
        "finding_no": n,
        "label": "Question",
        "field": field,
        "page": page,
        "quote": quote,
        "quote_unverified": "",
        "comment": " ".join(comment.split()),
        "standard": "",
        "book_document_id": "",
        "clause": "",
        "source": SOURCE,
        "topic": TOPIC,
        "code_note": note,
        "numbers_json": None,
        "named_books_json": json.dumps(named, ensure_ascii=False) if named else None,
        "code_compare_json": None,
        "deferred": False,
        "ask": "concern",
    }


def lines(
    conn, paper_id: str, readable: frozenset[str], start: int = 0, *, provider=None
) -> list[dict]:
    """Lane 2's lines for the paper (`engine.to_line` columns), numbered from `start` + 1. `provider`: tests pass a fake."""
    from . import aim_review

    found, _hidden, pages = cross_doc.pairs(conn, paper_id, frozenset(readable))
    asked = candidates(found, pages)
    if not asked:
        return []
    out: list[dict] = []
    done = 0  # pairs the model answered
    try:
        provider = provider if provider is not None else _provider()
        for i in range(0, len(asked), BATCH):
            batch = asked[i : i + BATCH]
            answers, model = ask(provider, batch)
            for n, p in enumerate(batch, 1):
                verdict, why = answers.get(n, ("", ""))
                if verdict != "conflict":
                    continue
                a, b = p.mine, p.theirs
                name = tag_cross._title(conn, b.doc_id)
                comment = (
                    f'For {a.tag}, this paper states "{a.quote}" (page {a.page}), and {name} states "{b.quote}" '
                    f"(page {b.page}). Engineer to check: do the two papers describe the same {a.field}?"
                )
                note = f"{NOTE_MEANING} {a.tag}; {aim_review.ENGINEER_QUESTION}: {AI_MARK} ({model}): {why}"
                out.append(
                    _row(
                        len(out) + 1,
                        start,
                        field=a.field,
                        page=a.page,
                        quote=a.quote,
                        comment=comment,
                        note=note,
                        named=[{"id": b.doc_id, "name": name}],
                    )
                )
            done += len(batch)
    except NotRun as exc:
        log.warning("cross-document meaning check not run: %s", exc)
        left = len(asked) - done
        out.append(
            _row(
                len(out) + 1,
                start,
                field="cross-document meaning check",
                page=None,
                quote="",
                comment=f"The cross-document meaning check of {left} of {len(asked)} pair{'s' if len(asked) != 1 else ''} "
                f"was not run: {exc}. Engineer to check these papers against each other by hand.",
                note=f"{NOTE_NOT_RUN}; {aim_review.NOT_JUDGED}: {exc}",
                named=[],
            )
        )
    return out
