/**
 * Order 164.1: "Confirm page values". Ticks, one batch call, the counts that
 * follow, and the conflict that can never be bulk-ticked.
 *
 * MUTATION PROOF: pre-tick the values and "nothing is pre-ticked" fails; send
 * one call per value and "one call" fails; let "Tick all" include the conflict
 * and "never bulk-ticked" fails; drop the held_before - held_after sum and the
 * counts test fails.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PageFact } from "../../../types/api";
import { ConfirmPageValues } from "./ConfirmPageValues";
import { resultLine } from "./confirmValues";

const pageFacts = vi.fn();
const confirmPageFacts = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: {
    pageFacts: (...a: unknown[]) => pageFacts(...a),
    confirmPageFacts: (...a: unknown[]) => confirmPageFacts(...a),
  },
}));

function fact(id: string, field: string, over: Partial<PageFact> = {}): PageFact {
  return {
    fact_id: id, field, value: "95", unit: "dB(A)", quote: `${field} 95 dB(A)`,
    confirmed: false, conflict: false, needs_check: true, ...over,
  };
}

function listed(facts: PageFact[]) {
  return { ok: true, data: { review_run_id: "run-1", page: 2, facts, boundary: "the values read on this page" } };
}

const done = (over = {}) => ({
  ok: true,
  data: {
    review_run_id: "run-1", confirmed: 3, already_confirmed: 0, held_before: 5, held_after: 2,
    status_before: {}, status_after: {}, boundary: "this review run", ...over,
  },
});

beforeEach(() => {
  pageFacts.mockReset();
  confirmPageFacts.mockReset().mockResolvedValue(done());
});

async function openWith(facts: PageFact[], onConfirmed = vi.fn()) {
  pageFacts.mockResolvedValue(listed(facts));
  render(<ConfirmPageValues runId="run-1" page={2} onConfirmed={onConfirmed} />);
  await userEvent.click(screen.getByRole("button", { name: "Confirm page values" }));
  await screen.findByText(/the values the program read on page 2/i);
  return onConfirmed;
}

describe("ConfirmPageValues", () => {
  it("lists the page's values with their quotes and pre-ticks nothing", async () => {
    await openWith([fact("a", "Design pressure"), fact("b", "Design temperature")]);
    expect(pageFacts).toHaveBeenCalledWith("run-1", 2);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(boxes.every((b) => !(b as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByText("“Design pressure 95 dB(A)”")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm 0 values" })).toBeDisabled();
  });

  it("ticks three values, calls the batch route once, and says what changed", async () => {
    const onConfirmed = await openWith([
      fact("a", "Design pressure"), fact("b", "Design temperature"), fact("c", "Corrosion allowance"),
    ]);
    for (const box of screen.getAllByRole("checkbox")) await userEvent.click(box);
    await userEvent.click(screen.getByRole("button", { name: "Confirm 3 values" }));
    await waitFor(() => expect(confirmPageFacts).toHaveBeenCalledTimes(1));
    expect(confirmPageFacts).toHaveBeenCalledWith("run-1", ["a", "b", "c"]);
    const line = await screen.findByRole("status");
    expect(line).toHaveTextContent(
      "3 confirmed; in this review 3 findings now have a verdict, 2 still wait for a value nobody has confirmed.");
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
    // the list is read again after the answer
    expect(pageFacts).toHaveBeenCalledTimes(2);
  });

  it("says it is working while the review is judged again, and nothing can be sent twice", async () => {
    await openWith([fact("a", "Design pressure")]);
    let finish: (v: unknown) => void = () => {};
    confirmPageFacts.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Confirm 1 value" }));
    expect(await screen.findByText(/judging this review again/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm 1 value" })).toBeDisabled();
    finish(done({ confirmed: 1, held_before: 1, held_after: 0 }));
    await waitFor(() => expect(screen.queryByText(/judging this review again/i)).toBeNull());
    expect(confirmPageFacts).toHaveBeenCalledTimes(1);
  });

  it("a conflict is listed first, is never ticked in bulk, and is confirmed on its own", async () => {
    await openWith([
      fact("a", "Design pressure"),
      fact("x", "Max temperature", { conflict: true, value: "120", unit: "°C" }),
    ]);
    expect(screen.getByRole("heading", { name: /read two different ways/i })).toBeInTheDocument();
    // only the plain value has a checkbox
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Tick all on this page" }));
    expect(screen.getByRole("button", { name: "Confirm 1 value" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm 1 value" }));
    await waitFor(() => expect(confirmPageFacts).toHaveBeenCalledWith("run-1", ["a"]));
    // the conflict has its own button and its own call
    await userEvent.click(screen.getByRole("button", { name: "Confirm this value: Max temperature" }));
    await waitFor(() => expect(confirmPageFacts).toHaveBeenLastCalledWith("run-1", ["x"]));
    expect(confirmPageFacts).toHaveBeenCalledTimes(2);
  });

  it("shows the server's refusal and leaves the ticks alone", async () => {
    await openWith([fact("a", "Design pressure")]);
    confirmPageFacts.mockResolvedValue({ ok: false, error: { message: "a value in the list was re-read since" } });
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Confirm 1 value" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("re-read since");
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("says plainly when nothing was read on the page, and names what is already confirmed", async () => {
    await openWith([fact("a", "Design pressure", { confirmed: true, needs_check: false })]);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText(/already confirmed on this page: design pressure/i)).toBeInTheDocument();
  });

  it("counts are worded with their boundary and singular forms", () => {
    expect(resultLine({
      review_run_id: "r", confirmed: 1, already_confirmed: 1, held_before: 2, held_after: 1,
      status_before: {}, status_after: {}, boundary: "",
    })).toBe("1 confirmed (1 already were); in this review 1 finding now has a verdict, 1 still waits for a value nobody has confirmed.");
  });
});
