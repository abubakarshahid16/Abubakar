import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EngineChoice } from "../../../api/reviewPoints";
import { usePlan } from "./usePoints";

const plan = vi.fn();
vi.mock("../../../api/reviewPoints", async (orig) => ({
  ...(await orig<typeof import("../../../api/reviewPoints")>()),
  reviewPoints: { plan: (...a: unknown[]) => plan(...a) },
}));

const answer = (choice: string) => ({ ok: true, data: { choice, parts: [], sentence: "s", text_leaves: false, refused: null, documents: { leaving: [] } } });

beforeEach(() => plan.mockReset());

describe("usePlan: a plan is used only for the choice on screen", () => {
  it("in the render right after the choice changes, the old plan is never offered for the new choice", async () => {
    plan.mockImplementation(async (_d: string, engine: string) => answer(engine));
    const seen: { engine: EngineChoice; state: string; choice?: string }[] = [];
    const { rerender } = renderHook(({ engine }: { engine: EngineChoice }) => {
      const r = usePlan("doc1", engine);
      seen.push({ engine, state: r.plan.state, choice: r.plan.state === "ok" ? (r.plan.data.choice as string) : undefined });
      return r;
    }, { initialProps: { engine: "automatic" as EngineChoice } });
    await waitFor(() => expect(seen.at(-1)).toMatchObject({ engine: "automatic", state: "ok" }));
    rerender({ engine: "claude" });
    await waitFor(() => expect(seen.at(-1)).toMatchObject({ engine: "claude", state: "ok", choice: "claude" }));
    // never a frame with the new choice and the old plan
    expect(seen.filter((s) => s.state === "ok").every((s) => s.engine === s.choice)).toBe(true);
  });
});
