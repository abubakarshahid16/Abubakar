/**
 * The run button and the life of a result.
 *
 * Measured live: a 3.5-minute Focused run during which the button still read
 * "Run analysis", was not disabled, carried no aria-busy and showed no
 * elapsed time - and a click on Documents threw the result away. Each test
 * here fails if the code holding the corresponding rule is removed:
 *
 *  - the button is disabled and aria-busy while a run is pending, and live
 *    again afterwards;
 *  - the elapsed counter is derived from the run's real start timestamp, not
 *    from counting ticks (a counter drifts on a missed tick and restarts from 0
 *    on remount);
 *  - a second activation during a run sends NO second request - through the
 *    button and through the run function itself;
 *  - question, mode, sections and results survive the component unmounting
 *    and remounting, and a run in flight across the unmount still lands;
 *  - everything is cleared when the client is signed out - on remount, by the
 *    watch while mounted, and when the run itself is the thing that got a 401.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken } from "../api/client";
import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen, runAnalysis } from "./AnalysisModeScreen";

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

function summaryBody(summary = "The discharge pressure floor is 250 kPa [S1].") {
  return {
    question: "q",
    evidence_ledger: [EV],
    summary,
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
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fetch that answers /analysis/summary from `answer` and counts what it saw. */
function mockSummary(answer: () => Promise<Response>) {
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/analysis/summary")) return answer();
    return Promise.reject(new Error(`unrouted ${url}`));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function summaryCalls(fetch: ReturnType<typeof vi.fn>) {
  return fetch.mock.calls.filter(([input]) => String(input).includes("/analysis/summary")).length;
}

/** Type and click without userEvent, so the same helper works under fake timers. */
function askSync(question = "what is the pressure floor") {
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
}

function runButton() {
  return screen.getByRole("button", { name: /Run analysis|Running/ });
}

beforeEach(() => {
  resetAnalysisScreen();
  setToken(null);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setToken(null);
  resetAnalysisScreen();
});

// ------------------------------------------------------------ F: the button

describe("AnalysisModeScreen: the run button while a run is in flight", () => {
  it("is disabled and aria-busy while the request is pending, and live again after it answers", async () => {
    const user = userEvent.setup();
    let release!: (r: Response) => void;
    mockSummary(() => new Promise<Response>((resolve) => (release = resolve)));
    render(<AnalysisModeScreen />);

    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    const before = runButton();
    expect(before).toBeEnabled();
    expect(before).toHaveAttribute("aria-busy", "false");

    await user.click(before);

    const during = runButton();
    expect(during).toBeDisabled();
    expect(during).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("analysis-run-status")).toBeInTheDocument();
    // What is known for a fact - the request was sent and has not answered.
    expect(screen.getByText(/Still waiting on: Summary\./)).toBeInTheDocument();

    release(json(summaryBody()));
    await screen.findByText(/Discharge pressure floor is 250 kPa/);

    const after = runButton();
    expect(after).toBeEnabled();
    expect(after).toHaveAttribute("aria-busy", "false");
    expect(screen.queryByTestId("analysis-run-status")).toBeNull();
  });

  it("shows seconds elapsed derived from the run's real start time, not a tick counter", () => {
    vi.useFakeTimers();
    mockSummary(() => new Promise<Response>(() => {}));
    render(<AnalysisModeScreen />);
    askSync();

    expect(screen.getByTestId("analysis-elapsed")).toHaveTextContent("0s");

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("analysis-elapsed")).toHaveTextContent("3s");

    // The clock jumps ten seconds with only ONE interval tick. A counter that
    // adds one per tick reads 4s here; a value derived from the start
    // timestamp reads 14s, which is the truth.
    act(() => {
      vi.setSystemTime(Date.now() + 10_000);
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId("analysis-elapsed")).toHaveTextContent("14s");
  });

  it("issues NO second request when the button is activated again during a run", async () => {
    const user = userEvent.setup();
    const fetch = mockSummary(() => new Promise<Response>(() => {}));
    render(<AnalysisModeScreen />);

    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    expect(summaryCalls(fetch)).toBe(1);

    // A second click, and the keyboard route for good measure.
    await user.click(runButton());
    fireEvent.keyDown(runButton(), { key: "Enter" });
    fireEvent.click(runButton());
    expect(summaryCalls(fetch)).toBe(1);
  });

  it("issues NO second request when the run function itself is called during a run", async () => {
    // Retry buttons and baseline nomination reach the run without going
    // through the button, so the button being disabled is not enough.
    const user = userEvent.setup();
    const fetch = mockSummary(() => new Promise<Response>(() => {}));
    render(<AnalysisModeScreen />);

    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    expect(summaryCalls(fetch)).toBe(1);

    await act(async () => {
      await runAnalysis();
      await runAnalysis();
    });
    expect(summaryCalls(fetch)).toBe(1);
  });
});

// ------------------------------------------------------- H: results survive

