import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { Connection } from "../components/Shell";
import { DocumentsView } from "./DocumentsView";
import type {
  ChunkRecord,
  ClassificationCoverage,
  ClassificationVocabulary,
  DocumentClassification,
  DocumentRecord,
  ExclusionsResponse,
} from "../types/api";

const fullWorker = {
  alive: true,
  current_document: null,
  seconds_since_heartbeat: 0.4,
  seconds_since_progress: 12,
  documents_completed: 5,
  pending_count: 0,
  oldest_pending_age_seconds: null,
  stalled: false,
  stalled_reasons: [] as string[],
  last_error: null,
};

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: {
    // /api/health is unauthenticated and carries only
    // these three. The full worker status is on /api/metrics.
    alive: true,
    stalled: false,
    busy: false,
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
    disciplines: [],
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

// -------------------------------------------------------- classification

/** The vocabulary every test gets unless it overrides one. One type is
 *  enough for the pre-existing tests, which never look at grouping. */
const defaultVocabulary: ClassificationVocabulary = {
  register_revision: "r1",
  types: ["Document"],
  disciplines: ["Civil"],
  subjects: [],
  needs_classification: 0,
};

const defaultCoverage: ClassificationCoverage = {
  register_loaded: true,
  register_revision: "r1",
  by_type: [{ type: "Document", in_register: 1, uploaded: 1, unconfirmed: 0 }],
  by_discipline: [],
  by_subject: [],
  needs_classification: 0,
  corpus_wide: false,
};

/** What `/documents/{id}/classification` answers when a test does not care:
 *  a confirmed "Document", so the default corpus renders one plain chip
 *  rather than every test having to think about classification at all. */
function defaultClassification(id: string): DocumentClassification {
  return {
    document_id: id,
    doc_type: "Document",
    discipline: null,
    doc_class: null,
    register_id: null,
    suggested_by: "register",
    confirmed_by: "admin@example.com",
    confirmed_at: "2026-09-01T00:00:00Z",
    confirmed: true,
    subjects: [],
  };
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockApi(docs: DocumentRecord[], over: Record<string, unknown> = {}) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.includes("/health")) return jsonResponse(over.health ?? health);
    // The worker DETAIL now comes from the scoped metrics route, not from
    // health - so a test about the worker has to mock metrics.
    if (url.includes("/metrics")) return jsonResponse(over.metrics ?? { worker: fullWorker });
    if (url.includes("/excluded")) return jsonResponse(over.excluded ?? exclusions);
    if (url.includes("/chunks")) {
      const wantExcluded = url.includes("retrievable=false");
      return jsonResponse({
        total_matching: 1,
        limit: 25,
        offset: 0,
        chunks: [wantExcluded ? excludedChunk : chunk],
      });
    }
    if (url.includes("/pages")) {
      return jsonResponse({
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
      });
    }

    if (url.includes("/classification/vocabulary")) {
      return jsonResponse(over.vocabulary ?? defaultVocabulary);
    }
    if (url.includes("/classification/coverage")) {
      return jsonResponse(over.coverage ?? defaultCoverage);
    }
    const perDocMatch = url.match(/\/documents\/([^/]+)\/classification/);
    if (perDocMatch) {
      const id = decodeURIComponent(perDocMatch[1]);
      const byId = over.classificationById as Record<string, DocumentClassification> | undefined;
      if (method === "PUT") {
        // over.confirmStatus, when set, forces the write to fail with that
        // status - used to test the "you may not do this" 404 path.
        const forcedStatus = over.confirmStatus as number | undefined;
        if (forcedStatus && forcedStatus !== 200) {
          return jsonResponse(
            { detail: { code: "not_found", message: "Not found." } },
            forcedStatus,
          );
        }
        const posted = init?.body ? JSON.parse(init.body as string) : {};
        const base = byId?.[id] ?? defaultClassification(id);
        return jsonResponse({
          ...base,
          doc_type: posted.doc_type ?? base.doc_type,
          confirmed: true,
          confirmed_by: "tester@example.com",
          confirmed_at: "2026-09-07T00:00:00Z",
        } satisfies DocumentClassification);
      }
      return jsonResponse(byId?.[id] ?? defaultClassification(id));
    }

    return jsonResponse(docs);
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
        disciplines: [],
        embedded_count: 340,
        status: "partially_searchable",
        indexed_at: null,
      }),
    ]);
    render(<App />);

    const line = await screen.findByText(/1,204 pages/);
    expect(line).toHaveTextContent("2,831 passages");
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
        disciplines: [],
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
      health: { ...health, ingestion: { ...health.ingestion, stalled: true } },
      metrics: {
        worker: {
          ...fullWorker,
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
      metrics: {
        worker: { ...fullWorker, pending_count: 3, oldest_pending_age_seconds: 42 },
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

    await user.click(await screen.findByRole("button", { name: /passages/i }));
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
  it("states excluded pages in words, with a way to see which, rather than a quiet count", async () => {
    // Routine exclusions - contents pages, front matter - are stated plainly
    // and QUIETLY. They used to be wrapped in the same amber block as a
    // dropped clause, on twelve of thirteen cards, so the one card that
    // actually mattered looked like all the others. Visible, not alarming;
    // the alarm is reserved for the test below.
    mockApi([
      makeDoc({
        pages_excluded: 3,
        pages_excluded_characters: 9585,
        pages_excluded_with_clause_headings: 0,
      }),
    ]);
    render(<App />);
    expect(await screen.findByText(/3 pages left out of search/i)).toBeInTheDocument();
    expect(screen.getByText(/No numbered clause was among them/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /See which pages, and why/i }),
    ).toBeInTheDocument();
    // And it is NOT an alert: that role is reserved for a dropped clause.
    expect(screen.queryByRole("alert")).toBeNull();
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

// --------------------------------------------------- malformed API responses

describe("a malformed response is an error card, never a white screen", () => {
  it("does not crash when /documents returns a non-array", async () => {
    // DocumentsView did setLoad({documents: result.data}) with no shape check,
    // then .length, .map, and handed the same value to WorkerPanel, which
    // calls .find. IngestionView already guarded against exactly this and the
    // other three call sites did not, which is why the guard now lives once at
    // the client boundary instead of four times in the views.
    mockApi({ error: "not a list" } as never);
    render(<App />);
    expect(
      await screen.findByText(/could not read|That did not work/i),
    ).toBeInTheDocument();
  });
});

// -------------------------------------------------- classification grouping
//
// App.tsx does not yet pass `isAdmin` through to DocumentsView (that plumbing
// is one line outside this file's ownership - see the final report), so the
// admin-only assertions render DocumentsView directly rather than through
// <App/>, which always gets the safe `isAdmin` default of false.

const onlineConnection: Connection = { state: "online", health, at: Date.now() };

function renderDocuments(isAdmin = false) {
  render(
    <DocumentsView connection={onlineConnection} onRetryConnection={() => {}} isAdmin={isAdmin} />,
  );
}

const threeTypeVocabulary: ClassificationVocabulary = {
  register_revision: "r1",
  types: ["Document", "Drawing", "Licensor BEP"],
  disciplines: ["Civil"],
  subjects: [],
  needs_classification: 1,
};

function threeTypeCoverage(over: Partial<Record<string, number>> = {}): ClassificationCoverage {
  return {
    register_loaded: true,
    register_revision: "r1",
    by_type: [
      { type: "Document", in_register: 10, uploaded: over.Document ?? 1, unconfirmed: 0 },
      { type: "Drawing", in_register: 5, uploaded: over.Drawing ?? 1, unconfirmed: 1 },
      { type: "Licensor BEP", in_register: 2, uploaded: over["Licensor BEP"] ?? 0, unconfirmed: 0 },
    ],
    by_discipline: [],
    by_subject: [],
    needs_classification: over.needs_classification ?? 1,
    corpus_wide: false,
  };
}

function classificationFor(over: Partial<DocumentClassification>): DocumentClassification {
  return { ...defaultClassification(over.document_id ?? "doc"), ...over };
}

describe("documents grouped by classification type", () => {
  it("groups documents under a heading per register type", async () => {
    mockApi(
      [
        makeDoc({ id: "d1", filename: "spec-one.pdf" }),
        makeDoc({ id: "d2", filename: "drawing-one.pdf" }),
      ],
      {
        vocabulary: threeTypeVocabulary,
        coverage: threeTypeCoverage({ needs_classification: 0 }),
        classificationById: {
          d1: classificationFor({ document_id: "d1", doc_type: "Document" }),
          d2: classificationFor({ document_id: "d2", doc_type: "Drawing" }),
        },
      },
    );
    renderDocuments();

    const documentHeading = await screen.findByRole("heading", { name: /^Document\s/ });
    expect(within(documentHeading).getByText("1")).toBeInTheDocument();
    const drawingHeading = screen.getByRole("heading", { name: /^Drawing\s/ });
    expect(within(drawingHeading).getByText("1")).toBeInTheDocument();

    expect(screen.getByText("spec-one.pdf")).toBeInTheDocument();
    expect(screen.getByText("drawing-one.pdf")).toBeInTheDocument();
  });

  it("renders a type the register lists but this caller has none of as an honest empty line", async () => {
    mockApi([makeDoc({ id: "d1", filename: "spec-one.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage({ needs_classification: 0 }),
      classificationById: { d1: classificationFor({ document_id: "d1", doc_type: "Document" }) },
    });
    renderDocuments();

    await screen.findByText("spec-one.pdf");
    // A group that vanished for having no documents would be indistinguishable
    // from a group nobody built - this line is the proof the empty group was
    // still generated.
    expect(
      screen.getByText(/None of the documents you can open is a Licensor BEP\./i),
    ).toBeInTheDocument();
  });

  it("puts a document with no classification yet in its own awaiting group, never as a guessed type", async () => {
    mockApi([makeDoc({ id: "d1", filename: "unclassified.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage(),
      classificationById: {
        d1: classificationFor({ document_id: "d1", doc_type: null, confirmed: false, suggested_by: "none" }),
      },
    });
    renderDocuments();

    const heading = await screen.findByRole("heading", { name: /Awaiting a type/i });
    expect(within(heading).getByText("1")).toBeInTheDocument();
    expect(screen.getByText("unclassified.pdf")).toBeInTheDocument();
    // Never a guessed type, never "Unknown", never a blank chip.
    expect(screen.queryByText(/^unknown$/i)).toBeNull();
    expect(screen.getByText(/Awaiting a type/i)).toBeInTheDocument();
  });

  it("renders an unconfirmed guess in amber, distinct from a confirmed type", async () => {
    mockApi(
      [
        makeDoc({ id: "d1", filename: "guessed.pdf" }),
        makeDoc({ id: "d2", filename: "confirmed.pdf" }),
      ],
      {
        vocabulary: threeTypeVocabulary,
        coverage: threeTypeCoverage(),
        classificationById: {
          d1: classificationFor({
            document_id: "d1",
            doc_type: "Drawing",
            confirmed: false,
            suggested_by: "filename",
          }),
          d2: classificationFor({ document_id: "d2", doc_type: "Document", confirmed: true }),
        },
      },
    );
    renderDocuments();

    await screen.findByText("guessed.pdf");
    const guessChip = screen.getByText(/Drawing\? · guessed from the title/i);
    expect(guessChip).toBeInTheDocument();
    expect(guessChip.className).toMatch(/warn-500/);

    // The confirmed document's chip carries NEITHER the amber classes nor a
    // question mark - the two things that mark a guess.
    const plainChip = screen.getByText("Document", { selector: "[data-testid=type-chip]" });
    expect(plainChip.className).not.toMatch(/warn-500/);
    expect(plainChip.textContent).not.toMatch(/\?/);
  });

  it("shows no confirm control for a non-admin, only a note that an administrator must act", async () => {
    mockApi([makeDoc({ id: "d1", filename: "guessed.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage(),
      classificationById: {
        d1: classificationFor({
          document_id: "d1",
          doc_type: "Drawing",
          confirmed: false,
          suggested_by: "filename",
        }),
      },
    });
    renderDocuments(false);

    await screen.findByText("guessed.pdf");
    expect(
      screen.getByText(/Awaiting confirmation by an administrator/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Confirm$/ })).toBeNull();
  });

  it("lets an admin confirm a guessed type, updating the card in place", async () => {
    mockApi([makeDoc({ id: "d1", filename: "guessed.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage(),
      classificationById: {
        d1: classificationFor({
          document_id: "d1",
          doc_type: "Drawing",
          confirmed: false,
          suggested_by: "filename",
        }),
      },
    });
    const user = userEvent.setup();
    renderDocuments(true);

    await screen.findByText("guessed.pdf");
    expect(screen.getByRole("button", { name: /^Confirm$/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Confirm$/ }));

    // The strip disappears and the chip goes plain once confirmed is true.
    await waitFor(() =>
      expect(screen.queryByText(/guessed from the title/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Drawing", { selector: "[data-testid=type-chip]" })).toBeInTheDocument();
  });

  it("treats a 404 on confirm as a permission refusal, never as the document being gone", async () => {
    mockApi([makeDoc({ id: "d1", filename: "guessed.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage(),
      classificationById: {
        d1: classificationFor({
          document_id: "d1",
          doc_type: "Drawing",
          confirmed: false,
          suggested_by: "filename",
        }),
      },
      confirmStatus: 404,
    });
    const user = userEvent.setup();
    renderDocuments(true);

    await screen.findByText("guessed.pdf");
    await user.click(screen.getByRole("button", { name: /^Confirm$/ }));

    expect(
      await screen.findByText(/do not have permission to confirm/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/does not exist|not found|gone/i)).toBeNull();
  });

  it("narrows the list to the ticked type and clears back to everything", async () => {
    mockApi(
      [
        makeDoc({ id: "d1", filename: "spec-one.pdf" }),
        makeDoc({ id: "d2", filename: "drawing-one.pdf" }),
      ],
      {
        vocabulary: threeTypeVocabulary,
        coverage: threeTypeCoverage({ needs_classification: 0 }),
        classificationById: {
          d1: classificationFor({ document_id: "d1", doc_type: "Document" }),
          d2: classificationFor({ document_id: "d2", doc_type: "Drawing" }),
        },
      },
    );
    const user = userEvent.setup();
    renderDocuments();

    await screen.findByText("spec-one.pdf");
    expect(screen.getByText("drawing-one.pdf")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /^Drawing/ }));
    expect(screen.queryByText("spec-one.pdf")).toBeNull();
    expect(screen.getByText("drawing-one.pdf")).toBeInTheDocument();

    // Nothing ticked = no filter = show everything again.
    await user.click(screen.getByRole("checkbox", { name: /^All$/ }));
    expect(screen.getByText("spec-one.pdf")).toBeInTheDocument();
    expect(screen.getByText("drawing-one.pdf")).toBeInTheDocument();
  });

  it("shows the coverage endpoint's own counts on the filter chips, not a locally counted total", async () => {
    // ONE document of type Drawing is loaded, but coverage claims 37 - a
    // number that could only have come from the server. If this component
    // ever starts counting the documents it fetched instead of trusting
    // coverage, this assertion is the one that catches it.
    mockApi([makeDoc({ id: "d1", filename: "drawing-one.pdf" })], {
      vocabulary: threeTypeVocabulary,
      coverage: threeTypeCoverage({ Drawing: 37, needs_classification: 0 }),
      classificationById: {
        d1: classificationFor({ document_id: "d1", doc_type: "Drawing" }),
      },
    });
    renderDocuments();

    const drawingChip = await screen.findByRole("checkbox", { name: /^Drawing/ });
    expect(within(drawingChip).getByText("37")).toBeInTheDocument();
    expect(within(drawingChip).queryByText("1")).toBeNull();
  });
});
