/**
 * AnswerCard, at the level of one card rather than one screen.
 *
 * ChatView.test.tsx holds the transcript-level property: an extract and a
 * refusal are never both page-level answers for the same question. These are
 * the component-level obligations that make that possible — that a failed
 * upgrade is reported ON the control that started it, that a refused upgrade
 * and an absent model do not read alike, and that a missing reason renders as
 * nothing at all rather than as a dash, a "null", or an empty bullet.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerCard, type AnswerView, type UpgradeFailure } from "./AnswerCard";
import type { AnswerPassage } from "../../types/api";

const P1: AnswerPassage = {
  chunk_id: "norsok:p00017:c00042:aa11",
  document_id: "doc_norsok",
  filename: "NORSOKM501Rev5.pdf",
  page_start: 17,
  page_end: 17,
  section: "A.1 Coating system no. 1",
  text: "Coating system no. 1 shall have a nominal dry film thickness of 280 um.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 6.5,
  identifier_hits: [],
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
};

const P2: AnswerPassage = {
  ...P1,
  chunk_id: "norsok:p00019:c00051:bb22",
  page_start: 19,
  page_end: 19,
  section: "A.4 Coating system no. 4",
  text: "Coating system no. 4 shall have a nominal dry film thickness of 450 um.",
};

function extractView(): AnswerView {
  return {
    answer_type: "extract",
    answer: P1.text,
    reason: null,
    passage: P1,
    supporting: [],
    passages: [],
    cited: [],
    rejected_citations: [],
    model: null,
    truncated: false,
    evidence_removed: [],
    seconds: 1.2,
    examples: [],
  };
}

function refusal(over: Partial<UpgradeFailure> = {}): UpgradeFailure {
  return {
    answer_type: "insufficient_evidence",
    reason: "the generated answer cited no supplied source",
    considered: [P2],
    activeSource: null,
    onSelectSource: () => {},
    ...over,
  };
}

function renderCard(upgradeFailure: UpgradeFailure | null, onExplain?: () => void) {
  return render(
    <AnswerCard
      view={extractView()}
      onSelectSource={() => {}}
      activeSource={null}
      onExplain={onExplain}
      upgradeFailure={upgradeFailure}
    />,
  );
}

describe("a failed upgrade is scoped to the control that started it", () => {
  it("says the plain-language version failed, not that the documents have no answer", () => {
    renderCard(refusal(), () => {});

    expect(
      screen.getByText(/The plain-language version could not be produced/i),
    ).toBeInTheDocument();
    // The page-level refusal is a claim about the QUESTION. This card is
    // simultaneously showing a quoted answer to that question.
    expect(screen.queryByText(/I cannot determine this from the available evidence/i)).toBeNull();
    expect(screen.queryByText(/Nothing was made up to fill the gap/i)).toBeNull();
  });

  it("leaves the quoted answer completely intact", () => {
    renderCard(refusal(), () => {});

    expect(screen.getByText(P1.text)).toBeInTheDocument();
    expect(screen.getByText(/Quoted verbatim from the document/i)).toBeInTheDocument();
  });

  it("says nothing at all when there was no failed upgrade", () => {
    renderCard(null, () => {});

    expect(screen.queryByText(/could not be produced/i)).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports the failure even when the button is no longer on offer", () => {
    // A failed upgrade that leaves no trace is indistinguishable from a
    // button that did nothing when pressed.
    renderCard(refusal(), undefined);

    expect(
      screen.getByText(/The plain-language version could not be produced/i),
    ).toBeInTheDocument();
  });

  it("hides the stale failure while the retry is running", () => {
    render(
      <AnswerCard
        view={extractView()}
        onSelectSource={() => {}}
        activeSource={null}
        onExplain={() => {}}
        explaining
        explainSeconds={12}
        upgradeFailure={refusal()}
      />,
    );

    expect(screen.getByRole("button", { name: /Explaining… 12s/ })).toBeInTheDocument();
    expect(screen.queryByText(/could not be produced/i)).toBeNull();
  });
});

describe("what was considered stays visible, with its document and page", () => {
  // WAS: "...and the clause for each passage". The clause label is no longer
  // printed anywhere a reader meets a passage: `chunks.section` does not reset
  // at chapter or appendix boundaries, so it names the wrong heading far more
  // often than the right one. The page does not have that problem, and it is
  // what makes the citation auditable. See `clauseLabel` in ./Provenance.tsx.
  it("names the document and the page for each passage, and no clause", () => {
    renderCard(refusal(), () => {});

    const notice = screen.getByRole("status");
    expect(within(notice).getByText("NORSOKM501Rev5.pdf")).toBeInTheDocument();
    expect(within(notice).getByText("page 19")).toBeInTheDocument();
    expect(within(notice).queryByText("A.4 Coating system no. 4")).toBeNull();
  });

  it("opens the passage the reader clicked, by its index in THAT attempt", () => {
    const onSelectSource = vi.fn();
    renderCard(refusal({ considered: [P1, P2], onSelectSource }), () => {});

    const rows = within(screen.getByRole("status")).getAllByRole("button");
    rows[1].click();
    expect(onSelectSource).toHaveBeenCalledWith(1);
  });

  it("shows no evidence section when the attempt had none", () => {
    renderCard(refusal({ considered: [] }), () => {});

    expect(screen.queryByText(/What the model was given/i)).toBeNull();
  });
});

// The rule this codebase will not bend: the machine being unreachable and a
// request being rejected are different situations with different remedies,
// and they must never wear the same face.
describe("the model being down never looks like the model refusing", () => {
  const unavailable = refusal({
    answer_type: "model_unavailable",
    reason: "the local answer model could not be reached (ConnectError)",
    considered: [],
  });

  it("raises an alert with the command that fixes it", () => {
    renderCard(unavailable, () => {});

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/local answer model is not running/i);
    expect(alert).toHaveTextContent("ollama serve");
    expect(alert).toHaveTextContent(/This is the machine, not your question/i);
  });

  it("does not raise an alert, or offer a command, for a refusal", () => {
    renderCard(refusal(), () => {});

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("ollama serve")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

// Found 2026-09-30: a Claude request failed and the screen blamed the local
// model and told the reader to run `ollama serve`. The notice now follows the
// engine that failed, in both directions.
describe("a failed answer names the engine that failed", () => {
  const claudeDown = refusal({
    answer_type: "model_unavailable",
    provider: "claude",
    reason: "the Claude call failed partway through this answer: HTTPStatusError: 400",
    considered: [],
  });

  it("a Claude failure is not blamed on the local model and offers no ollama command", () => {
    renderCard(claudeDown, () => {});

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Claude did not answer/i);
    expect(alert).toHaveTextContent(/HTTPStatusError: 400/);
    expect(alert).not.toHaveTextContent(/local answer model/i);
    expect(alert).not.toHaveTextContent(/ollama/i);
    expect(alert).not.toHaveTextContent(/not your question/i);
  });

  it("a local failure still names the local model and the command", () => {
    renderCard(
      refusal({
        answer_type: "model_unavailable",
        provider: "ollama",
        reason: "the local answer model could not be reached (ConnectError)",
        considered: [],
      }),
      () => {},
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/local answer model is not running/i);
    expect(alert).toHaveTextContent("ollama serve");
    expect(alert).not.toHaveTextContent(/Claude did not answer/i);
  });
});

describe("an absent reason renders as nothing, never as a placeholder", () => {
  it("prints no null, no dash and no empty sentence for a refusal", () => {
    renderCard(refusal({ reason: null }), () => {});

    const notice = screen.getByRole("status");
    const text = notice.textContent ?? "";
    expect(text).not.toMatch(/null|undefined/i);
    expect(text).not.toMatch(/(^|\s)[-—–]\s|\.\s*\./);
    // and it still says what happened, in a whole sentence
    expect(text).toMatch(/the model produced nothing that could be checked\./i);
  });

  it("prints no null and no dash for an unreachable model", () => {
    renderCard(refusal({ answer_type: "model_unavailable", reason: null, considered: [] }), () => {});

    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).not.toMatch(/null|undefined/i);
    expect(text).toMatch(/Ollama could not be reached\./);
  });

  it("does not run two sentences together without a full stop", () => {
    renderCard(refusal({ reason: "the generated answer cited no supplied source" }), () => {});

    const text = screen.getByRole("status").textContent ?? "";
    expect(text).toContain("no supplied source. Nothing is shown");
    expect(text).not.toContain("no supplied source Nothing");
  });
});

describe("plan C3: a comparison renders each named side on its own", () => {
  function comparisonView(): AnswerView {
    return {
      answer_type: "comparison",
      answer:
        "SAES-W-010: Post weld heat treatment shall be carried out at 620 C." +
        "\n\n" +
        "ASME-B31-3: not found in the pages read.",
      reason: null,
      passage: null,
      supporting: [],
      passages: [P1],
      cited: [],
      rejected_citations: [],
      model: null,
      truncated: false,
      evidence_removed: [],
      seconds: 2.4,
      examples: [],
      comparison: {
        sides: [
          { name: "SAES-W-010", document_ids: [P1.document_id], answer_type: "extract" },
          { name: "ASME-B31-3", document_ids: ["doc_asme"], answer_type: "insufficient_evidence" },
        ],
      },
    };
  }

  function renderComparison() {
    return render(
      <AnswerCard view={comparisonView()} onSelectSource={() => {}} activeSource={null} />,
    );
  }

  it("shows both side names, each with its own text", () => {
    renderComparison();
    expect(screen.getByText("SAES-W-010")).toBeInTheDocument();
    expect(screen.getByText("ASME-B31-3")).toBeInTheDocument();
    expect(screen.getByText(/Post weld heat treatment shall be carried out at 620 C/)).toBeInTheDocument();
  });

  it("says not found in the pages read for the side with nothing, never a model sentence for it", () => {
    renderComparison();
    expect(screen.getByText(/Not found in the pages read\./)).toBeInTheDocument();
  });

  it("cites the side that has evidence", () => {
    renderComparison();
    expect(screen.getByText(P1.filename, { exact: false })).toBeInTheDocument();
  });

  it("never labels the whole card as written by the model - it is not one model's prose", () => {
    renderComparison();
    expect(screen.queryByText(/Written by the model/i)).toBeNull();
    expect(screen.getByText(/Compared across 2 named sides/i)).toBeInTheDocument();
  });

  it("never says a found side does not mention the topic", () => {
    renderComparison();
    expect(screen.queryByText(/does not mention/i)).toBeNull();
  });
});

describe("the retry is labelled as a retry", () => {
  it("says try again after a failure, and offers the first go otherwise", async () => {
    const onExplain = vi.fn();
    const { unmount } = renderCard(refusal(), onExplain);
    await userEvent.click(
      screen.getByRole("button", { name: /Try the plain-language version again/i }),
    );
    expect(onExplain).toHaveBeenCalledTimes(1);
    unmount();

    renderCard(null, () => {});
    expect(
      screen.getByRole("button", { name: /^Explain in plain language$/ }),
    ).toBeInTheDocument();
  });
});
