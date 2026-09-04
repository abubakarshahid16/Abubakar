import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { ChunkRecord, DocumentRecord, ExclusionsResponse } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model: "qwen3.5:4b",
  ingestion: {
    alive: true,
    current_document: null,
    seconds_since_heartbeat: 0.5,
    seconds_since_progress: 20,
    documents_completed: 5,
    pending_count: 0,
    oldest_pending_age_seconds: null,
    stalled: false,
    stalled_reasons: [],
    last_error: null,
  },
};

function makeDoc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc_book1",
    filename: "book1-professionalpractices.pdf",
    sha256: "b02fb622b193",
    size_bytes: 11482200,
    page_count: 546,
    pages_done: 546,
    chunk_count: 1096,
    chunk_count_total: 1110,
    embedded_count: 1096,
    status: "ready",
    needs_ocr_pages: 12,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    uploaded_at: "2026-09-04T00:00:00Z",
    indexed_at: "2026-09-04T00:10:00Z",
    ...over,
  };
}

const chunk: ChunkRecord = {
  id: "b02fb622b193:p00024:c00030:01e60cd0",
  ordinal: 30,
  page_start: 24,
  page_end: 24,
  section: "1.1 The Pace of Change",
  kind: "prose",
  token_count: 297,
  content_hash: "01e60cd0fac74a6d",
  retrievable: true,
  quality_flags: null,
  text: "experimental cars drive themselves. Computer programs beat human experts at chess.",
};

const excludedChunk: ChunkRecord = {
  ...chunk,
  id: "b02fb622b193:p00570:c01402:7f29a168",
  ordinal: 1402,
  page_start: 570,
  page_end: 570,
  section: null,
  retrievable: false,
  quality_flags: "no_clause(longest=1<6)",
  text: "eabeb2terfcb 1t a 2 1t ea1s",
};

const exclusions: ExclusionsResponse = {
  total: 423,
  summary: [
    { scope: "chunk", rule: "content_quality_gate", count: 400, characters_dropped: 72882 },
    { scope: "page", rule: "page_classified_toc", count: 8, characters_dropped: 7866 },
  ],
  limit: 25,
  offset: 0,
  excluded: [
    {
      scope: "chunk",
      page_start: 570,
      page_end: 570,
      chunk_id: "c1",
      rule: "content_quality_gate",
      reason: "no_clause(longest=1<6)",
      text_length: 480,
      text_sample: "eabeb2terfcb 1t a 2 1t ea1s 1s(1s b)",
    },
  ],
};

