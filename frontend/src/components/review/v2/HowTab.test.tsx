import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HowTab } from "./HowTab";
import { localOnlyWords, methodLine, type MethodInfo } from "./words";

const info = (over: Partial<MethodInfo> = {}): MethodInfo => ({
  method: "general", old_engine: false, local_available: false, local_words: "invented local sentence", mark: "invented mark", ...over,
});
const answer = (body: unknown) => vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })));

describe("the method words come from the route", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("draws the route's mark and Local-only sentence, whatever they say", async () => {
    vi.stubGlobal("fetch", answer(info()));
    render(<HowTab top={null} sections={[]} />);
    await waitFor(() => expect(screen.getByTestId("v2-how-method").textContent).toBe("Method: the current review. invented mark."));
    expect(screen.getByTestId("v2-how-local").textContent).toBe("invented local sentence");
  });

  it("with the way back on it says earlier and shows no Local-only sentence", async () => {
    vi.stubGlobal("fetch", answer(info({ method: "earlier", old_engine: true })));
    render(<HowTab top={null} sections={[]} />);
    await waitFor(() => expect(screen.getByTestId("v2-how-method").textContent).toContain("earlier"));
    expect(screen.queryByTestId("v2-how-local")).toBeNull();
  });

  it("draws nothing of it while the route has not answered", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<HowTab top={null} sections={[]} />);
    expect(screen.queryByTestId("v2-how-method")).toBeNull();
  });

  it("the helpers say nothing for a null answer or a local engine that is available", () => {
    expect(methodLine(null)).toBeNull();
    expect(localOnlyWords(null)).toBeNull();
    expect(localOnlyWords(info({ local_available: true }))).toBeNull();
  });
});
