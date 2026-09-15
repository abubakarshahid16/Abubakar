/**
 * The "Search in" type filter, on the Analysis screen.
 *
 * Each test here fails if the code holding its rule is removed - the
 * documented recurring defect in this project is a test that still passes
 * after the feature is deleted, so every assertion below is anchored to
 * something a deleted feature could not produce:
 *
 *  - ticking a type puts `scope.types` in the body of ALL THREE analysis
 *    calls (summary, gaps, recommendations) - the same scope to every engine,
 *    because the backend's shared narrowing function exists so two panels on
 *    one screen can never answer about different slices of the corpus.
 *  - nothing ticked sends NO `scope` key at all (not `scope: null`, not
 *    `scope: {}`) - the route must behave byte-for-byte as it did before this
 *    feature existed.
 *  - the rendered count is the SERVER'S `documents_in_scope`, never one this
 *    screen computed - proved by mocking a response whose count differs from
 *    the number of documents actually mocked elsewhere on the page.
 *  - reticking after a run replaces the count with the pending notice, rather
 *    than leaving a now-stale number on screen.
 *  - an empty result under an active filter says the filter narrowed the
 *    search, which is a different fact from the documents having nothing to
 *    say.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen } from "./AnalysisModeScreen";

// ------------------------------------------------------------------ fixtures

const EV: EvidenceItem = {
  evidence_id: "ev1",
  document_id: "doc_1",
  filename: "pump-spec.pdf",
  page_start: 12,
  page_end: 12,
  section: "4.2",
  exact_span: "The discharge pressure shall not be less than 250 kPa.",
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  relevance_score: null,
  relevance_score_type: null,
};

function summaryBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    summary: "The discharge pressure floor is 250 kPa [S1].",
    summary_truncated: false,
    summary_cited_evidence_ids: ["ev1"],
    documented_findings: [
      { claim: "Discharge pressure floor is 250 kPa.", citation_ids: ["ev1"], text_source: "extracted" },
    ],
    rejected_citations: [],
    evidence_removed: [],
    refusal: null,
    dropped_sentences: [],
    not_implemented_sections: [],
    ...over,
  };
}

function gapsBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    claim_clusters: [
      {
        facet: ["discharge pressure"],
        label: "agreement",
        rows: [
          {
            evidence_id: "ev1",
            filename: "pump-spec.pdf",
            page_start: 12,
            section: "4.2",
            exact_span: EV.exact_span,
            raw_value: "250",
            raw_unit: "kPa",
            normalized_value: null,
            normalized_unit: null,
          },
        ],
        note: null,
      },
    ],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    not_implemented_sections: [],
    ...over,
  };
}

function recommendationBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    recommendation: {
      text: "Specify a pump rated above the 250 kPa floor [S1].",
      citation_ids: ["ev1"],
      basis: "documents_only",
      confidence: "low",
      checks: [],
    },
    public_market_findings: [],
    not_implemented_sections: [],
    ...over,
  };
}

const VOCAB = {
  register_revision: "r1",
  types: ["Drawing", "Specification"],
  disciplines: [],
  subjects: [],
  needs_classification: 0,
};

const COVERAGE = {
  register_loaded: true,
  register_revision: "r1",
  by_type: [
    { type: "Drawing", in_register: 10, uploaded: 4, unconfirmed: 0 },
    { type: "Specification", in_register: 20, uploaded: 16, unconfirmed: 0 },
  ],
  by_discipline: [],
  by_subject: [],
  needs_classification: 0,
  corpus_wide: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * A fetch mock that always answers the classification lookups (so the "Search
 * in" control has a vocabulary to render) plus whatever analysis routes the
 * test supplies, and records every request's parsed JSON body keyed by route.
 */
function mockFetch(analysisAnswers: Record<string, () => Promise<Response>>) {
  const bodies: Record<string, unknown[]> = {
    "/analysis/summary": [],
    "/analysis/gaps": [],
    "/analysis/recommendations": [],
  };
  const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/classification/vocabulary")) return Promise.resolve(json(VOCAB));
    if (url.includes("/classification/coverage")) return Promise.resolve(json(COVERAGE));
    for (const route of Object.keys(bodies)) {
      if (url.includes(route)) {
        if (typeof init?.body === "string") bodies[route].push(JSON.parse(init.body));
        const answer = analysisAnswers[route];
        if (answer) return answer();
      }
    }
    return Promise.reject(new Error(`unrouted ${url}`));
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, bodies };
}

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => resetAnalysisScreen());

async function waitForVocabulary() {
  // The vocabulary read is async (useTypeVocabulary); the control renders
  // nothing until it answers.
  await screen.findByRole("checkbox", { name: /^Drawing/ });
}

