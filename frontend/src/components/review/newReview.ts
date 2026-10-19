/**
 * Order 123 item 1: what happens to a file dropped on "New review".
 *
 * After the upload, the document is marked a contractor submittal (the role
 * the Submittals page lists and the review reads), with the same route the
 * Documents page uses for its role change. The review itself is started by
 * the page, which already knows whether this document has a review to open
 * instead (a re-upload of identical bytes is the same document).
 *
 * The standards are not chosen here: the review picks them itself.
 */
import { classification } from "../../api/client";
import type { UploadState } from "../Uploader";

export type Prepared = { ok: true; documentId: string } | { ok: false; message: string };

export async function prepareSubmittal(name: string, state: UploadState): Promise<Prepared> {
  if (state.phase === "error") {
    return { ok: false, message: `${name} was not uploaded: ${state.message}` };
  }
  if (state.phase !== "done") return { ok: false, message: `${name} is still uploading.` };
  if (state.awaitingGrant) {
    return {
      ok: false,
      message: `${name} is already stored but you cannot read it yet. An administrator must grant access before it can be reviewed.`,
    };
  }
  // IDENTICAL BYTES ARE THE SAME DOCUMENT: the server kept the first copy
  // and names it, and that is the one to review.
  const documentId = state.duplicateOf ?? state.documentId;
  if (!documentId) return { ok: false, message: `${name} was uploaded but the server did not name it.` };
  const role = await classification.setRoleBulk({
    document_ids: [documentId], document_role: "CONTRACTOR_SUBMITTAL",
  });
  if (!role.ok) {
    return { ok: false, message: `${name} could not be marked a contractor submittal: ${role.error.message}` };
  }
  // A 207 is a 2xx: the one document asked for is in `failed`, not written.
  if (role.data.failed.length > 0) {
    return { ok: false, message: `${name} could not be marked a contractor submittal: the server could not find it.` };
  }
  return { ok: true, documentId };
}
