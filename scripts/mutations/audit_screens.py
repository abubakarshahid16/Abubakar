"""Mutations of the frontend screen audit (2026-09-30): routing, review runs,
Standards Library tabs, the Dashboard's review block and labels, Deliverables,
provenance wording, and a 401 on every transport.

Each entry puts back the defect the audit found; the named vitest test must
fail on it. Ids M1500-M1519.
"""

from __future__ import annotations

from ._base import FRONTEND_SRC, Mutation

_ROUTING = FRONTEND_SRC / "routing.ts"
_RUNS = FRONTEND_SRC / "views" / "ReviewRunsView.tsx"
_STD = FRONTEND_SRC / "views" / "StandardsView.tsx"
_PANEL = FRONTEND_SRC / "components" / "review" / "ReviewDashboardPanel.tsx"
_DELIV = FRONTEND_SRC / "views" / "DeliverablesView.tsx"
_DASH = FRONTEND_SRC / "views" / "DashboardViewContent.tsx"
_PROV = FRONTEND_SRC / "components" / "chat" / "Provenance.tsx"
_CLIENT = FRONTEND_SRC / "api" / "client.ts"
_UPLOADER = FRONTEND_SRC / "components" / "Uploader.tsx"

_T_ROUTING = "src/routing.test.ts"
_T_RUNS = "src/views/ReviewRunsView.test.tsx"
_T_STD = "src/views/StandardsView.test.tsx"
_T_PANEL = "src/components/review/ReviewDashboardPanel.test.tsx"
_T_DELIV = "src/views/DeliverablesView.test.tsx"
_T_DASH = "src/views/DashboardView.test.tsx"
_T_PROV = "src/components/chat/Provenance.unknown.test.ts"
_T_CLIENT = "src/api/client.pageImage.test.ts"
_T_UPLOADER = "src/components/Uploader.auth.test.tsx"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1500", phase=1500, runner="vitest",
             description="the route allow-list is a hand-kept list that omits standards",
             path=_ROUTING,
             anchor="  if (!isRoutableView(view)) {",
             replacement='  if (!["dashboard", "documents", "chat", "analysis", "reports", '
                         '"deliverables", "ingestion", "admin", "review"].includes(view)) {',
             target=_T_ROUTING, keyword="every navigation entry survives a refresh",
             tags=("ui",)),
    Mutation(id="M1501", phase=1501, runner="vitest",
             description="a failed standards list becomes an empty one: "
                         "'No standards were selected for this run.'",
             path=_RUNS,
             anchor="      setStandards(null);\n"
                    "      setMissingStandards([]);\n"
                    "      setStandardsError(listed.error.message);",
             replacement="      setStandards([]);\n"
                         "      setMissingStandards([]);",
             target=_T_RUNS, keyword="not that none were selected",
             tags=("honesty", "ui")),
    Mutation(id="M1502", phase=1502, runner="vitest",
             description="the run card shows the AI's code bare, not labelled as the AI's",
             path=_RUNS,
             anchor='          <span className="text-slateish-400">AI recommended: </span>\n',
             replacement="",
             target=_T_RUNS, keyword="labels the run card",
             tags=("honesty", "ui")),
    Mutation(id="M1503", phase=1503, runner="vitest",
             description="the run card never shows the engineer's final code",
             path=_RUNS,
             anchor="      {run.engineer_final_code && (\n"
                    '        <p className="mt-1 text-sm text-slateish-200" data-testid="run-card-final">',
             replacement="      {false && (\n"
                         '        <p className="mt-1 text-sm text-slateish-200" data-testid="run-card-final">',
             target=_T_RUNS, keyword="final code beside the AI",
             tags=("honesty", "ui")),
    Mutation(id="M1504", phase=1504, runner="vitest",
             description="the run card prints the raw database status",
             path=_RUNS,
             anchor="        {run.standards_in_scope} standards in scope · {runStatusLabel(run.status)}",
             replacement="        {run.standards_in_scope} standards in scope · status {run.status}",
             target=_T_RUNS, keyword="status in plain words",
             tags=("ui",)),
    Mutation(id="M1505", phase=1505, runner="vitest",
             description="the requirements tab spins forever when its list fails",
             path=_STD,
             anchor="    return loadError !== null\n"
                    '      ? <TabLoadError what="requirements" message={loadError} />\n'
                    "      : <Spinner />;",
             replacement="    return <Spinner />;",
             target=_T_STD, keyword="requirements load failure",
             tags=("honesty", "ui")),
    Mutation(id="M1506", phase=1506, runner="vitest",
             description="the revisions tab spins forever when its list fails",
             path=_STD,
             anchor="    return loadError !== null\n"
                    '      ? <TabLoadError what="revisions" message={loadError} />\n'
                    "      : <Spinner />;",
             replacement="    return <Spinner />;",
             target=_T_STD, keyword="revisions load failure",
             tags=("honesty", "ui")),
    Mutation(id="M1507", phase=1507, runner="vitest",
             description="the Dashboard review block vanishes, button and all, when its figures fail",
             path=_PANEL,
             anchor="  if (!data && loadError === null) return null;",
             replacement="  if (!data) return null;",
             target=_T_PANEL, keyword="says the figures failed",
             tags=("honesty", "ui")),
    Mutation(id="M1508", phase=1508, runner="vitest",
             description="a failed submittal list shows as an empty picker",
             path=_PANEL,
             anchor="            {submittalsError !== null && (",
             replacement="            {false && (",
             target=_T_PANEL, keyword="submittal list failed",
             tags=("honesty", "ui")),
    Mutation(id="M1509", phase=1509, runner="vitest",
             description="the review block's counts state no boundary",
             path=_PANEL,
             anchor="        These review counts cover only the documents you can open.\n",
             replacement="",
             target=_T_PANEL, keyword="cover only the documents the reader can open",
             tags=("honesty", "ui")),
    Mutation(id="M1510", phase=1510, runner="vitest",
             description="the recent reviews table prints the raw database status",
             path=_PANEL,
             anchor="{runStatusLabel(run.status)}</td>",
             replacement="{run.status}</td>",
             target=_T_PANEL, keyword="status in plain words",
             tags=("ui",)),
    Mutation(id="M1511", phase=1511, runner="vitest",
             description="a failed WBS register also says nothing is registered",
             path=_DELIV,
             anchor=': !registerLoaded ? <p className="px-4 py-3 text-sm text-slateish-400">',
             replacement=': false ? <p className="px-4 py-3 text-sm text-slateish-400">',
             target=_T_DELIV, keyword="never that nothing is registered",
             tags=("honesty", "ui")),
    Mutation(id="M1512", phase=1512, runner="vitest",
             description="two Dashboard tiles are both called Needs attention",
             path=_DASH,
             anchor='          label="System warnings"',
             replacement='          label="Needs attention"',
             target=_T_DASH, keyword="warnings tile for what it counts",
             tags=("honesty", "ui")),
    Mutation(id="M1513", phase=1513, runner="vitest",
             description="the corpus-wide banner claims the scope-limited review counts too",
             path=_DASH,
             anchor="                them because you hold the admin capability. The AI Submittal\n"
                    "                Review counts are not corpus-wide: they cover only the\n"
                    "                documents you can open, and say so on their own block.",
             replacement="                them because you hold the admin capability.",
             target=_T_DASH, keyword="scope-limited review counts",
             tags=("honesty", "ui")),
    Mutation(id="M1514", phase=1514, runner="vitest",
             description="Open deliverables goes nowhere",
             path=_DASH,
             anchor='<button type="button" onClick={onOpenDeliverables} className=',
             replacement='<button type="button" className=',
             target=_T_DASH, keyword="dead hash link",
             tags=("ui",)),
    Mutation(id="M1515", phase=1515, runner="vitest",
             description="a passage of unknown source is labelled Verbatim from PDF",
             path=_PROV,
             anchor='  return isExtracted(passage) ? "Verbatim from PDF" : PROVENANCE_UNKNOWN;',
             replacement='  return "Verbatim from PDF";',
             target=_T_PROV, keyword="never calls",
             tags=("honesty", "ui")),
    Mutation(id="M1516", phase=1516, runner="vitest",
             description="a passage of unknown source is 'quoted directly, no AI rewriting'",
             path=_PROV,
             anchor='  if (isExtracted(passage)) return "quoted directly, no AI rewriting";',
             replacement='  if (!isRecognised(passage)) return "quoted directly, no AI rewriting";',
             target=_T_PROV, keyword="never calls",
             tags=("honesty", "ui")),
    Mutation(id="M1517", phase=1517, runner="vitest",
             description="a 401 on a page image leaves the dead token in place",
             path=_CLIENT,
             anchor="    if (!response.ok) {\n"
                    "      signOutOn401(response.status);\n"
                    "      return { url: null, answerLocated: null };",
             replacement="    if (!response.ok) {\n"
                         "      return { url: null, answerLocated: null };",
             target=_T_CLIENT, keyword="page image is refused",
             tags=("auth",)),
    Mutation(id="M1518", phase=1518, runner="vitest",
             description="a 401 on the upload leaves the dead token in place",
             path=_UPLOADER,
             anchor="        reportResponseStatus(xhr.status);\n",
             replacement="",
             target=_T_UPLOADER, keyword="a 401 on the upload",
             tags=("auth",)),
    Mutation(id="M1519", phase=1519, runner="vitest",
             description="a 401 on the CRS workbook leaves the dead token in place",
             path=_CLIENT,
             anchor="    if (!response.ok) {\n"
                    "      signOutOn401(response.status);\n"
                    "      let error: ApiError = {",
             replacement="    if (!response.ok) {\n"
                         "      let error: ApiError = {",
             target=_T_CLIENT, keyword="CRS workbook is refused",
             tags=("auth",)),
)
