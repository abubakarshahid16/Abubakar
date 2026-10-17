/**
 * #967 PR 2: a card's answers are the issue gate's own recorded decisions.
 *
 * MUTATION PROOF: decide only the leader and "writes one decision per
 * finding" fails; drop the reason length check and "asks why first" fails;
 * call reject without the typed reason and the same test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { DecisionCard } from "./DecisionCard";
import { AGREE_REASON, SheetCard } from "./SheetCard";
import { buildCards } from "./sheetCards";

const decideCrsFinding = vi.fn();
const update = vi.fn();
const decideCode = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: {
    decideCrsFinding: (...a: unknown[]) => decideCrsFinding(...a),
    update: (...a: unknown[]) => update(...a),
    decideCode: (...a: unknown[]) => decideCode(...a),
  },
}));

beforeEach(() => {
  decideCrsFinding.mockReset().mockResolvedValue({ ok: true, data: {} });
  update.mockReset().mockResolvedValue({ ok: true, data: {} });
  decideCode.mockReset().mockResolvedValue({ ok: true, data: {} });
});

function f(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "MISSING_INFORMATION", matched_phrase: `Field ${id}`,
    required_action: `Contractor to state Field ${id}.`, finding: `Field ${id} is blank.`,
    requirement_source_text: "The orifice shall be stated.", standard_document_id: "std-1",
    standard_clause: "5.2", contractor_page: 2, approval_status: "pending", ...over,
  } as ReviewFinding;
}

function renderCard(findings: ReviewFinding[], onAnswered = vi.fn(), onOpenRule = vi.fn()) {
  const [card] = buildCards(findings);
  render(
    <SheetCard card={card} runId="run-1" selected standardNames={new Map([["std-1", "API 520.pdf"]])}
      onSelect={vi.fn()} onOpenRule={onOpenRule} onAnswered={onAnswered} />,
  );
  return { card, onAnswered, onOpenRule };
}

describe("SheetCard", () => {
  it("shows the owner's sections in order, with the rule's source", async () => {
    const { onOpenRule } = renderCard([f("a")]);
    const headings = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(headings).toEqual(["We noticed", "The rule", "Our comment"]);
    expect(screen.getByText("Rule not yet proven, so you decide")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /API 520\.pdf, clause 5\.2/ }));
    expect(onOpenRule).toHaveBeenCalled();
  });

  it("writes one accept decision per finding of a group, with the click as its reason", async () => {
    const { onAnswered } = renderCard([f("a"), f("b"), f("c")]);
    await userEvent.click(screen.getByRole("button", { name: "Agree, ask the contractor" }));
    expect(decideCrsFinding.mock.calls).toEqual([
      ["run-1", "a", "accept", AGREE_REASON], ["run-1", "b", "accept", AGREE_REASON], ["run-1", "c", "accept", AGREE_REASON],
    ]);
    expect(onAnswered).toHaveBeenCalled();
  });

  it("asks why first before leaving a comment off the sheet", async () => {
    renderCard([f("a"), f("b")]);
    await userEvent.click(screen.getByRole("button", { name: "Not needed" }));
    expect(decideCrsFinding).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/why is this comment not needed/i), "short");
    await userEvent.click(screen.getByRole("button", { name: "Leave it off the sheet" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/10 characters/);
    expect(decideCrsFinding).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/why is this comment not needed/i), " - the value is on the GA drawing");
    await userEvent.click(screen.getByRole("button", { name: "Leave it off the sheet" }));
    expect(decideCrsFinding.mock.calls.map((c) => [c[1], c[2], c[3]])).toEqual([
      ["a", "reject", "short - the value is on the GA drawing"], ["b", "reject", "short - the value is on the GA drawing"],
    ]);
  });

  it("shows the server's refusal and stops", async () => {
    decideCrsFinding.mockResolvedValueOnce({ ok: false, error: { message: "no review finding with that id in this run" } });
    renderCard([f("a"), f("b")]);
    await userEvent.click(screen.getByRole("button", { name: "Agree, ask the contractor" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no review finding with that id in this run");
    expect(decideCrsFinding).toHaveBeenCalledTimes(1);
  });

  it("saves the engineer's own wording on a single-finding card", async () => {
    renderCard([f("a")]);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByLabelText("Our comment");
    await userEvent.clear(box);
    await userEvent.type(box, "Please state the orifice letter.");
    await userEvent.click(screen.getByRole("button", { name: "Save and agree" }));
    expect(update).toHaveBeenCalledWith("a", { engineer_comment: "Please state the orifice letter." });
  });

  it("offers Change answer on a done card, never a silent undo", async () => {
    renderCard([f("a", { approval_status: "rejected" })]);
    expect(screen.queryByRole("button", { name: "Agree, ask the contractor" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Change answer" }));
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "a", "accept", AGREE_REASON);
  });

  it("shows one line, not the whole card, when not selected", () => {
    const [card] = buildCards([f("a")]);
    render(<SheetCard card={card} runId="run-1" selected={false} standardNames={new Map()}
      onSelect={vi.fn()} onOpenRule={vi.fn()} onAnswered={vi.fn()} />);
    expect(screen.queryByText("We noticed")).toBeNull();
    expect(screen.getByRole("button", { name: /Field a is not given/ })).toBeInTheDocument();
  });
});

describe("DecisionCard", () => {
  const run = {
    review_run_id: "run-1", recommended_code: "Approved with Comments", engineer_final_code: null,
  } as never;

  it("marks the suggestion and asks why when the choice differs", async () => {
    const onDecided = vi.fn();
    render(<DecisionCard run={run} onDecided={onDecided} />);
    expect(screen.getByText("suggested").closest("label")).toHaveTextContent("Approved with Comments");
    await userEvent.click(screen.getByRole("radio", { name: /^Approved\s*Everything checked/ }));
    await userEvent.click(screen.getByRole("button", { name: "Record my decision" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/say why/i);
    expect(decideCode).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/say why/i), "Both blanks were answered by letter.");
    await userEvent.click(screen.getByRole("button", { name: "Record my decision" }));
    expect(decideCode).toHaveBeenCalledWith("run-1", "Approved", "Both blanks were answered by letter.");
    expect(onDecided).toHaveBeenCalled();
  });

  it("records the suggestion without a reason", async () => {
    render(<DecisionCard run={run} onDecided={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: /Approved with Comments/ }));
    await userEvent.click(screen.getByRole("button", { name: "Record my decision" }));
    expect(decideCode).toHaveBeenCalledWith("run-1", "Approved with Comments", null);
  });
});
