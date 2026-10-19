/**
 * v2.1 follow-up: the panel's keys (Enter keep, E edit wording, R remove)
 * sleep while the reader types in a text field anywhere on the page, the
 * panel's own forms and fields outside it alike.
 *
 * MUTATION PROOF: drop the isTyping check from DecisionPanel's key handler
 * and "typing in a field never decides" fails (E opens the wording form, R
 * the reasons, Enter keeps).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../../../types/api";
import { buildCrsRows } from "../../crs/crsRows";
import { EMPTY_FACTS } from "../../crs/tiers";
import type { CrsDecisions } from "../../crs/useCrsDecisions";
import { DecisionPanel } from "./DecisionPanel";

const finding = {
  id: "a", compliance_status: "NON_COMPLIANT", matched_phrase: "Field a", finding: "a found",
  required_action: "Contractor to fix a.", contractor_page: 1, approval_status: "pending",
  standard_document_id: "std-1", standard_clause: "4.1",
} as ReviewFinding;
const [row] = buildCrsRows([finding], EMPTY_FACTS, new Map());

function stubDecisions() {
  return {
    state: { decisions: {}, opened: {} }, decisionOf: () => null,
    keep: vi.fn(), edit: vi.fn(), remove: vi.fn(),
  } as unknown as CrsDecisions;
}

function setup(field: HTMLElement) {
  const decisions = stubDecisions();
  const onDecided = vi.fn();
  render(
    <div>
      <DecisionPanel row={row} decisions={decisions} onDecided={onDecided} />
    </div>,
  );
  document.body.appendChild(field);
  field.focus();
  return { decisions, onDecided };
}

function editable(): HTMLElement {
  const el = document.createElement("div");
  el.setAttribute("contenteditable", "true");
  el.tabIndex = 0;
  // jsdom does not compute isContentEditable; a browser does.
  Object.defineProperty(el, "isContentEditable", { value: true });
  return el;
}

describe("DecisionPanel keys while typing (v2.1 follow-up)", () => {
  it.each([
    ["an input outside the panel", () => document.createElement("input")],
    ["a textarea outside the panel", () => document.createElement("textarea")],
    ["a contenteditable outside the panel", editable],
  ])("typing in %s never decides", (_name, make) => {
    const field = make();
    const { decisions, onDecided } = setup(field);
    for (const key of ["e", "E", "r", "R", "Enter"]) fireEvent.keyDown(field, { key });
    expect(decisions.keep).not.toHaveBeenCalled();
    expect(onDecided).not.toHaveBeenCalled();
    expect(screen.queryByText(/Required action/)).toBeNull();
    expect(screen.queryByText("Why remove this comment?")).toBeNull();
    field.remove();
  });

  it("the same keys outside a text field do decide (the check above is not vacuous)", () => {
    const decisions = stubDecisions();
    render(<DecisionPanel row={row} decisions={decisions} onDecided={vi.fn()} />);
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(decisions.keep).toHaveBeenCalledWith(row.key);
    fireEvent.keyDown(document.body, { key: "r" });
    expect(screen.getByText("Why remove this comment?")).toBeInTheDocument();
  });
});
