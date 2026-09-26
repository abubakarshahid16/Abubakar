"""Owner order 2026-09-26: the extraction filter audit - loosened rules and kept guards."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_extraction_filter_audit.py"
_D = APP / "datasheets.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1066", phase=90, description="GUARD: a revision table read by the geometry reader becomes facts",
             path=_D, anchor='                if row.get("table_id") in revision_tables:\n',
             replacement="                if False:\n",
             target=_T, keyword="revision_block_title_block", tags=("honesty", "critical")),
    Mutation(id="M1068", phase=90, description="GUARD: the value gate is dropped, so captions and names become facts",
             path=_D, anchor="                if not states_a_value(value):\n                    # A LABEL WITH FREE TEXT",
             replacement="                if False:\n                    # A LABEL WITH FREE TEXT",
             target=_T, keyword="revision_block_title_block", tags=("honesty", "critical")),
    Mutation(id="M1069", phase=90, description="GUARD: the designation rule admits any free text",
             path=_D, anchor='    return bool(_DESIGNATION.match(" ".join((value or "").split())))\n',
             replacement="    return True\n",
             target=_T, keyword="still_not", tags=("honesty", "critical")),
    Mutation(id="M1070", phase=90, description="LOOSENED: a material or code designation is refused again",
             path=_D, anchor='                and not is_designation_value(value))\n',
             replacement="                and True)\n",
             target=_T, keyword="every_real_pair or a_designation_is_an_answer", tags=("extraction",)),
    Mutation(id="M1071", phase=90, description="LOOSENED: the unit before the value takes the value slot again",
             path=_D, anchor="            if (_unit_follows(parts, index - 1) and index < len(parts)\n",
             replacement="            if (False and index < len(parts)\n",
             target=_T, keyword="every_real_pair or unit_before_the_value", tags=("extraction",)),
    Mutation(id="M1072", phase=90, description="LOOSENED: radiography FULL / facing RF are refused again",
             path=_D, anchor='    "full", "spot", "partial", "rf", "rtj", "ff",\n',
             replacement="",
             target=_T, keyword="every_real_pair", tags=("extraction",)),
)
