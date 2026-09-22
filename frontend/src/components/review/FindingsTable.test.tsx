/**
 * The findings table, on the shape the drum sheet actually produces:
 * 1,578 requirements with no evidence and 2 that need a person.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FindingsTable } from "./FindingsTable";
import type { ReviewFinding } from "../../types/api";

function finding(over: Partial<ReviewFinding> & { id: string }): ReviewFinding {
  return {
    document_id: "doc_sub", baseline_document_id: null, template_id: null,
    discipline: null, confidence: "medium", category: "requirement_deviation",
    severity: "major", requirement: "A requirement.", finding: "",
    required_action: "", governing_sources: [], unresolved_evidence: [],
    response_text: null, disposition: null, citation_ids: [],
    owner_user_id: null, due_date: null, status: "open",
    approval_status: "pending", approved_by: null, approved_at: null,
    escalation_level: 0, created_by: null, created_at: "", updated_at: "",
    ...over,
  } as ReviewFinding;
}

/** Two actionable rows and a hundred with no evidence: the real proportion. */
function drumRun(): ReviewFinding[] {
  const rows: ReviewFinding[] = [
    finding({
      id: "a", compliance_status: "MISSING_INFORMATION",
      standard_document_id: "doc_std", standard_clause: "1.1",
    }),
    finding({
      id: "b", compliance_status: "NEEDS_ENGINEER_REVIEW",
      standard_document_id: "doc_std", standard_clause: "6.2.2",
      matched_phrase: "maximum operating pressure", match_method: "containment",
      contractor_evidence_text: "2.2 bar (ga)",
      equipment_tag: "2003-47-V-0001A/B",
    }),
  ];
  for (let i = 0; i < 100; i += 1) {
    rows.push(finding({
      id: `m${i}`, compliance_status: "MISSING_INFORMATION",
      standard_document_id: "doc_std", standard_clause: `9.${i}`,
    }));
  }
  return rows;
}

describe("what a reviewer sees first", () => {
  it("collapses the no-evidence rows behind their own count", () => {
    render(<FindingsTable findings={drumRun()} selectedId={null} onSelect={vi.fn()} />);

    // The one actionable row is on screen...
    expect(screen.getByText("maximum operating pressure")).toBeInTheDocument();
    // ...and the 101 with no evidence are not, but their count is.
    expect(screen.getByText(/101 requirements had no evidence/)).toBeInTheDocument();
    expect(screen.getByText(/101 of 102/)).toBeInTheDocument();
  });

  it("says plainly that no evidence is a question, not a breach", () => {
    render(<FindingsTable findings={drumRun()} selectedId={null} onSelect={vi.fn()} />);

    expect(
      screen.getByText(/question for the contractor, not a breach/i),
    ).toBeInTheDocument();
  });

  it("opens them on request - collapsed is not hidden", async () => {
    render(<FindingsTable findings={drumRun()} selectedId={null} onSelect={vi.fn()} />);

    await userEvent.click(screen.getByText(/101 requirements had no evidence/));

    expect(screen.getByText(/Hide the 101 with no evidence/)).toBeInTheDocument();
    expect(screen.getAllByText("No evidence submitted").length).toBeGreaterThan(1);
  });

  it("puts the row that needs a person above the ones that do not", async () => {
    const rows = [
      finding({ id: "m", compliance_status: "MISSING_INFORMATION", standard_clause: "1.1" }),
      finding({ id: "n", compliance_status: "NON_COMPLIANT", standard_clause: "2.2" }),
      finding({ id: "c", compliance_status: "COMPLIANT", standard_clause: "3.3" }),
    ];
    render(<FindingsTable findings={rows} selectedId={null} onSelect={vi.fn()} />);
    await userEvent.click(screen.getByText(/1 requirements had no evidence/));

    const order = screen.getAllByRole("row").slice(1).map(
      (row) => within(row).getByText(/clause/).textContent,
    );
    expect(order[0]).toContain("2.2");
    expect(order[order.length - 1]).toContain("1.1");
  });
});

