/**
 * Reports. Every report here is a single-answer evidence report - one question,
 * its answer, the frozen evidence, and the documents cited at generation time.
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
import { formatWhen } from "../format/when";
import { useState } from "react";

import { EmptyState, Spinner } from "../components/states";
import type { ReportRecord, ReportVerification } from "../types/api";
import { NEW_LOOK } from "../look";
import { Button, Notice, Tag } from "../components/kit/Kit";

const nf = new Intl.NumberFormat("en-GB");

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** The question as typed, less a trailing backslash or space: on Windows the
 *  backslash key sits by Enter, and "...requirements\" was shown as the
 *  title (order 88c, #1097). Display only - the stored question is part of
 *  the report's frozen, hashed snapshot and is never rewritten. */
export function displayQuestion(text: string | null): string | null {
  return text === null ? null : text.replace(/[\\\s]+$/, "");
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
    <div className="aurora-field space-y-6">
      <div aria-hidden className="aurora-a" />
      <div aria-hidden className="aurora-b" />
      <header>
        {NEW_LOOK ? <h2 className="text-xl font-semibold text-slateish-200">Answer reports</h2> : <h1 className="text-xl font-semibold text-slateish-200">Reports</h1>}
        <p className="mt-1 text-sm text-slateish-400">
          Each report holds one question and its answer, with the quoted sources and their documents.
          It stays as it was when it was made.
        </p>
      </header>

      {suppressedCount > 0 && (
        <p
          role="status"
          className="surface-card rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-slateish-300"
        >
          <span aria-hidden="true">◌ </span>
          {nf.format(suppressedCount)} report{suppressedCount === 1 ? " is" : "s are"} not
          shown because a document {suppressedCount === 1 ? "it cites" : "they cite"} is no
          longer open to you.
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
            hint="Make a report from an answer in Chat. It keeps the question, the answer, the quoted sources and a fingerprint of each document, to spot later changes."
            action={
              onGenerate && (
                <Button variant="primary"
                 
                  onClick={onGenerate}
                >
                  Generate a report
                </Button>
              )
            }
          />
        )}

        {reports !== null && reports.length > 0 && (() => {
          // SAID ONCE, NOT ON EVERY ROW (H's audit 42: an amber "Original PDF missing" on each of 30 rows): when every report here is
          // a recreated copy the page says so once, in the kit's notice; when only some are, each of those rows says it in plain grey.
          const allRecreated = NEW_LOOK && reports.every((r) => r.recreation_available);
          return (
            <>
              {allRecreated && (
                <Notice>
                  The original PDFs of these reports are not on this computer. Each download is a copy made again from the saved sources.
                </Notice>
              )}
              <ul className={allRecreated ? "virtual-list mt-3 space-y-3" : "virtual-list space-y-3"}>
                {reports.map((r) => (
                  <ReportRow key={r.id} report={r} onDownload={onDownload} onVerify={onVerify} saidAbove={allRecreated} />
                ))}
              </ul>
            </>
          );
        })()}
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
  saidAbove = false,
}: {
  report: ReportRecord;
  onDownload: (id: string) => void;
  onVerify: (id: string) => Promise<ReportVerification>;
  /** the page already says, once, that every report here is a recreated copy */
  saidAbove?: boolean;
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
    <li className="card-3d surface-card overflow-hidden rounded-[var(--radius-md)] border border-ink-700 bg-ink-850">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0 flex-[1_1_20rem]">
          <h3 className="font-medium text-slateish-200">{displayQuestion(report.question)}</h3>
          {report.resolved_question &&
            displayQuestion(report.resolved_question) !== displayQuestion(report.question) && (
            <p className="mt-0.5 text-xs text-slateish-400">
              Read as: {displayQuestion(report.resolved_question)}
            </p>
          )}

          {/* when, how long, how big: no sign-in name or address on a card (H's audit, 27 Nov 2026: the signed-in person's email showed on
              every report), and plain type, not mono */}
          <p className="mt-1 text-xs text-slateish-400">
            {formatWhen(report.created_at)} · {nf.format(report.page_count)} page
            {report.page_count === 1 ? "" : "s"} · {formatBytes(report.size_bytes)}
          </p>

          {NEW_LOOK ? (
            // the new look (owner, E3): the report's title, date and its buttons first; its cited documents and what it leaves out folded
            <details className="look-details mt-3 text-sm">
              <summary className="cursor-pointer select-none text-xs font-semibold text-signal-300 hover:underline">
                Documents cited ({report.documents.length})
              </summary>
              <CitedDetail report={report} />
            </details>
          ) : (
            <CitedDetail report={report} />
          )}
        </div>

        {/* the report's buttons are one group that may wrap but never runs past the card ("Download recreated copy" was cut at
            800, the card hides what overflows); the text keeps 20rem and the group drops under it when both do not fit (27 Nov 2026) */}
        <div className="flex min-w-0 max-w-full flex-wrap gap-1.5">
          {report.recreation_available && !saidAbove && (
            <span className={NEW_LOOK ? "text-xs text-slateish-400" : "text-xs text-warn-500"}>Original PDF missing. This copy uses the saved sources.</span>
          )}
          {report.file_available === false && !report.recreation_available ? (
            <span className="rounded-[var(--radius-sm)] border border-warn-500/40 px-2.5 py-1 text-xs text-warn-500">
              File missing: this report&apos;s PDF is not on this machine
            </span>
          ) : (
            <Button variant="secondary" size="sm"
             
              onClick={() => onDownload(report.id)}
            >
              {report.recreation_available ? "Download recreated copy" : "Download"}
            </Button>
          )}
          <Button variant="secondary" size="sm"
           
            onClick={runVerify}
            disabled={verify.state === "checking"}
            aria-busy={verify.state === "checking"}
          >
            {verify.state === "checking" ? "Verifying…" : "Verify"}
          </Button>
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

      {verify.state === "done" && <VerificationPanel v={verify.result} fileMissing={report.file_available === false} />}
    </li>
  );
}

