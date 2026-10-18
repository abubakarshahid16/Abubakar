import { describe, expect, it } from "vitest";
import { INBOX_RECORD, parseRoute, pathForView, titleForView } from "./routing";
import { ADMIN_NAV, NAV } from "./components/Shell";

describe("application routes", () => {
  it("parses views and record deep links", () => {
    expect(parseRoute("/analysis")).toEqual({ kind: "view", view: "analysis", recordId: undefined });
    expect(parseRoute("/deliverables/WBS%201.2")).toEqual({ kind: "view", view: "deliverables", recordId: "WBS 1.2" });
  });

  it("order 95 piece 3: /review/inbox is a record route of the review view", () => {
    expect(parseRoute("/review/inbox")).toEqual({ kind: "view", view: "review", recordId: INBOX_RECORD });
  });

  it("rejects unknown or over-deep paths", () => {
    expect(parseRoute("/secret")).toEqual({ kind: "forbidden", path: "/secret" });
    expect(parseRoute("/documents/a/b")).toEqual({ kind: "forbidden", path: "/documents/a/b" });
    expect(parseRoute("/review/run-1/a/b")).toEqual({ kind: "forbidden", path: "/review/run-1/a/b" });
  });

  it("#967: a review run's behind-the-scenes pages are a third segment, named ones only", () => {
    expect(parseRoute("/review/run-1/findings")).toEqual({ kind: "view", view: "review", recordId: "run-1", panel: "findings" });
    expect(parseRoute("/review/run-1/secret")).toEqual({ kind: "forbidden", path: "/review/run-1/secret" });
    expect(pathForView("review", "run-1", "crs")).toBe("/review/run-1/crs");
    expect(parseRoute(pathForView("review", "run/1", "steps"))).toEqual({ kind: "view", view: "review", recordId: "run/1", panel: "steps" });
    expect(pathForView("review", undefined, "crs")).toBe("/review");
  });

  it('order 95 piece 5: "How this was reviewed" is /review/<run>/how', () => {
    expect(parseRoute("/review/run-1/how")).toEqual({ kind: "view", view: "review", recordId: "run-1", panel: "how" });
    expect(pathForView("review", "run-1", "how")).toBe("/review/run-1/how");
  });

  it("generates stable links and distinct page titles", () => {
    expect(pathForView("reports")).toBe("/reports");
    expect(pathForView("chat", "review/42")).toBe("/chat/review%2F42");
    expect(titleForView("dashboard")).not.toBe(titleForView("documents"));
  });
});

describe("every navigation entry survives a refresh", () => {
  it("parses every NAV entry and the admin entry back to its own view", () => {
    for (const item of [...NAV, ADMIN_NAV]) {
      expect(parseRoute(pathForView(item.id))).toEqual({ kind: "view", view: item.id, recordId: undefined });
    }
  });

  it("opens /standards directly (refresh or back button)", () => {
    expect(parseRoute("/standards")).toEqual({ kind: "view", view: "standards", recordId: undefined });
  });
});
