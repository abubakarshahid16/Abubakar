/**
 * The upload carries the bearer token.
 *
 * `Uploader` is the one transport `api.request()` does not own - it needs
 * XMLHttpRequest for progress - and it previously sent no Authorization header
 * at all. Under AUTH_MODE=demo_required that is a 401 on every upload from a
 * screen that reported "Cannot reach the backend".
 *
 * MUTATION PROOF: delete the `authorize(...)` line in Uploader.tsx and
 * `sends the bearer token` fails. The header assertion is the test; the
 * successful-upload assertion beside it would pass either way, which is
 * exactly why it is not the only one.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import { Uploader } from "./Uploader";
import { isSignedIn, onSignedOut, setToken } from "../api/client";

interface SentRequest {
  headers: Record<string, string>;
  url: string;
}

const sent: SentRequest[] = [];

/** What the next FakeXHR answers; reset before every test. */
let answer = { status: 200, body: JSON.stringify({ document: { id: "doc_1" }, duplicate_of: null }) };

class FakeXHR {
  headers: Record<string, string> = {};
  url = "";
  status = answer.status;
  responseText = answer.body;
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  open(_method: string, url: string) {
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send() {
    sent.push({ headers: { ...this.headers }, url: this.url });
    this.onload?.();
  }
}

beforeEach(() => {
  sent.length = 0;
  answer = { status: 200, body: JSON.stringify({ document: { id: "doc_1" }, duplicate_of: null }) };
  onSignedOut(null);
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
});

function drop(file: File) {
  const { container } = render(<Uploader onUploaded={() => {}} />);
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("the uploader rendered no file input");
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Uploader authorization", () => {
  it("sends the bearer token on the upload request", async () => {
    setToken("test-token-abc");
    drop(new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(sent.length).toBe(1));
    expect(sent[0].headers.Authorization).toBe("Bearer test-token-abc");
  });

  it("never puts the token in the URL", async () => {
    setToken("test-token-abc");
    drop(new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(sent.length).toBe(1));
    expect(sent[0].url).not.toContain("test-token-abc");
    expect(sent[0].url).toBe("/api/documents");
  });

  it("sends no Authorization header when signed out", async () => {
    setToken(null);
    drop(new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(sent.length).toBe(1));
    // Absent, not an empty "Bearer ": a header saying nothing is worse than no
    // header, because the server cannot tell it from a malformed token.
    expect(sent[0].headers.Authorization).toBeUndefined();
  });
});

describe("audit 2026-09-30: a 401 on the upload signs out like every other request", () => {
  it("clears the token and tells the app", async () => {
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    setToken("expired-token");
    answer = { status: 401, body: JSON.stringify({ detail: { code: "unauthenticated", message: "sign in" } }) };
    drop(new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(signedOut).toHaveBeenCalledTimes(1));
    expect(isSignedIn()).toBe(false);
    onSignedOut(null);
  });

  it("does not sign out on a refusal that is not a 401", async () => {
    const signedOut = vi.fn();
    onSignedOut(signedOut);
    setToken("good-token");
    answer = { status: 413, body: JSON.stringify({ detail: { code: "too_large", message: "big" } }) };
    drop(new File([new Uint8Array([37, 80, 68, 70])], "spec.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(sent.length).toBe(1));
    expect(signedOut).not.toHaveBeenCalled();
    expect(isSignedIn()).toBe(true);
    onSignedOut(null);
  });
});