async function askWithBothToggles(user: ReturnType<typeof userEvent.setup>) {
  // Turn on every engine that takes a scope: summary (the default, via
  // "focused" mode), gaps and recommendation.
  await user.click(screen.getByRole("checkbox", { name: /gap analysis/i }));
  await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
  await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
}

// -------------------------------------------------------------- the request

describe("AnalysisModeScreen: the Search in filter reaches every engine identically", () => {
  it("puts scope.types in the body of the summary, gaps AND recommendation calls", async () => {
    const user = userEvent.setup();
    const { bodies } = mockFetch({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/gaps": () => Promise.resolve(json(gapsBody())),
      "/analysis/recommendations": () => Promise.resolve(json(recommendationBody())),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.click(screen.getByRole("checkbox", { name: /^Drawing/ }));
    await askWithBothToggles(user);

    await waitFor(() => {
      expect(bodies["/analysis/summary"]).toHaveLength(1);
      expect(bodies["/analysis/gaps"]).toHaveLength(1);
      expect(bodies["/analysis/recommendations"]).toHaveLength(1);
    });

    // The SAME scope, on all three - not one filtered call and two unfiltered
    // ones, which is exactly the defect the backend's shared narrowing
    // function was written to make impossible from its side.
    for (const route of ["/analysis/summary", "/analysis/gaps", "/analysis/recommendations"]) {
      expect((bodies[route][0] as { scope?: { types: string[] } }).scope).toEqual({
        types: ["Drawing"],
      });
    }
  });

  it("sends NO scope key at all when nothing is ticked", async () => {
    const user = userEvent.setup();
    const { bodies } = mockFetch({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    await waitFor(() => expect(bodies["/analysis/summary"]).toHaveLength(1));
    // Not `scope: undefined` reaching JSON.stringify (which would also drop
    // the key) but the key genuinely absent from the object built - the
    // assertion that would catch a `scope: null` regression too.
    expect(Object.prototype.hasOwnProperty.call(bodies["/analysis/summary"][0], "scope")).toBe(
      false,
    );
  });
});

// -------------------------------------------------------------- the render

describe("AnalysisModeScreen: the rendered scope count is the server's, never a local count", () => {
  it("renders documents_in_scope from applied_scope even though it differs from the ledger's document count", async () => {
    const user = userEvent.setup();
    mockFetch({
      // Only ONE document is mocked in the evidence ledger below, but the
      // server's applied_scope says 7 documents are in scope. If this screen
      // were computing the count itself from what it can see, it could only
      // ever say 1 - rendering 7 is the proof the number came from the wire.
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              applied_scope: {
                applied: true,
                types: ["Drawing"],
                disciplines: [],
                subject_ids: [],
                documents_in_scope: 7,
              },
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.click(screen.getByRole("checkbox", { name: /^Drawing/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(await screen.findByText(/7 documents in scope/)).toBeInTheDocument();
  });

  it("shows the pending notice, not a stale count, once the ticks change after a run", async () => {
    const user = userEvent.setup();
    mockFetch({
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              applied_scope: {
                applied: true,
                types: ["Drawing"],
                disciplines: [],
                subject_ids: [],
                documents_in_scope: 3,
              },
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.click(screen.getByRole("checkbox", { name: /^Drawing/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText(/3 documents in scope/)).toBeInTheDocument();

    // Reticking after the run - the count it described no longer describes
    // what a fresh run would search.
    await user.click(screen.getByRole("checkbox", { name: /^Specification/ }));

    expect(screen.queryByText(/3 documents in scope/)).toBeNull();
    expect(
      screen.getByText(/Filter set to Drawing, Specification\. Run again to apply it\./),
    ).toBeInTheDocument();
  });
});

// ------------------------------------------------------- the honest empty case

describe("AnalysisModeScreen: an empty result under an active filter explains why", () => {
  it("says the filter narrowed the search, not that the documents are silent", async () => {
    const user = userEvent.setup();
    mockFetch({
      // Served, but nothing renderable - the same shape an unfiltered corpus
      // with no answer would produce, which is exactly why the wording must
      // differ when a filter is active.
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              summary: null,
              summary_cited_evidence_ids: [],
              documented_findings: [],
              refusal: null,
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.click(screen.getByRole("checkbox", { name: /^Drawing/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(
      await screen.findByText(/The type filter narrowed the search, and nothing in scope matched/),
    ).toBeInTheDocument();
    // The claim this screen must never make when a filter hid the answer.
    expect(screen.queryByText(/Nothing the retrieval found could be summarised/)).toBeNull();
  });

  it("keeps the unfiltered empty wording when no filter is active", async () => {
    const user = userEvent.setup();
    mockFetch({
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              summary: null,
              summary_cited_evidence_ids: [],
              documented_findings: [],
              refusal: null,
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await waitForVocabulary();

    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(
      await screen.findByText(/Nothing the retrieval found could be summarised/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/The type filter narrowed the search/)).toBeNull();
  });
});
