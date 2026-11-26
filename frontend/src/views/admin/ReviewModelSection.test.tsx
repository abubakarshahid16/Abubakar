/**
 * The Administration page's Review model section (lead-4, 26 Nov 2026): Claude is listed as the main engine with no picker, each
 * local model says "local model, not yet scored", a model the server refuses is not offered and says why, and Save sends the
 * default and the per-step picks. Invented model names only; the server is faked.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { formatWhen } from "../../format/when";
import { ReviewModelSection, type ReviewModelOptions, reviewModelApi } from "./ReviewModelSection";

const OPTIONS: ReviewModelOptions = {
  claude: [{ name: "invented-claude-lead", engine: "claude", selectable: false, why: "the method's own Claude model, as scored",
    score_words: "measured on 3 kinds", used_for: "every step but the attack" }],
  local: [
    { name: "invented-small:14b", engine: "local", selectable: true, why: null, score_words: "local model, not yet scored",
      price_words: "USD 0 (runs on this computer)", is_default: true, measured: "invented: did not finish a valve review" },
    { name: "invented-huge:35b", engine: "local", selectable: false, why: "too large for this computer (its file is over 15 GB)",
      score_words: "local model, not yet scored", price_words: "USD 0 (runs on this computer)" },
  ],
  engine_down: false,
  engine_down_words: null,
  steps: ["name", "judge"],
  answer_model: "invented-small:14b",
  used_by: "Local only runs of the general review; Automatic and Claude never use a local model.",
  stored: { default: null, steps: {}, set_by: null, set_at: null },
  history: [{ slot: "judge", old_model: null, new_model: "invented-small:14b", changed_by: "u-invented", changed_at: "2026-11-26T03:00:00+00:00" }],
};

function fake(save = vi.fn().mockResolvedValue({ ok: true, data: { stored: OPTIONS.stored } })) {
  return { load: vi.fn().mockResolvedValue({ ok: true, data: OPTIONS }), save } as unknown as typeof reviewModelApi;
}

describe("ReviewModelSection", () => {
  it("lists Claude as the main engine without a picker and every local model as not yet scored", async () => {
    render(<ReviewModelSection api={fake()} />);
    expect(await screen.findByText(/Claude \(the main engine\)/)).toBeInTheDocument();
    const rows = screen.getAllByTestId("review-model-local");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row).toHaveTextContent("local model, not yet scored");
    expect(rows[1]).toHaveTextContent("cannot be chosen: too large for this computer");
    expect(rows[0]).toHaveTextContent("(default)");
    expect(rows[0]).toHaveTextContent("invented: did not finish a valve review");
    expect(rows[1]).not.toHaveTextContent("(default)");
    const pickers = screen.getAllByRole("combobox");
    expect(pickers).toHaveLength(3); // the default and one per step; none for Claude
    expect(within(pickers[0]).queryByRole("option", { name: "invented-huge:35b" })).toBeNull();
    expect(screen.getByTestId("review-model-history")).toHaveTextContent("judge: the default → invented-small:14b (by u-invented)");
  });

  it("saves the default and the per-step picks", async () => {
    const save = vi.fn().mockResolvedValue({ ok: true, data: { stored: OPTIONS.stored } });
    render(<ReviewModelSection api={fake(save)} />);
    await userEvent.selectOptions(await screen.findByLabelText("Default local model"), "invented-small:14b");
    await userEvent.selectOptions(screen.getByLabelText("Local model for judge"), "invented-small:14b");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledWith({ default: "invented-small:14b", steps: { judge: "invented-small:14b" } });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("says why the configured answer model was replaced by the code's default", async () => {
    const replaced = { ...OPTIONS, answer_model_why: "ANSWER_MODEL names invented-huge:35b, which cannot be used here" };
    const api = { load: vi.fn().mockResolvedValue({ ok: true, data: replaced }), save: vi.fn() } as unknown as typeof reviewModelApi;
    render(<ReviewModelSection api={api} />);
    expect(await screen.findByTestId("review-model-fell-back")).toHaveTextContent("invented-huge:35b, which cannot be used here");
  });

  it("says when it was last saved and when each change was made with the zone named, and says when nothing was recorded", async () => {
    const at = "2026-11-26T03:24:16+00:00";
    const saved = { ...OPTIONS, stored: { ...OPTIONS.stored, set_at: at } };
    const api = { load: vi.fn().mockResolvedValue({ ok: true, data: saved }), save: vi.fn() } as unknown as typeof reviewModelApi;
    const { unmount } = render(<ReviewModelSection api={api} />);
    expect(await screen.findByText(`Last saved ${formatWhen(at)}`)).toBeInTheDocument();
    expect(screen.queryByText(/2026-11-26T03:24:16/)).toBeNull(); // never the raw stamp
    expect(screen.getByTestId("review-model-history")).toHaveTextContent(formatWhen(OPTIONS.history![0].changed_at));
    unmount();
    const empty = { ...OPTIONS, history: [], history_since: "2026-11-26T10:34:00Z", history_since_update: "update 11" };
    render(<ReviewModelSection api={{ load: vi.fn().mockResolvedValue({ ok: true, data: empty }), save: vi.fn() } as unknown as typeof reviewModelApi} />);
    expect(await screen.findByTestId("review-model-no-history"))
      .toHaveTextContent(`No change recorded since ${formatWhen("2026-11-26T10:34:00Z")} (update 11).`);
  });

  it("shows the server's refusal in its own words", async () => {
    const save = vi.fn().mockResolvedValue({ ok: false, disconnected: false, error: { message: "invented refusal" } });
    render(<ReviewModelSection api={fake(save)} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invented refusal");
  });
});
