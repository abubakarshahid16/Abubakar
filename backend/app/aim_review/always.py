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

from . import library as L
from .steps import HELD, KNOWLEDGE, item_book

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
        if isinstance(it, dict) and it.get("source") == HELD
    ]
    # two locks: the book is on the shown list AND it is a usable rule book (the client's own by its role, or public)
    names = {str(b.get("book")): b.get("identifier") for b in books.values()}
    ok = L.usable_ids(conn, {b for _it, b in listed}, names)
    listed = [(it, b) for it, b in listed if b and b in allowed_books and b in ok]
    facts, named = _library_facts(conn, identity, allowed_books, text)
    g3_named = {
        b: str((books.get(it.get("book") or "") or {}).get("identifier") or "")
        for it, b in listed
    }
    pairs, entries = form_context(identity)  # update 13 (off: "", "", main's G2 and G3)
    required = "\n".join(
        x for x in (_required([it for it, _b in listed]), entries) if x
    )
    return [
        _item("G1", G1_CHECK, "presence", facts, named),
        _item("G2", G2_CHECK, "limit", pairs, {}),
        _item("G3", G3_CHECK, "presence", required, g3_named),
    ]  # fmt: skip


def form_context(identity: dict) -> tuple[str, str]:
    """(G2's pairs, G3's entries) from the app's OWN data for the paper's type, only with update 13 on (planner, 26 Nov 2026: the
    planted mistakes of kinds 1, 2 and 4 were missed under the broad G2 and G3): the consistency pairs every datasheet must keep
    (`datasheet_checks.json` "consistency") and the entries the type's form requires (its mandatory list).
    The words are the app's field names and its own pair sentences: no paper words. ("", "") when off or the type has no form."""
    from .updates import u13

    if not u13():
        return "", ""
    from app import datasheet_checks as DC

    rules = DC.load_rules()
    pairs = "\n".join(
        f"- {c['text']}" for c in rules.get("consistency") or [] if c.get("text")
    )
    etype = _sheet_type(
        str((identity or {}).get("equipment_type") or "").strip(), rules
    )
    names: list[str] = []
    if etype:  # the REQUIRED entries only (the type's mandatory list), never every box of its form
        mandatory = (rules.get("mandatory") or {}).get(
            DC.mandatory_list_key(etype, rules)
        ) or []
        names = [str(m).replace("_", " ") for m in mandatory if m]
    return (
        (
            "PAIRS THAT MUST AGREE wherever the paper states both (the app's consistency rules):\n"
            + pairs
        )
        if pairs
        else "",
        (
            "THE FORM OF THIS KIND OF PAPER requires these entries: "
            + "; ".join(names)
            + "."
        )
        if names
        else "",
    )


def is_always(item_id) -> bool:
    """Is this line one of the always-on items? By its id (never by its topic words)."""
    return str(item_id or "") in IDS


def _item(gid: str, check: str, kind: str, context: str, named: dict[str, str]) -> dict:
    """`named`: {book id: its identifier as the context prints it}: the listed books the item's words name. They are declared to
    the send gate (`carries`) and kept on every line of the item (`named_books`), so the page hides a name a viewer may not read
    (rule 5; `aim_review_view.book_hidden`)."""
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
        "carries": sorted(
            named
        ),  # the listed books the context names or quotes: declared to the send gate with the item
        "named_books": [{"id": i, "name": n} for i, n in sorted(named.items())],
    }


def _sheet_type(key: str, rules: dict) -> str:
    """The name the app's form tables know the review's equipment key by: the key spelled with spaces, else its name or a synonym in
    the equipment taxonomy (`reference/equipment_taxonomy.json`), the first one that is not the generic list; "" when none is."""
    import json
    from pathlib import Path

    from app import datasheet_checks as DC

    if not key:
        return ""
    names = [key.replace("_", " ")]
    path = (
        Path(__file__).resolve().parent.parent / "reference" / "equipment_taxonomy.json"
    )
    for fam in json.loads(path.read_text()).get("families") or []:
        for t in fam.get("types") or []:
            if t.get("id") == key:
                names += [
                    str(t.get("name") or "").split(" (")[0],
                    *map(str, t.get("synonyms") or []),
                ]
    generic = DC.mandatory_list_key("", rules)
    return next(
        (n for n in names if n and DC.mandatory_list_key(n, rules) != generic), ""
    )


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
    conn,
    identity: dict,
    allowed_books: frozenset[str],
    text: dict[int, str],
) -> tuple[str, dict[str, str]]:
    """G1's facts, from the app's own tables: each cited standard and whether a book on this review's list holds it (with the edition
    its file name or title prints), and the standards governing the paper's type. Never a book that is not on the list. Returns
    (the facts, {book id: identifier} of the listed books they name)."""
    from app import cited_edition

    from . import library as L

    try:
        lib = L.library(conn, within=frozenset(allowed_books))
        rows, named = [], {}
        for _key, (ident, year) in sorted(
            cited_edition.cited_years("\n".join(text[n] for n in sorted(text))).items()
        ):
            entry = L.resolve(lib, ident)
            entry = (
                entry if L.usable(entry) else None
            )  # a citation never makes another role a rule book (N2)
            if entry:
                named[str(entry["id"])] = L.identifier_of(entry)
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
        ]  # the governing table names company-standard books only: every one is a usable rule book (N4: no check needed)
        named |= {
            str(entry["id"]): L.identifier_of(entry)
            for entry, _name in L.governing_books(lib, identity.get("equipment_type"))
            if entry
        }
    except Exception as exc:  # noqa: BLE001 - a help to the judge: without them G1 is judged on the paper alone, and the run says so
        from . import faults

        faults.record("aim_g1_facts", "the library facts for G1", exc)
        return "", {}
    out = ["THE LIBRARY FACTS (from the app's own tables):"]
    out += rows or ["- the paper cites no standard the app can read"]
    if gov:
        out.append("- the app's governing table names for this type: " + "; ".join(gov))
    return "\n".join(out), named
