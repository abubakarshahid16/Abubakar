import { describe, expect, it } from "vitest";
import { parseRoute, pathForView, titleForView } from "./routing";

describe("application routes", () => {
  it("parses views and record deep links", () => {
    expect(parseRoute("/analysis")).toEqual({ kind: "view", view: "analysis", recordId: undefined });
    expect(parseRoute("/deliverables/WBS%201.2")).toEqual({ kind: "view", view: "deliverables", recordId: "WBS 1.2" });
  });

  it("rejects unknown or over-deep paths", () => {
    expect(parseRoute("/secret")).toEqual({ kind: "forbidden", path: "/secret" });
    expect(parseRoute("/documents/a/b")).toEqual({ kind: "forbidden", path: "/documents/a/b" });
  });

  it("generates stable links and distinct page titles", () => {
    expect(pathForView("reports")).toBe("/reports");
    expect(pathForView("chat", "review/42")).toBe("/chat/review%2F42");
    expect(titleForView("dashboard")).not.toBe(titleForView("documents"));
  });
});
