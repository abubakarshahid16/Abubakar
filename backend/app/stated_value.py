"""A stated value as it is QUOTED in a finding's text (order 124 item 9).

A fact's stored `field_value` has no length cap: a reader sometimes stores a
whole table row run together, many cells, as one value. Pasted whole into a
finding's sentence, it fills the comment sheet's Observation cell with a raw
table chunk. Here a long value is shown as a plainly marked EXCERPT instead.

TEXT ONLY. Nothing here is a comparison input: every verdict, status and count
is still worked out from the full value, and the full value stays on the fact
with its page citation, where the engineer reads it. A cut quote always ends
with " …", so it is never presented as the whole value (CLAUDE.md rule 4).
"""

from __future__ import annotations

#: The longest value quoted whole, in characters (whitespace collapsed). A real
#: datasheet value - a number and unit, a range, a material grade, a short
#: phrase - fits in one line of a comment cell; a value longer than this is in
#: practice a table row run together. 80 is one plain line of text.
EXCERPT_CHARS = 80

#: Ends every excerpt, so a cut quote never reads as the whole value.
EXCERPT_MARK = " …"


def fact_value(fact: dict) -> str:
    """The fact's whole stated value: its printed text, else its raw value."""
    return str(fact.get("field_value") or fact.get("raw_value") or "").strip()


def stated[V](value: V) -> V | str:
    """`value` for a finding's sentence: unchanged when short (a number or None
    always is); otherwise its start, whitespace collapsed, cut at a word
    boundary, ending " …"."""
    if not isinstance(value, str):
        return value
    collapsed = " ".join(value.split())
    if len(collapsed) <= EXCERPT_CHARS:
        return value
    head = collapsed[: EXCERPT_CHARS + 1].rsplit(" ", 1)[0]
    if len(head) > EXCERPT_CHARS:  # one word longer than the limit
        head = head[:EXCERPT_CHARS]
    return (head.rstrip(" ,;:") or head) + EXCERPT_MARK


def flat(value: str | None) -> str:
    """`value` with its whitespace collapsed, as quoted in a finding's text."""
    return stated(" ".join(str(value or "").split()))


def said(fact: dict) -> str:
    """`fact_value` as quoted in a finding's text (`stated`)."""
    return stated(fact_value(fact))
