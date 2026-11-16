/** Order 14 lane E: the page a file came in on goes with the upload ONLY when the caller gives it (switch on); off: the same form. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { uploadOne } from "./Uploader";

const forms: FormData[] = [];
class FakeXHR {
  status = 200;
  responseText = JSON.stringify({ document: { id: "doc_1" }, duplicate_of: null });
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send(form: FormData) { forms.push(form); this.onload?.(); }
}
beforeEach(() => { forms.length = 0; vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest); });
afterEach(() => vi.unstubAllGlobals());

const pdf = () => new File([new Uint8Array([37, 80, 68, 70])], "a.pdf", { type: "application/pdf" });

describe("uploadOne and the page it came in on", () => {
  it("sends exactly the old form without a page", async () => {
    await uploadOne(pdf(), ["Civil"], () => {});
    expect([...forms[0].keys()]).toEqual(["file", "disciplines"]);
  });
  it("sends the page when the caller gives one", async () => {
    await uploadOne(pdf(), ["Civil"], () => {}, "review");
    expect(forms[0].get("uploaded_from")).toBe("review");
  });
});
