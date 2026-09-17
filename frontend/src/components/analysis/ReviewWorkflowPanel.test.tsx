import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ReviewWorkflowPanel } from "./ReviewWorkflowPanel";
import { reviews } from "../../api/client";

const finding = { id: "f1", document_id: "d1", baseline_document_id: null, template_id: null, discipline: null, confidence: "medium" as const, category: "technical_query" as const, severity: "major" as const, requirement: "Requirement", finding: "Finding", required_action: "Action", governing_sources: [], unresolved_evidence: [], response_text: null, disposition: null, citation_ids: [], owner_user_id: null, due_date: null, status: "open" as const, approval_status: "pending" as const, approved_by: null, approved_at: null, escalation_level: 0, created_by: null, created_at: "2026-01-01", updated_at: "2026-01-01" };

it("renders the complete traceability chain returned by the API", async () => {
  vi.spyOn(reviews, "traceability").mockResolvedValue({ ok: true, data: { finding, document: { id: "d1", filename: "submittal.pdf" }, baseline: { filename: "requirements.pdf" }, citations: ["c1"], events: [], deliverables: [], owner: null, action: "Resolve the deviation" } });
  render(<ReviewWorkflowPanel findings={[finding]} onUpdate={async () => undefined} />);
  await userEvent.click(screen.getByRole("button", { name: "View full chain" }));
  expect(await screen.findByText(/Finding → submittal.pdf → requirements.pdf → 1 citation/)).toBeInTheDocument();
  expect(screen.getByText(/Resolve the deviation/)).toBeInTheDocument();
  vi.restoreAllMocks();
});
