/**
 * The AI Submittal Review block on the Dashboard.
 *
 * MASTER PLAN SECTION 20 AND CLAUDE.md RULE 10, exactly: four primary cards,
 * one prominent `Upload a document and run AI review` button, one compact
 * Recent Reviews table. Nothing else. The rule names what belongs here and
 * this component holds all of it, so a fifth tile cannot be added by editing
 * the Dashboard without editing the rule first.
 *
 * EVERY FIGURE CARRIES ITS POPULATION (CLAUDE.md rule 4): "0 of 2 awaiting
 * review", not a bare 0. And the Needs Attention tile lists WHY, because a
 * tile reading "9" is a number a reader has to trust.
 */
import { formatWhen } from "../../format/when";
import "../kit/kit.css";
import { equipmentLabel } from "../../format/equipment";
import { useCallback, useEffect, useState } from "react";

import { api, reviews as reviewsApi } from "../../api/client";
import type { DocumentRecord, ReviewDashboard } from "../../types/api";
import { StartReviewStep } from "./panels/StartReviewStep";
import { NEW_LOOK } from "../../look";
import { StatusChip, TileLine } from "../look/LookParts";
import { reviewStatusTone } from "../look/lookTone";
import {
  LIST_MAX, runStatusLabel, statusLabel, totalFromResponse,
  truncationNote,
} from "./reviewFormat";
import { Button, LinkButton } from "../kit/Kit";

/** The population of the review cards: the latest review of each paper (earlier runs of a paper are not counted). */
function boundary(data: ReviewDashboard): string {
  if (typeof data.papers_with_a_review !== "number") return "";
  const n = data.papers_with_a_review;
  const earlier = data.earlier_runs_not_counted ?? 0;
  return ` · of ${n.toLocaleString()} paper${n === 1 ? "" : "s"}, latest review each`
    + (earlier > 0 ? ` · ${earlier.toLocaleString()} earlier review${earlier === 1 ? "" : "s"} not counted` : "");
}

type RecentRun = ReviewDashboard["recent"][number];

/** A general review's own words in the Recent reviews table: its comments and confirmations, as the results page counts them. */
function generalFindings(run: RecentRun): string {
  const c = (run.general_counts ?? null) as { comments?: number; confirmations?: number; stopped?: boolean } | null;
  if (!c || typeof c.comments !== "number") return "";
  const sent = `${c.comments.toLocaleString()} comment${c.comments === 1 ? "" : "s"} sent`;
  const held = typeof c.confirmations === "number" ? `, ${c.confirmations.toLocaleString()} confirmation${c.confirmations === 1 ? "" : "s"} not sent` : "";
  return sent + held;
}

/** The status of a row: a general review says whether an engineer signed it; an earlier-method run says so. */
function rowStatus(run: RecentRun): string {
  if (run.method !== "general") return runStatusLabel(run.status, run.waiting_reason);
  const c = (run.general_counts ?? null) as { stopped?: boolean } | null;
  if (run.status !== "completed") return runStatusLabel(run.status, run.waiting_reason);
  const signed = run.general_signoff === "signed" ? "Signed off"
    : run.general_signoff === "changed" ? "Changed since sign-off" : "Not signed off yet";
  return c?.stopped ? `${signed} (stopped early)` : signed;
}

export interface ReviewDashboardPanelProps {
  /** Take the reader to the review page, at this run if one is given. */
  onOpenReview: (runId?: string) => void;
  /** Take the reader to Documents, where upload and its progress live. */
  onOpenDocuments: () => void;
  /** Whether this caller may start a review. `POST /api/reviews/run` is
   *  admin-gated and answers a plain 404 to anyone else - "That is not
   *  something the backend knows about", which reads as the submittal being
   *  missing, not as a permission the reader lacks. Defaults to `true`
   *  (not `false`, unlike `DocumentCard`'s `isAdmin`) because the server is
   *  the real gate either way, and every caller of this panel before #925
   *  assumed the button was reachable; `App.tsx` now passes the real value. */
  isAdmin?: boolean;
}

type Launch =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; message: string };

