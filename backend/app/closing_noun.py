"""A requirement whose quantity is named at the END of the sentence (#913, PF2).

"At normal flow the valve shall operate between 20 % and 80 % of its travel."
stores the subject "At normal flow the valve" (the words before "shall"), but
the quantity is the valve's travel, named last. The sheet's label is "Travel at
normal flow", which is not a phrase of the subject, so the pairing found no row
and a real defect (88 % on the sheet) got no verdict.

THE RULE. When the plain containment pass finds nothing, the closing noun phrase
("of its X" / "of the X", one to three words, last words of the sentence) is put
IN FRONT of the subject, and a label pairs only if it STRADDLES the join: it
starts inside the closing phrase and runs on into the subject ("travel" + "at
normal flow"). Three consequences, each a refusal:

  * a label that is only the closing phrase never pairs ("best efficiency flow"
    is the reference of "80 % of the best efficiency flow", not its quantity);
  * a label that is only subject words never pairs here (the plain pass owns it);
  * a one-word label never pairs (the #893 rule): it cannot run past the join.

Shape only: no field, standard, unit or layout is named. It runs only after the
plain pass found nothing, so no existing pairing changes; its hits still go
through the same unit, equipment and lookup-table rules and the same tie rule.
"""

from __future__ import annotations

import re

#: "... of its travel." / "... of the best efficiency flow" at the sentence end.
_CLOSING = re.compile(
    r"\bof\s+(?:its|their|the|a|an|each|this|that)\s+([a-z][a-z\-]*(?:\s+[a-z][a-z\-]*){0,2})\s*[.;]?\s*$"
)


def closing_phrase(text: str | None) -> str:
    """The closing noun phrase of `text` as lowercase words, or ''."""
    folded = re.sub(r"[^\w\s.;\-]", " ", (text or "").lower())
    found = _CLOSING.search(re.sub(r"\s+", " ", folded).strip())
    return re.sub(r"[.;]", "", found.group(1)).strip() if found else ""


def compose(requirement: dict, subject: str) -> tuple[str, str]:
    """(`closing phrase + subject`, closing phrase), or ('', '') without one."""
    closing = closing_phrase(
        requirement.get("source_text") or requirement.get("requirement_text")
    )
    if not closing or not subject:
        return "", ""
    return f"{closing} {subject}", closing


def straddles(name: str, composed: str, closing: str) -> bool:
    """Does the whole-word phrase `name` start in `closing` and run past it?"""
    found = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", composed)
    return bool(found) and found.start() < len(closing) and found.end() > len(closing)


def straddling(hits: list[dict], composed: str, closing: str) -> list[dict]:
    """The containment `hits` whose label straddles the join (see `straddles`)."""
    return [h for h in hits if straddles(h["name"], composed, closing)]
