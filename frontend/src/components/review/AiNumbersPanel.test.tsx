/**
 * #845: the run card's AI numbers, printed verbatim from the run's stored
 * record, each step with where it ran. Null renders as nothing.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiNumbers, AiStepNumbers } from "../../types/api";
import { AiNumbersPanel } from "./AiNumbersPanel";

const step = (over: Partial<AiStepNumbers>): AiStepNumbers => ({
  step: "AI matcher", state: "ran", where: "local model", model: "ollama:m",
  local_instead: null, lines: [], ...over,
});

const NUMBERS: AiNumbers = {
  reader: step({ step: "AI reader", lines: ["2 of 3 page(s) read by the AI."] }),
  matcher: step({ lines: ["Asked about 1 of 1 requirement(s) the match rules could not pair."] }),
  engineering_check: null,
  wording: step({ step: "AI wording", where: "cloud model", state: "incomplete",
    lines: ["Of 4 row(s) worded: 3 kept, 1 refused by the lock."] }),
};

describe("AiNumbersPanel", () => {
  it("prints each recorded step's lines verbatim with where it ran", () => {
    render(<AiNumbersPanel numbers={NUMBERS} />);
    const reader = screen.getByTestId("ai-step-AI reader");
    expect(within(reader).getByText("ran, local model")).toBeInTheDocument();
    expect(within(reader).getByText("2 of 3 page(s) read by the AI.")).toBeInTheDocument();
    const wording = screen.getByTestId("ai-step-AI wording");
    expect(within(wording).getByText("incomplete, cloud model")).toBeInTheDocument();
  });

  it("#645: prints the AI clause checks line after the other steps", () => {
    const line = "2 of 5 sentence requirement(s) now have a proposed check (drafts for the engineer); "
      + "1 proposal(s) refused by code, 2 not read by the model.";
    render(<AiNumbersPanel numbers={{ ...NUMBERS,
      clause_checks: step({ step: "AI clause checks", state: "incomplete", lines: [line] }) }} />);
    const checks = screen.getByTestId("ai-step-AI clause checks");
    expect(within(checks).getByText(line)).toBeInTheDocument();
    expect(within(checks).getByText("incomplete, local model")).toBeInTheDocument();
  });

  it("leaves out a step with no record instead of showing a zero", () => {
    render(<AiNumbersPanel numbers={NUMBERS} />);
    expect(screen.queryByTestId("ai-step-AI engineering check")).toBeNull();
    expect(screen.getAllByRole("listitem").some((li) => /\b0\b/.test(li.textContent ?? ""))).toBe(false);
  });

  it("shows no panel when the run holds no AI record", () => {
    const { container } = render(<AiNumbersPanel numbers={null} />);
    expect(container).toBeEmptyDOMElement();
    render(<AiNumbersPanel numbers={{ reader: null, matcher: null, engineering_check: null, wording: null }} />);
    expect(screen.queryByTestId("ai-numbers")).toBeNull();
  });

  it("names a step where the record names no engine without inventing one", () => {
    render(<AiNumbersPanel numbers={{ ...NUMBERS, reader: step({ step: "AI reader", state: "off", where: null,
      lines: ["Off: the code readers read all 4 page(s)."] }) }} />);
    expect(within(screen.getByTestId("ai-step-AI reader")).getByText("off")).toBeInTheDocument();
  });

  it("says once that the local model stood in for the cloud model", () => {
    const note = "ran on the local model: 1 of 2 document(s) in its prompt are not approved for the cloud model";
    render(<AiNumbersPanel numbers={{ ...NUMBERS,
      wording: step({ step: "AI wording", local_instead: note, lines: ["Of 2 row(s) worded: 2 kept, 0 refused by the lock."] }),
      engineering_check: step({ step: "AI engineering check", local_instead: note,
        lines: [`AI engineering check complete: 1 of 1 proposed item(s) kept, over 1 call. The check ${note}.`] }),
    }} />);
    expect(within(screen.getByTestId("ai-step-AI wording")).getByText(`This step ${note}.`)).toBeInTheDocument();
    expect(within(screen.getByTestId("ai-step-AI engineering check")).queryByText(`This step ${note}.`)).toBeNull();
  });
});
