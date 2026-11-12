import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeavingList } from "./LeavingList";

const leaving = [
  { id: "doc_1", title: "Pump datasheet rev B.pdf", kind: "paper", why: "paper under review" },
  { id: "doc_2", title: "API 610 rule book.pdf", kind: "rule book", why: "cited by the paper" },
];

describe("LeavingList", () => {
  it("lists every document that will be sent with its title, kind and why, never an id", () => {
    render(<LeavingList leaving={leaving} notSent={[]} notReadable={0} textLeaves />);
    const box = within(screen.getByTestId("leaving-list"));
    expect(box.getByText("These documents will be sent to Claude")).toBeInTheDocument();
    expect(box.getByText("Pump datasheet rev B.pdf")).toBeInTheDocument();
    expect(box.getByText(/rule book, cited by the paper/)).toBeInTheDocument();
    expect(box.queryByText(/doc_1|doc_2/)).toBeNull();
    expect(box.getByText("A rule book found only during the review is not sent; the result lists it.")).toBeInTheDocument();
    expect(box.getByText(/2 document\(s\), of the documents you may read/)).toBeInTheDocument();
  });

  it("says nothing leaves for Local only, even if a list were passed", () => {
    render(<LeavingList leaving={leaving} notSent={[]} notReadable={0} textLeaves={false} />);
    expect(screen.getByText("Nothing leaves this Mac.")).toBeInTheDocument();
    expect(screen.queryByText("Pump datasheet rev B.pdf")).toBeNull();
  });

  it("says nothing leaves when the list is empty", () => {
    render(<LeavingList leaving={[]} notSent={[]} notReadable={0} textLeaves />);
    expect(screen.getByText("Nothing leaves this Mac.")).toBeInTheDocument();
  });

  it("lists what will not be sent with the reason, naming a cited standard that is not held", () => {
    render(
      <LeavingList
        leaving={leaving}
        textLeaves
        notReadable={0}
        notSent={[
          { id: "doc_3", title: "Supply contract.pdf", kind: "contract", why: "cited by the paper", reason: "a contract goes only with the owner's recorded yes" },
          { name: "API 999", kind: "rule book", why: "cited by the paper", reason: "not held in the library" },
        ]}
      />,
    );
    expect(screen.getByText("These will not be sent")).toBeInTheDocument();
    expect(screen.getByText(/a contract goes only with the owner's recorded yes/)).toBeInTheDocument();
    expect(screen.getByText("API 999")).toBeInTheDocument();
  });

  it("counts a document the reader may not open and never names it", () => {
    render(<LeavingList leaving={leaving} notSent={[]} notReadable={2} textLeaves />);
    expect(screen.getByText(/2 more document\(s\) cited are ones you may not read/)).toBeInTheDocument();
  });
});
