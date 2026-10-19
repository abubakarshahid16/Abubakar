/**
 * Order 123 item 1: the Uploader as "New review" uses it - one file, and the
 * caller told about it once it is stored, so the review can start.
 *
 * Fails without the change: without `single` two dropped files are both
 * uploaded, and without `onFileDone` the caller never hears of the upload.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import { Uploader } from "./Uploader";

const sent: string[] = [];

class FakeXHR {
  status = 200;
  responseText = JSON.stringify({ document: { id: `doc_${sent.length + 1}` }, duplicate_of: null });
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send() {
    sent.push("upload");
    this.onload?.();
  }
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    JSON.stringify({ required: false, choices: [], default: [] }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  )));
  sent.length = 0;
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
});

const pdf = (name: string) => new File([new Uint8Array([37, 80, 68, 70])], name, { type: "application/pdf" });

describe("Uploader for one file (order 123 item 1)", () => {
  it("uploads only the first of several dropped files and reports it when stored", async () => {
    const onFileDone = vi.fn();
    const { container, getByRole } = render(<Uploader single onUploaded={() => {}} onFileDone={onFileDone} />);
    await waitFor(() => expect(getByRole("button", { name: "choose a file" })).not.toBeDisabled());
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.multiple).toBe(false);
    fireEvent.change(input, { target: { files: [pdf("a.pdf"), pdf("b.pdf")] } });
    await waitFor(() => expect(onFileDone).toHaveBeenCalledTimes(1));
    expect(sent).toHaveLength(1);
    expect(onFileDone).toHaveBeenCalledWith("a.pdf", {
      phase: "done", documentId: "doc_1", duplicateOf: null, awaitingGrant: false,
    });
  });
});
