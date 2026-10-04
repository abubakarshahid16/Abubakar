/**
 * In-app links navigate through the app, never by reloading the page (the
 * token is memory-only, so a reload signs the reader out).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MetricWarningRow } from "./dashboard/MetricWarning";
import { NavLink, NavigationContext } from "./NavLink";
import { ReviewWorkflowPanel } from "./analysis/ReviewWorkflowPanel";
import { reviews } from "../api/client";
import type { MetricWarning } from "../types/api";

afterEach(() => vi.restoreAllMocks());

describe("NavLink", () => {
  it("calls the app's navigation and cancels the browser's page load", () => {
    const navigate = vi.fn();
    render(<NavigationContext.Provider value={navigate}>
      <NavLink view="documents" recordId="doc-a">go</NavLink>
    </NavigationContext.Provider>);
    const notPrevented = fireEvent.click(screen.getByRole("link", { name: "go" }));
    expect(navigate).toHaveBeenCalledWith("documents", "doc-a");
    expect(notPrevented).toBe(false); // preventDefault was called
  });

  it("leaves a ctrl-click to the browser (new tab)", () => {
    const navigate = vi.fn();
    render(<NavigationContext.Provider value={navigate}>
      <NavLink view="documents">go</NavLink>
    </NavigationContext.Provider>);
    fireEvent.click(screen.getByRole("link", { name: "go" }), { ctrlKey: true });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("shows plain text, not a reloading link, when there is no router", () => {
    render(<NavLink view="documents">go</NavLink>);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("go")).toBeInTheDocument();
  });
});

describe("the two former plain-anchor sites", () => {
  it("a dashboard warning opens its document through the router", () => {
    const navigate = vi.fn();
    const warning = { code: "STALE", severity: "warning", message: "Index is stale", document_id: "doc-x" } as MetricWarning;
    render(<NavigationContext.Provider value={navigate}>
      <ul><MetricWarningRow warning={warning} /></ul>
    </NavigationContext.Provider>);
    fireEvent.click(screen.getByRole("link", { name: "Index is stale" }));
    expect(navigate).toHaveBeenCalledWith("documents", "doc-x");
  });

  it("a warning with no document opens Deliverables through the router", () => {
    const navigate = vi.fn();
    const warning = { code: "X", severity: "info", message: "General notice", document_id: null } as MetricWarning;
    render(<NavigationContext.Provider value={navigate}>
      <ul><MetricWarningRow warning={warning} /></ul>
    </NavigationContext.Provider>);
    fireEvent.click(screen.getByRole("link", { name: "General notice" }));
    expect(navigate).toHaveBeenCalledWith("deliverables", undefined);
  });

  it("the traceability chain links through the router", async () => {
    const finding = { id: "f1", document_id: "d1", baseline_document_id: null, template_id: null, discipline: null, confidence: "medium" as const, category: "technical_query" as const, severity: "major" as const, requirement: "Requirement", finding: "Finding", required_action: "Action", governing_sources: [], unresolved_evidence: [], response_text: null, disposition: null, citation_ids: [], owner_user_id: null, due_date: null, status: "open" as const, approval_status: "pending" as const, approved_by: null, approved_at: null, escalation_level: 0, created_by: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
    vi.spyOn(reviews, "traceability").mockResolvedValue({ ok: true, data: { finding, document: { id: "d1", filename: "submittal-a.pdf" }, baseline: null, citations: [], events: [], deliverables: [{ id: "dl-9", title: "Deliverable nine" }], owner: null, action: "Act" } } as never);
    const navigate = vi.fn();
    render(<NavigationContext.Provider value={navigate}>
      <ReviewWorkflowPanel findings={[finding]} onUpdate={async () => undefined} />
    </NavigationContext.Provider>);
    await userEvent.click(screen.getByRole("button", { name: "View full chain" }));
    fireEvent.click(await screen.findByRole("link", { name: "submittal-a.pdf" }));
    expect(navigate).toHaveBeenCalledWith("documents", undefined);
    fireEvent.click(screen.getByRole("link", { name: "Deliverable nine" }));
    expect(navigate).toHaveBeenCalledWith("deliverables", "dl-9");
  });
});
