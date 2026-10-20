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
    unchanged. An open marker never closed is left in the reason untouched."""
    text = text or ""
    start = text.find(OPEN)
    if start < 0:
        return text, ""
    end = text.find(CLOSE, start + len(OPEN))
    if end < 0:
        return text, ""
    notes = text[start + len(OPEN) : end]
    before, after = text[:start].rstrip(), text[end + len(CLOSE) :].lstrip()
    return (f"{before} {after}" if before and after else before or after), notes


def reason_of(finding: dict) -> str:
    """A finding's rationale without the pairing notes: what a contractor-facing
    cell may be built from."""
    return split_method_notes(finding.get("ai_rationale"))[0]
