/** G2: picking a kind is never silent: "Saving the kind..." while it is on its way, and the problem beside the picker when it failed. */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentClassification, DocumentKindOption } from "../types/api";
import { DocumentKindChip } from "./DocumentKindChip";

const KINDS: DocumentKindOption[] = [{ id: "datasheet", label: "Datasheet" }, { id: "procedure", label: "Procedure" }];
const CLS = { document_id: "d1", subjects: [], document_kind: null, document_kind_state: "needs_engineer" } as unknown as DocumentClassification;

function later<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

async function pick(onConfirm: (kind: string) => Promise<string | null>) {
  render(<DocumentKindChip classification={CLS} kinds={KINDS} isAdmin onConfirm={onConfirm} />);
  await userEvent.click(screen.getByText("Choose type"));
  await userEvent.selectOptions(screen.getByLabelText("Document type"), "datasheet");
}

describe("DocumentKindChip: a pick is never silent", () => {
  it("says it is saving, with no second 'Choose kind' to click, until the save answers", async () => {
    const wait = later<string | null>();
    await pick(() => wait.promise);
    expect(screen.getByTestId("kind-saving")).toHaveTextContent("Saving the type");
    expect(screen.queryByText("Choose type")).toBeNull();
    await act(async () => wait.resolve(null));
    expect(screen.queryByTestId("kind-saving")).toBeNull();
    expect(screen.queryByTestId("kind-problem")).toBeNull();
  });

  it("shows the problem beside the card and brings the picker back when the save failed", async () => {
    await pick(() => Promise.resolve("Could not save the kind for a.pdf. Try again."));
    expect(await screen.findByTestId("kind-problem")).toHaveTextContent("Could not save the kind for a.pdf");
    expect(screen.getByLabelText("Document type")).toBeInTheDocument();
  });

  it("treats a thrown save as a problem, never as silence", async () => {
    const boom = vi.fn().mockRejectedValue(new Error("down"));
    await pick(boom);
    expect(await screen.findByTestId("kind-problem")).toHaveTextContent("could not be saved");
  });
});
