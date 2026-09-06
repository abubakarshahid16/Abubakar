/**
 * Two defects observed in one live run of the Analysis screen.
 *
 * DEFECT 1 - THE SUMMARY PRINTED NAKED NUMBERS. The prose read:
 *
 *   "4 mandates that all contract drawings be developed using CADD and BIM"
 *   "1 specifies that concept design drawings must include site plans"
 *
 * Every sentence opened with a bare digit. Those digits were the model's
 * citation markers [S4] and [S1]. The renderer was NOT position-blind - its
 * regex has always matched anywhere in the string, and each of those digits was
 * a real, clickable chip - but the chip's only glyph was the number itself. A
 * lone number pressed against prose is read as a quantity. The marker survived
 * as a control and died as a signal, and it died hardest where the model had
 * just started putting it: at the START of the sentence, where nothing
 * separates it from the words that follow.
 *
 * So these tests assert the thing the old code got wrong, and they assert it at
 * all three positions rather than only the one that was reported. A marker must
 * be a MARKER wherever it lands - leading, trailing, mid-sentence - and must
 * never be renderable as a bare digit. They also pin the other half of the
 * rule: a number the model merely WROTE ("30 percent") is prose and must not be
 * dressed as a citation, because a renderer that made every number a marker
 * would pass a naive "no bare numbers" test while lying about every quantity in
 * the document.
 *
 * DEFECT 2 - QUOTE MODE APPEARED TO DO NOTHING. Quote turns the summary, the
 * recommendation and the market engines off and runs the one engine that needs
 * no model. That left Gap analysis as its only section - and `Section` drew its
 * <h2> unconditionally while `SlotBody` returned null for `idle`, so selecting
 * Quote produced a "Gap analysis" heading with empty space under it, directly
 * beneath "Nothing has been run yet". A heading over nothing reads as a broken
 * render, which is what "the quote in analysis is not working" was describing.
 *
 * MUTATION PROOF. Each test below was proved by breaking the code it covers and
 * confirming that THIS test went red while the rest of the suite stayed green.
 * The mutations are recorded against each describe block.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SummaryCard } from "../components/analysis/SummaryCard";
import type { AnalysisResult } from "../types/analysis";
import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen } from "./AnalysisModeScreen";

// ------------------------------------------------------------------ fixtures

const IDS = ["ev_1", "ev_2", "ev_3", "ev_4", "ev_5"];

function makeResult(over: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    analysis_id: "an_01",
    question: "What do the drawing requirements say?",
    run_status: "complete",
    status: "answered",
    coverage: {
      authorized_documents_selected: 1,
      documents_attempted: 1,
      documents_search_completed: 1,
      relevant_documents: 1,
      no_sufficient_evidence_documents: 0,
      failed_documents: 0,
      not_searchable_documents: 0,
      complete: false,
    },
    documents: [],
    evidence_ledger: [],
    documented_findings: [],
    summary: "Both specifications require 280 µm [S1].",
    summary_truncated: false,
    summary_cited_evidence_ids: IDS,
    claim_clusters: [],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    public_market_findings: [],
    recommendation: null,
    assumptions: [],
    limitations: [],
    not_implemented_sections: [],
    batches_done: null,
    batches_total: null,
    seconds: 1,
    ...over,
  };
}

/** The generated-prose paragraph, which is the only thing under test here. */
function prose(container: HTMLElement): HTMLElement {
  const el = container.querySelector<HTMLElement>(".model-prose");
  if (el === null) throw new Error("no generated-prose block rendered");
  return el;
}

/**
 * Every citation marker in the prose, in document order.
 *
 * Found by the `data-citation-marker` attribute rather than by role: a DEAD
 * marker is deliberately not a button, and a test that only looked for buttons
 * would call a marker missing when it was merely uncitable.
 */
function markers(container: HTMLElement): HTMLElement[] {
  return [...prose(container).querySelectorAll<HTMLElement>("[data-citation-marker]")];
}

/**
 * The prose with every marker element removed - i.e. what the reader sees as
 * ORDINARY TEXT.
 *
 * This is the assertion surface that actually catches the defect. `textContent`
 * on the paragraph includes the markers' own glyphs, so "4 mandates" looks
 * identical whether the 4 is a chip or literal text. Stripping the marker
 * elements first is what makes "is this a marker or is it prose?" answerable.
 */
function proseTextWithoutMarkers(container: HTMLElement): string {
  const clone = prose(container).cloneNode(true) as HTMLElement;
  for (const m of [...clone.querySelectorAll("[data-citation-marker]")]) m.remove();
  return clone.textContent ?? "";
}

