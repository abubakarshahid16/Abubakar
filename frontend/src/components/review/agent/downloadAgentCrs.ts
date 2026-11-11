import { agentReview } from "../../../api/agentReview";

/** Same blob pattern as downloadCrs: fetch with the session, hand the file
 *  to the browser. Returns the API's own message, or null when handed over. */
export async function downloadAgentCrs(runId: string, copy: "internal" | "contractor"): Promise<string | null> {
  const result = await agentReview.exportCrs(runId, copy);
  if (!result.ok) return result.error.message;
  const url = URL.createObjectURL(result.data.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.data.filename;
  link.click();
  URL.revokeObjectURL(url);
  return null;
}
