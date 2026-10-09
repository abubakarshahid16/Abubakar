/**
 * W5b-01 (#525): the uploader offers PDF and Word (.docx), and says so.
 *
 * MUTATION PROOF: drop `.docx` from the input's `accept` and "offers Word
 * files" fails; put the old "Drag PDFs here" copy back and "says Word files
 * are accepted" fails.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { Uploader } from "./Uploader";
import { onSignedOut, setToken } from "../api/client";

beforeEach(() => {
  onSignedOut(null);
  setToken("t");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    JSON.stringify({ required: false, choices: [], default: [] }),
    { status: 200, headers: { "Content-Type": "application/json" } })));
});

describe("Uploader file types", () => {
  it("offers Word files", async () => {
    render(<Uploader onUploaded={() => {}} />);
    const input = await screen.findByLabelText("Choose PDF or Word files to upload");
    expect(input.getAttribute("accept")).toContain(".docx");
    expect(input.getAttribute("accept")).toContain(".pdf");
  });

  it("says Word files are accepted", async () => {
    render(<Uploader onUploaded={() => {}} />);
    expect(await screen.findByText(/Word \(\.docx\)/)).toBeTruthy();
  });
});
