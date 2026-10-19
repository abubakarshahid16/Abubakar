/**
 * The pages a review keeps behind links (#967 PR 3, "moves"): all findings,
 * the standards in scope, how the document was checked, the AI numbers and
 * the CRS. Each is a route of its own (`/review/<run>/<panel>`) and is
 * built from the panels the old stacked page showed - moved, not rewritten,
 * so what they say is unchanged (rule 2: one version of each part).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type {
  CrsPreview, DocumentRecord, ReviewFinding, ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary,
} from "../../../types/api";
import { CRS_SHEET_IS_DEFAULT, PANELS, panelForReviewScreen } from "../../../routing";
import { NavLink } from "../../NavLink";
import { ReviewPipeline } from "../../../views/ReviewPipeline";
import { AiNumbersPanel } from "../AiNumbersPanel";
import { CrsPreviewSheet } from "../CrsPreviewSheet";
import { downloadCrs } from "../downloadCrs";
import { FindingDetail } from "../FindingDetail";
import { FindingsTable } from "../FindingsTable";
import { ReviewStepsPanel } from "../ReviewStepsPanel";
import { RunCoverageLine } from "../RunCoverageLine";
import { StandardOverrideControl } from "../StandardOverrideControl";
import { groupFindingsByTopic } from "../reviewFormat";
import { ReviewNotes } from "./ReviewNotes";
import { RequirementSplitPanel, RequirementsNotAppliedList, TableValuesNotComparedList } from "./RunDetailLists";
import { RunSummary } from "./RunSummary";
import { StandardsInScope } from "./StandardsInScope";

export const PANEL_TITLES: Record<string, string> = {
  findings: "All findings",
  standards: "The rule books used",
  steps: "How we checked this document",
  numbers: "What each AI step did on this review",
  crs: "Comment Resolution Sheet",
};

export interface StandardsState {
  standards: ReviewRunStandard[] | null;
  missing: ReviewRunMissingReference[];
  error: string | null;
}

export interface BehindTheScenesProps {
  panel: string;
  run: ReviewRunSummary;
  findings: ReviewFinding[];
  documents: DocumentRecord[];
  standardsState: StandardsState;
  /** #791: the status a count in the review steps was clicked for. */
  focusStatus: string | null;
  onOpenPanel: (panel?: string) => void;
  onFocusStatus: (status: string) => void;
  onStandardsChanged: (changed: ReviewRunStandard[], missing: ReviewRunMissingReference[]) => void;
  onChanged: () => void;
  /** v2.1 (W2): shown inside the review workspace, whose own tab strip
   *  already names the page. Hides this component's own navigation and
   *  heading, so the reader sees one set of tabs. Default false: the old
   *  screens are unchanged. */
  embedded?: boolean;
}

export function BehindTheScenes(props: BehindTheScenesProps) {
  const { panel, run, onOpenPanel, embedded = false } = props;
  const known = (PANELS.review ?? []).includes(panel);
  return (
    <div className="space-y-4">
      {!embedded && (
        <>
        <nav aria-label="Behind the scenes" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <button type="button" onClick={() => onOpenPanel(undefined)} className="text-signal-300 underline-offset-2 hover:underline">
            ← Back to the sheet
          </button>
          {/* Only the behind-the-scenes pages: "cards" and "crs-sheet" are the
              two review screens themselves, not pages behind them. */}
          {(PANELS.review ?? []).filter((name) => name in PANEL_TITLES).map((name) => (
            <button
              key={name} type="button" onClick={() => onOpenPanel(name)}
              aria-current={name === panel ? "page" : undefined}
              className={name === panel ? "font-semibold text-slateish-100" : "text-slateish-300 hover:text-slateish-100"}
            >
              {PANEL_TITLES[name]}
            </button>
          ))}
        </nav>
        <h2 className="text-lg font-semibold text-slateish-100">
          {PANEL_TITLES[panel] ?? "Behind the scenes"} · {run.submittal_filename}
        </h2>
        </>
      )}
      {!known && <p className="text-sm text-slateish-400">There is no such page for this review.</p>}
      {panel === "findings" && <AllFindingsPage {...props} />}
      {panel === "standards" && <StandardsPage {...props} />}
      {panel === "steps" && <StepsPage {...props} />}
      {panel === "numbers" && <NumbersPage {...props} />}
      {panel === "crs" && <CrsSheetPage runId={run.review_run_id} inWorkspace={embedded} />}
    </div>
  );
}

/** Standard document id -> the filename an engineer would recognise. */
function useStandardNames(standards: ReviewRunStandard[] | null) {
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const item of standards ?? []) {
      if (item.filename) map.set(item.standard_document_id, item.filename);
    }
    return map;
  }, [standards]);
}

