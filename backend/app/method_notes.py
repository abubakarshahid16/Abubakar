"""Order 159: HOW a pairing was made is for the engineer, not the contractor.

`comparison` appends notes to a finding's rationale when the pairing was not
word for word ("field linked through the synonym table as ...", the other
copies of a field, a unit read from the clause's own text). They explain what
the verdict rests on, so the engineer's internal copy keeps them. The
contractor's copy must not carry them: they are the program's own words.

The notes sit between an explicit open and close marker, so any reader can take
them off without guessing at wording. A rationale stored before this module
has no marker and is left as it is.
"""

from __future__ import annotations

OPEN = "[[how the pairing was made: "
CLOSE = "]]"


def wrap(notes: list[str]) -> str:
    """The marked block for `notes` (empty when there are none)."""
    return f"{OPEN}{'; '.join(notes)}{CLOSE}" if notes else ""


def split_method_notes(text: str | None) -> tuple[str, str]:
    """`(reason without the notes, the notes)`. No marker: `(text, "")`,
    unchanged. A block runs from its open marker to the LAST close marker
    after it (a field name may contain the close marker itself), and every
    block is taken off; an open marker never closed takes the rest of the
    text with it, so no raw marker is ever left in the reason."""
    text = text or ""
    found: list[str] = []
    while (start := text.find(OPEN)) >= 0:
        end = text.rfind(CLOSE, start + len(OPEN))
        stop = end + len(CLOSE) if end >= 0 else len(text)
        found.append(text[start + len(OPEN) : end if end >= 0 else len(text)])
        before, after = text[:start].rstrip(), text[stop:].lstrip()
        text = f"{before} {after}" if before and after else before or after
    return text, "; ".join(found)


def reason_of(finding: dict) -> str:
    """A finding's rationale without the pairing notes: what a contractor-facing
    cell may be built from."""
    return split_method_notes(finding.get("ai_rationale"))[0]


def why_bits(rationale: str | None) -> list[str]:
    """The internal copy's "Why" parts: the reason, then how the pairing was
    made (the notes), each only when there is something to say."""
    reason, notes = split_method_notes(rationale)
    return [
        part
        for part in (
            f"Why: {reason.strip()}" if reason.strip() else "",
            f"How paired: {notes}" if notes else "",
        )
        if part
    ]
