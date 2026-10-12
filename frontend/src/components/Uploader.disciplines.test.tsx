/**
 * #609: an upload names who may see it, by default the uploader's own
 * disciplines, so no document is left visible to no discipline.
 *
 * MUTATION PROOF (run 2026-10-08):
 *  - drop the `form.append("disciplines", ...)` line in Uploader.tsx and
 *    "sends the default discipline with the file" fails;
 *  - start the picker with `chosen: []` instead of `r.data.default` and
 *    "shows the uploader's own discipline, ticked" fails;
 *  - drop `|| (picker.s === "ready" && chosen.length === 0)` from `blocked`
 *    and "blocks the upload when no discipline is ticked" fails.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Uploader } from "./Uploader";
import { onSignedOut, setToken } from "../api/client";

const forms: FormData[] = [];

class FakeXHR {
  status = 200;
  responseText = JSON.stringify({ document: { id: "doc_1" }, duplicate_of: null });
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send(form: FormData) {
    forms.push(form);
    this.onload?.();
  }
}

function answer(body: object) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } },
  )));
}

beforeEach(() => {
  forms.length = 0;
  onSignedOut(null);
  setToken("t");
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
  answer({ required: true, choices: ["Civil", "Mechanical"], default: ["Civil"] });
});

const pdf = () => new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" });

async function renderReady() {
  const view = render(<Uploader onUploaded={() => {}} />);
  await screen.findByTestId("upload-disciplines");
  return view;
}

describe("Uploader disciplines (#609)", () => {
  it("shows the uploader's own discipline, ticked", async () => {
    await renderReady();
    expect(screen.getByRole("checkbox", { name: "Civil" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Mechanical" })).not.toBeChecked();
  });

  it("sends the default discipline with the file", async () => {
    const { container } = await renderReady();
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [pdf()] } });
    await waitFor(() => expect(forms.length).toBe(1));
    expect(forms[0].getAll("disciplines")).toEqual(["Civil"]);
  });

  it("sends a changed choice", async () => {
    const { container } = await renderReady();
    fireEvent.click(screen.getByRole("checkbox", { name: "Mechanical" }));
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [pdf()] } });
    await waitFor(() => expect(forms.length).toBe(1));
    expect(forms[0].getAll("disciplines")).toEqual(["Civil", "Mechanical"]);
  });

  it("blocks the upload when no discipline is ticked", async () => {
    const { container } = await renderReady();
    fireEvent.click(screen.getByRole("checkbox", { name: "Civil" }));
    expect(screen.getByText(/Choose at least one discipline/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "choose files" })).toBeDisabled();
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [pdf()] } });
    await new Promise((r) => setTimeout(r, 20));
    expect(forms.length).toBe(0);
  });

  it("asks nothing and sends no discipline with sign-in off", async () => {
    answer({ required: false, choices: [], default: [] });
    const { container } = render(<Uploader onUploaded={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "choose files" })).not.toBeDisabled());
    expect(screen.queryByTestId("upload-disciplines")).toBeNull();
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [pdf()] } });
    await waitFor(() => expect(forms.length).toBe(1));
    expect(forms[0].getAll("disciplines")).toEqual([]);
  });
});