/** Owner order section 3: COMMENTS GROUPED BY TOPIC - the field a comment is
 *  about - so ten findings on one field read as one group rather than ten
 *  unrelated rows. Ungrouped when there is only one group. #791: a count
 *  clicked in the review steps shows only the findings it counts. */
function AllFindingsPage({ run, findings, documents, standardsState, focusStatus, onChanged }: BehindTheScenesProps) {
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const standardNames = useStandardNames(standardsState.standards);
  const finding = findings.find((item) => item.id === selectedFinding) ?? null;
  const groups = groupFindingsByTopic(findings);
  const table = (list: ReviewFinding[], initialStatus?: string) => (
    <FindingsTable
      findings={list} selectedId={selectedFinding} documents={documents}
      standardNames={standardNames} onSelect={(item) => setSelectedFinding(item.id)}
      initialStatus={initialStatus}
    />
  );
  return (
    <div className="space-y-4">
      {focusStatus ? table(findings, focusStatus)
        : groups.length <= 1 ? table(findings)
        : (
          <div className="space-y-4" data-testid="findings-by-topic">
            {groups.map((group) => (
              <div key={group.topic}>
                <h3 className="mb-1 text-sm font-semibold text-slateish-200">{group.topic} ({group.findings.length})</h3>
                {table(group.findings)}
              </div>
            ))}
          </div>
        )}
      {finding && (
        <FindingDetail
          key={finding.id} finding={finding} documents={documents} standardNames={standardNames}
          whyApplies={standardsState.standards === null ? undefined
            : standardsState.standards.find((s) => s.standard_document_id === finding.standard_document_id) ?? null}
          onChanged={onChanged}
        />
      )}
      <p className="text-xs text-slateish-500">{findings.length} findings of this run.</p>
      {run.review_run_id ? null : null}
    </div>
  );
}

function StandardsPage({ run, standardsState, onStandardsChanged, onChanged }: BehindTheScenesProps) {
  return (
    <div className="space-y-4">
      <StandardsInScope standards={standardsState.standards} missing={standardsState.missing} error={standardsState.error} />
      <StandardOverrideControl
        key={run.review_run_id} runId={run.review_run_id} decided={Boolean(run.engineer_final_code)}
        onChanged={(changed, missing) => { onStandardsChanged(changed, missing); onChanged(); }}
      />
    </div>
  );
}

function StepsPage({ run, onFocusStatus, onOpenPanel }: BehindTheScenesProps) {
  return (
    <div className="space-y-4">
      {/* PF4 (#884): the run's applicable rules, each accounted for. */}
      <RunCoverageLine key={`coverage-${run.review_run_id}`} runId={run.review_run_id} />
      <ReviewStepsPanel
        key={`steps-${run.review_run_id}`} run={run}
        onShowStatus={(status) => { onFocusStatus(status); onOpenPanel("findings"); }}
      />
      {/* #791: how this run was done, step by step. */}
      <ReviewPipeline key={`pipeline-${run.review_run_id}`} runId={run.review_run_id} />
      {run.requirement_split && <RequirementSplitPanel split={run.requirement_split} />}
      {(run.requirements_not_applied?.length ?? 0) > 0 && (
        <RequirementsNotAppliedList lines={run.requirements_not_applied ?? []} />
      )}
      {(run.table_values_not_compared?.length ?? 0) > 0 && (
        <TableValuesNotComparedList lines={run.table_values_not_compared ?? []} />
      )}
    </div>
  );
}

function NumbersPage({ run, findings }: BehindTheScenesProps) {
  return (
    <div className="space-y-4">
      <RunSummary findings={findings} />
      <AiNumbersPanel numbers={run.ai_numbers} />
    </div>
  );
}

/** The deliverable without leaving the application: the sheet on screen from
 *  the same builder as the file, the two exports, and what still stands
 *  between this run and the contractor's copy (PF5).
 *
 *  v2.1 (S3): also the workspace's "CRS" tab (workspace/crs/CrsTabPanel).
 *  There (`inWorkspace`) the sheet opens by itself, since opening the tab is
 *  asking to see it, and the link to sign on the old comment sheet becomes a
 *  pointer to the workspace's own Sign and export, so the reader never
 *  leaves the workspace to sign.
 *
 *  Order 141 D: both the sheet and the internal copy are read from the
 *  record. In the workspace `beforeCopy` saves the decisions on screen
 *  first; when it cannot, the sheet says so above itself and the copy is
 *  not downloaded (plain words instead), never a copy that silently leaves
 *  the engineer's Keep / Edit / Remove out. */