describe("filters", () => {
  it("narrows by equipment tag", async () => {
    const rows = [
      finding({ id: "a", compliance_status: "COMPLIANT", equipment_tag: "PSV-4301", matched_phrase: "set pressure" }),
      finding({ id: "b", compliance_status: "COMPLIANT", equipment_tag: "PSV-4360", matched_phrase: "set pressure" }),
    ];
    render(<FindingsTable findings={rows} selectedId={null} onSelect={vi.fn()} />);
    expect(screen.getAllByText("set pressure")).toHaveLength(2);

    await userEvent.selectOptions(
      screen.getByLabelText("Filter by equipment tag"), "PSV-4301");

    expect(screen.getAllByText("set pressure")).toHaveLength(1);
    // Scoped to the table: the tag is also an <option> in the filter itself.
    const body = screen.getAllByRole("row")[1];
    expect(within(body).getByText("PSV-4301")).toBeInTheDocument();
  });

  it("shows the filtered count against the total", async () => {
    const rows = [
      finding({ id: "a", compliance_status: "COMPLIANT" }),
      finding({ id: "b", compliance_status: "NON_COMPLIANT" }),
    ];
    render(<FindingsTable findings={rows} selectedId={null} onSelect={vi.fn()} />);

    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "COMPLIANT");

    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
  });
});

describe("the pairing is labelled", () => {
  it("marks a model pairing differently from a rule", () => {
    const rows = [
      finding({ id: "a", compliance_status: "COMPLIANT", match_method: "model" }),
      finding({ id: "b", compliance_status: "COMPLIANT", match_method: "containment" }),
    ];
    render(<FindingsTable findings={rows} selectedId={null} onSelect={vi.fn()} />);

    expect(screen.getByText("paired by model")).toBeInTheDocument();
    expect(screen.getByText("matched by rule")).toBeInTheDocument();
  });

  it("never prints high confidence", () => {
    render(
      <FindingsTable
        findings={[finding({ id: "a", compliance_status: "COMPLIANT", confidence: "medium" })]}
        selectedId={null} onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText(/confidence medium/)).toBeInTheDocument();
    expect(screen.queryByText(/confidence high/)).toBeNull();
  });
});

describe("B9: a requirement that needs another document", () => {
  function mixedRun(): ReviewFinding[] {
    const rows: ReviewFinding[] = [
      finding({
        id: "act", compliance_status: "NEEDS_ENGINEER_REVIEW",
        standard_document_id: "doc_std", standard_clause: "6.2.2",
        matched_phrase: "maximum operating pressure", match_method: "containment",
      }),
    ];
    for (let i = 0; i < 3; i += 1) {
      rows.push(finding({
        id: `m${i}`, compliance_status: "MISSING_INFORMATION",
        standard_document_id: "doc_std", standard_clause: `9.${i}`,
      }));
    }
    for (let i = 0; i < 40; i += 1) {
      rows.push(finding({
        id: `s${i}`, compliance_status: "NOT_IN_DOCUMENT_SCOPE",
        standard_document_id: "doc_std", standard_clause: `4.${i}`,
        requirement: `Statement ${i}`,
      }));
    }
    return rows;
  }

  it("is collapsed behind its OWN count, never inside 'no evidence'", () => {
    render(<FindingsTable findings={mixedRun()} selectedId={null} onSelect={vi.fn()} />);

    expect(screen.getByText(/40 requirements need another document/)).toBeInTheDocument();
    expect(screen.getByText(/40 of 44/)).toBeInTheDocument();
    // The contractor's count is the 3 real omissions, not 43.
    expect(screen.getByText(/3 requirements had no evidence/)).toBeInTheDocument();
    expect(screen.queryByText(/43 requirements had no evidence/)).toBeNull();
    expect(screen.queryByText("Statement 0")).toBeNull();
  });

  it("never words it as the contractor's omission or a breach", async () => {
    const user = userEvent.setup();
    render(<FindingsTable findings={mixedRun()} selectedId={null} onSelect={vi.fn()} />);

    const summary = screen.getByText(/40 requirements need another document/).closest("button");
    expect(summary).not.toBeNull();
    expect(summary!.textContent).toMatch(/not a contractor omission, and not a\s+breach/);

    await user.click(summary!);
    const row = screen.getByText("Statement 0").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getByText(
      "Requires another document - not answerable from this submittal type",
    )).toBeInTheDocument();
    expect(within(row!).queryByText("No evidence submitted")).toBeNull();
  });
});
