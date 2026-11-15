import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.fn();
vi.mock("./core", () => ({ request: (...a: unknown[]) => request(...a) }));

import { pageV2Switch, reviewPoints } from "./reviewPoints";

beforeEach(() => request.mockReset());

describe("the redesigned page's calls", () => {
  it("the switch is on only when the server says enabled", async () => {
    request.mockResolvedValue({ ok: true, data: { enabled: true } });
    expect(await pageV2Switch()).toBe(true);
    request.mockResolvedValue({ ok: true, data: { enabled: false } });
    expect(await pageV2Switch()).toBe(false);
  });
  it("anything unreadable is off: the old page stays", async () => {
    request.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "x" } });
    expect(await pageV2Switch()).toBe(false);
    request.mockImplementationOnce(() => { throw new Error("network"); });
    expect(await pageV2Switch()).toBe(false);
  });
  it("the plan and the writes go to the right routes with the right bodies", async () => {
    request.mockResolvedValue({ ok: true, data: {} });
    await reviewPoints.plan("doc 1", "local");
    expect(request.mock.calls[0][0]).toBe("/reviews/plan?submittal_document_id=doc%201&engine=local");
    await reviewPoints.decide("d", { point_id: "p", state: "remove", reason: "because" });
    expect(request.mock.calls[1][0]).toBe("/reviews/papers/d/points/decision");
    expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ point_id: "p", state: "remove", reason: "because" });
    await reviewPoints.keepAll("d", ["a", "b"]);
    expect(JSON.parse(request.mock.calls[2][1].body)).toEqual({ point_ids: ["a", "b"] });
    await reviewPoints.start("d", "claude");
    expect(request.mock.calls[3][0]).toBe("/reviews/start");
    expect(JSON.parse(request.mock.calls[3][1].body)).toEqual({ submittal_document_id: "d", engine: "claude" });
  });
});
