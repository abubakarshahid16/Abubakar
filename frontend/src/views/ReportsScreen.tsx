/**
 * The container for ReportsView: owns the API calls, hands the view data.
 *
 * ReportsView was written unwired against props (docs/frontend-wiring.md), so
 * this is the only file that knows the endpoints exist. Generation is not
 * offered here - a report is generated from an answered message in Chat,
 * where the message is; this screen lists, verifies and downloads.
 */
import { useCallback, useEffect, useState } from "react";

import { reports as reportsApi, type DownloadFailure } from "../api/client";
import type { ReportRecord, ReportVerification } from "../types/api";
import { ReportsView } from "./ReportsView";

/** What the reader is told when a download does not produce a file.
 *
 *  Every message ends by saying nothing was saved, because the failure the
 *  reader must never have to guess at is the one that leaves a truncated or
 *  empty PDF in their downloads folder looking like a real report.
 *
 *  `unavailable` is the 404. The backend answers 404 both for a report that
 *  is gone and for one that is simply outside the caller's scope, and it says
 *  "no report with that id" in both cases. Repeating that sentence tells a
 *  reader their own listed report does not exist, which is false; asserting
 *  the opposite - "you are not allowed to see it" - would confirm to a
 *  stranger that some id is real. The wording below states only what this
 *  screen actually knows: no file came back, and it cannot tell which case
 *  this is. */
function wordingFor(failure: DownloadFailure): { title: string; detail: string } {
  switch (failure.kind) {
    case "unauthenticated":
      return {
        title: "You are not signed in",
        detail:
          "The download was refused because this browser has no valid session — " +
          "signing in again is enough, and a page reload always ends a session " +
          "because the token is never stored. Nothing has been saved.",
      };
    case "forbidden":
      return {
        title: "The download was refused",
        detail:
          "The backend declined this download. Check whether it was started with " +
          "different settings. Nothing has been saved.",
      };
    case "unavailable":
      return {
        title: "No file came back for this report",
        detail:
          "The backend returned no PDF. That is the same answer it gives for a " +
          "report that has been removed and for one that is no longer in your " +
          "scope, so this screen cannot tell you which applies. Nothing has been saved.",
      };
    case "server":
      return { title: "The download failed", detail: `${failure.message} Nothing has been saved.` };
    case "network":
      return {
        title: "Cannot reach the backend",
        detail: `${failure.detail} The download never left this browser. Nothing has been saved.`,
      };
  }
}

type DownloadState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "failed"; title: string; detail: string };

export function ReportsScreen() {
  const [reports, setReports] = useState<ReportRecord[] | null>(null);
  const [suppressed, setSuppressed] = useState(0);
  const [downloadState, setDownloadState] = useState<DownloadState>({ state: "idle" });

  const load = useCallback(async () => {
    const r = await reportsApi.list();
    if (r.ok) {
      setReports(r.data.reports);
      setSuppressed(r.data.suppressed_count);
    } else {
      // An empty list is a real state and a failed request is not the same
      // state; the view shows "still loading" for null and the shell owns a
      // disconnected backend.
      setReports([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const verify = useCallback(async (id: string): Promise<ReportVerification> => {
    const r = await reportsApi.verify(id);
    if (r.ok) return r.data;
    // A verification that could not run must not read as "intact".
    return { report_id: id, snapshot_intact: false, file_intact: false,
             evidence_drift: ["verification request failed: " + r.error.message] };
  }, []);

  /**
   * Download by fetching the bytes with the Authorization header, then handing
   * them to the browser as a blob.
   *
   * This used to be `window.open(reportsApi.downloadUrl(id))`. A navigation
   * carries no Authorization header and the token is held in memory only, so
   * under auth_mode=demo_required the request arrived unauthenticated, resolved
   * to an empty scope, and the backend answered 404 for a report listed on this
   * very screen.
   *
   * The token is never put in the URL to work around that - a URL reaches
   * history, access logs and Referer headers, and the POC plan's rule 6 forbids secrets
   * in logs. Nothing is written unless the response was a success, so a failure
   * cannot leave an empty or truncated PDF behind.
   */
  const download = useCallback(async (id: string) => {
    setDownloadState({ state: "working" });
    const r = await reportsApi.download(id);
    if (!r.ok) {
      setDownloadState({ state: "failed", ...wordingFor(r.failure) });
      return;
    }

    const url = URL.createObjectURL(r.blob);
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = r.filename;
      a.rel = "noopener";
      // Firefox needs the anchor in the document for a programmatic click.
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      // Revoke, always - an object URL that is never revoked pins the whole
      // PDF in memory for the life of the page. Deferred by one task rather
      // than revoked inline: revoking in the same tick as click() can cancel
      // the save before the browser has read the blob.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    setDownloadState({ state: "idle" });
  }, []);

  return (
    <div className="space-y-4">
      {downloadState.state === "failed" && (
        // Same shape and palette as ReportsView's "Verification could not be
        // completed" panel: role=alert, a danger-coloured heading, and the
        // explanation underneath in body text. This screen cannot render
        // inside the report row - ReportsView owns that markup - so it sits
        // above the list as its own card.
        <div
          role="alert"
          className="rounded-lg border border-danger-500/30 bg-danger-500/10 px-4 py-3 text-sm"
        >
          <p className="font-medium text-danger-500">{downloadState.title}</p>
          <p className="mt-1 text-slateish-300">{downloadState.detail}</p>
        </div>
      )}

      <ReportsView
        reports={reports}
        onDownload={download}
        onVerify={verify}
        suppressedCount={suppressed}
      />
    </div>
  );
}
