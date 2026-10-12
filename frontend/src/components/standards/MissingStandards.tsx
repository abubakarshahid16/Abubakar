/**
 * Standards the reviews need but the library does not hold - API, ASME, ASTM,
 * ISO, IEC, NFPA, NACE, NORSOK and the client's own - each with where to
 * obtain it and whether it has been asked for.
 *
 * WHAT IT REFUSES TO DO:
 *  - Download anything. Every one of these is sold under licence; the link is
 *    the publisher's own catalogue page (no search query, so nothing from a
 *    document is sent when it is followed). A company standard has no link:
 *    it comes from the client's standards custodian.
 *  - Say "requested" for a standard nobody recorded. MISSING_LOCALLY is the
 *    default; REQUESTED shows who recorded it and when.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import { ErrorState, Spinner } from "../states";
import type { ApiError, MissingStandard } from "../../types/api";

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "ready"; rows: MissingStandard[] };

const STATUS_LABEL: Record<string, string> = {
  MISSING_LOCALLY: "Missing",
  REQUESTED: "Requested",
  OBTAINED: "Obtained",
};

export function MissingStandards() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const result = await api.missingStandards();
    if (result.ok) setLoad({ state: "ready", rows: result.data });
    else setLoad({ state: "error", error: result.error });
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const markRequested = async (identifier: string) => {
    setBusy(identifier);
    setFailure(null);
    const result = await api.requestMissingStandard(identifier, null);
    setBusy(null);
    if (!result.ok) {
      setFailure(result.error.message || "Could not record the request.");
      return;
    }
    await refresh();
  };

  if (load.state === "loading") return <Spinner />;
  if (load.state === "error") {
    return <ErrorState error={load.error} onRetry={() => void refresh()} />;
  }

  return (
    <section aria-labelledby="missing-standards" className="flex flex-col gap-2">
      <h3 id="missing-standards" className="text-sm font-medium">
        Standards cited but not in the library ({load.rows.length})
      </h3>
      <p className="text-xs opacity-70">
        Cited by the submittals and standards you can read. Nothing is downloaded:
        each is sold under licence, so obtain the copy through your normal
        channel and upload it here.
      </p>
      {failure && <p role="alert" className="text-xs text-red-400">{failure}</p>}
      {load.rows.length === 0 ? (
        <p className="text-xs opacity-70">Every cited standard is in the library.</p>
      ) : (
        <table className="w-full text-left text-xs">
          <thead>
            <tr>
              <th scope="col">Standard</th>
              <th scope="col">Cited by</th>
              <th scope="col">Where to obtain</th>
              <th scope="col">Status</th>
              <th scope="col"><span className="sr-only">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {load.rows.map((row) => (
              <tr key={row.identifier}>
                <td>{row.identifier}</td>
                <td>{row.cited_by.length}</td>
                <td>
                  {row.obtain.url ? (
                    <a href={row.obtain.url} target="_blank" rel="noopener noreferrer"
                       className="underline">
                      {row.obtain.publisher}
                    </a>
                  ) : (
                    <span>{row.obtain.note}</span>
                  )}
                </td>
                <td>
                  {STATUS_LABEL[row.status] ?? row.status}
                  {row.status === "REQUESTED" && row.requested_by && (
                    <span className="opacity-70"> by {row.requested_by}</span>
                  )}
                </td>
                <td>
                  {row.status === "MISSING_LOCALLY" && (
                    <button type="button" disabled={busy === row.identifier}
                            onClick={() => void markRequested(row.identifier)}
                            className="rounded border border-white/20 px-2 py-0.5">
                      Mark requested
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