/** `fileMissing`: the PDF is not on this computer, so the file check cannot run (H's read of #1979: "file changed" was said for a file
 *  that is only missing). That is said plainly and is not counted as a problem. */
function VerificationPanel({ v, fileMissing }: { v: ReportVerification; fileMissing: boolean }) {
  const drift = v.evidence_drift.length;
  const anyProblem = !v.snapshot_intact || (!fileMissing && !v.file_intact) || drift > 0;
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
          okText="Saved report unchanged: its question, answer and sources are as they were made."
          badText="Saved report changed since it was made: do not rely on it."
        />
        {fileMissing ? (
          <li data-testid="verify-file-missing" className="flex items-start gap-2 text-slateish-400">
            <span>The original PDF is not on this computer, so it cannot be checked.</span>
          </li>
        ) : (
          <Check
            ok={v.file_intact}
            okText="PDF unchanged: the file is as it was made."
            badText="PDF changed since it was made: do not rely on it."
          />
        )}
        {drift > 0 ? (
          <li className="flex items-start gap-2 text-warn-500">
            <span aria-hidden="true" className={NEW_LOOK ? undefined : "font-mono"}>
              ▲
            </span>
            <span>
              {nf.format(drift)} cited document{drift === 1 ? " has" : "s have"} changed since
              this report was made. The report still shows what the sources said then.
            </span>
          </li>
        ) : (
          <li className="flex items-start gap-2 text-signal-400">
            <span aria-hidden="true" className={NEW_LOOK ? undefined : "font-mono"}>
              ✓
            </span>
            <span>No cited document has changed since this report was made</span>
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
      <span aria-hidden="true" className={NEW_LOOK ? undefined : "font-mono"}>
        {ok ? "✓" : "✕"}
      </span>
      <span>{ok ? okText : badText}</span>
    </li>
  );
}

/** A report's cited documents and what it leaves out: the same words and marks in both looks (the new look folds them). */
function CitedDetail({ report }: { report: ReportRecord }) {
  return (
    <>
          <div className="mt-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-slateish-400">
              Documents cited
            </p>
            {report.documents.length === 0 ? (
              <p className="mt-1 text-xs text-slateish-400">None recorded.</p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {report.documents.map((d) => (
                  <li key={d.document_id} className="text-xs text-slateish-300">
                    <span>{d.filename}</span>{" "}
                    {NEW_LOOK ? <Tag>{d.sha256_prefix}</Tag> : <span className="font-mono text-slateish-400">{d.sha256_prefix}</span>}
                    {d.revision && <span className="text-slateish-400"> · rev {d.revision}</span>}
                    {d.approval_status && (
                      <span className="text-slateish-400"> · {d.approval_status}</span>
                    )}
                    <span className="text-slateish-400">
                      {" "}
                      {d.passages_cited === 0
                        // Said plainly: "0 passages" next to a cited document reads as a contradiction.
                        ? "· on the document list; no part of it is quoted in this report"
                        : `· ${nf.format(d.passages_cited)} quoted part${d.passages_cited === 1 ? "" : "s"}`}
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
            <div className="mt-3 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900/60 px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
                Outside this report
              </p>
              <p className="mt-1 text-xs text-slateish-400">
                This single-answer PDF does not include:{" "}
                {report.not_implemented_sections.join(", ")}.
              </p>
            </div>
          )}
    </>
  );
}
