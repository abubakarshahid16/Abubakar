"""Mutations for the comparison side-by-side contract (2026-10-01, M1840-M1844).
File: backend/app/chat_comparison.py. Target: backend/tests/test_chat_comparison_sides.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_chat_comparison_sides.py"
_P = APP / "chat_comparison.py"
_TAG = ("chat_comparison_sides",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1840", phase=1840,
             description="the second side's citations are no longer moved past the first side's passages",
             path=_P,
             anchor='text = _renumber((side.get("answer") or "").strip(), len(passages))',
             replacement='text = (side.get("answer") or "").strip()',
             target=_T, keyword="second_sides_citations", tags=_TAG),
    Mutation(id="M1841", phase=1841,
             description="a standard typed but not in the library is silently dropped",
             path=_P,
             anchor="    for name in missing:\n",
             replacement="    for name in ():\n",
             target=_T, keyword="typed_but_not_in_the_library", tags=_TAG),
    Mutation(id="M1842", phase=1842,
             description="a comparison with no topic searches anyway",
             path=_P,
             anchor="    if topic is None:\n        return _clarify(question, all_names + missing)\n",
             replacement="    topic = topic or ''\n",
             target=_T, keyword="no_topic_asks", tags=_TAG),
    Mutation(id="M1843", phase=1843,
             description="each side is asked the reader's whole question again",
             path=_P,
             anchor='side_question = f"What does {name} say about {topic}?"',
             replacement="side_question = question",
             target=_T, keyword="each_sides_question", tags=_TAG),
    Mutation(id="M1844", phase=1844,
             description="a side's own text is no longer carried per side",
             path=_P,
             anchor='entry["text"] = text or _not_found(name)',
             replacement='entry["text"] = None',
             target=_T, keyword="keeps_its_own_multi_paragraph_text", tags=_TAG),
    Mutation(id="M1845", phase=1845,
             description="the word 'against' is read as the topic of a comparison",
             path=_P,
             anchor='_CONNECTORS = {"and", "or", "against", "from", "than", "on",',
             replacement='_CONNECTORS = {"and", "or", "on",',
             target=_T, keyword="test_topic_of", tags=_TAG),
)
