"""What the contractor's Standard Reference and Page/Section columns print for
a checklist row, an AI draft and a field that is not on the sheet (order 228).

Pure text from the finding's stored fields; nothing is read or guessed."""

import re

#: Page/Section for a field the datasheet does not hold.
NOT_FOUND = "Not found on the datasheet"

_CHECK_ID = re.compile(r"(Datasheet check [A-Z]+-[A-Z0-9]+)")


def checklist_reference(finding: dict) -> str:
    """A checklist row cites its standard and clause ("API 520-I 3.20", and
    "(p.14)" once the page is located), as the comment sheet does. The check's
    own id ("Datasheet check PSV-14") is the answer only when no clause is
    stored, and stays in the internal columns otherwise."""
    cited = " ".join(str(finding.get("standard_clause") or "").split())
    if cited:
        page = finding.get("standard_page")
        return cited + (f" (p.{page})" if page else "")
    m = _CHECK_ID.match(
        finding.get("requirement_source_text") or finding.get("ai_rationale") or ""
    )
    return m.group(1) if m else "Datasheet check"


def relates_to(rationale: str) -> str:
    """The standard NAME after "Relates to: " - not the engine's "Written by
    ..." note that follows it."""
    if "Relates to: " not in rationale:
        return ""
    return rationale.split("Relates to: ", 1)[1].split(" Written by ", 1)[0].rstrip(".")


def not_on_the_sheet(group: list[dict], pages: list) -> bool:
    """Nothing was read and no page is known: the field is not on the sheet."""
    return not pages and not any(g.get("fact_id") for g in group)
