/**
 * The audit action, and whether a reader can actually perform it.
 *
 * Four defects a tester hit live, each with a test that goes red if the fix is
 * removed rather than one that only asserts "something rendered":
 *
 *  1. The citation row was a ~60px filename button. Clicking the PASSAGE TEXT
 *     - the largest thing in the row - did nothing. These tests click the
 *     passage and the page number, not the filename, so restoring the old
 *     filename-only button fails them.
 *  2. Keyboard: Enter AND Space on the focused row activate it. A div with
 *     onClick passes a click test and fails both of these.
 *  3. The Sources panel populates off-screen on a long page. Selecting a
 *     citation must call scrollIntoView, with block:"nearest" and WITHOUT
 *     smooth behaviour under prefers-reduced-motion.
 *  4. Closing the outbound-query modal returns focus to its trigger, by
 *     Confirm, by Cancel and by Escape - all three, because they are three
 *     different code paths for a reader who has just lost their place.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { MarketPanel } from "../components/analysis/MarketPanel";
import type { EgressState, MarketFinding, PublicMarketQuery } from "../types/analysis";
import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen } from "./AnalysisModeScreen";

// ------------------------------------------------------------------ fixtures

const PASSAGE = "The discharge pressure shall not be less than 250 kPa.";

const EV: EvidenceItem = {
  evidence_id: "ev1",
  document_id: "doc_1",
  filename: "doc17.pdf",
  page_start: 12,
  page_end: 12,
  section: "4.2",
  exact_span: PASSAGE,
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
            exact_span: PASSAGE,
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

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function routeGaps() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/analysis/gaps")) return Promise.resolve(json(gapsBody()));
      return Promise.reject(new Error(`unrouted ${url}`));
    }),
  );
}

/** Quote mode runs gaps and nothing else, so the claim table is the only
 *  citation surface on screen and there is one row to reason about. */
async function runQuoteAnalysis(user: ReturnType<typeof userEvent.setup>) {
  render(<AnalysisModeScreen />);
  await user.click(screen.getByRole("radio", { name: /Quote/ }));
  await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
  return await screen.findByRole("button", { name: /Show evidence from doc17\.pdf, page 12/ });
}

/** jsdom implements neither of these. Both are installed per-test so a test
 *  that forgets one cannot pass on the other's leftovers. */
function spyScrollIntoView() {
  const spy = vi.fn();
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    value: spy,
    writable: true,
    configurable: true,
  });
  return spy;
}

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((q: string) => ({
      matches: reduced && q.includes("prefers-reduced-motion"),
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

beforeEach(() => resetAnalysisScreen());
afterEach(() => {
  vi.unstubAllGlobals();
  // Leave the prototype as jsdom had it: absent.
  delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
});

// ------------------------------------------ DEFECT 1: the whole row is the target

describe("citation row: the whole row is the click target", () => {
  it("selects the citation when the PASSAGE TEXT is clicked, not only the filename", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    // Nothing is selected yet: the placeholder is what the rail shows.
    expect(screen.getByText(/Select a citation or evidence row/)).toBeInTheDocument();

    // The passage is inside the row and is NOT itself a control - clicking it
    // must still reach the row.
    await user.click(within(row).getByText(PASSAGE));

    const panel = await screen.findByRole("region", { name: "Selected passage" });
    expect(within(panel).getByText(PASSAGE)).toBeInTheDocument();
    expect(screen.queryByText(/Select a citation or evidence row/)).not.toBeInTheDocument();
  });

  it("selects the citation when the PAGE NUMBER is clicked", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    await user.click(within(row).getByText("p.12"));

    expect(await screen.findByRole("region", { name: "Selected passage" })).toBeInTheDocument();
  });

  it("exposes the row as a real control: a name, a role and a tab stop", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    expect(row).toHaveAttribute("tabindex", "0");
    // A div with onClick is not this.
    expect(row.tagName === "BUTTON" || row.getAttribute("role") === "button").toBe(true);
  });
});

// ------------------------------------------------- DEFECT 1: keyboard activation

