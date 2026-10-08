/**
 * Honest copy (CLAUDE.md rules 1 and 4): what a screen says about Claude and
 * about a failed load. Invented identifiers only.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginView } from "./LoginView";
import { ReportsScreen } from "./ReportsScreen";
import { ReviewRunsView } from "./ReviewRunsView";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("login footer", () => {
  it("does not claim that nothing leaves the machine", () => {
    render(<LoginView onLogin={vi.fn()} connected />);
    expect(screen.queryByText(/nothing you type leaves this machine/i)).toBeNull();
    expect(screen.getByText(/When Claude is switched on/)).toBeInTheDocument();
    expect(screen.getByText(/stored on this machine/)).toBeInTheDocument();
  });
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const report = (n: number) => ({
  id: `rpt_${n}`, question: `question number ${n}`, resolved_question: null,
  created_at: "2026-09-05T17:00:00+00:00", page_count: 1, size_bytes: 1,
  report_sha256: "a".repeat(64), owner_username: null, documents: [],
  not_implemented_sections: [],
});

describe("ReportsScreen failed loads", () => {
  it("a failed first load is an error, not 'No reports yet'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: { code: "internal", message: "list broke" } }, 500)));
    render(<ReportsScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be loaded/i);
    expect(screen.queryByText("No reports yet")).toBeNull();
  });

  it("a failed 'Load next 100' keeps the rows already loaded", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      if (calls === 1) return json({ reports: [report(1)], suppressed_count: 0, total_matching: 150 });
      return json({ detail: { code: "internal", message: "page two broke" } }, 500);
    }));
    render(<ReportsScreen />);
    expect(await screen.findByText(/question number 1/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load next 100" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/More reports could not be loaded/);
    expect(screen.getByText(/question number 1/)).toBeInTheDocument();
  });
});

describe("vision reader line", () => {
  it("says page images are sent to Claude when the reader is ready", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/reviews/vision-reader-status")) {
        return json({ state: "READY", ready: true, reason: "ok", fix: "", detail: null, checked_at: "2026-09-27T00:00:00+00:00" });
      }
      if (url.includes("/readiness")) {
        return json({ submittal_document_id: "doc-sub", pages_total: 5, pages_read: 3, unread_pages: [4],
          unread_page_reasons: { "4": "no pairs" }, standards_cited: 0, standards_held: [], standards_missing: [],
          last_run_id: null, nothing_changed: false, changes: [] });
      }
      if (url.includes("/documents")) return json([{ id: "doc-sub", filename: "SUB-A-1.pdf", document_role: "CONTRACTOR_SUBMITTAL" }]);
      if (url.includes("/reviews/runs")) return json({ runs: [] });
      return json({});
    }));
    render(<ReviewRunsView />);
    await userEvent.selectOptions(await screen.findByLabelText("Submittal"), "doc-sub");
    await waitFor(() => expect(screen.getByTestId("vision-reader-status"))
      .toHaveTextContent(/page images to Claude/));
  });
});