// ------------------------------------------------ DEFECT 1: marker positions
//
// MUTATIONS PROVED AGAINST THIS BLOCK
//  M1. SummaryCard.tsx `markerLabel`: `return \`S${n}\`` -> `return \`${n}\``
//      (the exact pre-fix rendering). 5 of these 15 tests go red on the
//      bare-digit assertions; the other 10 stay green.
//  M2. SummaryCard.tsx CITATION regex: `/\[S(\d+)\]/g` ->
//      `/(?<=\S\s)\[S(\d+)\]/g` - a renderer that only sees a marker with prose
//      in front of it, which is exactly the trailing-only renderer the brief
//      hypothesised. 4 red, 11 green, and the four are precisely the LEADING
//      cases: "END of a sentence" and "MID-sentence" both stay green. That
//      split is why all three positions are tested and not only the reported
//      one - a suite that tested trailing alone would have called this
//      mutation healthy.

describe("citation markers render as markers at every position in a sentence", () => {
  it("a marker at the START of a sentence is a marker, not bare text", () => {
    // The reported string, verbatim.
    const result = makeResult({
      summary: "[S4] mandates that all contract drawings be developed using CADD and BIM software.",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    const found = markers(container);
    expect(found).toHaveLength(1);
    expect(found[0].getAttribute("data-citation-marker")).toBe("4");

    // It is FIRST in the paragraph: the leading position is handled, not
    // dropped and not relocated.
    expect(prose(container).firstElementChild).toBe(found[0]);

    // The defect itself: the reader must not be shown "4 mandates that...".
    // A bare digit is not an acceptable rendering of a citation at any
    // position, so the marker's own glyphs may not be the number alone.
    expect(found[0].textContent).not.toBe("4");
    expect(found[0].textContent).toBe("S4");

    // And with the marker element lifted out, no stray digit is left behind in
    // the prose - the marker is not ALSO printed as text.
    expect(proseTextWithoutMarkers(container)).not.toMatch(/\d/);
    expect(proseTextWithoutMarkers(container).trim()).toBe(
      "mandates that all contract drawings be developed using CADD and BIM software.",
    );
  });

  it("a marker at the END of a sentence is a marker, not bare text", () => {
    const result = makeResult({
      summary: "All contract drawings shall be developed using CADD and BIM software [S4].",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    const found = markers(container);
    expect(found).toHaveLength(1);
    expect(found[0].textContent).toBe("S4");
    expect(found[0].textContent).not.toBe("4");
    expect(proseTextWithoutMarkers(container)).not.toMatch(/\d/);
  });

  it("a marker MID-sentence is a marker, not bare text", () => {
    const result = makeResult({
      summary: "The drawing requirement [S5] applies to furniture layouts as well.",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    const found = markers(container);
    expect(found).toHaveLength(1);
    expect(found[0].textContent).toBe("S5");
    expect(found[0].textContent).not.toBe("5");

    // Neither neighbour was swallowed: the words on both sides survive intact.
    const text = proseTextWithoutMarkers(container);
    expect(text).toContain("The drawing requirement");
    expect(text).toContain("applies to furniture layouts as well.");
    expect(text).not.toMatch(/\d/);
  });

  it("all three positions in ONE passage each render as a marker", () => {
    const result = makeResult({
      summary: "[S4] mandates CADD. The requirement [S5] is interior. Civil follows [S6].",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    expect(markers(container).map((m) => m.getAttribute("data-citation-marker"))).toEqual([
      "4",
      "5",
      "6",
    ]);
    expect(markers(container).map((m) => m.textContent)).toEqual(["S4", "S5", "S6"]);
    // Not one digit is left loose in the prose.
    expect(proseTextWithoutMarkers(container)).not.toMatch(/\d/);
  });

  it("a LEADING marker is still the clickable control it was, not just a styled span", async () => {
    // The old rendering was ugly but live. The fix must not trade the
    // affordance for the appearance: a marker that reads correctly and no
    // longer opens the passage is a worse regression than the one being fixed.
    const onCite = vi.fn();
    const user = userEvent.setup();
    const result = makeResult({ summary: "[S4] mandates CADD and BIM software." });
    render(<SummaryCard result={result} onCite={onCite} />);

    const chip = screen.getByRole("button", { name: "Show source 4" });
    await user.click(chip);
    expect(onCite).toHaveBeenCalledTimes(1);
    expect(onCite).toHaveBeenCalledWith(IDS[3]);
  });

  it("a leading marker with no source behind it is marked dead, and is not a button", () => {
    const result = makeResult({
      summary: "[S9] mandates CADD.",
      summary_cited_evidence_ids: ["ev_1"],
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    const found = markers(container);
    expect(found).toHaveLength(1);
    expect(found[0].tagName).not.toBe("BUTTON");
    // Still not a bare digit: an uncitable marker must not be readable as "9
    // mandates CADD" either.
    expect(found[0].textContent).toBe("S9");
    expect(screen.queryByRole("button", { name: "Show source 9" })).toBeNull();
  });
});

// ---------------------------------------- DEFECT 1: a quantity is not a marker
//
// MUTATION PROVED AGAINST THIS BLOCK
//  M3. SummaryCard.tsx CITATION regex: `/\[S(\d+)\]/g` -> `/\[?S?(\d+)\]?/g`
//      (a permissive marker matcher). "30 percent" becomes a citation chip.
//      Exactly the 2 tests in this block go red; all 13 others stay green,
//      including every position test above - which is the point: a fix that
//      made every number a marker would satisfy "no bare digits" and be a
//      worse lie than the defect.

describe("a number the model merely wrote is prose, not a citation", () => {
  it("'30 percent' stays ordinary text and does not become a marker", () => {
    const result = makeResult({
      summary: "The tolerance is 30 percent across both drawing sets [S1].",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    // Exactly one marker - the real one - and it is [S1], not the 30.
    const found = markers(container);
    expect(found).toHaveLength(1);
    expect(found[0].getAttribute("data-citation-marker")).toBe("1");

    // The quantity survives in the prose as a quantity.
    expect(proseTextWithoutMarkers(container)).toContain("The tolerance is 30 percent");
    expect(screen.queryByRole("button", { name: "Show source 30" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Show source 3$/ })).toBeNull();
  });

  it("bare numbers with no marker at all produce no markers", () => {
    const result = makeResult({
      summary: "Sheets 1 through 7 carry the 250 kPa figure [S2].",
    });
    const { container } = render(<SummaryCard result={result} onCite={vi.fn()} />);

    expect(markers(container)).toHaveLength(1);
    expect(markers(container)[0].getAttribute("data-citation-marker")).toBe("2");
    expect(proseTextWithoutMarkers(container)).toContain("Sheets 1 through 7 carry the 250 kPa");
  });
});

// ------------------------------------------- DEFECT 2: Quote mode's rendering
//
// MUTATIONS PROVED AGAINST THIS BLOCK
//  M4. AnalysisModeScreen.tsx: drop `&& hasBody(gapsSlot)` from the gaps
//      section guard - literally the pre-fix code. 1 red ("renders NO section
//      headings before a run"), 14 green.
//  M5. AnalysisModeScreen.tsx `hasBody`: `slot.s !== "off" && slot.s !== "idle"`
//      -> `slot.s !== null` (always true). 2 red - the Quote case and the
//      Focused case - 13 green.

const EV: EvidenceItem = {
  evidence_id: "ev1",
  document_id: "doc_1",
  filename: "doc17.pdf",
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

function gapsBody() {
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
            filename: "doc17.pdf",
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
  };
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Records every request the screen issues, so a mode's ROUTE can be asserted
 *  rather than assumed. */
function routeGaps(calls: string[], body: unknown = gapsBody()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)}`);
      const url = String(input);
      if (url.includes("/analysis/gaps")) return Promise.resolve(json(body));
      return Promise.reject(new Error(`unrouted ${url}`));
    }),
  );
}

async function selectQuote(user: ReturnType<typeof userEvent.setup>) {
  render(<AnalysisModeScreen />);
  await user.click(screen.getByRole("radio", { name: /Quote/ }));
}

/**
 * A section that is on screen must have something under its heading.
 *
 * "Something" means text beyond the heading and its eyebrow - the exact failure
 * being guarded is a header with empty space beneath it.
 */
/**
 * The screen's Gap analysis SECTION - the one with the <h2> and the eyebrow.
 *
 * `GapAnalysisCard` publishes a region under the same accessible name, so a
 * plain findByRole is ambiguous once a result is on screen. The section under
 * test is the outer one: the element that contains the other candidates rather
 * than being contained by one. Resolving it structurally keeps these tests
 * working while GapAnalysisCard's own markup is edited elsewhere.
 */
async function gapSection(): Promise<HTMLElement> {
  const all = await screen.findAllByRole("region", { name: "Gap analysis" });
  const outer = all.find((a) => all.every((b) => a === b || a.contains(b)));
  if (outer === undefined) throw new Error("no outermost Gap analysis section");
  return outer;
}

function bodyTextOf(section: HTMLElement): string {
  const clone = section.cloneNode(true) as HTMLElement;
  const header = clone.firstElementChild;
  if (header !== null) header.remove();
  return (clone.textContent ?? "").trim();
}

beforeEach(() => resetAnalysisScreen());
afterEach(() => vi.unstubAllGlobals());

describe("Quote mode: no section heading is rendered above empty content", () => {
  it("renders NO section headings before a run - not an empty 'Gap analysis' header", async () => {
    const user = userEvent.setup();
    await selectQuote(user);

    // This is the defect: Quote's only section used to draw its heading at
    // idle, over nothing, right under "Nothing has been run yet".
    expect(screen.queryByRole("region", { name: "Gap analysis" })).toBeNull();
    expect(screen.getByText(/Nothing has been run yet/)).toBeInTheDocument();

    // Quote turns these three off, so they are absent rather than empty.
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
    expect(screen.queryByRole("region", { name: "AI recommendation" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Public market intelligence" })).toBeNull();
  });

  it("renders no empty section heading in Focused mode before a run either", () => {
    // Same guard, other mode: Focused's Summary section drew the same empty
    // header. Fixing only the reported mode would leave the defect in place.
    // Focused is the default, so nothing needs clicking to reach it.
    render(<AnalysisModeScreen />);
    expect(screen.getByRole("radio", { name: /Focused/ })).toBeChecked();

    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
    expect(screen.getByText(/Nothing has been run yet/)).toBeInTheDocument();
  });

  it("every section on screen after a Quote run has content under its heading", async () => {
    const calls: string[] = [];
    routeGaps(calls);
    const user = userEvent.setup();
    await selectQuote(user);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    const section = await gapSection();
    expect(bodyTextOf(section)).not.toBe("");
    expect(within(section).getByText(EV.exact_span)).toBeInTheDocument();
  });

  it("an EMPTY quote result still renders content under the heading, never a bare header", async () => {
    const calls: string[] = [];
    routeGaps(calls, {
      question: "q",
      evidence_ledger: [],
      claim_clusters: [],
      gaps: { applicability: "not_applicable", baseline: null, items: [] },
      not_implemented_sections: [],
    });
    const user = userEvent.setup();
    await selectQuote(user);
    await user.type(screen.getByLabelText("Question"), "nothing matches this");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    const section = await gapSection();
    // The empty state is CONTENT: it tells the reader the run happened and
    // found nothing, which is the opposite of a heading over blank space.
    expect(within(section).getByText(/No comparable claims were found/)).toBeInTheDocument();
    expect(bodyTextOf(section)).not.toBe("");
  });
});

// -------------------------------------- DEFECT 2: Quote mode is legible as such
//
// MUTATION PROVED AGAINST THIS BLOCK
//  M6. AnalysisModeScreen.tsx: force the gaps eyebrow to "baseline-controlled"
//      and delete the `mode === "quote"` note - i.e. the pre-fix rendering, in
//      which Quote's output arrived under a heading that never mentioned Quote.
//      1 red ("names the mode on the section it produced"), 14 green.

describe("Quote mode: the reader can tell that Quote ran and what it produced", () => {
  it("issues exactly one request, to the gaps route, and nothing to summary", async () => {
    const calls: string[] = [];
    routeGaps(calls);
    const user = userEvent.setup();
    await selectQuote(user);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    await gapSection();

    expect(calls).toEqual(["POST /api/analysis/gaps"]);
    expect(calls.some((c) => c.includes("/analysis/summary"))).toBe(false);
    expect(calls.some((c) => c.includes("/analysis/recommendations"))).toBe(false);
  });

  it("names the mode on the section it produced, and says no model wrote it", async () => {
    const calls: string[] = [];
    routeGaps(calls);
    const user = userEvent.setup();
    await selectQuote(user);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    const section = await gapSection();
    // Two separate statements, both required: the eyebrow names the mode on the
    // heading, and the note under it says what that mode actually produced.
    expect(
      within(section).getByText("quote mode — cited document evidence, no model"),
    ).toBeInTheDocument();
    expect(within(section).getByText(/Quote mode ran the mechanical comparison/)).toBeInTheDocument();
    expect(within(section).getByText(/no model wrote any of it/i)).toBeInTheDocument();
  });

  it("does NOT claim quote mode in Focused, where a model did write the summary", async () => {
    // The label is a claim about the run. It must be false when it is false.
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /Gap analysis/ }));
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/analysis/gaps")) return Promise.resolve(json(gapsBody()));
        if (url.includes("/analysis/summary"))
          return Promise.resolve(
            json({
              question: "q",
              evidence_ledger: [EV],
              summary: "The floor is 250 kPa [S1].",
              summary_truncated: false,
              summary_cited_evidence_ids: ["ev1"],
              documented_findings: [],
              dropped_sentences: [],
              refusal: null,
              not_implemented_sections: [],
            }),
          );
        return Promise.reject(new Error(`unrouted ${url}`));
      }),
    );
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));

    const section = await gapSection();
    expect(within(section).queryByText(/quote mode/i)).toBeNull();
    expect(within(section).queryByText(/no model wrote any of it/i)).toBeNull();
    expect(within(section).getByText("baseline-controlled")).toBeInTheDocument();
  });
});
