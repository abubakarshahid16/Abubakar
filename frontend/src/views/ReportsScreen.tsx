/**
 * The container for ReportsView: owns the API calls, hands the view data.
 *
 * ReportsView was written unwired against props (docs/frontend-wiring.md), so
 * this is the only file that knows the endpoints exist. Generation is not
 * offered here - a report is generated from an answered message in Chat,
 * where the message is; this screen lists, verifies and downloads.
 */
import { useCallback, useEffect, useState } from "react";

import { reports as reportsApi } from "../api/client";
import type { ReportRecord, ReportVerification } from "../types/api";
import { ReportsView } from "./ReportsView";

export function ReportsScreen() {
  const [reports, setReports] = useState<ReportRecord[] | null>(null);
  const [suppressed, setSuppressed] = useState(0);

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

  const download = useCallback((id: string) => {
    window.open(reportsApi.downloadUrl(id), "_blank", "noopener");
  }, []);

  return (
    <ReportsView
      reports={reports}
      onDownload={download}
      onVerify={verify}
      suppressedCount={suppressed}
    />
  );
}
