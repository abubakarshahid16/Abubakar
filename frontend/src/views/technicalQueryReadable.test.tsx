/** The query page made readable (owner's Part 3, item 2): look only, every word kept. Invented values. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MadeFold, ReplyText, RevisionLines } from "./TechnicalQueryReadableParts";
import { replyBlocks, splitMarks } from "./technicalQueryReadable";

const REPLY = "COMPANY replies as follows.\n\n1. **Design pressure**\nNot found in the documents searched.\n\n**2. Thermal relief**\nThe source [S1] gives the rule for storage tanks.\n\n3. As-built drawings are required before completion [S2].\n\nBased on the closing sentence of this invented reply.";

describe("the reply as a list", () => {
  it("keeps the lead, each numbered answer with its body, and the closing paragraph, with no ** left", () => {
    expect(replyBlocks(REPLY)).toEqual([
      { kind: "para", text: "COMPANY replies as follows." },
      { kind: "item", n: 1, title: "**Design pressure**", body: ["Not found in the documents searched."] },
      { kind: "item", n: 2, title: "Thermal relief**", body: ["The source [S1] gives the rule for storage tanks."] },
      { kind: "item", n: 3, title: "As-built drawings are required before completion [S2].", body: [] },
      { kind: "para", text: "Based on the closing sentence of this invented reply." },
    ]);
    render(<ReplyText answer={REPLY} />);
    const box = screen.getByTestId("reply-text");
    expect(box.textContent).not.toContain("**");
    expect(box.textContent).toContain("[S1]"); // citation labels stay
    const items = within(box).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("value"))).toEqual(["1", "2", "3"]);
    expect(within(items[1]).getByText("Thermal relief").tagName).toBe("P");
    expect(box.lastElementChild?.textContent).toBe("Based on the closing sentence of this invented reply.");
  });

  it("a reply with no numbered answers stays paragraphs, with its **bold** as bold", () => {
    render(<ReplyText answer={"Class 300 applies **per clause 4.1** [S1].\n\nNothing else."} />);
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("per clause 4.1").tagName).toBe("STRONG");
  });
});

describe("the marks in their place", () => {
  const marks = [
    "The question was proposed by the system; no engineer has confirmed it yet.",
    "Written by the AI on this computer from sources the system found; no engineer has kept them yet.",
    "The revision of Invented Spec A is not confirmed yet (Documents, Details, Save metadata).",
    "The draft does not answer request item 1; check it by hand.",
  ];
  it("folds how it was made, says the revision beside the sources, and keeps the warnings in view", () => {
    expect(splitMarks(marks, true)).toEqual({ made: marks.slice(0, 2), shown: [marks[3]] });
    expect(splitMarks(marks, false).shown).toEqual([marks[2], marks[3]]); // the page could not name the documents: the server's line stays
  });

  it("says each unconfirmed document in one plain sentence, with How to confirm folded", () => {
    render(<><RevisionLines documents={["Invented Spec A", "Invented Std B"]} isAdmin /><MadeFold lines={["Written by an engineer."]} /></>);
    expect(screen.getAllByTestId("revision-line").map((l) => l.textContent)).toEqual([
      "We have not yet confirmed that we hold the latest revision of Invented Spec A.",
      "We have not yet confirmed that we hold the latest revision of Invented Std B.",
    ]);
    for (const id of ["revision-how", "how-made"]) {
      const fold = screen.getByTestId(id);
      expect(fold.tagName).toBe("DETAILS");
      expect((fold as HTMLDetailsElement).open).toBe(false);
    }
  });
});
