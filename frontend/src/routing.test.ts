import { describe, expect, it } from "vitest";
import {
  CRS_SHEET_IS_DEFAULT, panelForReviewScreen, parseRoute, pathForView, reviewScreenFor, titleForView,
} from "./routing";
import { ADMIN_NAV, NAV } from "./components/Shell";

describe("application routes", () => {
  it("parses views and record deep links", () => {
    expect(parseRoute("/analysis")).toEqual({ kind: "view", view: "analysis", recordId: undefined });
    expect(parseRoute("/deliverables/WBS%201.2")).toEqual({ kind: "view", view: "deliverables", recordId: "WBS 1.2" });
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

  it("order 95 piece 2: the card view is also at \"cards\", the new sheet at \"crs-sheet\"", () => {
    expect(parseRoute("/review/run-1/cards")).toEqual({ kind: "view", view: "review", recordId: "run-1", panel: "cards" });
    expect(pathForView("review", "run-1", "cards")).toBe("/review/run-1/cards");
    expect(parseRoute("/review/run-1/crs-sheet")).toEqual({ kind: "view", view: "review", recordId: "run-1", panel: "crs-sheet" });
  });

  it("order 95 piece 2: the card view stays the default until the owner switches it", () => {
    // MUTATION PROOF: flip CRS_SHEET_IS_DEFAULT without the owner and this fails.
    expect(CRS_SHEET_IS_DEFAULT).toBe(false);
    expect(reviewScreenFor(undefined)).toEqual({ screen: "cards" });
    expect(panelForReviewScreen("crsSheet")).toBe("crs-sheet");
    expect(panelForReviewScreen("cards")).toBeUndefined();
  });

  it.each([false, true])("order 95 piece 2: the review screens with CRS_SHEET_IS_DEFAULT = %s", (isDefault) => {
    expect(reviewScreenFor(undefined, isDefault)).toEqual(isDefault ? { screen: "crsSheet" } : { screen: "cards" });
    // The explicit addresses open the same screen whichever is the default.
    expect(reviewScreenFor("crs-sheet", isDefault)).toEqual({ screen: "crsSheet" });
    expect(reviewScreenFor("cards", isDefault)).toEqual({ screen: "cards" });
    // Behind-the-scenes pages (the old "crs" page among them) stay the card view's.
    expect(reviewScreenFor("findings", isDefault)).toEqual({ screen: "cards", panel: "findings" });
    expect(reviewScreenFor("crs", isDefault)).toEqual({ screen: "cards", panel: "crs" });
    // A link to the default screen is plain `/review/<run>`; to the other, its own segment.
    expect(panelForReviewScreen("crsSheet", isDefault)).toBe(isDefault ? undefined : "crs-sheet");
    expect(panelForReviewScreen("cards", isDefault)).toBe(isDefault ? "cards" : undefined);
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
