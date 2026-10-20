"""Does a plain statement ask the datasheet to state something? (orders 180.1 item 2)

A statement paired with a blank datasheet field makes a "contractor to provide X"
row. That row is supported only if the sentence asks the sheet to STATE a value or
choice. "Weld repairs shall be re-examined and the results noted on a data report"
asks for work, not for a value in an "Ultrasonic" field; "The vendor shall state
the ultrasonic examination extent" asks for one. Only a plain statement (no value,
limit or option set of its own) is judged; any other requirement type asks through
its own value. Structure words only; no field, standard or layout is named.
"""

from __future__ import annotations

import re

#: A stating verb after a modal or "to (be)" ("shall be specified", "vendor to
#: state"), or opening the sentence ("Provide the ...").
_ASKS_TO_STATE = re.compile(
    r"\b(?:shall|must|should|will|is|are|to)\s+(?:also\s+|each\s+|always\s+)?(?:be\s+)?"
    r"(?:state\w*|specif\w*|indicat\w*|report\w*|record\w*|provid\w*|submit\w*|"
    r"identif\w*|declar\w*|list\w*|document\w*|supply|supplied|furnish\w*)\b"
    r"|^\s*(?:state|specify|indicate|report|record|provide|submit|identify|declare|list)\b",
    re.IGNORECASE,
)


def asks_to_state(requirement: dict) -> bool:
    """True unless this is a plain statement that asks for no stated value."""
    if requirement.get("requirement_type") != "statement":
        return True
    text = " ".join(
        str(
            requirement.get("source_text") or requirement.get("requirement_text") or ""
        ).split()
    )
    return _ASKS_TO_STATE.search(text) is not None
