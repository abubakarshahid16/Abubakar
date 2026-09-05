/**
 * The container between the API and ReportsView. Two properties matter: the
 * suppressed count reaches the screen as a number, never as the hidden
 * reports themselves; and a verification that could not run must not read as
 * "intact".
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportList, ReportRecord } from "../types/api";
import { ReportsScreen } from "./ReportsScreen";

const record: ReportRecord = {
  id: "rpt_abc123def456",
  question: "what are the vibration limits for pump P-101A",
  resolved_question: null,
  created_at: "2026-09-05T17:00:00+00:00",
  page_count: 1,
  size_bytes: 41_000,
  report_sha256: "a".repeat(64),
  owner_username: null,
  documents: [
    {
      document_id: "doc_1",
      filename: "spec.pdf",
      sha256_prefix: "abcdef012345",
      revision: null,
      approval_status: null,
      passages_cited: 1,
      text_source: "extracted",
    },
  ],
  not_implemented_sections: ["coverage ledger", "gap analysis", "recommendation", "public-market findings"],
};

function mockList(body: ReportList, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ReportsScreen", () => {
  it("lists reports and shows how many are hidden, never which", async () => {
    mockList({ reports: [record], suppressed_count: 2 });
    render(<ReportsScreen />);
    expect(await screen.findByText(/vibration limits/)).toBeInTheDocument();
    // The count is on screen; the hidden reports themselves are not, because
    // the API never sent them - that is the point of sending a count.
    expect(
      screen.getByText(/2 reports are not shown because a document they cite is no longer in your scope/),
    ).toBeInTheDocument();
  });

  it("treats a failed listing as empty rather than as loading forever", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: { code: "internal", message: "x" } }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    render(<ReportsScreen />);
    // The view renders a spinner for null and an empty state for []. A 500
    // must land on the second: a spinner that never stops is a hang.
    await waitFor(() => expect(screen.queryByRole("status", { name: /loading/i })).toBeNull());
    expect(screen.queryByText(/vibration limits/)).toBeNull();
  });
});
