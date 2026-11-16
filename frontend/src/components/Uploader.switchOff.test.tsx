/**
 * Order 14 lane E, review R99 (F3, F6): the Documents-page Uploader sends the page a file came in on ONLY when the
 * suggested-role switch is clearly on. Off, or any answer that is not a clear one (an error, an old server), sends exactly
 * the old form: the file and the disciplines.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Uploader } from "./Uploader";
import { onSignedOut, setToken } from "../api/client";
import { resetRoleSuggestionSwitch, roleSuggestionSwitch, SWITCH_OFF } from "../api/roleSuggestion";

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

const json = (body: object, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** The disciplines picker answers normally; the switch route answers `switchAnswer`. */
function server(switchAnswer: () => Response) {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) =>
    String(url).includes("/document-kinds/role-suggestion")
      ? switchAnswer()
      : json({ required: true, choices: ["Civil"], default: ["Civil"] })));
}

beforeEach(() => {
  forms.length = 0;
  onSignedOut(null);
  setToken("t");
  resetRoleSuggestionSwitch();
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetRoleSuggestionSwitch();
});

const pdf = () => new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" });

async function dropOneFile() {
  const { container } = render(<Uploader onUploaded={() => {}} />);
  await screen.findByTestId("upload-disciplines");
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [pdf()] } });
  await waitFor(() => expect(forms.length).toBe(1));
  return forms[0];
}

describe("the Uploader and the suggested-role switch", () => {
  it("switch off: sends exactly the old form, no page", async () => {
    server(() => json({ enabled: false, review_roles: ["CONTRACTOR_SUBMITTAL"] }));
    const form = await dropOneFile();
    expect([...form.keys()]).toEqual(["file", "disciplines"]);
  });

  it.each([
    ["a server error", () => json({ code: "internal", message: "x" }, 500)],
    ["an old server without the route", () => json({ detail: "Not Found" }, 404)],
    ["an answer of the wrong shape", () => json({ enabled: "yes" })],
  ])("%s counts as off: no page is sent", async (_why, answer) => {
    server(answer);
    expect(await roleSuggestionSwitch()).toEqual(SWITCH_OFF);
    const form = await dropOneFile();
    expect(form.has("uploaded_from")).toBe(false);
  });

  it("a network failure counts as off", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network down"); }));
    expect(await roleSuggestionSwitch()).toEqual(SWITCH_OFF);
  });

  it("switch on: sends the Documents page with the file (the control)", async () => {
    server(() => json({ enabled: true, review_roles: ["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"] }));
    const form = await dropOneFile();
    expect(form.get("uploaded_from")).toBe("documents");
  });
});
