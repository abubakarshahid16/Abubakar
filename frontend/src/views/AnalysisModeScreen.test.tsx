/**
 * What these tests are for.
 *
 * Not "does it render". Each one names a rule this project has been burned by
 * and fails if the code holding that rule is removed:
 *
 *  - backend-offline and request-failed are two different renderings. There is
 *    an existing defect record about them looking the same, and a test that
 *    only asserted "an error appears" would have passed throughout it. Both
 *    tests here assert the OTHER one's wording is absent.
 *  - an empty result is neither of those and is not a spinner that never stops.
 *  - a confidence word that is not "low" or "medium" never reaches the screen.
 *  - a claim that cites nothing is not rendered at all - not rendered with a
 *    caveat, because the claim would still be on screen.
 *  - a market row that does not declare itself a sample is not rendered, and
 *    the ones that are carry the tag.
 *  - a late response from a superseded run does not overwrite the current one.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceItem } from "../types/api";
import {
  AnalysisModeScreen,
  citedFindings,
  completeness,
  confidenceWord,
  locate,
  onlySamples,
  resetAnalysisScreen,
  toClaimRow,
} from "./AnalysisModeScreen";

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
    removed: [],
    not_implemented_sections: ["analysis lifecycle and cancellation"],
    ...over,
  };
}

function gapsBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    claim_clusters: [
      {
        facet: ["discharge pressure", "kPa"],
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
      checks: [{ label: "the gap analysis did not apply", fired: true }],
    },
    public_market_findings: [],
    not_implemented_sections: [],
    recommendation_refusal: null,
    ...over,
  };
}

const SAMPLE_ROW = {
  claim: "SAMPLE ROW ALPHA",
  url: "sample://one",
  publisher: "Illustrative Publisher",
  published_at: null,
  retrieved_at: "2026-09-05",
  verification: "source_not_verified",
  is_sample: true,
};

const UNLABELLED_ROW = { ...SAMPLE_ROW, claim: "UNLABELLED ROW BETA", url: "sample://two", is_sample: false };

// --------------------------------------------------------------- fetch mock

type Route = (url: string) => Promise<Response> | undefined;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function routes(table: Record<string, () => Promise<Response>>) {
  const fn: Route = (url) => {
    for (const [fragment, make] of Object.entries(table)) {
      if (url.includes(fragment)) return make();
    }
    return undefined;
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const hit = fn(url);
      if (hit) return hit;
      return Promise.reject(new Error(`unrouted ${url}`));
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());
// The screen's state deliberately outlives the component (it survives a view
// switch), so each test starts it from nothing rather than from the last one.
beforeEach(() => resetAnalysisScreen());

async function ask(user: ReturnType<typeof userEvent.setup>, question = "what is the pressure floor") {
  await user.type(screen.getByLabelText("Question"), question);
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
}

// ------------------------------------------------------------------ the four states

describe("AnalysisModeScreen: four states, four renderings", () => {
  it("shows a loading state while the request is in flight", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => new Promise<Response>(() => {}) });
    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText(/Generating the summary/)).toBeInTheDocument();
  });

  it("says the BACKEND IS NOT RUNNING when the request never reached it, and does not call it a failed request", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => Promise.reject(new TypeError("Failed to fetch")) });
    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText("The backend is not running")).toBeInTheDocument();
    // The distinction this project has an existing defect record about.
    expect(screen.queryByText("Something went wrong")).toBeNull();
    expect(screen.queryByText("That did not work")).toBeNull();
  });

  it("says THE REQUEST FAILED when the backend served a refusal, and does not call it offline", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () =>
        Promise.resolve(
          json({ detail: { code: "model_unavailable", message: "the local answer model could not be reached" } }, 500),
        ),
    });
    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText("The local answer model is not running")).toBeInTheDocument();
    expect(screen.getByText(/the local answer model could not be reached/)).toBeInTheDocument();
    // The other half of the same distinction.
    expect(screen.queryByText("The backend is not running")).toBeNull();
  });

  it("distinguishes a 503 gateway (nothing served it) from a served error", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => Promise.resolve(json({}, 503)) });
    render(<AnalysisModeScreen />);
    await ask(user);
    // A gateway status means nothing answered on the port - the client maps it
    // to disconnected, and the screen must follow it there.
    expect(await screen.findByText("The backend is not running")).toBeInTheDocument();
  });

  it("shows an EMPTY RESULT as empty, not as a failure and not as a spinner that never stops", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              summary: null,
              summary_cited_evidence_ids: [],
              documented_findings: [],
              evidence_ledger: [],
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText("No summary was produced for this question.")).toBeInTheDocument();
    expect(screen.queryByText("The backend is not running")).toBeNull();
    expect(screen.queryByText(/Generating the summary/)).toBeNull();
  });
});

// ------------------------------------------------------------ the product rules

describe("AnalysisModeScreen: rules that must hold on screen", () => {
  it("RULE 2: a confidence of 'high' from the backend never reaches the screen", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/recommendations": () =>
        Promise.resolve(json(recommendationBody({ recommendation: { ...recommendationBody().recommendation, confidence: "high" } }))),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user);
    await screen.findByText(/AI Advisory/);
    // "high" is not a word this system issues. It becomes "not assessed".
    expect(screen.queryByText("high")).toBeNull();
    expect(screen.getByText("not assessed")).toBeInTheDocument();
  });

  it("RULE 2: 'low' and 'medium' are passed through unchanged", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/recommendations": () => Promise.resolve(json(recommendationBody())),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user);
    expect(await screen.findByText("low")).toBeInTheDocument();
    expect(screen.queryByText("not assessed")).toBeNull();
  });

  it("RULE 4: a documented finding that cites nothing is not rendered at all", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              documented_findings: [
                { claim: "CITED FINDING", citation_ids: ["ev1"], text_source: "extracted" },
                { claim: "UNCITED FINDING", citation_ids: [], text_source: "extracted" },
                { claim: "DANGLING FINDING", citation_ids: ["ev_missing"], text_source: "extracted" },
              ],
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText("CITED FINDING")).toBeInTheDocument();
    // Not rendered with a warning beside it: the claim would still be on screen.
    expect(screen.queryByText("UNCITED FINDING")).toBeNull();
    expect(screen.queryByText("DANGLING FINDING")).toBeNull();
  });

  it("RULE 4: generated prose whose markers point at no supplied source is not rendered", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () =>
        Promise.resolve(
          json(
            summaryBody({
              summary: "UNCITED PROSE about a 250 kPa floor.",
              summary_cited_evidence_ids: [],
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await ask(user);
    // The findings still render; the uncited prose does not.
    expect(await screen.findByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();
    expect(screen.queryByText(/UNCITED PROSE/)).toBeNull();
  });

  it("RULE 4: every claim row on screen carries its document and its page", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/gaps": () => Promise.resolve(json(gapsBody())) });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await ask(user);
    const table = await screen.findByRole("region", { name: "Claim comparison" });
    expect(within(table).getByRole("button", { name: /pump-spec\.pdf, page 12/i })).toBeInTheDocument();
    expect(within(table).getByText("p.12")).toBeInTheDocument();
  });

  it("RULE 4: a claim row with no page number is dropped, taking its empty cluster with it", async () => {
    const user = userEvent.setup();
    const body = gapsBody();
    const cluster = body.claim_clusters[0];
    routes({
      "/analysis/gaps": () =>
        Promise.resolve(
          json(
            gapsBody({
              claim_clusters: [
                { ...cluster, rows: [{ ...cluster.rows[0], page_start: null, exact_span: "PAGELESS SPAN" }] },
              ],
            }),
          ),
        ),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await ask(user);
    expect(await screen.findByText("No comparable claims were found.")).toBeInTheDocument();
    expect(screen.queryByText("PAGELESS SPAN")).toBeNull();
  });

  it("RULE 5: a market row that does not declare itself a sample is not rendered; the ones that are carry the tag", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/market/findings": () =>
        Promise.resolve(
          json({
            notice: "SAMPLE DATA - NOT LIVE",
            egress: { web_search_enabled: false, allow_public_egress: false },
            findings: [SAMPLE_ROW, UNLABELLED_ROW],
            is_sample: true,
          }),
        ),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /public market sample/i }));
    await ask(user);
    const panel = await screen.findByRole("region", { name: "Public market intelligence" });
    expect(within(panel).getByText("SAMPLE ROW ALPHA")).toBeInTheDocument();
    // A row that could be mistaken for a real finding is not drawn at all.
    expect(screen.queryByText("UNLABELLED ROW BETA")).toBeNull();
    expect(within(panel).getAllByText("Sample")).toHaveLength(1);
    expect(within(panel).getByText(/SAMPLE DATA/)).toBeInTheDocument();
  });

  /** The market panel used to render TWICE: once inside the AI recommendation
   *  section off `public_market_findings`, and once in its own section off
   *  `/market/findings`. The rows were identical - the recommendation field is
   *  literally `market.findings()["findings"]` - but the recommendation copy
   *  was passed a HARD-CODED `{web_search_enabled: false, allow_public_egress:
   *  false}` instead of the egress the API measured, so the same sample rows
   *  appeared twice under two different egress claims, one of them invented.
   *
   *  RULE 5 itself is covered by the test above, which drives the same panel
   *  through the route that still renders it. This test exists only to keep
   *  the second copy from coming back.
   */
  it("renders the market panel once, even when the recommendation carries the same rows", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/recommendations": () =>
        Promise.resolve(json(recommendationBody({ public_market_findings: [SAMPLE_ROW] }))),
      "/market/findings": () =>
        Promise.resolve(
          json({
            notice: "SAMPLE DATA - NOT LIVE",
            egress: { web_search_enabled: false, allow_public_egress: false },
            findings: [SAMPLE_ROW],
            is_sample: true,
          }),
        ),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await user.click(screen.getByRole("checkbox", { name: /public market sample/i }));
    await ask(user);
    // Both engines returned the row. It is drawn once.
    const market = await screen.findByRole("region", { name: "Public market intelligence" });
    expect(within(market).getByText("SAMPLE ROW ALPHA")).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Public market information" })).toHaveLength(1);
    expect(screen.getAllByText("SAMPLE ROW ALPHA")).toHaveLength(1);
  });

  /** The market assertion this test used to carry became vacuous when the
   *  recommendation section stopped rendering market rows at all: an absence
   *  that nothing can produce is not a test. What remains is the empty state,
   *  which is real - a null recommendation must say so rather than render an
   *  empty card. Whether the market panel appears twice is now the concern of
   *  the render-once test above, where a fixture can actually produce it.
   */
  it("says so when no recommendation was generated", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/recommendations": () =>
        Promise.resolve(json(recommendationBody({ recommendation: null, public_market_findings: [SAMPLE_ROW] }))),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user);
    expect(await screen.findByText("No recommendation was generated.")).toBeInTheDocument();
  });

  it("shows the backend refusal reason instead of inventing one", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody())),
      "/analysis/recommendations": () => Promise.resolve(json(recommendationBody({
        recommendation: null,
        recommendation_refusal: "The model declined because the evidence window was exceeded.",
      }))),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user);
    expect(await screen.findByText("The model declined because the evidence window was exceeded.")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing was produced that carried a citation/i)).toBeNull();
  });

  it("RULE 3: an unnormalisable value renders as nothing - no 0, no dash, no empty row", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/gaps": () => Promise.resolve(json(gapsBody())) });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await ask(user);
    const table = await screen.findByRole("region", { name: "Claim comparison" });
    expect(within(table).getByText("as written")).toBeInTheDocument();
    expect(within(table).getByText("250 kPa")).toBeInTheDocument();
    // normalized_value was null. Nothing stands in for it.
    expect(within(table).queryByText("normalised")).toBeNull();
    expect(within(table).queryByText("0")).toBeNull();
  });

  it("RULE 1: nothing on screen claims the analysis is complete", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => Promise.resolve(json(summaryBody())) });
    render(<AnalysisModeScreen />);
    await ask(user);
    await screen.findByText(/Discharge pressure floor/);
    expect(screen.queryByText(/analysis is complete/i)).toBeNull();
    expect(screen.queryByText("This analysis is partial")).toBeNull();
  });
});