export function ReviewDashboardPanel(
  { onOpenReview, onOpenDocuments, isAdmin = true }: ReviewDashboardPanelProps,
) {
  const [data, setData] = useState<ReviewDashboard | null>(null);
  // A FAILED LOAD IS NOT AN EMPTY ONE (audit 2026-09-30). The panel used to
  // return null when the dashboard call failed - the Dashboard's one review
  // button vanished with no word why - and to show an empty picker when the
  // submittal list failed, which reads as "no submittals are loaded".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submittals, setSubmittals] = useState<DocumentRecord[] | null>(null);
  const [submittalsError, setSubmittalsError] = useState<string | null>(null);
  const [submittalsTotal, setSubmittalsTotal] = useState<number | null>(null);
  const [picking, setPicking] = useState(false);
  const [target, setTarget] = useState("");
  const [launch, setLaunch] = useState<Launch>({ kind: "idle" });
  const [stepFor, setStepFor] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await reviewsApi.dashboard();
    if (result.ok) {
      setData(result.data);
      setLoadError(null);
    } else {
      // The figures are dropped, not kept: a stale count shown as current
      // is the same class of lie as an unmeasured one.
      setData(null);
      setLoadError(result.error.message);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    // An explicit limit: without one the server stops at 20 and the picker
    // silently omits the rest.
    void api.documents({ document_role: ["CONTRACTOR_SUBMITTAL"], limit: LIST_MAX }).then((r) => {
      if (r.ok) {
        setSubmittals(r.data);
        setSubmittalsTotal(totalFromResponse(r.response));
        setSubmittalsError(null);
      } else {
        setSubmittals(null);
        setSubmittalsError(r.error.message);
      }
    });
  }, []);

  /** THE ONE START: the button opens the pre-start step (engine, what will leave this Mac, the list, the cost); its Start begins. */
  function run() {
    if (!target) return;
    setLaunch({ kind: "idle" });
    setStepFor(target);
  }

  // Still loading: nothing yet, as before. Failed: the block stays, says
  // what failed, and keeps the button - starting a review does not need the
  // dashboard's counts.
  if (!data && loadError === null) return null;

  return (
    <section
      aria-labelledby="review-dashboard-title"
      className="mt-6 rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="review-dashboard-title" className="text-sm font-semibold text-slateish-200">
          AI Submittal Review
        </h2>
        <LinkButton weight="medium" tone="action" size="xs" onClick={() => onOpenReview()}>
          Open all reviews
        </LinkButton>
      </div>

      {/* THE BOUNDARY OF EVERY COUNT BELOW (CLAUDE.md rule 4). The review
          dashboard is always counted over the caller's own grants, even for
          an admin whose system figures elsewhere on this screen are
          corpus-wide. */}
      <p className="mt-1 text-xs text-slateish-400" data-testid="review-boundary">
        These review counts cover only the documents you can open.
      </p>

      {loadError !== null && (
        <div role="alert" className="mt-3 rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-500">
          The review figures could not be loaded - {loadError}. This is not a
          count of zero.{" "}
          <LinkButton weight="medium" tone="inherit" onClick={() => void load()}>
            Try again
          </LinkButton>
        </div>
      )}

      {/* ------------------------------------------- the four cards */}
      {data && (
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Card
          label="Submittals" // one line in its card at every width (lead 4's 07:48 audit: "Contractor submittals" wrapped at 800)
          value={data.submittals_total}
          detail={`${data.submittals_awaiting_review} of ${data.submittals_total} awaiting review`}
        />
        <Card
          label="Active standards"
          value={data.standards_available}
          detail={
            data.standards_referenced_total
              ? `${data.standards_referenced_missing} of ${data.standards_referenced_total} cited standards are not in the library`
              : "no citations read from the submittals yet"
          }
          tone={data.standards_referenced_missing ? "warn" : undefined}
        />
        <Card
          label="Reviews in progress"
          value={data.reviews_running}
          detail={`${data.reviews_running} running · ${data.reviews_awaiting_decision} waiting for an engineer's sign-off or code`
            + (typeof data.reviews_signed === "number" ? ` · ${data.reviews_signed} signed off (done)` : "")
            + boundary(data)}
        />
        <Card
          label="Needs attention"
          value={data.needs_attention}
          tone={data.needs_attention ? "warn" : undefined}
          detail={
            (Object.entries(data.needs_attention_reasons)
              .map(([reason, count]) => `${count} ${reason}`)
              .join(" · ") || "nothing") + boundary(data)
          }
        />
      </div>
      )}

      {/* --------------------------------------------- the one button */}
      <div className="mt-4">
        <Button variant="primary"
          onClick={() => setPicking((value) => !value)}
          disabled={!isAdmin}
        >
          Upload a document and run AI review
        </Button>
        {/* THE REASON, not a quietly-greyed-out button. The server gives a
            non-admin a 404 that reads as "no such submittal", not as "you
            lack permission" - this says the real reason before anyone has to
            guess from a confusing error. */}
        {!isAdmin && (
          <p className="mt-1 text-xs text-slateish-400">
            Only an administrator can start a review.
          </p>
        )}

        {isAdmin && picking && (
          <div className="mt-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3">
            <label className="block text-xs text-slateish-400" htmlFor="dash-target">
              Run a review on a datasheet already loaded
            </label>
            {submittalsError !== null && (
              <p role="alert" className="mt-1 rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-500">
                The list of contractor submittals could not be loaded - {submittalsError}.
                It is not known whether any are loaded.
              </p>
            )}
            {truncationNote((submittals ?? []).length, submittalsTotal, "contractor submittals") && (
              <p className="mt-1 text-xs text-slateish-400" data-testid="submittals-boundary">
                {truncationNote((submittals ?? []).length, submittalsTotal, "contractor submittals")}
              </p>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <select
                id="dash-target" value={target}
                onChange={(event) => setTarget(event.target.value)}
                className="min-w-[16rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-slateish-100"
              >
                <option value="">Choose a contractor submittal…</option>
                {(submittals ?? []).map((doc) => (
                  <option key={doc.id} value={doc.id}>{doc.filename}</option>
                ))}
              </select>
              <Button variant="primary"
                onClick={run}
                disabled={!target || launch.kind === "running" || stepFor !== null}
              >
                {launch.kind === "running" ? "Running…" : "Run AI review"}
              </Button>
            </div>
            {stepFor && (
              <div className="mt-2">
                <StartReviewStep
                  documentId={stepFor}
                  filename={(submittals ?? []).find((d) => d.id === stepFor)?.filename ?? null}
                  onCancel={() => setStepFor(null)}
                  // STRAIGHT TO THE FINDINGS: landing the reader back on a dashboard would make them look for what they asked for.
                  onStarted={(runId) => { setStepFor(null); setPicking(false); onOpenReview(runId); }}
                />
              </div>
            )}
            {launch.kind === "running" && (
              <p aria-live="polite" className="mt-2 text-xs text-slateish-300">
                Selecting applicable standards and comparing requirements.
              </p>
            )}
            {launch.kind === "error" && (
              <p role="alert" className="mt-2 rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-500">
                {launch.message}
              </p>
            )}
            {/* UPLOAD LIVES WHERE UPLOAD PROGRESS LIVES. A new file has to be
                ingested - extracted, chunked, embedded - before there is
                anything to review, and the Documents screen is what shows
                that happening. A second uploader here would either hide the
                wait or duplicate the screen that reports it. */}
            <p className="mt-3 text-xs text-slateish-400">
              Need to add a new datasheet?{" "}
              <LinkButton weight="medium" tone="action" onClick={onOpenDocuments}>
                Upload it on the Documents page
              </LinkButton>{" "}
              — it appears here once it has finished processing.
            </p>
          </div>
        )}
      </div>

      {/* ----------------------------------------- Recent Reviews table */}
      {data && (
      <div className="mt-4">
        {/* one heading style on the page (owner's design audit, 26 Nov 2026 23:05, F): sentence case like the others in the new look */}
        <h3 className={NEW_LOOK ? "text-base font-semibold text-slateish-200" : "text-xs uppercase tracking-wide text-slateish-400"}>
          Recent reviews
        </h3>
        {data.recent.length === 0 ? (
          <p className="mt-2 text-xs text-slateish-400">
            No reviews have been run yet.
          </p>
        ) : (
          <div className={NEW_LOOK ? "kit-stack-wrap relative mt-3 overflow-x-auto rounded-[var(--radius-md)] bg-ink-800" : "relative mt-2 overflow-x-auto rounded-[var(--radius-md)] border border-ink-700"}
            data-testid="dashboard-runs-table-box">
            {/* the new look: on a narrow box each row stacks, every column named (H's audit 1); a wide box keeps the table */}
            <table className={NEW_LOOK ? "kit-stack-table w-full text-left text-sm" : "w-full text-left text-xs"}>
              <thead className={NEW_LOOK ? "text-xs font-semibold text-slateish-400" : "bg-ink-900 uppercase tracking-wide text-slateish-400"}>
                <tr>
                  <th scope="col" className={HEAD}>Document</th>
                  <th scope="col" className={HEAD}>Equipment</th>
                  <th scope="col" className={HEAD}>Findings or comments</th>
                  <th scope="col" className={HEAD}>Suggested code</th>
                  <th scope="col" className={HEAD}>Status</th>
                  <th scope="col" className={HEAD}><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((run) => (
                  <tr key={run.review_run_id} className={NEW_LOOK ? "border-t border-ink-700/60" : "border-t border-ink-800"}>
                    <td className={NEW_LOOK ? "whitespace-nowrap px-3 py-3.5 text-slateish-200" : "px-3 py-2 text-slateish-200"}>
                      {NEW_LOOK ? (
                        // one line (owner): a long name stops at a set width with a visible "…", whole on hover
                        <span className="inline-block max-w-[12rem] truncate align-bottom" title={run.submittal_filename ?? undefined}>{run.submittal_filename}</span>
                      ) : run.submittal_filename}
                      <span className={NEW_LOOK ? "ms-2 whitespace-nowrap text-xs text-slateish-500" : "block text-slateish-500"}>
                        {formatWhen(run.created_at)}{run.method === "general" ? "" : " · earlier version"}
                      </span>
                    </td>
                    <td className={CELL} data-label="Equipment" title={run.equipment_tags.join(", ") || undefined}>
                      {equipmentLabel(run.equipment_tags) || null}
                    </td>
                    <td className={NEW_LOOK ? `${CELL} min-w-[10.5rem]` : CELL} data-label="Findings or comments">
                      {/* The count as it is, 0 included: the run record does not say whether it is an AI review, so no guess. A general review says its own comments. */}
                      {run.method === "general" ? generalFindings(run) : run.findings_total.toLocaleString()}
                      {run.method !== "general" && run.by_status.NON_COMPLIANT ? (
                        <span className="kit-chip kit-chip--late">
                          {run.by_status.NON_COMPLIANT} {statusLabel("NON_COMPLIANT").toLowerCase()}
                        </span>
                      ) : null}
                    </td>
                    <td className={CELL} data-label="Suggested code">
                      {/* order 14: one run never shows an approving code; the server's note stands in its place */}
                      {(run.recommended_code ?? run.recommended_code_note) || null}
                      {/* BOTH CODES, NEVER ONE. An engineer's decision does
                          not delete what the machine recommended. */}
                      {run.engineer_final_code && (
                        <span className="block text-slateish-400">
                          engineer: {run.engineer_final_code}
                        </span>
                      )}
                    </td>
                    {/* its own label when the row stacks (F's gate: the chip landed after "Suggested code:" and read as the code) */}
                    <td className={NEW_LOOK ? "whitespace-nowrap px-3 py-3.5" : "px-3 py-2 text-slateish-300"} data-label="Status">
                      {NEW_LOOK ? <StatusChip tone={reviewStatusTone(rowStatus(run))}>{rowStatus(run)}</StatusChip> : rowStatus(run)}
                    </td>
                    <td className={NEW_LOOK ? "px-3 py-3.5 text-right" : "px-3 py-2"}>
                      <Button size="sm" onClick={() => onOpenReview(run.review_run_id)}>
                        Open
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}
    </section>
  );
}

/** The table cells: the classic padding, or the new look's taller rows (owner: "more row height"). */
const CELL = NEW_LOOK ? "px-3 py-3.5 text-slateish-300" : "px-3 py-2 text-slateish-300";
const HEAD = NEW_LOOK ? "px-3 py-2.5" : "px-3 py-2";

function Card({ label, value, detail, tone }: {
  label: string; value: number; detail: string; tone?: "warn";
}) {
  if (NEW_LOOK) {
    // the new look (owner): one big number, a short label, at most one short line; a long line folds behind "Details", never dropped
    return (
      // the shared kit's card, with the tiles' name and number styles: one tile look on the Dashboard (H's gate, 27 Nov 2026)
      <div className="kit-card">
        <p className="kit-tile__name">{label}</p>
        <p className={tone === "warn" ? "kit-tile__number text-warn-500" : "kit-tile__number"}>
          {value.toLocaleString()}
        </p>
        <TileLine text={detail} />
      </div>
    );
  }
  return (
    <div className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3">
      <p className="text-xs uppercase tracking-wide text-slateish-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${tone === "warn" ? "text-warn-500" : "text-slateish-100"}`}>
        {value.toLocaleString()}
      </p>
      {/* THE DENOMINATOR, ALWAYS. A bare count on a tile reads as total. */}
      <p className="mt-1 text-xs text-slateish-400">{detail}</p>
    </div>
  );
}
