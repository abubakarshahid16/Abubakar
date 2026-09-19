/**
 * The AI Submittal Review block on the Dashboard.
 *
 * MASTER PLAN SECTION 20 AND CLAUDE.md RULE 10, exactly: four primary cards,
 * one prominent `Upload Datasheet and Run AI Review` button, one compact
 * Recent Reviews table. Nothing else. The rule names what belongs here and
 * this component holds all of it, so a fifth tile cannot be added by editing
 * the Dashboard without editing the rule first.
 *
 * EVERY FIGURE CARRIES ITS POPULATION (CLAUDE.md rule 4): "0 of 2 awaiting
 * review", not a bare 0. And the Needs Attention tile lists WHY, because a
 * tile reading "9" is a number a reader has to trust.
 */
import { useCallback, useEffect, useState } from "react";

import { api, reviews as reviewsApi } from "../../api/client";
import type { DocumentRecord, ReviewDashboard } from "../../types/api";
import { statusLabel, statusTone, whenLabel } from "./reviewFormat";

export interface ReviewDashboardPanelProps {
  /** Take the reader to the review page, at this run if one is given. */
  onOpenReview: (runId?: string) => void;
  /** Take the reader to Documents, where upload and its progress live. */
  onOpenDocuments: () => void;
}

type Launch =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; message: string };

export function ReviewDashboardPanel(
  { onOpenReview, onOpenDocuments }: ReviewDashboardPanelProps,
) {
  const [data, setData] = useState<ReviewDashboard | null>(null);
  const [submittals, setSubmittals] = useState<DocumentRecord[]>([]);
  const [picking, setPicking] = useState(false);
  const [target, setTarget] = useState("");
  const [launch, setLaunch] = useState<Launch>({ kind: "idle" });

  const load = useCallback(async () => {
    const result = await reviewsApi.dashboard();
    if (result.ok) setData(result.data);
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    void api.documents({ document_role: ["CONTRACTOR_SUBMITTAL"] }).then((r) => {
      if (r.ok) setSubmittals(r.data);
    });
  }, []);

  async function run() {
    if (!target) return;
    setLaunch({ kind: "running" });
    const result = await reviewsApi.startReviewRun(target);
    if (!result.ok) {
      setLaunch({ kind: "error", message: result.error.message });
      return;
    }
    setLaunch({ kind: "idle" });
    setPicking(false);
    // STRAIGHT TO THE FINDINGS. The reader pressed a button that says it
    // runs a review; landing them back on a dashboard would make them go
    // looking for the thing they just asked for.
    onOpenReview(result.data.review_run_id);
  }

  if (!data) return null;

  return (
    <section
      aria-labelledby="review-dashboard-title"
      className="mt-6 rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="review-dashboard-title" className="text-sm font-semibold text-slateish-200">
          AI Submittal Review
        </h2>
        <button
          type="button" onClick={() => onOpenReview()}
          className="text-xs font-medium text-signal-400 hover:underline"
        >
          Open all reviews
        </button>
      </div>

      {/* ------------------------------------------- the four cards */}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Card
          label="Contractor submittals"
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
          value={data.reviews_running + data.reviews_awaiting_decision}
          detail={`${data.reviews_running} running · ${data.reviews_awaiting_decision} awaiting an engineer's code`}
        />
        <Card
          label="Needs attention"
          value={data.needs_attention}
          tone={data.needs_attention ? "warn" : undefined}
          detail={
            Object.entries(data.needs_attention_reasons)
              .map(([reason, count]) => `${count} ${reason}`)
              .join(" · ") || "nothing"
          }
        />
      </div>

      {/* --------------------------------------------- the one button */}
      <div className="mt-4">
        <button
          type="button" onClick={() => setPicking((value) => !value)}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950"
        >
          Upload Datasheet and Run AI Review
        </button>

        {picking && (
          <div className="mt-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3">
            <label className="block text-xs text-slateish-400" htmlFor="dash-target">
              Run a review on a datasheet already loaded
            </label>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <select
                id="dash-target" value={target}
                onChange={(event) => setTarget(event.target.value)}
                className="min-w-[16rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-slateish-100"
              >
                <option value="">Choose a contractor submittal…</option>
                {submittals.map((doc) => (
                  <option key={doc.id} value={doc.id}>{doc.filename}</option>
                ))}
              </select>
              <button
                type="button" onClick={() => void run()}
                disabled={!target || launch.kind === "running"}
                className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
              >
                {launch.kind === "running" ? "Running…" : "Run AI review"}
              </button>
            </div>
            {launch.kind === "running" && (
              <p aria-live="polite" className="mt-2 text-xs text-slateish-300">
                Selecting applicable standards and comparing requirements.
              </p>
            )}
            {launch.kind === "error" && (
              <p role="alert" className="mt-2 rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
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
              <button
                type="button" onClick={onOpenDocuments}
                className="font-medium text-signal-400 hover:underline"
              >
                Upload it on the Documents page
              </button>{" "}
              — it appears here once it has finished processing.
            </p>
          </div>
        )}
      </div>

      {/* ----------------------------------------- Recent Reviews table */}
      <div className="mt-4">
        <h3 className="text-xs uppercase tracking-wide text-slateish-400">
          Recent reviews
        </h3>
        {data.recent.length === 0 ? (
          <p className="mt-2 text-xs text-slateish-400">
            No reviews have been run yet.
          </p>
        ) : (
          <div className="mt-2 overflow-x-auto rounded-[var(--radius-md)] border border-ink-700">
            <table className="w-full text-left text-xs">
              <thead className="bg-ink-900 uppercase tracking-wide text-slateish-400">
                <tr>
                  <th scope="col" className="px-3 py-2">Document</th>
                  <th scope="col" className="px-3 py-2">Equipment</th>
                  <th scope="col" className="px-3 py-2">Findings</th>
                  <th scope="col" className="px-3 py-2">Recommended</th>
                  <th scope="col" className="px-3 py-2">Status</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((run) => (
                  <tr key={run.review_run_id} className="border-t border-ink-800">
                    <td className="px-3 py-2 text-slateish-200">
                      {run.submittal_filename}
                      <span className="block text-slateish-500">{whenLabel(run.created_at)}</span>
                    </td>
                    <td className="px-3 py-2 text-slateish-300">
                      {run.equipment_tags.join(", ")}
                    </td>
                    <td className="px-3 py-2 text-slateish-300">
                      {run.findings_total.toLocaleString()}
                      {run.by_status.NON_COMPLIANT ? (
                        <span className={`ml-1 rounded-full border px-1.5 ${statusTone("NON_COMPLIANT")}`}>
                          {run.by_status.NON_COMPLIANT} {statusLabel("NON_COMPLIANT").toLowerCase()}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-slateish-300">
                      {run.recommended_code}
                      {/* BOTH CODES, NEVER ONE. An engineer's decision does
                          not delete what the machine recommended. */}
                      {run.engineer_final_code && (
                        <span className="block text-slateish-400">
                          engineer: {run.engineer_final_code}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slateish-300">{run.status}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button" onClick={() => onOpenReview(run.review_run_id)}
                        className="font-medium text-signal-400 hover:underline"
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Card({ label, value, detail, tone }: {
  label: string; value: number; detail: string; tone?: "warn";
}) {
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