// ------------------------------------------------------------ request ownership

describe("AnalysisModeScreen: a response belongs to the run that asked for it", () => {
  it("drops a summary that arrives after the reader has changed mode", async () => {
    const user = userEvent.setup();
    let release!: (r: Response) => void;
    const held = new Promise<Response>((resolve) => {
      release = resolve;
    });
    let call = 0;
    routes({
      "/analysis/summary": () => {
        call += 1;
        // The first run is held open; any later run answers at once.
        return call === 1 ? held : Promise.resolve(json(summaryBody({ summary: "SECOND RUN [S1]" })));
      },
    });

    render(<AnalysisModeScreen />);
    await ask(user);
    expect(await screen.findByText(/Generating the summary/)).toBeInTheDocument();

    // The reader moves on. Both modes use the summary route, so the stale
    // response has somewhere to land if nothing stops it.
    await user.click(screen.getByRole("radio", { name: /Comprehensive/ }));

    release(json(summaryBody({ summary: "FIRST RUN, LATE [S1]" })));
    await waitFor(() => expect(screen.queryByText(/Generating the summary/)).toBeNull());

    expect(screen.queryByText(/FIRST RUN, LATE/)).toBeNull();
  });

  it("keeps the newer run's result when the older one lands after it", async () => {
    const user = userEvent.setup();
    let release!: (r: Response) => void;
    const held = new Promise<Response>((resolve) => {
      release = resolve;
    });
    let call = 0;
    routes({
      "/analysis/summary": () => {
        call += 1;
        return call === 1 ? held : Promise.resolve(json(summaryBody({ summary: "SECOND RUN [S1]" })));
      },
    });

    render(<AnalysisModeScreen />);
    await ask(user);
    await screen.findByText(/Generating the summary/);
    await user.click(screen.getByRole("radio", { name: /Comprehensive/ }));
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText(/SECOND RUN/)).toBeInTheDocument();

    release(json(summaryBody({ summary: "FIRST RUN, LATE [S1]" })));
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.getByText(/SECOND RUN/)).toBeInTheDocument();
    expect(screen.queryByText(/FIRST RUN, LATE/)).toBeNull();
  });
});

