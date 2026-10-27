"""Does a review checklist REPLACE its standards' library requirements? (order 235.2)

The relief-valve checklist governs the standards it cites: their library
requirements are not checked one by one, its items are (#746, planner decision).
That is right for a checklist that spells out the standard's checks. A checklist
that only asks "is this field stated" cannot stand in for a 1,000-clause
standard, and calling the standard "covered by the checklist" would be a claim
the checklist cannot back. So an entry says so in the data: `"governs": false`
(the pump checklist does) and its standards stay checked requirement by
requirement beside it. Absent, it governs, as before.
"""

from __future__ import annotations


def governs(entry: dict) -> dict:
    """The `governs` key the checklist carries, from its data entry."""
    return {"governs": entry.get("governs", True) is not False}


def standards(checklist: dict) -> list[str]:
    """The standards a checklist governs: those its items cite, or none when it
    does not replace them."""
    if not checklist.get("governs", True):
        return []
    return sorted({item["source"]["standard"] for item in checklist["items"]})