describe("citation row: keyboard activation", () => {
  it("selects the citation on ENTER", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    row.focus();
    expect(row).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("region", { name: "Selected passage" })).toBeInTheDocument();
  });

  it("selects the citation on SPACE", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    row.focus();
    await user.keyboard("[Space]");

    expect(await screen.findByRole("region", { name: "Selected passage" })).toBeInTheDocument();
  });

  it("ignores a key that is neither Enter nor Space", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    row.focus();
    await user.keyboard("a");

    expect(screen.getByText(/Select a citation or evidence row/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------- DEFECT 2: the selected state

describe("citation row: the selected row is distinguishable", () => {
  it("marks the selected row, in words and not by colour alone", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    expect(row).toHaveAttribute("aria-pressed", "false");
    expect(within(row).queryByText("Showing")).not.toBeInTheDocument();

    await user.click(within(row).getByText(PASSAGE));

    const after = await screen.findByRole("button", {
      name: /Show evidence from doc17\.pdf, page 12/,
    });
    expect(after).toHaveAttribute("aria-pressed", "true");
    // Text, not colour alone.
    expect(within(after).getByText("Showing")).toBeInTheDocument();
  });
});

// -------------------------------------------- DEFECT 2: bring the panel into view

describe("sources panel: selecting a citation brings the panel into view", () => {
  it("calls scrollIntoView with block:nearest when a citation is selected", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(false);
    const scroll = spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    expect(scroll).not.toHaveBeenCalled();

    await user.click(within(row).getByText(PASSAGE));
    await waitFor(() => expect(scroll).toHaveBeenCalled());

    const arg = scroll.mock.calls[0][0] as ScrollIntoViewOptions;
    // "center" would yank the page for a reader who can already see the panel.
    expect(arg.block).toBe("nearest");
    expect(arg.behavior).toBe("smooth");
    // It is the sources panel that was scrolled to, not something else.
    expect(scroll.mock.instances[0]).toBe(screen.getByTestId("analysis-sources-panel"));
  });

  it("does NOT scroll smoothly when prefers-reduced-motion is set", async () => {
    const user = userEvent.setup();
    routeGaps();
    stubReducedMotion(true);
    const scroll = spyScrollIntoView();

    const row = await runQuoteAnalysis(user);
    await user.click(within(row).getByText(PASSAGE));
    await waitFor(() => expect(scroll).toHaveBeenCalled());

    const arg = scroll.mock.calls[0][0] as ScrollIntoViewOptions;
    expect(arg.block).toBe("nearest");
    expect(arg.behavior).toBeUndefined();
  });
});

// ------------------------------------------- DEFECT 3: focus returns to the trigger

const EGRESS_OPEN: EgressState = { web_search_enabled: false, allow_public_egress: true };
const EGRESS_BLOCKED: EgressState = { web_search_enabled: false, allow_public_egress: false };
const FINDINGS: MarketFinding[] = [];

/** The panel's dialog is controlled by its parent, exactly as
 *  AnalysisModeScreen controls it: `pendingQuery` in, `onCancel`/`onConfirm`
 *  out. This harness is the smallest thing that reproduces that. */
function MarketHarness({ egress }: { egress: EgressState }) {
  const [pending, setPending] = useState<PublicMarketQuery | null>(null);
  return (
    <MarketPanel
      findings={FINDINGS}
      egress={egress}
      onPreviewQuery={(q) => setPending(q)}
      pendingQuery={pending}
      onConfirmQuery={() => setPending(null)}
      onCancelQuery={() => setPending(null)}
    />
  );
}

async function openDialog(user: ReturnType<typeof userEvent.setup>, egress: EgressState) {
  render(<MarketHarness egress={egress} />);
  await user.type(screen.getByLabelText("Query"), "pump pressure standards");
  const trigger = screen.getByRole("button", { name: "Preview exact outbound query" });
  trigger.focus();
  await user.click(trigger);
  const dialog = await screen.findByRole("dialog");
  // The trap still works: focus moved INTO the dialog on open.
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus());
  return { trigger, dialog };
}

describe("market dialog: focus returns to the trigger on every close path", () => {
  it("restores focus after CONFIRM", async () => {
    const user = userEvent.setup();
    const { trigger, dialog } = await openDialog(user, EGRESS_OPEN);

    await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it("restores focus after CANCEL", async () => {
    const user = userEvent.setup();
    const { trigger, dialog } = await openDialog(user, EGRESS_BLOCKED);

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("restores focus after ESCAPE", async () => {
    const user = userEvent.setup();
    const { trigger } = await openDialog(user, EGRESS_BLOCKED);

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});