describe("AnalysisModeScreen: intent does not override selected engines", () => {
  it("runs the selected Focused mode for WHAT IS PID rather than silently switching to Quote", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/analysis/gaps")) return Promise.resolve(json(gapsBody()));
      if (url.includes("/analysis/summary")) return Promise.resolve(json(summaryBody()));
      return Promise.reject(new Error(`unrouted ${url}`));
    });
    vi.stubGlobal("fetch", fetch);

    render(<AnalysisModeScreen />);
    await ask(user, "WHAT IS PID ??");

    expect(await screen.findByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/analysis/summary"))).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/analysis/gaps"))).toBe(false);
  });

  it("honours optional sections for WHAT IS PID when the reader selected them", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/analysis/gaps")) return Promise.resolve(json(gapsBody()));
      if (url.includes("/analysis/summary")) return Promise.resolve(json(summaryBody()));
      if (url.includes("/analysis/recommendations")) return Promise.resolve(json(recommendationBody()));
      if (url.includes("/market/findings")) return Promise.resolve(json({ findings: [SAMPLE_ROW], notice: "", egress: { web_search_enabled: false, allow_public_egress: false } }));
      return Promise.reject(new Error(`unrouted ${url}`));
    });
    vi.stubGlobal("fetch", fetch);

    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /gap analysis/i }));
    await user.click(screen.getByRole("checkbox", { name: /public market sample/i }));
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user, "WHAT IS PID ??");

    expect(await screen.findByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/analysis/gaps"))).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/analysis/summary"))).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/analysis/recommendations"))).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/market/findings"))).toBe(true);
  });
});

