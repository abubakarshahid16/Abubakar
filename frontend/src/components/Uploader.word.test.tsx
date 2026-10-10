/**
 * W5b-01 (#525): the uploader offers PDF, Word (.docx) and scanned images
 * (PNG, JPEG, TIFF), and says so.
 *
 * MUTATION PROOF: drop `.docx` from the input's `accept` and "offers Word
 * files" fails; put the old "Drag PDFs here" copy back and "says Word files
 * are accepted" fails; drop the image types and "offers scanned images" fails.
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
    const input = await screen.findByLabelText("Choose PDF, Word or image files to upload");
    expect(input.getAttribute("accept")).toContain(".docx");
    expect(input.getAttribute("accept")).toContain(".pdf");
  });

  it("offers scanned images", async () => {
    render(<Uploader onUploaded={() => {}} />);
    const input = await screen.findByLabelText("Choose PDF, Word or image files to upload");
    for (const suffix of [".png", ".jpg", ".tif"]) {
      expect(input.getAttribute("accept")).toContain(suffix);
    }
    expect(await screen.findByText(/scanned image \(PNG, JPEG, TIFF\)/)).toBeTruthy();
  });

  it("says Word files are accepted", async () => {
    render(<Uploader onUploaded={() => {}} />);
    expect(await screen.findByText(/Word \(\.docx\)/)).toBeTruthy();
  });
});
