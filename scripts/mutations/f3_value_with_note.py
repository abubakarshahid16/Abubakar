"""#725 F3: a datasheet value with a note is a value plus a note. M6301 onward."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_f3_value_with_note.py"
_D = APP / "datasheets.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M6301", phase=6301, description="a value beside a marker is called blank again",
             path=_D, anchor="    if blank and value_and_note(value)[0] is not None:\n        return False, None\n",
             replacement="",
             target=_T, keyword="value_with_a_note", tags=("datasheet", "critical")),
    Mutation(id="M6302", phase=6302, description="the parse keeps the marker text, so the value is lost",
             path=_D, anchor="    if blank_markers.names_a_marker(raw_value):\n        text, found = value_and_note(raw_value)\n",
             replacement="    if False:\n        text, found = value_and_note(raw_value)\n",
             target=_T, keyword="value_with_a_note", tags=("datasheet", "critical")),
    Mutation(id="M6303", phase=6303, description="any text left beside a marker counts as a value",
             path=_D, anchor="    if rest and (measure_value(rest)[0] is not None or parse_range(rest) is not None):\n",
             replacement="    if rest:\n",
             target=_T, keyword="still_blank", tags=("datasheet",)),
    Mutation(id="M6304", phase=6304, description="the note is not stored with the fact",
             path=_D, anchor='        "value_note": cols["value_note"],\n', replacement='        "value_note": None,\n',
             target=_T, keyword="stored_with_the_fact", tags=("datasheet",)),
    Mutation(id="M6305", phase=6305, description="a finding on a noted value hides the note",
             path=APP / "comparison.py",
             anchor="        note += f\"; the datasheet marks this value {fact['value_note']!r}\"\n",
             replacement="        pass\n",
             target=_T, keyword="names_the_note", tags=("honesty",)),
    Mutation(id="M6306", phase=6306, description="the reader's value gate measures the marker too, so the row is dropped",
             path=_D, anchor="    measured = text if note is not None and text is not None else value\n",
             replacement="    measured = value\n",
             target="tests/test_179_layouts.py", keyword="one_printed_cell_read_by_both", tags=("datasheet",)),
)
