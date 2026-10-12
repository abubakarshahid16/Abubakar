"""Mutations for the compare-honesty fixes (2026-10-01, M1846-M1849, M1851-M1860 (M1850 is taken by corpus_typo), audit entry 99).
Files: backend/app/chat_comparison.py, chat_presentation.py, schemas.py and
frontend/src/components/chat/AnswerComparison.tsx.
Targets: backend/tests/test_compare_honesty.py, frontend AnswerComparison.test.tsx.
"""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_compare_honesty.py"
_TUI = "src/components/chat/AnswerComparison.test.tsx"
_C = APP / "chat_comparison.py"
_PR = APP / "chat_presentation.py"
_SC = APP / "schemas.py"
_UI = FRONTEND_SRC / "components" / "chat" / "AnswerComparison.tsx"
_TAG = ("compare_honesty",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1846", phase=1846,
             description="a compare gets the ordinary 'Checked N' header again",
             path=_PR,
             anchor='    if kind == "comparison":\n        line = _comparison_line(result)\n',
             replacement='    if False:\n        line = _comparison_line(result)\n',
             target=_T, keyword="header", tags=_TAG),
    Mutation(id="M1847", phase=1847,
             description="the header counts only the sides that found text as searched",
             path=_PR,
             anchor='    searched = [s for s in sides if s.get("searched", s.get("answer_type") != "not_in_library")]',
             replacement='    searched = [s for s in sides if (s.get("source_count") or 0) > 0]',
             target=_T, keyword="header", tags=_TAG),
    Mutation(id="M1848", phase=1848,
             description="the header says every searched side found text",
             path=_PR,
             anchor='    found = sum(1 for s in searched if (s.get("source_count") or 0) > 0)',
             replacement='    found = len(searched)',
             target=_T, keyword="header", tags=_TAG),
    Mutation(id="M1849", phase=1849,
             description="nothing found is written as the number 0, not 'none'",
             path=_PR,
             anchor="{found if found else 'none'}",
             replacement="{found}",
             target=_T, keyword="none_never_zero", tags=_TAG),
    Mutation(id="M1880", phase=1880,
             description="the header hides a named document the reader cannot read",
             path=_PR,
             anchor='    absent = len(sides) - len(searched)',
             replacement='    absent = 0',
             target=_T, keyword="header", tags=_TAG),
    Mutation(id="M1851", phase=1851,
             description="every side is recorded as searched, readable or not",
             path=_C,
             anchor='        searched = bool(allowed_document_ids & ids)',
             replacement='        searched = True',
             target=_T, keyword="never_searched", tags=_TAG),
    Mutation(id="M1852", phase=1852,
             description="a side that was never searched is reported as a search that found nothing",
             path=_C,
             anchor='        if not searched:\n            entry["answer_type"] = "not_in_library"',
             replacement='        if False:\n            entry["answer_type"] = "not_in_library"',
             target=_T, keyword="own_search_ran", tags=_TAG),
    Mutation(id="M1853", phase=1853,
             description="a multi-digit citation offset is truncated to one digit",
             path=_C,
             anchor='[S{int(m.group(1)) + offset}]',
             replacement='[S{int(m.group(1)) + offset % 10}]',
             target=_T, keyword="multi_digit", tags=_TAG),
    Mutation(id="M1854", phase=1854,
             description="every side's sources are said to start at the top of the list",
             path=_C,
             anchor='"text": None, "source_start": len(passages), "source_count": 0,\n        }\n        breakdown.append(entry)',
             replacement='"text": None, "source_start": 0, "source_count": 0,\n        }\n        breakdown.append(entry)',
             target=_T, keyword="citations", tags=_TAG),
    Mutation(id="M1855", phase=1855,
             description="a side's source count is wrong",
             path=_C,
             anchor='            entry["source_count"] = len(side_passages)',
             replacement='            entry["source_count"] = 1',
             target=_T, keyword="citations", tags=_TAG),
    Mutation(id="M1856", phase=1856,
             description="the response schema drops the per-side searched flag",
             path=_SC,
             anchor='    searched: bool = Field(\n        True, description="whether a search',
             replacement='    searched_unused: bool = Field(\n        True, description="whether a search',
             target=_T, keyword="route_returns", tags=_TAG),
    Mutation(id="M1857", phase=1857, runner="vitest",
             description="the screen shows 'not found' for a side that was never searched",
             path=_UI,
             anchor='const notInLibrary = side.answer_type === "not_in_library" || side.searched === false;',
             replacement='const notInLibrary = side.answer_type === "not_in_library";',
             target=_TUI, keyword="never searched", tags=_TAG),
    Mutation(id="M1858", phase=1858, runner="vitest",
             description="an in-text citation on a comparison opens the wrong source",
             path=_UI,
             anchor='                  onCite={onSelectSource}\n',
             replacement='                  onCite={(i) => onSelectSource(i + 1)}\n',
             target=_TUI, keyword="citation", tags=_TAG),
    Mutation(id="M1859", phase=1859, runner="vitest",
             description="a side's bullets are flattened into one line of raw marks",
             path=_UI,
             anchor='                  text={text}\n',
             replacement='                  text={text.replace(/\\n/g, " ")}\n',
             target=_TUI, keyword="markdown", tags=_TAG),
)