describe("AnalysisModeScreen: results survive the component unmounting", () => {
  it("keeps the question, mode, sections and result across unmount and remount, without re-fetching", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/analysis/summary")) return Promise.resolve(json(summaryBody()));
      if (url.includes("/analysis/gaps")) return Promise.resolve(json({ question: "q", evidence_ledger: [], claim_clusters: [], gaps: null, not_implemented_sections: [] }));
      return Promise.reject(new Error(`unrouted ${url}`));
    });
    vi.stubGlobal("fetch", fetch);

    const first = render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Comprehensive/ }));
    await user.click(screen.getByRole("checkbox", { name: /gap analysis/i }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    await screen.findByText(/Discharge pressure floor is 250 kPa/);
    const callsAfterRun = fetch.mock.calls.length;

    // The reader clicks Documents. App.tsx renders the view conditionally,
    // so this is exactly what happens to the component.
    first.unmount();
    expect(screen.queryByText(/Discharge pressure floor is 250 kPa/)).toBeNull();

    render(<AnalysisModeScreen />);
    expect(screen.getByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();
    expect(screen.getByLabelText("Question")).toHaveValue("what is the pressure floor");
    expect(screen.getByRole("radio", { name: /Comprehensive/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /gap analysis/i })).toBeChecked();
    // Restored from memory, not re-run: a re-run would be another 3.5 minutes.
    expect(fetch.mock.calls.length).toBe(callsAfterRun);
  });

  it("lands a result that arrives while the reader is on another view", async () => {
    const user = userEvent.setup();
    let release!: (r: Response) => void;
    mockSummary(() => new Promise<Response>((resolve) => (release = resolve)));

    const first = render(<AnalysisModeScreen />);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    expect(runButton()).toBeDisabled();

    first.unmount();
    release(json(summaryBody("LANDED WHILE AWAY [S1]")));
    await new Promise((r) => setTimeout(r, 0));

    render(<AnalysisModeScreen />);
    expect(await screen.findByText(/LANDED WHILE AWAY/)).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("shows the elapsed time from the original start after a remount mid-run", () => {
    vi.useFakeTimers();
    mockSummary(() => new Promise<Response>(() => {}));
    const first = render(<AnalysisModeScreen />);
    askSync();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    first.unmount();
    act(() => {
      vi.advanceTimersByTime(7000);
    });
    render(<AnalysisModeScreen />);
    expect(screen.getByTestId("analysis-elapsed")).toHaveTextContent("12s");
    expect(runButton()).toBeDisabled();
  });
});

// ------------------------------------------------------- H: and sign-out

describe("AnalysisModeScreen: nothing survives a sign-out", () => {
  it("clears question and results when the client has been signed out before the remount", async () => {
    const user = userEvent.setup();
    mockSummary(() => Promise.resolve(json(summaryBody())));
    setToken("session-token");

    const first = render(<AnalysisModeScreen />);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    await screen.findByText(/Discharge pressure floor is 250 kPa/);
    first.unmount();

    // What api/client.ts does on a 401, and what App.tsx's Log out does: the
    // token goes away. Neither path is observable from here except this way.
    setToken(null);

    render(<AnalysisModeScreen />);
    expect(screen.queryByText(/Discharge pressure floor is 250 kPa/)).toBeNull();
    expect(screen.getByLabelText("Question")).toHaveValue("");
    expect(screen.getByText("Nothing has been run yet.")).toBeInTheDocument();
  });

  it("clears them while still mounted, within a second of the sign-out", async () => {
    vi.useFakeTimers();
    mockSummary(() => Promise.resolve(json(summaryBody())));
    setToken("session-token");

    render(<AnalysisModeScreen />);
    askSync();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();

    setToken(null);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.queryByText(/Discharge pressure floor is 250 kPa/)).toBeNull();
    expect(screen.getByLabelText("Question")).toHaveValue("");
  });

  it("keeps nothing from a run whose own response was the 401", async () => {
    // The response that signs the reader out must not be rendered as a red
    // "request failed" card under their question: the client has already
    // dropped the token by the time the slot would be written.
    vi.useFakeTimers();
    let call = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes("/analysis/summary")) return Promise.reject(new Error(`unrouted ${url}`));
      call += 1;
      return Promise.resolve(
        call === 1
          ? json(summaryBody())
          : json({ detail: { code: "unauthenticated", message: "expired" } }, 401),
      );
    });
    vi.stubGlobal("fetch", fetch);
    setToken("session-token");

    render(<AnalysisModeScreen />);
    askSync();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();

    // Only fetch is mocked: the real client handles the 401 and drops the
    // token before this screen ever sees the result.
    fireEvent.click(runButton());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.queryByText(/Discharge pressure floor is 250 kPa/)).toBeNull();
    expect(screen.queryByText(/expired/)).toBeNull();
    expect(screen.getByLabelText("Question")).toHaveValue("");
    expect(screen.getByText("Nothing has been run yet.")).toBeInTheDocument();
  });

  it("does NOT clear results on remount when nothing was ever signed in (auth disabled)", async () => {
    const user = userEvent.setup();
    mockSummary(() => Promise.resolve(json(summaryBody())));

    const first = render(<AnalysisModeScreen />);
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(runButton());
    await screen.findByText(/Discharge pressure floor is 250 kPa/);
    first.unmount();

    render(<AnalysisModeScreen />);
    expect(screen.getByText(/Discharge pressure floor is 250 kPa/)).toBeInTheDocument();
  });
});
