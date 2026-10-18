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
import { AGREE_REASON, SheetCard, TICK_REASON } from "./SheetCard";
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

  it("scrolls the opened card into view, wherever the list put it", () => {
    const spy = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", { value: spy, writable: true, configurable: true });
    try {
      renderCard([f("a")]);
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ block: "nearest" }));
    } finally {
      delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
    }
  });

  it("shows one line, not the whole card, when not selected", () => {
    const [card] = buildCards([f("a")]);
    render(<SheetCard card={card} runId="run-1" selected={false} standardNames={new Map()}
      onSelect={vi.fn()} onOpenRule={vi.fn()} onAnswered={vi.fn()} />);
    expect(screen.queryByText("We noticed")).toBeNull();
    expect(screen.getByRole("button", { name: /Field a is not given/ })).toBeInTheDocument();
  });
});

describe("the safety-tick card (rule_trust #947 step 8)", () => {
  const tick = (id: string, over: Partial<ReviewFinding> = {}) => f(id, {
    compliance_status: "COMPLIANT", show_for_engineer_tick: true, trust_label: "AUTO_PROVEN", tier: "SAFETY",
    matched_phrase: "Set pressure", finding: "Set pressure 9 barg meets the standard.", required_action: undefined, ...over,
  });

  it("asks for the engineer's own check, never a comment to the contractor, and the tick is the accept", async () => {
    renderCard([tick("s")]);
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(["We noticed", "The rule", "Your check"]);
    expect(screen.queryByText("Our comment")).toBeNull();
    expect(screen.getByText("Checked by a proven rule")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I checked it, tick" }));
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "s", "accept", TICK_REASON);
  });

  it("'something is off' asks what is off, then rejects with the engineer's words", async () => {
    renderCard([tick("s")]);
    await userEvent.click(screen.getByRole("button", { name: "Something is off" }));
    expect(decideCrsFinding).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/what is off/i), "The page says 9 barg at 20 C, not at relief.");
    await userEvent.click(screen.getByRole("button", { name: "Record that something is off" }));
    expect(decideCrsFinding).toHaveBeenCalledWith("run-1", "s", "reject", "The page says 9 barg at 20 C, not at relief.");
  });

  it("a ticked card says so, and offers a change that is a new recorded decision", async () => {
    renderCard([tick("s", { confirmed_by: "eng" })]);
    expect(screen.getByText(/You checked it and ticked it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change answer" }));
    expect(screen.getByLabelText(/what is off/i)).toBeInTheDocument();
  });
});

describe("DecisionCard", () => {
  const run = {
    review_run_id: "run-1", recommended_code: "Approved with Comments", engineer_final_code: null,
  } as unknown as Parameters<typeof DecisionCard>[0]["run"];

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

  it("shows the recorded decision beside the suggestion, never instead of it", () => {
    render(<DecisionCard run={{ ...run, engineer_final_code: "Approved with Comments" } as never} onDecided={vi.fn()} />);
    expect(screen.getByText("suggested")).toBeInTheDocument();
    expect(screen.getByText("Recorded: Approved with Comments.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change my decision" })).toBeDisabled();
  });

  it("records the suggestion without a reason", async () => {
    render(<DecisionCard run={run} onDecided={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: /Approved with Comments/ }));
    await userEvent.click(screen.getByRole("button", { name: "Record my decision" }));
    expect(decideCode).toHaveBeenCalledWith("run-1", "Approved with Comments", null);
  });
});
