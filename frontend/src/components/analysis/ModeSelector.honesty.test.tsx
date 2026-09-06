/**
 * The mode descriptions are read as promises. This file guards the three that
 * were false: a one-minute Focused run, a cancellable Comprehensive run, and a
 * batch-by-batch sweep of every authorised document. None of those exist -
 * Comprehensive is one synchronous request with limit 24, and
 * AnalysisModeScreen says so plainly one click later. The assertions here are
 * phrased against the rendered radio-group text, so restoring any of the old
 * wording turns this file red.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModeSelector, type AnalysisMode, type AnalysisToggles } from "./ModeSelector";

const TOGGLES: AnalysisToggles = { gaps: false, market: false, recommendation: false };

/** Every description string the radio group shows the reader. */
function descriptions(): string[] {
  render(
    <ModeSelector
      mode={"focused" as AnalysisMode}
      onChange={() => {}}
      toggles={TOGGLES}
      onToggle={() => {}}
    />,
  );
  const group = screen.getByRole("group", { name: /analysis mode/i });
  return Array.from(group.querySelectorAll("input[type=radio]")).map((input) => {
    const descId = input.getAttribute("aria-describedby");
    expect(descId).toBeTruthy();
    const node = document.getElementById(descId as string);
    expect(node).not.toBeNull();
    return (node as HTMLElement).textContent ?? "";
  });
}

describe("analysis mode descriptions make no false promise", () => {
  it("shows one description per mode", () => {
    expect(descriptions()).toHaveLength(3);
  });

  it("does not claim a one-minute focused run", () => {
    const joined = descriptions().join(" ").toLowerCase();
    expect(joined).not.toContain("about a minute");
    // Any single-minute claim, however phrased: "a minute", "~1 minute", "1 min".
    expect(joined).not.toMatch(/\b(?:about\s+|around\s+|~\s*)?(?:a|one|1)\s*min\b/);
  });

  it("does not promise cancellation, which no code path implements", () => {
    const joined = descriptions().join(" ").toLowerCase();
    expect(joined).not.toContain("you can cancel");
    expect(joined).not.toMatch(/\bcancel(?:led|ling|lable|able|s|lation)?\b/);
    expect(joined).not.toMatch(/\bstop the run\b|\babort\b|\binterrupt\b/);
  });

  it("does not claim batching or per-document coverage", () => {
    const joined = descriptions().join(" ").toLowerCase();
    expect(joined).not.toContain("batch by batch");
    expect(joined).not.toMatch(/\bbatch(?:es|ed|ing)?\b/);
    expect(joined).not.toMatch(/\bevery (?:authorised|authorized) document\b/);
    expect(joined).not.toMatch(/\b(?:all|every|each) (?:of your |the )?documents?\b/);
  });

  it("does not promise streaming or progress, which the backend does not expose", () => {
    const joined = descriptions().join(" ").toLowerCase();
    expect(joined).not.toMatch(/\bstream(?:s|ed|ing)?\b/);
    expect(joined).not.toMatch(/\bprogress\b|\b\d{1,3}\s*%/);
  });

  it("keeps the quote mode claim, which is true and model-free", () => {
    const [quote] = descriptions();
    expect(quote).toMatch(/no model involved/i);
  });
});