function mockApi(docs: DocumentRecord[], over: Record<string, unknown> = {}) {
  const spy = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = (() => {
      if (url.includes("/health")) return over.health ?? health;
      if (url.includes("/excluded")) return over.excluded ?? exclusions;
      if (url.includes("/chunks")) {
        const wantExcluded = url.includes("retrievable=false");
        return {
          total_matching: 1,
          limit: 25,
          offset: 0,
          chunks: [wantExcluded ? excludedChunk : chunk],
        };
      }
      if (url.includes("/pages")) {
        return {
          total: 1,
          limit: 100,
          offset: 0,
          pages: [
            {
              page_no: 1,
              char_count: 1200,
              needs_ocr: false,
              equation_heavy: false,
              batch_no: 0,
              preview: "…",
            },
          ],
        };
      }
      return docs;
    })();
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("B2 documents list", () => {
  it("shows the live ingestion progress line and does not say ready mid-embed", async () => {
    mockApi([
      makeDoc({
        filename: "big-spec.pdf",
        page_count: 1204,
        chunk_count: 2831,
        chunk_count_total: 2900,
        embedded_count: 340,
        status: "partially_searchable",
        indexed_at: null,
      }),
    ]);
    render(<App />);

    const line = await screen.findByText(/1,204 pages/);
    expect(line).toHaveTextContent("2,831 sections");
    expect(line).toHaveTextContent("keyword search ready");
    expect(line).toHaveTextContent("340/2,831 embedded");

    expect(screen.getByText("partially searchable")).toBeInTheDocument();
    expect(screen.queryByText(/^ready$/)).not.toBeInTheDocument();
  });

  it("renders no_searchable_content as a warning with its reason", async () => {
    mockApi([
      makeDoc({
        filename: "scanned-spec.pdf",
        page_count: 3,
        needs_ocr_pages: 3,
        chunk_count: 0,
        chunk_count_total: 0,
        embedded_count: 0,
        status: "no_searchable_content",
        error: {
          code: "no_searchable_content",
          message: "all 3 pages are scanned images with no extractable text; OCR is not implemented",
        },
      }),
    ]);
    render(<App />);

    expect(await screen.findByText("no searchable content")).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(/Nothing on this document is searchable/i)).toBeInTheDocument();
    expect(within(alert).getByText(/scanned images/i)).toBeInTheDocument();
  });

  it("warns prominently when the retrievable ratio is under 60%", async () => {
    mockApi([makeDoc({ chunk_count: 400, chunk_count_total: 1000, embedded_count: 400 })]);
    render(<App />);

    expect(await screen.findByText(/Only 40% of this document is searchable/i)).toBeInTheDocument();
    expect(screen.getByText(/quality gate may be over-rejecting/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /see what was excluded/i })).toBeInTheDocument();
  });

  it("does not warn when the ratio is healthy", async () => {
    mockApi([makeDoc()]);
    render(<App />);
    await screen.findByText(/book1-professionalpractices/);
    expect(screen.queryByText(/of this document is searchable/i)).not.toBeInTheDocument();
  });

  it("warns only about scanned pages recognition has NOT yet read", async () => {
    mockApi([makeDoc({ needs_ocr_pages: 12, recognised_pages: 0, equation_pages: 11 })]);
    render(<App />);
    expect(await screen.findByText("12 awaiting OCR")).toBeInTheDocument();
    expect(screen.getByText("11 equation-heavy")).toBeInTheDocument();
  });

  it("states the OCR fraction as a fact once pages have been read", async () => {
    // A document being partly OCR'd is a capability working, not a problem, so
    // this belongs with the per-document facts and NOT in an amber pill. The
    // fraction matters: a bare "12" invites reading a 546-page document as an
    // OCR'd one.
    mockApi([
      makeDoc({ page_count: 546, needs_ocr_pages: 12, recognised_pages: 12 }),
    ]);
    render(<App />);
    expect(
      await screen.findByText(/12 of 546 pages\s+read by OCR/),
    ).toBeInTheDocument();
    // Nothing is outstanding, so the warning must be GONE - asserting the
    // absence, because a stale amber badge is a false alarm.
    expect(screen.queryByText(/awaiting OCR/)).toBeNull();
  });

  it("shows both when recognition is only part-way through", async () => {
    mockApi([
      makeDoc({ page_count: 546, needs_ocr_pages: 12, recognised_pages: 5 }),
    ]);
    render(<App />);
    expect(await screen.findByText("7 awaiting OCR")).toBeInTheDocument();
    expect(screen.getByText(/5 of 546 pages\s+read by OCR/)).toBeInTheDocument();
  });

  it("requires a second click to delete", async () => {
    mockApi([makeDoc()]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("button", { name: /confirm delete/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("button", { name: /confirm delete/i })).not.toBeInTheDocument();
  });

  it("shows an empty state rather than a blank screen", async () => {
    mockApi([]);
    render(<App />);
    expect(await screen.findByText(/No documents yet/i)).toBeInTheDocument();
  });
});

describe("worker panel", () => {
  it("shows a stalled worker with its reasons", async () => {
    mockApi([makeDoc()], {
      health: {
        ...health,
        ingestion: {
          ...health.ingestion,
          stalled: true,
          pending_count: 6,
          oldest_pending_age_seconds: 900,
          stalled_reasons: ["6_pending_but_no_progress_for_240s"],
        },
      },
    });
    render(<App />);

    // The reason code is now a sentence, and the alarm names the situation
    // rather than shouting an internal flag.
    expect(await screen.findByText("not moving")).toBeInTheDocument();
    expect(
      screen.getByText(/6 documents are waiting, and nothing has moved/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/6_pending_but_no_progress_for_240s/)).toBeNull();
  });

  it("shows the backlog even when not stalled", async () => {
    mockApi([makeDoc()], {
      health: {
        ...health,
        ingestion: { ...health.ingestion, pending_count: 3, oldest_pending_age_seconds: 42 },
      },
    });
    render(<App />);
    await screen.findByText(/Ingestion worker/);
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});

describe("B3 chunk inspector", () => {
  it("opens, shows full chunk detail, and can filter to excluded chunks", async () => {
    mockApi([makeDoc()]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /inspect chunks/i }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getByText("1.1 The Pace of Change")).toBeInTheDocument();
    expect(within(dialog).getByText(/297 tokens/)).toBeInTheDocument();
    expect(within(dialog).getByText(/page 24/)).toBeInTheDocument();
    expect(within(dialog).getByText(/experimental cars drive themselves/)).toBeInTheDocument();
    expect(within(dialog).getByText(chunk.id)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Excluded" }));
    await waitFor(() =>
      expect(within(dialog).getByText(/no_clause\(longest=1<6\)/)).toBeInTheDocument(),
    );
    expect(
      within(dialog).getByText(/left blank rather than guessed/i),
    ).toBeInTheDocument();
  });
});

describe("B4 excluded viewer", () => {
  it("groups by rule so a bulk exclusion is visible at a glance", async () => {
    mockApi([makeDoc()]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Excluded" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getAllByText("content_quality_gate").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("400 chunks")).toBeInTheDocument();
    expect(within(dialog).getByText("page_classified_toc")).toBeInTheDocument();
    expect(within(dialog).getByText(/eabeb2terfcb/)).toBeInTheDocument();
  });

  it("is reachable in one click from the low-ratio warning", async () => {
    mockApi([makeDoc({ chunk_count: 400, chunk_count_total: 1000 })]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /see what was excluded/i }));
    expect(await screen.findByRole("dialog")).toHaveAccessibleName(/Excluded from search/i);
  });
});

describe("B5 page image viewer", () => {
  it("shows the rendered page and offers zoom", async () => {
    mockApi([makeDoc()]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Pages" }));
    const dialog = await screen.findByRole("dialog");

    const img = within(dialog).getByRole("img", { name: /Page 1 of/i });
    expect(img).toHaveAttribute("src", "/api/documents/doc_book1/pages/1/image");
    expect(within(dialog).getByRole("group", { name: /zoom/i })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "200%" }));
    expect(within(dialog).getByRole("button", { name: "200%" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("closes on Escape", async () => {
    mockApi([makeDoc()]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Pages" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

// ------------------------------------------------- excluded pages (FIX 1b)

describe("excluded pages are impossible to miss", () => {
  it("warns about excluded pages rather than showing a quiet count", async () => {
    mockApi([
      makeDoc({
        pages_excluded: 3,
        pages_excluded_characters: 9585,
        pages_excluded_with_clause_headings: 0,
      }),
    ]);
    render(<App />);
    expect(await screen.findByText(/3 pages excluded from search/i)).toBeInTheDocument();
    expect(screen.getByText(/9,585 characters are not searchable/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /See which pages, and why/i }),
    ).toBeInTheDocument();
  });

  it("escalates to an ALERT when a dropped page carried clause headings", async () => {
    mockApi([
      makeDoc({
        pages_excluded: 1,
        pages_excluded_characters: 3195,
        pages_excluded_with_clause_headings: 1,
      }),
    ]);
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/contains? numbered clause headings/i);
    expect(alert).toHaveTextContent(/Real content has almost certainly been dropped/i);
    // and it is not softened into the ordinary warning wording
    expect(screen.queryByText(/excluded on purpose/i)).toBeNull();
  });

  it("says nothing when no page was excluded", async () => {
    mockApi([makeDoc({ pages_excluded: 0, pages_excluded_with_clause_headings: 0 })]);
    render(<App />);
    await screen.findByText("book1-professionalpractices.pdf");
    expect(screen.queryByText(/excluded from search/i)).toBeNull();
  });
});