describe("AnalysisModeScreen: selected work is explicit", () => {
  it("does not imply market or recommendation will run in Quote mode", async () => {
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);

    await user.click(screen.getByRole("radio", { name: /Quote/ }));

    const plan = screen.getByRole("region", { name: "Selected analysis work" });
    expect(within(plan).getByText("Quote: mechanical evidence comparison")).toBeInTheDocument();
    expect(within(plan).getByText("Gap analysis")).toBeInTheDocument();
    expect(within(plan).getByText("Summary, recommendation and market")).toBeInTheDocument();
    expect(within(plan).getByText("Off")).toBeInTheDocument();
    expect(screen.getByText(/Quote mode runs only cited document evidence/)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ the guards

describe("the guards, directly", () => {
  it("confidenceWord admits only low and medium", () => {
    expect(confidenceWord("low")).toBe("low");
    expect(confidenceWord("medium")).toBe("medium");
    expect(confidenceWord("high")).toBeNull();
    expect(confidenceWord("HIGH")).toBeNull();
    expect(confidenceWord(null)).toBeNull();
    expect(confidenceWord(0.9)).toBeNull();
  });

  it("completeness never returns true", () => {
    expect(completeness(false)).toBe(false);
    expect(completeness(true)).toBeNull();
    expect(completeness(null)).toBeNull();
    expect(completeness(undefined)).toBeNull();
  });

  it("onlySamples keeps only rows that declare is_sample", () => {
    expect(onlySamples([SAMPLE_ROW as never, UNLABELLED_ROW as never])).toHaveLength(1);
    expect(onlySamples(undefined)).toEqual([]);
  });

  it("locate refuses an evidence item with no page or no document", () => {
    const m = locate([
      EV,
      { ...EV, evidence_id: "nopage", page_start: null as unknown as number },
      { ...EV, evidence_id: "nodoc", document_id: "" },
    ]);
    expect(m.has("ev1")).toBe(true);
    expect(m.has("nopage")).toBe(false);
    expect(m.has("nodoc")).toBe(false);
  });

  it("citedFindings drops the uncited and the dangling", () => {
    const located = locate([EV]);
    const kept = citedFindings(
      [
        { claim: "a", citation_ids: ["ev1"], text_source: "extracted" },
        { claim: "b", citation_ids: [], text_source: "extracted" },
        { claim: "c", citation_ids: ["ev1", "gone"], text_source: "extracted" },
      ],
      located,
    );
    expect(kept.map((f) => f.claim)).toEqual(["a"]);
  });

  it("toClaimRow keeps a null normalised value null rather than zero", () => {
    const located = locate([EV]);
    const row = toClaimRow(
      {
        evidence_id: "ev1",
        filename: "pump-spec.pdf",
        page_start: 12,
        section: null,
        exact_span: EV.exact_span,
        raw_value: "250",
        raw_unit: "kPa",
        normalized_value: null,
        normalized_unit: null,
      },
      located,
    );
    expect(row?.normalized_value).toBeNull();
    expect(row?.section).toBeNull();
  });

});
