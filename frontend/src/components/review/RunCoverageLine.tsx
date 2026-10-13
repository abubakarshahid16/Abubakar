/**
 * PF4 (#884): one line on the run - how many of the run's applicable rules
 * were checked, sent to the engineer, or not checked, out of all of them.
 * The words are the server's (`clause_coverage.line`), so the screen and the
 * report cannot disagree. A run with no ledger says so; a failed read says so.
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../api/client";

export function RunCoverageLine({ runId }: { runId: string }) {
  const [line, setLine] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    // a failure of any kind is caught and said, never a crash of the run view
    Promise.resolve().then(() => reviewsApi.runCoverage(runId))
      .then((r) => { if (live) setLine(r.ok ? r.data.line : "Clause coverage could not be read."); })
      .catch(() => { if (live) setLine("Clause coverage could not be read."); });
    return () => { live = false; };
  }, [runId]);

  if (line === null) return null;
  return <p data-testid="run-coverage" className="text-xs text-slateish-300">Clause coverage: {line}.</p>;
}
