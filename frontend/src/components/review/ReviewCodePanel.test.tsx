/**
 * The recommendation and the engineer's decision, side by side.
 *
 * Section 15's rule on screen: the AI recommends, the engineer decides, and
 * a reason is required only when the two differ.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewCodePanel } from "./ReviewCodePanel";
import type { ReviewRunSummary } from "../../types/api";

const decideCode = vi.fn();
vi.mock("../../api/client", () => ({
  reviews: { decideCode: (...args: unknown[]) => decideCode(...args) },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc_sub",
    submittal_filename: "sheet.pdf", equipment_tags: [], status: "completed",
    created_at: null, completed_at: null, standards_in_scope: 10,
    findings_total: 1580, by_status: {},
    recommended_code: "Manual Review Required",
    recommended_reason:
      "the review examined 48 fields; the denominator is a NOMINAL ESTIMATE "
      + "of 385, and that is not enough of the submittal to recommend a code",
    completeness: null,
    ...over,
  } as ReviewRunSummary;
}

beforeEach(() => {
  decideCode.mockReset();
  decideCode.mockResolvedValue({ ok: true, data: run() });
});

describe("both codes, never one", () => {
  it("shows the recommendation with its reason verbatim", () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);

    // Scoped to the card: the code is also an <option> in the select below.
    const card = screen.getByText(/Recommended by the system/).parentElement!;
    expect(within(card).getByText("Manual Review Required")).toBeInTheDocument();
    expect(within(card).getByText(/NOMINAL ESTIMATE/)).toBeInTheDocument();
  });

  it("keeps the recommendation on screen after a decision is recorded", () => {
    render(
      <ReviewCodePanel
        run={run({
          engineer_final_code: "Approved with Comments",
          override_reason: "both open items are lookup tables",
          decided_by: "eng", decided_at: "2026-09-19T12:00:00Z",
        })}
        onDecided={vi.fn()}
      />,
    );

    // THE AUDITOR'S QUESTION: what did the machine say? Both are present,
    // each scoped to its own card so an <option> cannot satisfy either.
    const recommended = screen.getByText(/Recommended by the system/).parentElement!;
    const decided = screen.getByText(/Engineer's final code/).parentElement!;
    expect(within(recommended).getByText("Manual Review Required")).toBeInTheDocument();
    expect(within(decided).getByText("Approved with Comments")).toBeInTheDocument();
    // Also in the card: the edit form below pre-fills the same reason, so
    // an unscoped query would match twice and prove neither.
    expect(within(decided).getByText(/both open items are lookup tables/)).toBeInTheDocument();
    expect(within(decided).getByText(/decided by/)).toBeInTheDocument();
  });

  it("names the engineer and keeps the id in the tooltip", () => {
    // THE SCREEN PRINTED `decided by user_phase6_demo`. An engineer knows
    // their name; nobody recognises their own row id. The id still travels -
    // the audit trail is keyed by it - but a reader should not have to read it.
    render(
      <ReviewCodePanel
        run={run({
          engineer_final_code: "Approved",
          decided_by: "user_phase6_demo", decided_by_name: "Ali Hassan",
        })}
        onDecided={vi.fn()}
      />,
    );

    const named = screen.getByText("Ali Hassan");
    expect(named).toBeInTheDocument();
    expect(named).toHaveAttribute("title", "user_phase6_demo");
    expect(screen.queryByText(/decided by user_phase6_demo/)).toBeNull();
  });

  it("falls back to the id when the engineer's row is gone", () => {
    // `decided_by` is ON DELETE SET NULL on the user, but a run can still
    // arrive carrying an id whose name did not resolve. The id is then all
    // that is known, and showing it beats showing nobody.
    render(
      <ReviewCodePanel
        run={run({ engineer_final_code: "Approved", decided_by: "gone" })}
        onDecided={vi.fn()}
      />,
    );

    expect(screen.getByText("gone")).toBeInTheDocument();
  });

  it("says a run is not decided when it is not", () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);

    expect(screen.getByText("Not decided yet.")).toBeInTheDocument();
  });
});

describe("a reason is required only when the codes differ", () => {
  it("does not ask for one when the engineer agrees", async () => {
    const onDecided = vi.fn();
    render(<ReviewCodePanel run={run()} onDecided={onDecided} />);

    await userEvent.click(screen.getByRole("button", { name: /Record final code/ }));

    expect(decideCode).toHaveBeenCalledWith("run-1", "Manual Review Required", null);
    expect(onDecided).toHaveBeenCalled();
  });

  it("asks for one as soon as a different code is chosen", async () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);

    await userEvent.selectOptions(
      screen.getByLabelText(/final code/i), "Approved");

    expect(screen.getByLabelText(/differs from the recommendation/i)).toBeInTheDocument();
  });

  it("refuses to send an override with no reason", async () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);
    await userEvent.selectOptions(
      screen.getByLabelText(/final code/i), "Approved");

    await userEvent.click(screen.getByRole("button", { name: /Record final code/ }));

    expect(decideCode).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/reason is required/i);
  });

  it("sends the override with its reason", async () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);
    await userEvent.selectOptions(
      screen.getByLabelText(/final code/i), "Approved");
    await userEvent.type(
      screen.getByLabelText(/differs from the recommendation/i),
      "every open item was checked by hand");

    await userEvent.click(screen.getByRole("button", { name: /Record final code/ }));

    expect(decideCode).toHaveBeenCalledWith(
      "run-1", "Approved", "every open item was checked by hand");
  });
});

describe("the server's refusal is shown, not swallowed", () => {
  it("renders the API's own message", async () => {
    decideCode.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "invalid_parameter", message: "overriding the recommended code requires a reason" },
    });
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Record final code/ }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "overriding the recommended code requires a reason");
  });
});

describe("a decided run says it cannot be re-run", () => {
  it("explains that a new review is a new run", () => {
    render(
      <ReviewCodePanel
        run={run({ engineer_final_code: "Approved" })} onDecided={vi.fn()}
      />,
    );

    expect(screen.getByText(/re-running it is refused/i)).toBeInTheDocument();
    expect(screen.getByText(/new review starts a new run/i)).toBeInTheDocument();
  });
});
