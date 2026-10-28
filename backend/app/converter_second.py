"""The converter's second question - "ask twice" (order 305.4).

Tonight's hand check found 8 of 8 converter "verified" rows unsafe: the model read one sentence once and missed
a hidden "only if". A row the first pass verified is now asked about AGAIN, in a differently worded question that
looks at the limit from the other side: not "which field and which number" but "does it hold for EVERY device,
or only when something is true?". CODE then compares the two answers; the model decides nothing.

A row stays `verified` only if (a) the second reply is readable, (b) it agrees with the first answer about the
condition (no condition = holds always; a condition = holds only then), (c) when there is a condition both name
the same words, and (d) every condition the model quotes is found word for word in the stored clause. Anything
else is `unproven` with a named reason. The gate removes disagreements and unquoted conditions; it does not
prove a rule (the same model can be wrong twice), so the hand check stays.

Only rows the first pass verified are asked (a handful per standard), on the lane the first pass used.
Pure functions: no database, no network.
"""

from __future__ import annotations

import json

from .converter_gates import fold

PROMPT_VERSION = "o305-ask-twice-v1"
UNREADABLE = "second_answer_unreadable"
DISAGREES = "second_answer_disagrees"
NOT_QUOTED = "second_condition_not_quoted"
REASONS = (UNREADABLE, DISAGREES, NOT_QUOTED)

SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "always": {"type": ["boolean", "null"]},
                    "only_when": {"type": ["string", "null"]},
                    "quote": {"type": ["string", "null"]},
                },
                "required": ["i"],
            },
        }
    },
    "required": ["checks"],
}


def system_text(equipment_type: str) -> str:
    return (
        f"You read sentences of an engineering STANDARD about a {equipment_type}. Each item has a sentence "
        "and a numeric limit already found in it. Answer ONE question per item: does this limit hold for "
        "EVERY such device without exception, or only when something is true (a kind of device, a "
        "service, a part, a case, an example)?\n"
        "Answer per item: i (the item number), always (true when the limit holds for every device with no "
        "'only if' of any kind, false when it holds only in some case), only_when (the words of the "
        "sentence that say when, or null when always is true), quote (those words copied exactly, "
        "or null). Never invent words: quote only what the sentence says. Unsure is a good answer: "
        "answer always null."
    )


def packet(pairs: list[tuple[dict, dict]], equipment_type: str, step: str):
    """One batch for the second question: (stored requirement, first-pass row) pairs. The clause and sentence
    are standards text, the same text the first pass sent; the limit is shown so the question is about it."""
    from .reasoning_provider import Packet

    items = [
        {
            "i": n,
            "clause": src.get("clause") or "",
            "text": " ".join((src.get("requirement_text") or "").split())[:1200],
            "limit": f"{row.get('limit')} {row.get('unit') or ''}".strip(),
        }
        for n, (src, row) in enumerate(pairs)
    ]
    return Packet(
        prompt=json.dumps({"items": items}, ensure_ascii=False),
        num_ctx=16384,
        num_predict=200 * len(pairs) + 300,
        json_schema=SCHEMA,
        system=system_text(equipment_type),
        step=step,
        prompt_version=PROMPT_VERSION,
    )


def _same_words(first: str, second: str) -> bool:
    a, b = fold(first), fold(second)
    return bool(a and b) and (a == b or a in b or b in a)


def judge(
    first_condition: str | None, answer: dict | None, sentence: str
) -> tuple[bool, str | None]:
    """(agrees, reason). `first_condition` is the first pass's condition (the clause's own scope words) or None."""
    if answer is None or not isinstance(answer.get("always"), bool):
        return False, UNREADABLE
    only_when = (answer.get("only_when") or "").strip()
    quote = (answer.get("quote") or "").strip()
    first = fold(first_condition)
    if answer["always"]:
        # "holds for every device" cannot stand beside a condition, from either answer
        return (False, DISAGREES) if first or only_when else (True, None)
    if not only_when or not first:
        return False, DISAGREES  # one answer sees a condition the other does not
    if (
        not quote
        or fold(quote) not in fold(sentence)
        or fold(only_when) not in fold(sentence)
    ):
        return False, NOT_QUOTED
    if not _same_words(first, only_when):
        return False, DISAGREES
    return True, None


def record(answer: dict | None) -> dict:
    """What the draft file keeps of the second answer (words of the clause, never anything else)."""
    answer = answer or {}
    return {
        "always": answer.get("always")
        if isinstance(answer.get("always"), bool)
        else None,
        "only_when": (answer.get("only_when") or None),
        "quote": (answer.get("quote") or None),
    }


def downgrade(row: dict, reason: str, note: str) -> None:
    """A verified row the second question did not confirm: unproven, no limit, the engineer looks."""
    row.update(status="unproven", reason=reason, note=note, applies=None)
    row.update(
        dict.fromkeys(("condition", "field", "comparator", "limit", "unit", "quote"))
    )


def ask_again(pairs, equipment_type, step, size, ask, parse, text_of, note) -> None:
    """The second question for every (stored requirement, row) pair the first pass verified, in batches of `size`.
    `ask(packet)` returns the reply or None (refused, failed); `parse(reply, n)` the answers by item number or None.
    Code compares (`judge`); the rows are changed in place."""
    todo = [(s, r) for s, r in pairs if r["status"] == "verified"]
    for start in range(0, len(todo), size):
        chunk = todo[start : start + size]
        reply = ask(packet(chunk, equipment_type, step))
        answers = parse(reply, len(chunk)) if reply is not None else None
        for n, (src, row) in enumerate(chunk):
            got = (answers or {}).get(n)
            agrees, why = judge(row.get("condition"), got, text_of(src))
            if agrees:
                row.update(asked_twice=True, second=record(got))
            else:
                downgrade(row, why, note)
