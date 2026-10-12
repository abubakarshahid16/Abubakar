import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DocumentClassification, DocumentKindOption } from "../types/api";
import { DocumentKindChip } from "./DocumentKindChip";

const KINDS: DocumentKindOption[] = [
  { id: "datasheet", label: "Datasheet" },
  { id: "procedure", label: "Procedure" },
];

function make(over: Partial<DocumentClassification>): DocumentClassification {
  return {
    document_id: "d1", doc_type: null, discipline: null, doc_class: null, register_id: null,
    suggested_by: "none", confirmed_by: null, confirmed_at: null, confirmed: false, subjects: [],
    ...over,
  } as DocumentClassification;
}

describe("DocumentKindChip", () => {
  it("renders nothing for a document that was never routed", () => {
    const { container } = render(<DocumentKindChip classification={make({})} kinds={KINDS} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a suggestion as a guess, never as a plain type", () => {
    render(<DocumentKindChip classification={make({ document_kind: "datasheet", document_kind_state: "suggested" })} kinds={KINDS} />);
    expect(screen.getByTestId("kind-chip")).toHaveTextContent(/Datasheet\? .*guessed, not confirmed/);
  });

  it("shows an unclear document as unclear, with no kind name", () => {
    render(<DocumentKindChip classification={make({ document_kind: null, document_kind_state: "needs_engineer" })} kinds={KINDS} />);
    const chip = screen.getByTestId("kind-chip");
    expect(chip).toHaveTextContent(/unclear, engineer to choose/i);
    expect(chip.textContent).not.toMatch(/datasheet|procedure/i);
  });

  it("shows a confirmed kind as a plain chip", () => {
    render(<DocumentKindChip classification={make({ document_kind: "procedure", document_kind_state: "confirmed" })} kinds={KINDS} />);
    expect(screen.getByTestId("kind-chip")).toHaveTextContent(/^Procedure$/);
  });

  it("offers no control to a non-admin", () => {
    render(<DocumentKindChip classification={make({ document_kind: "datasheet", document_kind_state: "suggested" })} kinds={KINDS} onConfirm={() => {}} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("lets an admin confirm the suggestion with one click", () => {
    const onConfirm = vi.fn();
    render(<DocumentKindChip classification={make({ document_kind: "datasheet", document_kind_state: "suggested" })} kinds={KINDS} isAdmin onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm kind" }));
    expect(onConfirm).toHaveBeenCalledWith("datasheet");
  });

  it("lets an admin choose a kind when the router could not tell", () => {
    const onConfirm = vi.fn();
    render(<DocumentKindChip classification={make({ document_kind_state: "needs_engineer" })} kinds={KINDS} isAdmin onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose kind" }));
    fireEvent.change(screen.getByLabelText("Document kind"), { target: { value: "procedure" } });
    expect(onConfirm).toHaveBeenCalledWith("procedure");
  });
});
