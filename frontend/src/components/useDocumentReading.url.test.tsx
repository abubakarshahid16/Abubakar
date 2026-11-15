/** V2: the readings are asked for at /api/document-reading, once. The URL was written "/api/..." on top of the client's own
 *  "/api" prefix, so it went to /api/api/document-reading and answered 404 on every Documents page. */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useDocumentReading } from "./useDocumentReading";

afterEach(() => vi.unstubAllGlobals());

it("asks /api/document-reading, not /api/api/document-reading", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ documents: { d1: {} } }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useDocumentReading());
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const url = String((fetchMock.mock.calls[0] as unknown[])[0]);
  expect(url).toBe("/api/document-reading");
  await waitFor(() => expect(Object.keys(result.current)).toContain("d1"));
});
