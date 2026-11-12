/**
 * No code word reaches the AI review tab (U2). The tab is rendered whole, with
 * lines that carry the code words the backend writes, and its text (the grey
 * Id column and tooltips excepted) is scanned. MUTATION PROOF: print
 * line.item_id or line.reason raw and this test fails.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentReviewPanel } from "./AgentReviewPanel";
import { hasBannedWord } from "./plainWords";

const api = { summary: vi.fn(), lines: vi.fn() };
vi.mock("../../../api/agentReview", () => ({
  agentReview: { summary: (...a: unknown[]) => api.summary(...a), lines: (...a: unknown[]) => api.lines(...a) },
  isFeatureOff: () => false,
}));
beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

const base = { page: 2, clause: "4.2", rule_book: "Book A", rule_tier: null };
const LINES = [
  { ...base, item_id: "S-EQ-04", verdict_class: "Query for the engineer", word: "Query", reason: "second opinion model is the same or unknown; first verdict GREEN" },
  { ...base, item_id: "R-614e60d6-1111-2222-3333-444455556666", verdict_class: "Query for the engineer", word: "Query", reason: "first verdict RED; no figure with its unit inside both quotes" },
  { ...base, item_id: "R-aaaaaaaa-1111-2222-3333-444455556666", verdict_class: "AI opinion, engineer to confirm", word: "AI thinks: not met", reason: "The datasheet gives 12 bar", rule_tier: "AI approved" },
];

describe("the AI review tab, rendered", () => {
  it("shows names and plain reasons; ids only in the grey Id column", async () => {
    api.summary.mockResolvedValue({ ok: true, data: {
      paper_kind: "datasheet", paper_kind_source: "title", equipment_type: "pressure_relief",
      counts_by_class: { "Query for the engineer": 2, "AI opinion, engineer to confirm": 1 }, usd: 1.2, models: ["claude-sonnet-x"], missing_books: [],
      equipment_notes: ["another equipment type: 4 rules not asked (pressure_relief 2, static 2)"], mode: "rule review", project_papers_used: [],
    } });
    api.lines.mockResolvedValue({ ok: true, data: { lines: LINES, next: null } });
    const { container } = render(<AgentReviewPanel runId="r1" />);
    await waitFor(() => expect(screen.getByTestId("agent-lines-boundary")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Checklist point 4 \(Book A 4\.2\)/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Rule: Book A 4\.2/ })).toHaveLength(2);
    // the id is still there for engineers: tooltip and grey column
    expect(screen.getByTestId("id-S-EQ-04")).toHaveTextContent("S-EQ-04");
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('[data-testid^="id-"]').forEach((n) => n.remove());
    clone.querySelectorAll("th").forEach((n) => { if (n.textContent === "Id") n.remove(); });
    const text = clone.textContent ?? "";
    for (const bad of ["GREEN", "RED", "first verdict", "S-EQ-", "pressure_relief", "second opinion"]) expect(text).not.toContain(bad);
    expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    expect(text).not.toMatch(/R-614e60d6/);
    expect(hasBannedWord(text.replace(/AI thinks: not met/g, ""))).toBe(false);
    expect(text).toContain("pressure relief");
    expect(text).toContain("The second check was not done by a different model, so this stays an opinion.");
    expect(text).toContain("The value and its unit were not found together in the quoted text.");
  });
});
