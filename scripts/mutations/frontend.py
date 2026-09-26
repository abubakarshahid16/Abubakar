"""Mutations of:

    frontend/src/components/DocumentPreview.tsx
    frontend/src/components/DocumentTechnicalDetails.tsx
    frontend/src/components/PageImageViewer.tsx
    frontend/src/components/analysis/RemovedSentences.tsx
    frontend/src/components/chat/AnswerCardContent.tsx
    frontend/src/components/chat/AnswerCardView.tsx
    frontend/src/components/classification/MetadataEditor.tsx
    frontend/src/components/review/FindingsTable.tsx
    frontend/src/components/review/reviewFormat.ts
    frontend/src/views/DocumentsView.tsx
    frontend/src/views/ReviewRunsView.tsx
    frontend/src/views/StandardsView.tsx
    frontend/src/views/analysis/AnalysisResultSections.tsx
    frontend/src/views/analysis/analysisStore.ts
"""

from __future__ import annotations

from ._base import FRONTEND_SRC, REPO, _B34_UI_TEST, _REVIEW_UI, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_2_UI --------------------------------------------------
    #: Phase 2 frontend: the visible workflows. Proven with vitest.
    Mutation(
        id="M21", phase=2, runner="vitest",
        description="open the page viewer at page 1, ignoring the cited page",
        path=FRONTEND_SRC / "components" / "PageImageViewer.tsx",
        anchor="  const [selected, setSelected] = useState(Math.max(1, initialPage ?? 1));",
        replacement="  const [selected, setSelected] = useState(1);",
        target="src/components/PageImageViewer.citation.test.tsx",
        keyword="opens at the cited page",
        tags=("citation", "ui"),
    ),
    Mutation(
        id="M22", phase=2, runner="vitest",
        description="stop clearing blank metadata fields, so a value cannot be removed",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="      body[field] = text[field]?.trim() ? text[field].trim() : null;",
        replacement="      if (text[field]?.trim()) body[field] = text[field].trim();",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="sends every field",
        tags=("metadata", "ui"),
    ),
    Mutation(
        id="M23", phase=2, runner="vitest",
        description="send the human role label instead of its contract value",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="      document_role: role === \"\" ? null : role,",
        replacement="      document_role: role === \"\" ? null : String(role).toLowerCase(),",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="sends the role the engineer chose",
        tags=("validation", "ui"),
    ),
    Mutation(
        id="M24", phase=2, runner="vitest",
        description="show the metadata form to a non-admin",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="  if (!canEdit) {",
        replacement="  if (false) {",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="does not offer the controls to a non-admin",
        tags=("permission", "ui"),
    ),
    Mutation(
        id="M25", phase=2, runner="vitest",
        description="render a workbook's empty cells instead of populated ones",
        path=FRONTEND_SRC / "components" / "DocumentPreview.tsx",
        anchor="  const rows = sheet.rows.filter((row) => row.some((cell) => cell !== \"\"));",
        replacement="  const rows: string[][] = [];",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="shows a workbook as sheets",
        tags=("preview", "ui"),
    ),
    Mutation(
        id="M26", phase=2, runner="vitest",
        description="render 'Unknown' for a field that was never recorded",
        path=FRONTEND_SRC / "components" / "DocumentTechnicalDetails.tsx",
        anchor='  if (value === null || value === undefined || value === "") return null;',
        replacement='  if (value === null || value === undefined || value === "") value = "Unknown";',
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="renders nothing at all",
        tags=("honesty", "ui"),
    ),
    # ---- from PHASE_3A_UI -------------------------------------------------
    #: Phase 3A frontend: what the Standards Library refuses to say.
    Mutation(
        id="M35", phase=3, runner="vitest",
        description="render '0 requirements' instead of 'none extracted yet'",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='        {standard.requirement_count === 0\n'
               '          ? "No requirements extracted yet"',
        replacement='        {false\n'
                    '          ? "No requirements extracted yet"',
        target="src/views/StandardsView.test.tsx",
        keyword="no requirements have been extracted",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M36", phase=3, runner="vitest",
        description="guess a clause number when the parser could not identify one",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='                  {row.clause ?? "Clause not identified"}',
        replacement='                  {row.clause ?? "1.1"}',
        target="src/views/StandardsView.test.tsx",
        keyword="clause could not be identified",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M37", phase=3, runner="vitest",
        description="stop labelling an extracted requirement as unconfirmed",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='                {row.extraction_method === "extracted" && !row.confirmed_by && (',
        replacement="                {false && (",
        target="src/views/StandardsView.test.tsx",
        keyword="labels an extracted requirement",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M38", phase=3, runner="vitest",
        description="show the supersede control to a non-admin",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor="      {isAdmin && (\n"
               '        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">',
        replacement="      {true && (\n"
                    '        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">',
        target="src/views/StandardsView.test.tsx",
        keyword="does not offer the supersede control",
        tags=("permission", "ui"),
    ),
    # ---- from ROLES_FIX ---------------------------------------------------
    #: Document roles: the watched folder's subfolder convention, and the bulk
    #: assignment endpoint. Not a phase - a contained fix between phases 5B and 6.
    #:
    #: M73 IS THE ONE THAT MATTERS. Every other mutation here breaks something a
    #: user would notice. M73 makes the watcher guess a role from the filename,
    #: which on this corpus is right 272 times out of 280 and would look like an
    #: improvement in a diff.
    Mutation(
        id="M82", phase=8, runner="vitest",
        description="show the bulk selection to a non-admin, whose every "
                    "apply would 404",
        path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
        anchor="                                selected={isAdmin ? selectedIds.includes(doc.id) : undefined}\n"
               "                                onToggleSelected={isAdmin ? toggleSelected : undefined}",
        replacement="                                selected={selectedIds.includes(doc.id)}\n"
                    "                                onToggleSelected={toggleSelected}",
        target="src/views/DocumentsView.bulkRole.test.tsx",
        keyword="no selection at all to a non-admin",
        tags=("permission",),
    ),
    Mutation(
        id="M83", phase=8, runner="vitest",
        description="report a partial bulk write as an unqualified success",
        path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
        anchor="        failed.length\n"
               "          ? `${failed.length} could not be updated and were left unchanged`\n"
               "          : null,",
        replacement="        null,",
        target="src/views/DocumentsView.bulkRole.test.tsx",
        keyword="says which documents were not updated",
        tags=("honesty", "critical"),
    ),
    # ---- from CORPUS_QUESTIONS --------------------------------------------
    #: Document Q&A answered "there are 12 distinct standards" from three retrieved
    #: passages, of a library holding 272. Both halves of the fix, both sides.
    # ------------------------------------------------ on screen, vitest
    Mutation(
        id="M260", phase=25, runner="vitest",
        description="HIDE THE LIBRARY'S HALF of a two-part answer, leaving "
                    "the documents' answer to stand for both",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardView.tsx",
        anchor='  const twoPart = view.corpus != null && view.answer_type !== "metadata";',
        replacement="  const twoPart = false;",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="two labelled parts",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M261", phase=25, runner="vitest",
        description="wrap a metadata answer in a second library block, "
                    "saying the same sentence twice",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardView.tsx",
        anchor='  const twoPart = view.corpus != null && view.answer_type !== "metadata";',
        replacement="  const twoPart = view.corpus != null;",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="once, not twice",
        tags=("ui",),
    ),
    Mutation(
        id="M262", phase=25, runner="vitest",
        description="lose `corpus` between the persisted message and the view",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardContent.tsx",
        anchor="    corpus: p.corpus ?? null,",
        replacement="    corpus: null,",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="carries both fields",
        tags=("ui",),
    ),
    # ---- from DEMO_POLISH -------------------------------------------------
    Mutation(
        id="M265", phase=27, runner="vitest",
        description="restore the duplicate nominal-estimate completeness line "
                    "when the recommendation already states it",
        path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
        anchor="      {completeness && !reasonStatesDenominator && (",
        replacement="      {completeness && (",
        target="src/views/ReviewRunsView.test.tsx",
        keyword="exactly once",
        tags=("honesty", "ui"),
    ),
    # ---- from B34_STANDARD_IDS --------------------------------------------
    #: Phase 31: B34 - a standard number is a NAME, not a measurement, under a
    #: CLOSED grammar; and a removed sentence is REPORTED, never silently deleted.
    #: M288-M293 loosen or remove the grammar in six different ways - each must be
    #: caught, and M289 and M293 are the loosenings that would let a fabricated
    #: value disguised as a standard number through ("per SAES-H-150, apply 150").
    Mutation(
        id="M298", phase=31, runner="vitest",
        description="hide the removed sentences from the reader",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='      {shown.length > 0 && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (',
        replacement='      {false && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (',
        target=_B34_UI_TEST, keyword="WITHOUT any click",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M299", phase=31, runner="vitest",
        description="stop greying removed sentences, so they read like the answer",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='          className="text-xs text-slateish-500 opacity-70"',
        replacement='          className="text-xs text-slateish-300"',
        target=_B34_UI_TEST, keyword="WITHOUT any click",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M300", phase=31, runner="vitest",
        description="do not render what was removed from a recommendation",
        path=REPO / "frontend" / "src" / "views" / "analysis" / "AnalysisResultSections.tsx",
        anchor='      <RemovedSentences removed={d.removed} what="recommendation" />\n',
        replacement="",
        target=_B34_UI_TEST, keyword="even when none survived",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M301", phase=31, runner="vitest",
        description="let an all-removed recommendation read as 'nothing was generated'",
        path=REPO / "frontend" / "src" / "views" / "analysis" / "analysisStore.ts",
        anchor="&& refusal === null && removed.length === 0) return null;",
        replacement="&& refusal === null) return null;",
        target=_B34_UI_TEST, keyword="even when none survived",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M302", phase=31, runner="vitest",
        description="put the removed value back into the answer's reach: render removed sentences as plain answer text",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='  if (removed.length === 0) return null;',
        replacement='  if (removed.length >= 0) return <p>{removed.map((s) => s.sentence).join(" ")}</p>;',
        target=_B34_UI_TEST, keyword="ONLY in the removed region",
        tags=("honesty", "ui"),
    ),
    # ---- from B9_NOT_IN_DOCUMENT_SCOPE ------------------------------------
    #: B9/B22: NOT_IN_DOCUMENT_SCOPE, rule R1 - an unmatched `statement` is not
    #: the contractor's omission, and must never approve a submittal either.
    Mutation(
        id="M323", phase=37, runner="vitest",
        description="fold out-of-scope rows into the 'no evidence' count",
        path=_REVIEW_UI / "FindingsTable.tsx",
        anchor="  const missing = filtered.filter((f) => f.compliance_status === MISSING);",
        replacement="  const missing = filtered.filter((f) => f.compliance_status === MISSING"
                    " || f.compliance_status === OUT_OF_SCOPE);",
        target="src/components/review/FindingsTable.test.tsx",
        keyword="OWN count",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M332", phase=37, runner="vitest",
        description="an out-of-scope row stops showing its page, so an engineer "
                    "cannot find and catch a misclassified one (owner's merge "
                    "condition 1a)",
        path=_REVIEW_UI / "FindingsTable.tsx",
        anchor="          {finding.standard_page ? ` · p${finding.standard_page}` : \"\"}",
        replacement="          {\"\"}",
        target="src/components/review/FindingsTable.test.tsx",
        keyword="clause, page and text",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M324", phase=37, runner="vitest",
        description="word it as missing evidence on screen",
        path=_REVIEW_UI / "reviewFormat.ts",
        anchor='    "Requires another document - not answerable from this submittal type",',
        # B3: follows the missing-information label, whatever it says.
        replacement='    "No value found in the fields read",',
        target="src/components/review/reviewFormat.test.ts",
        keyword="approved wording",
        tags=("honesty", "ui"),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M464", phase=57, runner="vitest",
        description="the run card stops saying which pages were not read into "
                    "fields (B3, UI)",
        path=REPO / "frontend" / "src" / "views" / "ReviewRunsView.tsx",
        anchor='        <p className="mt-1 text-xs text-slateish-500" data-testid="page-coverage">\n'
               "          {pageCoverage}\n"
               "        </p>\n",
        replacement="        <></>\n",
        target="src/views/ReviewRunsView.test.tsx",
        keyword="which pages were not read",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M465", phase=57, runner="vitest",
        description="the page-coverage line drops the unread pages and reads as "
                    "'every page read' (B3, UI)",
        path=REPO / "frontend" / "src" / "components" / "review" / "reviewFormat.ts",
        anchor="  if (!unread.length) return `${head}.`;\n",
        replacement="  return `${head}.`;\n",
        target="src/components/review/reviewFormat.test.ts",
        keyword="names the unread pages",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M472", phase=57, runner="vitest",
        description="an unread-page finding reads as a bare 'Needs engineer "
                    "review', so the drop in missing information looks like a "
                    "regression (B3, owner decision 5)",
        path=_REVIEW_UI / "reviewFormat.ts",
        anchor='  if (finding.compliance_status === "NEEDS_ENGINEER_REVIEW"\n',
        replacement="  if (false\n",
        target="src/components/review/reviewFormat.test.ts",
        keyword="UNREAD_PAGES finding",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M473", phase=57, runner="vitest",
        description="the findings table shows the status's label, not the "
                    "finding's (B3, owner decision 5)",
        path=_REVIEW_UI / "FindingsTable.tsx",
        anchor="          {findingLabel(finding)}\n",
        replacement="          {statusLabel(finding.compliance_status)}\n",
        target="src/components/review/FindingsTable.test.tsx",
        keyword="not a bare status",
        tags=("honesty", "ui"),
    ),
    # ---- B5 live wiring, 2026-09-25
    Mutation(
        id="M746", phase=66, runner="vitest",
        description="B5 live: the review screen drops the selection's evidence line",
        path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
        anchor="          {item.evidence_quote && (\n",
        replacement="          {false && (\n",
        target="src/views/ReviewRunsView.test.tsx",
        keyword="citation line",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M747", phase=66, runner="vitest",
        description="B5 live: the review screen hides cited standards not held",
        path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
        anchor="  const notHeld = missing.length > 0 && (\n",
        replacement="  const notHeld = false && (\n",
        target="src/views/ReviewRunsView.test.tsx",
        keyword="missing",
        tags=("honesty", "ui"),
    ),
    # ---- chat redesign PR 4 (owner order 2026-09-26): the new Chat screen ----
    Mutation(
        id="M955", phase=83, runner="vitest",
        description='general text: a stray [S#] is shown as a source reference',
        path=FRONTEND_SRC / 'components' / 'chat' / 'Markdown.tsx',
        anchor='      if (!onCite) {\n',
        replacement='      if (!onCite) {\n        out.push(token);\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='cites nothing, even a marker',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M956", phase=83, runner="vitest",
        description='model text rendered as HTML',
        path=FRONTEND_SRC / 'components' / 'chat' / 'Markdown.tsx',
        anchor='                <Inline text={line} onCite={onCite} activeSource={activeSource} />\n',
        replacement='                <span dangerouslySetInnerHTML={{ __html: line }} />\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='never renders model text as HTML',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M957", phase=83, runner="vitest",
        description='the points-found badge is never shown',
        path=FRONTEND_SRC / 'components' / 'chat' / 'UsedLine.tsx',
        anchor='          {verification && <VerificationBadge verification={verification} />}\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='counts the points found',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M958", phase=83, runner="vitest",
        description='the quoted words are not marked in the source preview',
        path=FRONTEND_SRC / 'components' / 'chat' / 'SourcePreview.tsx',
        anchor='    if (at >= 0) spans.push([at, at + q.trim().length]);\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='counts the points found',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M959", phase=83, runner="vitest",
        description='Stop never tells the server which turn to stop',
        path=FRONTEND_SRC / 'views' / 'ChatView.tsx',
        anchor='    if (p.turnId) {\n      const r = await api.cancelTurn(',
        replacement='    if (false) {\n      const r = await api.cancelTurn(',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='stops by turn id',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M960", phase=83, runner="vitest",
        description='Stop before the turn id does not close the connection',
        path=FRONTEND_SRC / 'views' / 'ChatView.tsx',
        anchor='    abort.current?.abort();\n  }, []);\n',
        replacement='  }, []);\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='closes the connection when Stop',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M961", phase=83, runner="vitest",
        description='the stream is never read: every answer falls back to the plain route',
        path=FRONTEND_SRC / 'api' / 'client.ts',
        anchor='  if (!(response.headers.get("Content-Type") ?? "").includes("text/event-stream")) {\n',
        replacement='  if (true) {\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='shows the real steps and the text',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M962", phase=83, runner="vitest",
        description='Shift+Enter sends instead of starting a new line',
        path=FRONTEND_SRC / 'components' / 'chat' / 'Composer.tsx',
        anchor='          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {\n',
        replacement='          if (e.key === "Enter" && !e.nativeEvent.isComposing) {\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='starts a new line',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M963", phase=83, runner="vitest",
        description='a question over the limit can be sent',
        path=FRONTEND_SRC / 'components' / 'chat' / 'Composer.tsx',
        anchor='  const canSend = !disabled && !busy && value.trim().length > 0 && !over;\n',
        replacement='  const canSend = !disabled && !busy && value.trim().length > 0;\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='counts toward the limit',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M964", phase=83, runner="vitest",
        description='Undo hides the notice but the delete still goes',
        path=FRONTEND_SRC / 'components' / 'chat' / 'RecentChats.tsx',
        anchor='    timer.current = null;\n    pendingRef.current = null;\n    setPending(null);\n  };\n',
        replacement='    timer.current = null;\n    setPending(null);\n  };\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='Undo means nothing is deleted',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M965", phase=83, runner="vitest",
        description='delete does not ask first',
        path=FRONTEND_SRC / 'components' / 'chat' / 'RecentChats.tsx',
        anchor='                  onClick={() => setConfirming(c.id)}\n',
        replacement='                  onClick={() => remove(c)}\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='asks before deleting',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M966", phase=83, runner="vitest",
        description='leaving inside the Undo window silently keeps the chat',
        path=FRONTEND_SRC / 'components' / 'chat' / 'RecentChats.tsx',
        anchor='    window.addEventListener("pagehide", onHide);\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='leaves inside the Undo window',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M967", phase=83, runner="vitest",
        description='the footer hides that Claude receives the question',
        path=FRONTEND_SRC / 'views' / 'ChatView.tsx',
        anchor='      {model === "claude" &&\n        " Claude writes these answers: your question and the passages it needs are sent to it."}\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='says honestly that Claude receives',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M968", phase=83, runner="vitest",
        description='a draft comment is shown as a plain answer',
        path=FRONTEND_SRC / 'components' / 'chat' / 'AssistantAnswer.tsx',
        anchor='  } else if (draftText) {\n',
        replacement='  } else if (false) {\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='is a draft an engineer edits',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M969", phase=83, runner="vitest",
        description='Exact wording re-asks instead of quoting',
        path=FRONTEND_SRC / 'views' / 'ChatView.tsx',
        anchor='              return q ? () => void send(`/quote ${q}`) : undefined;\n',
        replacement='              return q ? () => void send(q) : undefined;\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='exact wording',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M970", phase=83, runner="vitest",
        description="a written answer loses 'not the document's words'",
        path=FRONTEND_SRC / 'components' / 'chat' / 'GeneratedAnswer.tsx',
        anchor='      <p className="mb-1.5 text-xs text-info-500">{MODEL_WORDS_LABEL(view.model)}</p>\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='counts the points found',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M971", phase=83, runner="vitest",
        description='How I got this is always open',
        path=FRONTEND_SRC / 'components' / 'chat' / 'UsedLine.tsx',
        anchor='      {hasDetail && open && (\n',
        replacement='      {hasDetail && (\n',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='only when asked',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M972", phase=83, runner="vitest",
        description="the server's notices (engineer's judgement) are dropped",
        path=FRONTEND_SRC / 'components' / 'chat' / 'AssistantAnswer.tsx',
        anchor='      {!withheld && <Notices notices={m.notices ?? []} />}\n',
        replacement='',
        target="src/views/ChatView.redesign.test.tsx",
        keyword='engineer notice',
        tags=("chat", "ui"),
    ),
    # ---- chat redesign PR 5: Was this right?, Add to comment sheet, @ a document ----
    Mutation(
        id="M990", phase=84, runner="vitest",
        description="an unsaved 'Was this right?' still shows as chosen",
        path=FRONTEND_SRC / 'components' / 'chat' / 'AnswerActions.tsx',
        anchor='    if (!(await onFeedback(helpful))) {\n      setRated(before);\n',
        replacement='    if (!(await onFeedback(helpful))) {\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='puts the choice back',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M991", phase=84, runner="vitest",
        description="a reopened chat forgets the reader's earlier answer",
        path=FRONTEND_SRC / 'components' / 'chat' / 'AnswerActions.tsx',
        anchor='  const [rated, setRated] = useState<boolean | null>(feedback);\n',
        replacement='  const [rated, setRated] = useState<boolean | null>(null);\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='earlier answer',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M992", phase=84, runner="vitest",
        description="the model's draft is filed instead of the engineer's edit",
        path=FRONTEND_SRC / 'components' / 'chat' / 'DraftCommentCard.tsx',
        anchor='    const r = await onFile(value.trim());\n',
        replacement='    const r = await onFile(plainText(text));\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='files the text on screen',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M993", phase=84, runner="vitest",
        description="Undo is offered after the server's window closed",
        path=FRONTEND_SRC / 'components' / 'chat' / 'DraftCommentCard.tsx',
        anchor='    setUndoOpen(left > 0);\n',
        replacement='    setUndoOpen(true);\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='window has closed',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M994", phase=84, runner="vitest",
        description='a draft naming no document offers a button that must fail',
        path=FRONTEND_SRC / 'components' / 'chat' / 'AssistantAnswer.tsx',
        anchor='          canFile={Array.isArray(m.draft?.source_ids) && (m.draft!.source_ids as unknown[]).length > 0}\n',
        replacement='          canFile={true}\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='names no document',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M995", phase=84, runner="vitest",
        description='a reopened chat offers to file a comment twice',
        path=FRONTEND_SRC / 'components' / 'chat' / 'AssistantAnswer.tsx',
        anchor='          alreadyFiled={Boolean(m.filed_comment)}\n',
        replacement='          alreadyFiled={false}\n',
        target="src/views/ChatView.actions.test.tsx",
        keyword='already filed',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M996", phase=84, runner="vitest",
        description='picked documents are never sent',
        path=FRONTEND_SRC / 'views' / 'ChatView.tsx',
        anchor='        ...(picked.length > 0 ? { document_ids: picked.map((d) => d.id) } : {}),\n',
        replacement='',
        target="src/views/ChatView.actions.test.tsx",
        keyword='documents picked',
        tags=("chat", "ui"),
    ),
    Mutation(
        id="M997", phase=84, runner="vitest",
        description='a comment with no review run is said to be on a comment sheet',
        path=FRONTEND_SRC / 'components' / 'chat' / 'DraftCommentCard.tsx',
        anchor='          {filing.result.review_run_id\n            ? `Added to the comment sheet',
        replacement='          {true\n            ? `Added to the comment sheet',
        target="src/views/ChatView.actions.test.tsx",
        keyword='no review run',
        tags=("chat", "ui"),
    ),
    # ---- chat redesign PR 6: the web lane on screen ----
    Mutation(
        id="M1007", phase=85, runner="vitest",
        description='a web search is offered again after it ran',
        path=FRONTEND_SRC / 'components' / 'chat' / 'WebAnswer.tsx',
        anchor='  const offerable = Boolean(phrase && payload.web_available && !payload.web_searched && onSearch);\n',
        replacement='  const offerable = Boolean(phrase && payload.web_available && onSearch);\n',
        target="src/views/ChatView.web.test.tsx",
        keyword='no second search',
        tags=("privacy", "ui"),
    ),
    Mutation(
        id="M1008", phase=85, runner="vitest",
        description='a search is offered when nothing was safe to send',
        path=FRONTEND_SRC / 'components' / 'chat' / 'WebAnswer.tsx',
        anchor='  const offerable = Boolean(phrase && payload.web_available && !payload.web_searched && onSearch);\n',
        replacement='  const offerable = Boolean(payload.web_available && !payload.web_searched && onSearch);\n',
        target="src/views/ChatView.web.test.tsx",
        keyword='nothing was safe',
        tags=("privacy", "ui"),
    ),
    Mutation(
        id="M1009", phase=85, runner="vitest",
        description='the Web switch is offered when the system forbids it',
        path=FRONTEND_SRC / 'components' / 'chat' / 'Composer.tsx',
        anchor='              disabled={!models.web_available || !onWeb}\n',
        replacement='              disabled={!onWeb}\n',
        target="src/views/ChatView.web.test.tsx",
        keyword='does not allow it',
        tags=("privacy", "ui"),
    ),
    Mutation(
        id="M1010", phase=85, runner="vitest",
        description='a web link opens without noopener',
        path=FRONTEND_SRC / 'components' / 'chat' / 'WebAnswer.tsx',
        anchor='            rel="noopener noreferrer nofollow"\n',
        replacement='            rel="nofollow"\n',
        target="src/views/ChatView.web.test.tsx",
        keyword='sends no text',
        tags=("privacy", "ui"),
    ),
)
