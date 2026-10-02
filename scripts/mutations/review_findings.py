"""Mutations for the review-findings batch (2026-10-02, M1940-M1949): the PDF
report's verbatim label, the confidence check nobody ran, the "machine is
offline" literal. Files: backend/app/reports.py, synthesis.py, analysis.py and
the analysis screens. Targets: test_reports.py, test_synthesis.py,
test_not_implemented_market_line.py and two vitest files.
"""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_R = "tests/test_reports.py"
_S = "tests/test_synthesis.py"
_N = "tests/test_not_implemented_market_line.py"
_TAG = ("review_findings",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1940", phase=1940,
             description="the PDF report prints the verbatim label over OCR text again",
             path=APP / "reports.py",
             anchor="        parts.append(f'<p class=\"label\">{_extract_label(s)}</p>')",
             replacement="        parts.append('<p class=\"label\">Quoted verbatim from the document</p>')",
             target=_R, keyword="never_labelled_verbatim or no_recorded_source", tags=_TAG),
    Mutation(id="M1941", phase=1941,
             description="a passage with no recorded text source is called verbatim",
             path=APP / "reports.py",
             anchor='    if judged and all(src == "extracted" for src in sources):',
             replacement='    if judged and all(src in ("extracted", None) for src in sources):',
             target=_R, keyword="follows_the_provenance or no_recorded_source", tags=_TAG),
    Mutation(id="M1942", phase=1942,
             description="an unrun confidence check is recorded as checked and clear",
             path=APP / "synthesis.py",
             anchor="            True if coverage_complete is False else None,",
             replacement="            coverage_complete is False,",
             target=_S, keyword="everything_clear or coverage_complete_true or api_carries_null or survives_the_merge", tags=_TAG),
    Mutation(id="M1943", phase=1943,
             description="merging two unrun checks reports them as clear",
             path=APP / "synthesis.py",
             anchor="            merged[check.label] = None\n",
             replacement="            merged[check.label] = False\n",
             target=_S, keyword="survives_the_merge or one_side_computed", tags=_TAG),
    Mutation(id="M1944", phase=1944, runner="vitest",
             description="the recommendation card shows a check nobody ran as clear",
             path=FRONTEND_SRC / "components" / "analysis" / "RecommendationCard.tsx",
             anchor='c.fired === false ? "— clear" : "? not checked"',
             replacement='"— clear"',
             target="src/components/analysis/RecommendationCard.test.tsx",
             keyword="not checked", tags=("ui",)),
    Mutation(id="M1945", phase=1945, runner="vitest",
             description="the analysis screen turns an unrun check into a clear one on the way in",
             path=FRONTEND_SRC / "views" / "analysis" / "analysisModel.ts",
             anchor="fired: c.fired === true ? true : c.fired === false ? false : null,",
             replacement="fired: c.fired === true,",
             target="src/views/AnalysisModeScreen.test.tsx",
             keyword="not checked", tags=("ui",)),
    Mutation(id="M1946", phase=1946,
             description="the market gap is worded as a literal offline claim again",
             path=APP / "analysis.py",
             anchor="    return [market_line() if item is None else item for item in NOT_IMPLEMENTED]",
             replacement='    return ["public market research (this machine is offline)" if item is None else item for item in NOT_IMPLEMENTED]',
             target=_N, tags=_TAG),
)
