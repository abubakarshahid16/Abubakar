"""The three ALWAYS-ON items of every general review (the lead, 18 Nov 2026): what a senior engineer checks on any paper, whatever
its kind or type, that a checklist built from rule books does not ask.

  G1 cited standards: is every standard the paper names the right one, and its edition the current one?
  G2 internal consistency: do the paper's own values agree with each other?
  G3 required entries: does the paper leave blank or omit an entry this review's checklist requires?

They are METHOD items, not read from the paper: the same three on every review (the fair rule holds). They are added when the paper
is judged, never stored with a type's saved checklist (so a saved checklist and its sha are unchanged). Each goes through the same
S4 judge and `steps._decide` as any other item, one finding per place. They are "not from a held standard", so they are never Met or
Not met; G2's numbers are compared by code as two values of the paper (`steps._paper_numbers`), never "compared by code"; a blank
entry is a Question by `blank_markers`. The words describe the KIND of check only: no field, type or standard name is in this code.

The facts given with G1 are the app's own: the standards the paper cites (`cited_edition.cited_years`, names and years only), which
of them are books on this review's list and the edition their file name or title prints (`cited_edition.held_year`), and the
standards the app's governing table names for the paper's type. A held book that is not on the list is never named.
"""

from __future__ import annotations

import logging

from .steps import KNOWLEDGE, item_book

log = logging.getLogger(__name__)

TOPIC = "always checked"
IDS = ("G1", "G2", "G3")

G1_CHECK = (
    "Every standard, code or specification the paper names (with its edition or year where given): is it the right one for "
    "this equipment or subject, and is the stated edition the current one? Use THE LIBRARY FACTS below. Report each wrong, "
    "obsolete or doubtful citation as its own finding (an AI opinion, quoting where the paper names it); a standard this paper "
    "needs that the library does not hold is a Question."
)
G2_CHECK = (
    "Values on the paper that must agree with each other: a normal or operating value above its rated, design or maximum value; "
    "a derived value that does not follow from its inputs; the same quantity stated twice with different values. For each "
    "disagreement quote one value and give numbers: paper_value from your quote, rule_value with limit_quote and limit_page for "
    "the other paper value, and the operator they must satisfy; code compares them."
)
G3_CHECK = (
    "Entries or tests that this review's checklist (listed below) requires on this kind of paper and that the paper leaves "
    "blank or omits. One finding per missing entry: quote the blank entry where the paper prints its label; a Question."
)


def items(
    conn,
    identity: dict,
    checklist: dict,
    allowed_books: frozenset[str],
    text: dict[int, str],
) -> list[dict]:
    """The three always-on items for this paper, in order G1, G2, G3, as checklist items (same fields). G3 lists ONLY the held
    items whose rule book is on this review's list (an item of another book is never judged, so its words never go out), and
    declares those books."""
    books = {
        b["alias"]: b
        for b in checklist.get("books") or []
        if isinstance(b, dict) and b.get("alias")
    }
    listed = [
        (it, item_book(it, books))
        for it in checklist.get("items") or []
        if isinstance(it, dict) and it.get("source") != KNOWLEDGE
    ]
    listed = [(it, b) for it, b in listed if b and b in allowed_books]
    return [
        _item("G1", G1_CHECK, "presence", _library_facts(conn, identity, allowed_books, text), []),
        _item("G2", G2_CHECK, "limit", "", []),
        _item("G3", G3_CHECK, "presence", _required([it for it, _b in listed]), sorted({b for _it, b in listed})),
    ]  # fmt: skip


def _item(gid: str, check: str, kind: str, context: str, carries: list[str]) -> dict:
    return {
        "id": gid,
        "topic": TOPIC,
        "what_to_check": check,
        "book": "",
        "clause": "",
        "page": None,
        "rule_quote": "",
        "applies_when": "always",
        "paper_fields": [],
        "paper_pages": [],
        "kind": kind,
        "source": KNOWLEDGE,
        "stands_in_for": "the checks a senior engineer makes on every paper",
        "always_on": True,
        "context": context,
        "carries": carries,  # the rule books whose words the context holds (G3): declared to the send gate with the item
    }


def _required(held: list[dict]) -> str:
    """G3's list: what this review's checklist asks of the paper (topic and fields), one line per item."""
    rows = []
    for it in held:
        fields = ", ".join(str(f) for f in it.get("paper_fields") or [] if f)
        rows.append(
            f"- {it.get('topic') or ''}: {it.get('what_to_check') or ''}"
            + (f" (fields: {fields})" if fields else "")
        )
    return "THE CHECKLIST OF THIS REVIEW asks:\n" + "\n".join(rows) if rows else ""


def _library_facts(
    conn, identity: dict, allowed_books: frozenset[str], text: dict[int, str]
) -> str:
    """G1's facts, from the app's own tables: each cited standard and whether a book on this review's list holds it (with the edition
    its file name or title prints), and the standards governing the paper's type. Never a book that is not on the list."""
    from app import cited_edition

    from . import library as L

    try:
        lib = L.library(conn, within=frozenset(allowed_books))
        rows = []
        for _key, (ident, year) in sorted(
            cited_edition.cited_years("\n".join(text[n] for n in sorted(text))).items()
        ):
            entry = L.resolve(lib, ident)
            held = cited_edition.held_year(entry) if entry else None
            where = (
                f"on this review's list as {L.identifier_of(entry)}"
                + (f", edition {held} by its file name or title" if held else "")
                if entry
                else "not among this review's books"
            )
            rows.append(
                f"- cited: {ident}" + (f" ({year})" if year else "") + f"; {where}"
            )
        gov = [
            (
                f"{name} (on this review's list as {L.identifier_of(entry)})"
                if entry
                else f"{name} (not among this review's books)"
            )
            for entry, name in L.governing_books(lib, identity.get("equipment_type"))
        ]
    except Exception as exc:  # noqa: BLE001 - the facts are a help to the judge; without them G1 is judged on the paper alone
        log.info(
            "general review: library facts for G1 not read (%s)", type(exc).__name__
        )
        return ""
    out = ["THE LIBRARY FACTS (from the app's own tables):"]
    out += rows or ["- the paper cites no standard the app can read"]
    if gov:
        out.append("- the app's governing table names for this type: " + "; ".join(gov))
    return "\n".join(out)
