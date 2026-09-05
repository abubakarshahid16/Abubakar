/**
 * ReportsView: hidden reports are counted, never described; documents are named
 * by filename and sha256 prefix, never by id; drift is never hidden.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportsView } from "./ReportsView";
import type { ReportRecord, ReportVerification } from "../types/api";

const DOC_ID = "doc_7c1f9e2a4b3d";

function makeReport(over: Partial<ReportRecord> = {}): ReportRecord {
  return {
    id: "rep_01",
    question: "What dry film thickness does coating system 1 require?",
    resolved_question: null,
    created_at: "2026-09-04T09:12:33.120Z",
    page_count: 3,
    size_bytes: 184_320,
    report_sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    owner_username: "ali",
    documents: [
      {
        document_id: DOC_ID,
        filename: "NORSOK-M-501-Rev5.pdf",
        sha256_prefix: "b02fb622b193",
        revision: null,
        approval_status: null,
        passages_cited: 2,
        text_source: "extracted",
      },
    ],
    not_implemented_sections: [],
    ...over,
  };
}

const intact: ReportVerification = {
  report_id: "rep_01",
  snapshot_intact: true,
  file_intact: true,
  evidence_drift: [],
};

function renderView(reports: ReportRecord[] | null, over: { suppressedCount?: number; onVerify?: () => Promise<ReportVerification> } = {}) {
  return render(
    <ReportsView
      reports={reports}
      onDownload={vi.fn()}
      onVerify={over.onVerify ?? vi.fn(async () => intact)}
      suppressedCount={over.suppressedCount ?? 0}
    />,
  );
}

describe("ReportsView: list states", () => {
  it("reports: null is a loading state", () => {
    renderView(null);
    expect(screen.getByRole("status")).toHaveTextContent(/Loading reports/);
    expect(screen.queryByText(/No reports yet/)).toBeNull();
  });

  it("reports: [] is the empty state, not a spinner", () => {
    const reports: ReportRecord[] = [];
    expect(reports).toHaveLength(0);
    renderView(reports);
    expect(screen.getByText("No reports yet")).toBeInTheDocument();
    expect(screen.queryByText(/Loading reports/)).toBeNull();
  });
});

describe("ReportsView: attribution and suppression", () => {
  it("owner_username: null says authentication was disabled, no user recorded", () => {
    const r = makeReport({ owner_username: null });
    expect(r.owner_username).toBeNull();
    renderView([r]);
    expect(screen.getByText(/authentication disabled — no user recorded/)).toBeInTheDocument();
  });

  it("suppressedCount: 2 renders a count line and names nothing", () => {
    renderView([makeReport()], { suppressedCount: 2 });
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent(/2 reports are not shown/);
    expect(line).toHaveTextContent(/no longer in your scope/);
  });

  it("suppressedCount: 0 renders no suppression line", () => {
    renderView([makeReport()], { suppressedCount: 0 });
    expect(screen.queryByText(/not shown because/)).toBeNull();
  });
});

describe("ReportsView: verification", () => {
  it("evidence_drift renders the changed-since-generated warning", async () => {
    const drifted: ReportVerification = { ...intact, evidence_drift: ["doc_x"] };
    expect(drifted.evidence_drift).toHaveLength(1);
    const user = userEvent.setup();
    renderView([makeReport()], { onVerify: vi.fn(async () => drifted) });
    await user.click(screen.getByRole("button", { name: "Verify" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/1 cited document has changed since this report was generated/);
    expect(screen.queryByText(/No cited document has changed/)).toBeNull();
  });

  it("an intact report with no drift is a status, not an alert", async () => {
    const user = userEvent.setup();
    renderView([makeReport()]);
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/No cited document has changed/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ReportsView: document naming", () => {
  it("renders the sha256 prefix and never the document_id", () => {
    const r = makeReport();
    expect(r.documents[0].document_id).toBe(DOC_ID);
    expect(r.documents[0].sha256_prefix).toBe("b02fb622b193");
    const { container } = renderView([r]);
    const li = screen.getByText("NORSOK-M-501-Rev5.pdf").closest("li")!;
    expect(within(li).getByText("b02fb622b193")).toBeInTheDocument();
    expect(container.textContent).not.toContain(DOC_ID);
  });

  it("lists not_implemented_sections by name", () => {
    const r = makeReport({ not_implemented_sections: ["gap_analysis", "market_summary"] });
    expect(r.not_implemented_sections.length).toBeGreaterThan(0);
    renderView([r]);
    expect(screen.getByText(/Outside this report/)).toBeInTheDocument();
    expect(screen.getByText(/This single-answer PDF does not include:/)).toBeInTheDocument();
    expect(screen.getByText(/gap_analysis, market_summary/)).toBeInTheDocument();
  });
});
