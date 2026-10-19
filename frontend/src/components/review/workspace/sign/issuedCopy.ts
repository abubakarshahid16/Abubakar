/**
 * v2.1 round 2: "Download the issued copy" after signing.
 *
 * READ ONLY, NOT ISSUING. It lists the copies the server already issued for
 * the review (`reviewsApi.crsIssuedCopies`, GET .../crs/issued) and fetches
 * the newest one byte for byte (`reviewsApi.issuedCrsCopy`, GET
 * .../crs/issued/{copy_id}). Nothing new is made or recorded on the server;
 * issuing stays only in crs/issueContractorCopy.ts
 * (views/oldIssueGateFenced.test.ts).
 *
 * A failed read is said in plain words first (workspace/plainError), with
 * the server's own words kept after "Details:", like the rest of the
 * workspace; the server's raw text is never shown alone.
 */
import { reviews as reviewsApi } from "../../../../api/client";
import { plainErrorText } from "../plainError";

export const NO_ISSUED_COPY_MESSAGE = "No issued copy is on record for this review yet.";
export const COULD_NOT_FIND_ISSUED_COPY = "Could not find the issued copy.";
export const COULD_NOT_DOWNLOAD_ISSUED_COPY = "Could not download the issued copy.";

/** Hand the newest issued copy to the browser. Returns a plain sentence
 *  when it could not, or null when the file was handed over. */
export async function downloadIssuedCopy(runId: string): Promise<string | null> {
  const listed = await reviewsApi.crsIssuedCopies(runId);
  if (!listed.ok) return plainErrorText(COULD_NOT_FIND_ISSUED_COPY, listed);
  const newest = [...listed.data.copies].sort((a, b) => b.issued_at.localeCompare(a.issued_at))[0];
  if (!newest) return NO_ISSUED_COPY_MESSAGE;
  const file = await reviewsApi.issuedCrsCopy(runId, newest.id);
  if (!file.ok) return plainErrorText(COULD_NOT_DOWNLOAD_ISSUED_COPY, file);
  const url = URL.createObjectURL(file.data.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.data.filename;
  link.click();
  URL.revokeObjectURL(url);
  return null;
}
