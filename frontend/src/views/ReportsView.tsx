/**
 * Reports. Every report here is a single-answer evidence report - one question,
 * the quoted evidence, the documents cited - frozen at generation time.
 *
 * Rules carried from docs/design-pdf-report.md section E and the auth design:
 *  - A report is listed only when every document it cites is still in the
 *    reader's scope. Hidden reports are COUNTED, never described.
 *  - Documents are named by filename and sha256 prefix. Never a path.
 *  - Verification says plainly whether the snapshot and file are intact and
 *    whether cited evidence has since changed. Drift is amber and never hidden.
 *  - not_implemented_sections are listed by name. A missing section is an
 *    omission the reader can see, not a blank.
 *
 * Data flow is by props; this component calls no api.* function itself.
 */
import { useState } from "react";

import { EmptyState, Spinner } from "../components/states";
import type { ReportRecord, ReportVerification } from "../types/analysis";

const nf = new Intl.NumberFormat("en-GB");

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+/, "").replace("Z", " UTC");
}

export function ReportsView({
  reports,
  onGenerate,
  onDownload,
  onVerify,
  suppressedCount,
}: {
  /** null = still loading */
  reports: ReportRecord[] | null;
  onGenerate?: () => void;
  onDownload: (id: string) => void;
  onVerify: (id: string) => Promise<ReportVerification>;
  /** Reports hidden because a cited document left the reader's scope. */
  suppressedCount: number;
}) {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slateish-200">Reports</h1>
        <p className="mt-1 text-sm text-slateish-400">
          Every report is a single-answer evidence report: one question, the quoted
          evidence, and the documents it came from, frozen when it was generated.
        </p>
      </header>

      {suppressedCount > 0 && (
        <p
          role="status"
          className="rounded border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-slateish-300"
        >
          <span aria-hidden="true">◌ </span>
          {nf.format(suppressedCount)} report{suppressedCount === 1 ? " is" : "s are"} not
          shown because a document {suppressedCount === 1 ? "it cites" : "they cite"} is no
          longer in your scope.
        </p>
      )}

      <section aria-labelledby="reports-heading">
        <h2 id="reports-heading" className="sr-only">
          Report list
        </h2>

        {reports === null && <Spinner label="Loading reports" />}

        {reports !== null && reports.length === 0 && (
          <EmptyState
            title="No reports yet"
            hint="Generate a report from an answer in Chat. It records the question, the quoted evidence and the documents cited."
            action={
              onGenerate && (
                <button
                  type="button"
                  onClick={onGenerate}
                  className="rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30"
                >
                  Generate a report
                </button>
              )
            }
          />
        )}

        {reports !== null && reports.length > 0 && (
          <ul className="space-y-3">
            {reports.map((r) => (
              <ReportRow key={r.id} report={r} onDownload={onDownload} onVerify={onVerify} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

type VerifyState =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "done"; result: ReportVerification }
  | { state: "failed" };

function ReportRow({
  report,
  onDownload,
  onVerify,
}: {
  report: ReportRecord;
  onDownload: (id: string) => void;
  onVerify: (id: string) => Promise<ReportVerification>;
}) {
  const [verify, setVerify] = useState<VerifyState>({ state: "idle" });

  const runVerify = async () => {
    setVerify({ state: "checking" });
    try {
      const result = await onVerify(report.id);
      setVerify({ state: "done", result });
    } catch {
      setVerify({ state: "failed" });
    }
  };

  return (
    <li className="rounded-lg border border-ink-700 bg-ink-850">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium text-slateish-200">{report.question}</h3>
          {report.resolved_question && report.resolved_question !== report.question && (
            <p className="mt-0.5 text-xs text-slateish-400">
              Read as: {report.resolved_question}
            </p>
          )}

          <p className="mt-1 font-mono text-xs text-slateish-400">
            {formatWhen(report.created_at)} · {nf.format(report.page_count)} page
            {report.page_count === 1 ? "" : "s"} · {formatBytes(report.size_bytes)} ·{" "}
            {report.owner_username ?? "authentication disabled — no user recorded"}
          </p>

          <div className="mt-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slateish-400">
              Documents cited
            </p>
            {report.documents.length === 0 ? (
              <p className="mt-1 text-xs text-slateish-400">None recorded.</p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {report.documents.map((d) => (
                  <li key={d.document_id} className="text-xs text-slateish-300">
                    <span>{d.filename}</span>{" "}
                    <span className="font-mono text-slateish-400">{d.sha256_prefix}</span>
                    {d.revision && <span className="text-slateish-400"> · rev {d.revision}</span>}
                    {d.approval_status && (
                      <span className="text-slateish-400"> · {d.approval_status}</span>
                    )}
                    <span className="text-slateish-400">
                      {" "}
                      · {nf.format(d.passages_cited)} passage{d.passages_cited === 1 ? "" : "s"}
                    </span>
                    {d.text_source && d.text_source !== "extracted" && (
                      <span className="text-warn-500">
                        {" "}
                        · {d.text_source === "recognised" ? "OCR text" : "partly OCR text"}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {report.not_implemented_sections.length > 0 && (
            <p className="mt-3 text-xs text-slateish-500">
              This report does not include: {report.not_implemented_sections.join(", ")}.
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => onDownload(report.id)}
            className="rounded border border-signal-500/60 px-2.5 py-1 text-xs text-signal-400 transition-colors hover:bg-signal-500/15"
          >
            Download
          </button>
          <button
            type="button"
            onClick={runVerify}
            disabled={verify.state === "checking"}
            aria-busy={verify.state === "checking"}
            className="rounded border border-ink-600 px-2.5 py-1 text-xs text-slateish-300 transition-colors hover:bg-ink-700 disabled:opacity-40"
          >
            {verify.state === "checking" ? "Verifying…" : "Verify"}
          </button>
        </div>
      </div>

      {verify.state === "failed" && (
        <div role="alert" className="border-t border-danger-500/30 bg-danger-500/10 px-4 py-3 text-sm">
          <p className="font-medium text-danger-500">Verification could not be completed</p>
          <p className="mt-1 text-slateish-300">
            The check did not return a result. Nothing below is known about this report.
          </p>
        </div>
      )}

      {verify.state === "done" && <VerificationPanel v={verify.result} />}
    </li>
  );
}

function VerificationPanel({ v }: { v: ReportVerification }) {
  const drift = v.evidence_drift.length;
  const anyProblem = !v.snapshot_intact || !v.file_intact || drift > 0;
  return (
    <div
      role={anyProblem ? "alert" : "status"}
      className={[
        "border-t px-4 py-3 text-sm",
        anyProblem ? "border-warn-500/30 bg-warn-500/10" : "border-ink-700",
      ].join(" ")}
    >
      <ul className="space-y-1">
        <Check
          ok={v.snapshot_intact}
          okText="Snapshot intact — the stored evidence matches its recorded hash"
          badText="Snapshot altered — the stored evidence does not match its recorded hash"
        />
        <Check
          ok={v.file_intact}
          okText="File intact — the PDF matches its recorded hash"
          badText="File altered — the PDF does not match its recorded hash"
        />
        {drift > 0 ? (
          <li className="flex items-start gap-2 text-warn-500">
            <span aria-hidden="true" className="font-mono">
              ▲
            </span>
            <span>
              {nf.format(drift)} cited document{drift === 1 ? " has" : "s have"} changed since
              this report was generated. The report still shows what the evidence said then.
            </span>
          </li>
        ) : (
          <li className="flex items-start gap-2 text-signal-400">
            <span aria-hidden="true" className="font-mono">
              ✓
            </span>
            <span>No cited document has changed since this report was generated</span>
          </li>
        )}
      </ul>
    </div>
  );
}

/** Text plus a glyph, never colour alone. */
function Check({ ok, okText, badText }: { ok: boolean; okText: string; badText: string }) {
  return (
    <li className={["flex items-start gap-2", ok ? "text-signal-400" : "text-danger-500"].join(" ")}>
      <span aria-hidden="true" className="font-mono">
        {ok ? "✓" : "✕"}
      </span>
      <span>{ok ? okText : badText}</span>
    </li>
  );
}
