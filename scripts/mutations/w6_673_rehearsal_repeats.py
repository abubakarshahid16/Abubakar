"""#673: the rehearsal counts repeats plainly (same standard, same text), also
rows without an identity key and rows under another clause, and says the
superseded ones apart. Ids M4931-M4935."""
from __future__ import annotations

from ._base import REPO, Mutation

_S = REPO / "scripts" / "rehearse_requirement_reextraction.py"
_T = "tests/test_w6_640_requirements_supersede.py"
_TAG = ("w6", "honesty")
_ROW = """              SELECT COUNT(*) AS n FROM standard_requirements WHERE {active}
               GROUP BY standard_document_id, requirement_text HAVING n > 1)\"\"\"),
        "repeated_table_cell_rows_active\""""

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4931", phase=4931, description="a repeat filed under another clause is not counted",
             path=_S, anchor=_ROW,
             replacement=_ROW.replace("GROUP BY standard_document_id, requirement_text",
                                      "GROUP BY standard_document_id, clause, requirement_text"),
             target=_T, keyword="old_style_repeats", tags=_TAG),
    Mutation(id="M4932", phase=4932, description="rows without an identity key are not counted (the old blind spot)",
             path=_S, anchor=_ROW,
             replacement=_ROW.replace("WHERE {active}", "WHERE identity_key IS NOT NULL AND {active}"),
             target=_T, keyword="old_style_repeats", tags=_TAG),
    Mutation(id="M4933", phase=4933, description="superseded rows are left out of the count that includes them",
             path=_S,
             anchor='''        "repeated_rows_including_superseded": _one(conn, """
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements
''',
             replacement='''        "repeated_rows_including_superseded": _one(conn, """
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements WHERE superseded_at IS NULL
''',
             target=_T, keyword="old_style_repeats", tags=_TAG),
    Mutation(id="M4934", phase=4934, description="the table-cell figure counts sentences too",
             path=_S, anchor="               WHERE requirement_type = 'table_value' AND {active}\n               GROUP BY standard_document_id, requirement_text",
             replacement="               WHERE {active}\n               GROUP BY standard_document_id, requirement_text",
             target=_T, keyword="old_style_repeats", tags=_TAG),
    Mutation(id="M4935", phase=4935, description="the repeated share is printed without its denominator",
             path=_S, anchor='f"repeated rows {label}: {repeated} of {total} active rows{share}"',
             replacement='f"repeated rows {label}: {repeated}{share}"',
             target=_T, keyword="repeated_share_with_its_denominator", tags=_TAG),
)
