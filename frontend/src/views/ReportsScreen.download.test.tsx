/**
 * The report download.
 *
 * The defect these tests pin down: the download was a `window.open` of a plain
 * URL. A navigation carries no Authorization header, and the bearer token is
 * held in memory only, so under auth_mode=demo_required the request resolved to
 * an empty scope and the backend answered
 *
 *     404 {"detail":{"code":"not_found","message":"no report with that id"}}
 *
 * for a report listed on the same screen. The reader was told their own report
 * did not exist.
 *
 * Four properties are asserted here, and each one was mutation-proved:
 *  1. the download request carries the Authorization header
 *  2. no token appears in any URL the client constructs
 *  3. a non-2xx produces a visible error and NO file
 *  4. the object URL is revoked
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken, onSignedOut, filenameFromContentDisposition } from "../api/client";
import type { ReportList, ReportRecord } from "../types/api";
import { ReportsScreen } from "./ReportsScreen";

const TOKEN = "tok_secret_do_not_log_9f3a2b";

const record: ReportRecord = {
  id: "rpt_abc123def456",
  question: "what are the vibration limits for pump P-101A",
  resolved_question: null,
  created_at: "2026-09-05T17:00:00+00:00",
  page_count: 1,
  size_bytes: 41_000,
  report_sha256: "a".repeat(64),
  owner_username: "demo",
  documents: [],
  not_implemented_sections: [],
};

const list: ReportList = { reports: [record], suppressed_count: 0 };

/** Every URL fetch() was called with, in order. */
let urls: string[] = [];
/** Every RequestInit fetch() was called with, in order. */
let inits: (RequestInit | undefined)[] = [];

let createdUrls: string[] = [];
let revokedUrls: string[] = [];
/** Anchors that were actually clicked - one click is one file offered. */
let clicked: { href: string; download: string }[] = [];

/**
 * Stand in for the download endpoint. Everything else answers with the list.
 *
 * The PDF response is built with a real Response so the client's own header
 * reading and blob reading are exercised rather than mocked away.
 */
