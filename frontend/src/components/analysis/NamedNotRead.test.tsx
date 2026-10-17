/** #633 item 1: an unread named document is said on the screen, never silent. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NamedNotRead } from "./NamedNotRead";

describe("NamedNotRead", () => {
  it("names each document the answer did not examine, with what to check", () => {
    render(<NamedNotRead names={["SAES-D-901", " PSV data sheet rev C "]} what="summary" />);
    const line = screen.getByTestId("named-not-read");
    expect(line).toHaveTextContent("2 documents named in the question were not read: SAES-D-901, PSV data sheet rev C");
    expect(line).toHaveTextContent("The summary did not examine them");
    expect(line).toHaveTextContent("check the name, that it is in the library, and that you may read it");
  });

  it("says one document in the singular and renders nothing for none", () => {
    const { rerender } = render(<NamedNotRead names={["API 520"]} what="gap analysis" />);
    expect(screen.getByTestId("named-not-read")).toHaveTextContent("A document named in the question was not read: API 520. The gap analysis did not examine it");
    rerender(<NamedNotRead names={[]} what="summary" />);
    expect(screen.queryByTestId("named-not-read")).toBeNull();
    rerender(<NamedNotRead names={["  "]} what="summary" />);
    expect(screen.queryByTestId("named-not-read")).toBeNull();
  });
});