export function CrsSheetPage({ runId, inWorkspace = false, beforeCopy }: {
  runId: string; inWorkspace?: boolean; beforeCopy?: () => Promise<string | null>;
}) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CrsPreview | null>(null);
  const [previewing, setPreviewing] = useState(inWorkspace);
  const [previewError, setPreviewError] = useState<string | null>(null);
  /** Why the sheet on screen may not show every decision; null when it does. */
  const [copyWaits, setCopyWaits] = useState<string | null>(null);
  const beforeCopyRef = useRef(beforeCopy);
  useEffect(() => { beforeCopyRef.current = beforeCopy; }, [beforeCopy]);

  // Inside the workspace the tab itself is the request to see the sheet.
  useEffect(() => {
    if (!inWorkspace) return;
    let live = true;
    void (async () => {
      const waits = beforeCopyRef.current ? await beforeCopyRef.current() : null;
      if (!live) return;
      setCopyWaits(waits);
      const result = await reviewsApi.previewCrs(runId);
      if (!live) return;
      setPreviewing(false);
      if (result.ok) setPreview(result.data);
      else setPreviewError(`The sheet could not be loaded: ${result.error.message}`);
    })();
    return () => { live = false; };
  }, [inWorkspace, runId]);

  async function exportCrs() {
    setExporting(true);
    setExportError(null);
    const waits = beforeCopy ? await beforeCopy() : null;
    if (waits) {
      setExportError(waits);
      setExporting(false);
      return;
    }
    // Saved now: the sheet on screen is read again if it was missing some.
    if (copyWaits) { setCopyWaits(null); void refreshPreview(); }
    setExportError(await downloadCrs(runId, "internal"));
    setExporting(false);
  }

  /** Fetched on open rather than with the run: a sheet nobody asked to see
   *  is a request nobody asked for. */
  async function togglePreview() {
    if (preview) { setPreview(null); setPreviewError(null); return; }
    setPreviewing(true);
    setPreviewError(null);
    const result = await reviewsApi.previewCrs(runId);
    setPreviewing(false);
    // SHOWN AS THE API RETURNED IT: a 404 here means this caller may not
    // read the submittal, and a friendlier sentence would hide which it was.
    if (!result.ok) { setPreviewError(result.error.message); return; }
    setPreview(result.data);
  }

  /** Order 141 D: save the decisions on screen, then read the sheet again. */
  async function readAgain() {
    const waits = beforeCopy ? await beforeCopy() : null;
    setCopyWaits(waits);
    if (!waits) await refreshPreview();
  }

  async function refreshPreview() {
    const result = await reviewsApi.previewCrs(runId);
    if (result.ok) setPreview(result.data); else setPreviewError(result.error.message);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {/* READ ACCESS SUFFICES and the server says so: exporting writes
            nothing, decides nothing and records no judgement. */}
        <button type="button" onClick={() => void exportCrs()} disabled={exporting}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50">
          {exporting ? "Preparing…" : "Export CRS - internal review copy"}
        </button>
        {/* Order 121: the contractor's copy is signed on the comment sheet
            ("Before you sign"), never here; this page only links there.
            Inside the workspace, signing is its own Sign and export. */}
        {inWorkspace ? (
          <span data-testid="crs-tab-sign-hint" className="text-sm text-slateish-400">
            To send it to the contractor, use Sign and export at the top.
          </span>
        ) : (
          <NavLink view="review" recordId={runId} panel={panelForReviewScreen("crsSheet", CRS_SHEET_IS_DEFAULT)}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-signal-300">
            Sign and export on the comment sheet
          </NavLink>
        )}
        {inWorkspace ? (
          previewing && <span className="text-sm text-slateish-400">Loading the sheet…</span>
        ) : (
          <button type="button" onClick={() => void togglePreview()} disabled={previewing} aria-expanded={preview !== null}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50">
            {previewing ? "Loading…" : preview ? "Hide CRS preview" : "Preview CRS"}
          </button>
        )}
      </div>
      {exportError && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-500">{exportError}</p>
      )}
      {previewError && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-500">{previewError}</p>
      )}
      {copyWaits && (
        <p role="status" data-testid="crs-copy-waits"
          className="flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-slateish-100">
          <span>{copyWaits} The sheet below shows the record as it is now.</span>
          <button type="button" onClick={() => void readAgain()}
            className="text-signal-300 underline-offset-2 hover:underline">
            Save and read the sheet again
          </button>
        </p>
      )}
      {preview && <CrsPreviewSheet preview={preview} runId={runId} onChanged={() => void refreshPreview()} />}
      <ReviewNotes key={runId} runId={runId} />
    </div>
  );
}