function stubFetch(pdf: () => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      urls.push(url);
      inits.push(init);
      if (url.includes("/download")) return Promise.resolve(pdf());
      return Promise.resolve(
        new Response(JSON.stringify(list), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

function pdfResponse(headers: Record<string, string> = {}) {
  // A Uint8Array, not a jsdom Blob: undici cannot read a jsdom Blob as a
  // request body (`object.stream is not a function`). The bytes are the PDF
  // magic number so the fixture is at least a plausible file.
  return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
    status: 200,
    headers: { "Content-Type": "application/pdf", ...headers },
  });
}

beforeEach(() => {
  urls = [];
  inits = [];
  createdUrls = [];
  revokedUrls = [];
  clicked = [];

  // jsdom implements neither. The revoke stub is what the leak test asserts on.
  let n = 0;
  vi.stubGlobal("URL", Object.assign(globalThis.URL, {
    createObjectURL: vi.fn(() => {
      const u = `blob:http://localhost/obj-${++n}`;
      createdUrls.push(u);
      return u;
    }),
    revokeObjectURL: vi.fn((u: string) => {
      revokedUrls.push(u);
    }),
  }));

  // Record clicks on the anchor the screen creates, and stop jsdom from
  // complaining about an unimplemented navigation.
  const realCreate = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation((tag: string, opts?: unknown) => {
    const el = realCreate(tag as "a", opts as ElementCreationOptions);
    if (tag === "a") {
      (el as HTMLAnchorElement).click = () => {
        const a = el as HTMLAnchorElement;
        clicked.push({ href: a.getAttribute("href") ?? "", download: a.download });
      };
    }
    return el;
  });

  setToken(TOKEN);
});

afterEach(() => {
  setToken(null);
  onSignedOut(null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function clickDownload() {
  render(<ReportsScreen />);
  const button = await screen.findByRole("button", { name: "Download" });
  await userEvent.click(button);
}

/** The URL the download request was actually issued to. */
function downloadUrl(): string {
  const u = urls.find((x) => x.includes("/download"));
  expect(u, "no download request was issued").toBeDefined();
  return u as string;
}

function authHeaderOf(url: string): string | null {
  const i = urls.indexOf(url);
  return new Headers(inits[i]?.headers).get("Authorization");
}

describe("report download: the request", () => {
  it("carries the Authorization header — the whole point of the fix", async () => {
    stubFetch(() => pdfResponse());
    await clickDownload();

    await waitFor(() => expect(urls.some((u) => u.includes("/download"))).toBe(true));
    // A navigation could never do this, which is why window.open produced a
    // 404 for a report the same screen had just listed.
    expect(authHeaderOf(downloadUrl())).toBe(`Bearer ${TOKEN}`);
  });

  it("puts the token in NO url — not the path, not the query, not the fragment", async () => {
    stubFetch(() => pdfResponse());
    await clickDownload();
    await waitFor(() => expect(clicked).toHaveLength(1));

    // Assert on the URL strings themselves. A token in a URL lands in browser
    // history, proxy and server access logs, and Referer headers.
    for (const u of urls) {
      expect(u, `token leaked into a request url: ${u}`).not.toContain(TOKEN);
      expect(u).not.toMatch(/token|bearer|authorization|access_token/i);
    }
    // And not into the href handed to the browser either.
    for (const c of clicked) {
      expect(c.href).not.toContain(TOKEN);
    }
    expect(downloadUrl()).toBe("/api/reports/rpt_abc123def456/download");
  });
});

describe("report download: success", () => {
  it("saves the bytes under the Content-Disposition filename when the server sends one", async () => {
    // Deliberately NOT the fallback name. An earlier version of this test used
    // the server's real name, which happens to equal the fallback exactly - so
    // deleting the Content-Disposition read entirely left the test green.
    stubFetch(() =>
      pdfResponse({ "Content-Disposition": 'attachment; filename="server-chose-this.pdf"' }),
    );
    await clickDownload();

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0].download).toBe("server-chose-this.pdf");
    // The fallback literal from api/client.ts, still un-renamed - see below.
    expect(clicked[0].download).not.toBe("nabaa-report-rpt_abc123def456.pdf");
    expect(clicked[0].href).toBe(createdUrls[0]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("uses the name this backend actually sends", async () => {
    // main.py - FileResponse(filename=f"rag-intelligence-report-{report_id}.pdf"),
    // which Starlette emits as `attachment; filename="..."`. This is the name a
    // reader actually gets, because the header wins whenever the server sends
    // one; the test above is what proves the header is genuinely read.
    stubFetch(() =>
      pdfResponse({
        "Content-Disposition":
          'attachment; filename="rag-intelligence-report-rpt_abc123def456.pdf"',
      }),
    );
    await clickDownload();

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0].download).toBe("rag-intelligence-report-rpt_abc123def456.pdf");
  });

  it("falls back to a sane name when the server sends no Content-Disposition", async () => {
    stubFetch(() => pdfResponse());
    await clickDownload();

    await waitFor(() => expect(clicked).toHaveLength(1));
    // STILL THE OLD NAME, and deliberately so: this asserts the fallback
    // literal in api/client.ts, which has not been renamed yet. The two must
    // change together - renaming only this expectation turns a real mismatch
    // into a green test. See the note in the rename report.
    expect(clicked[0].download).toBe("nabaa-report-rpt_abc123def456.pdf");
  });

  it("revokes the object URL — a leaked one pins the whole PDF in memory", async () => {
    stubFetch(() => pdfResponse());
    await clickDownload();

    await waitFor(() => expect(createdUrls).toHaveLength(1));
    await waitFor(() => expect(revokedUrls).toEqual(createdUrls));
  });
});

describe("report download: failure produces a message and no file", () => {
  /** The exact defect: 404 for a report that is listed right there. */
  it("404 says no file came back, and does NOT repeat the backend's 'no report with that id'", async () => {
    stubFetch(
      () =>
        new Response(
          JSON.stringify({ detail: { code: "not_found", message: "no report with that id" } }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
    );
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No file came back for this report");
    expect(alert).toHaveTextContent("Nothing has been saved.");
    // Existence is not asserted in either direction.
    expect(alert.textContent).not.toMatch(/no report with that id/i);
    expect(alert.textContent).not.toMatch(/does not exist|never existed/i);
    // ...and no file was offered.
    expect(clicked).toEqual([]);
    expect(createdUrls).toEqual([]);
  });

  it("401 tells the reader they are not signed in", async () => {
    stubFetch(() => new Response("", { status: 401 }));
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You are not signed in");
    expect(clicked).toEqual([]);
    expect(createdUrls).toEqual([]);
  });

  it("403 says refused, and does not say the report is missing", async () => {
    stubFetch(() => new Response("", { status: 403 }));
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The download was refused");
    expect(clicked).toEqual([]);
  });

  it("500 reports a server failure and writes nothing", async () => {
    stubFetch(() => new Response("", { status: 500 }));
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The download failed");
    expect(clicked).toEqual([]);
    expect(createdUrls).toEqual([]);
  });

  it("a network failure reads as unreachable, not as a missing report", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the backend");
    expect(clicked).toEqual([]);
    expect(createdUrls).toEqual([]);
  });

  it("a body that dies mid-PDF saves nothing, even though the status said 200", async () => {
    // The status line arrives before the bytes. A connection dropped during
    // the body throws on the read, on a response that already said 200 - and
    // a half-read PDF handed to the reader is the worst outcome of all,
    // because it looks like a file.
    stubFetch(() => {
      const r = pdfResponse();
      Object.defineProperty(r, "blob", {
        value: () => Promise.reject(new TypeError("terminated")),
      });
      return r;
    });
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the backend");
    expect(alert).toHaveTextContent("Nothing has been saved.");
    expect(clicked).toEqual([]);
    expect(createdUrls).toEqual([]);
  });

  it("a gateway status reads as unreachable rather than as an API error", async () => {
    stubFetch(() => new Response("", { status: 503 }));
    await clickDownload();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the backend");
    expect(clicked).toEqual([]);
  });
});

describe("filenameFromContentDisposition", () => {
  it("reads a quoted filename", () => {
    expect(filenameFromContentDisposition('attachment; filename="a b.pdf"')).toBe("a b.pdf");
  });
  it("reads a bare filename", () => {
    expect(filenameFromContentDisposition("attachment; filename=a.pdf")).toBe("a.pdf");
  });
  it("prefers the RFC 5987 form", () => {
    expect(
      filenameFromContentDisposition("attachment; filename=\"x.pdf\"; filename*=UTF-8''%C3%A5.pdf"),
    ).toBe("å.pdf");
  });
  it("returns null when there is no filename", () => {
    expect(filenameFromContentDisposition("attachment")).toBeNull();
    expect(filenameFromContentDisposition(null)).toBeNull();
  });
  it("reduces a server-sent path to a bare name", () => {
    // A `download` attribute is not a place to let the server pick directories.
    expect(filenameFromContentDisposition('attachment; filename="../../etc/passwd"')).toBe("passwd");
  });
});
