/**
 * The AI reviewer's calls. A 404 on agent-status is "switch off", not an
 * error; any unreadable answer is off too (the screen shows nothing).
 * MUTATION PROOF: make agentSwitch return "on" on a failed call and the 404
 * test fails; drop `enabled` handling and the enabled:false test fails.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentReview, agentSwitch, isFeatureOff } from "./agentReview";

function stub(status: number, body: unknown) {
  const spy = vi.fn((..._a: unknown[]) => Promise.resolve(new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  })));
  vi.stubGlobal("fetch", spy);
  return spy;
}
afterEach(() => vi.unstubAllGlobals());

describe("agentSwitch", () => {
  it("404 feature_off means the switch is off, with no error", async () => {
    stub(404, { detail: "feature_off" });
    expect(await agentSwitch()).toEqual({ state: "off" });
  });
  it("enabled:false is off; enabled:true is on with the lane flag", async () => {
    stub(200, { enabled: false, claude_lane_open: true });
    expect(await agentSwitch()).toEqual({ state: "off" });
    stub(200, { enabled: true, claude_lane_open: false });
    expect(await agentSwitch()).toEqual({ state: "on", status: { enabled: true, claude_lane_open: false } });
  });
  it("a network failure or a wrong shape is off", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("down"))));
    expect(await agentSwitch()).toEqual({ state: "off" });
    stub(200, { nope: 1 });
    expect(await agentSwitch()).toEqual({ state: "off" });
  });
});

describe("calls", () => {
  it("start posts the document id as JSON", async () => {
    const spy = stub(200, { review_run_id: "r1" });
    await agentReview.start("doc 1");
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/reviews/agent-run");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ submittal_document_id: "doc 1" }));
  });
  it("lines pass the cursor, encoded; trace and rules-used use their routes", async () => {
    const spy = stub(200, { lines: [], next: null });
    await agentReview.lines("r/1", "a b");
    expect(spy.mock.calls[0][0]).toBe("/api/reviews/runs/r%2F1/agent/lines?cursor=a%20b");
    stub(200, { item_id: "i", gate: [] });
    const t = stub(200, { item_id: "i", gate: [] });
    await agentReview.trace("r1", "i 1");
    expect(t.mock.calls[0][0]).toBe("/api/reviews/runs/r1/agent/lines/i%201/trace");
    const u = stub(200, { asked: [], left_out: [], missing_books: [] });
    await agentReview.rulesUsed("r1");
    expect(u.mock.calls[0][0]).toBe("/api/reviews/runs/r1/rules-used");
  });
  it("a body of the wrong shape is a failure, not data", async () => {
    stub(200, { lines: "x" });
    const r = await agentReview.lines("r1");
    expect(r.ok).toBe(false);
  });
  it("exportCrs asks for the copy and returns the server's file name", async () => {
    const spy = vi.fn((..._a: unknown[]) => Promise.resolve(new Response(new Blob(["x"]), {
      status: 200, headers: { "Content-Disposition": 'attachment; filename="CRS_x.xlsx"' },
    })));
    vi.stubGlobal("fetch", spy);
    const r = await agentReview.exportCrs("r1", "contractor");
    expect(spy.mock.calls[0][0]).toBe("/api/reviews/runs/r1/agent/crs?copy=contractor");
    expect(r.ok && r.data.filename).toBe("CRS_x.xlsx");
  });
  it("isFeatureOff reads a 404 only", async () => {
    stub(404, { detail: "feature_off" });
    expect(isFeatureOff(await agentReview.summary("r1"))).toBe(true);
    stub(500, {});
    expect(isFeatureOff(await agentReview.summary("r1"))).toBe(false);
  });
});
