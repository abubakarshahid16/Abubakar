import { reviews as reviewsApi } from "../../api/client";

/** Fetch the CRS with the bearer token and hand it to the browser; an
 *  `<a href>` cannot send the header. The filename is the server's. Returns
 *  the API's own error message, or null when the file was handed over. */
export async function downloadCrs(runId: string, copy: "internal" | "issue"): Promise<string | null> {
  const result = await reviewsApi.exportCrs(runId, copy);
  if (!result.ok) return result.error.message;
  const url = URL.createObjectURL(result.data.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.data.filename;
  link.click();
  URL.revokeObjectURL(url);
  return null;
}
