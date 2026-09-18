/**
 * The bulk "Set role" action on the Documents page.
 *
 * TWO PROPERTIES, and neither is about the select box:
 *
 *   THE CONTROL DOES NOT EXIST FOR A NON-ADMIN. `POST /api/documents/bulk/role`
 *   404s anyone without the admin capability, and a button that always fails is
 *   worse than no button - it teaches the reader the app is broken.
 *
 *   A PARTIAL WRITE IS REPORTED AS ONE. The endpoint answers 207 and names the
 *   documents it could not update; a screen that reads `ok` and says "3
 *   documents updated" after a request naming 4 has told the person something
 *   false, and the whole point of the endpoint's shape was to make that
 *   impossible. The test asserts the failure is on screen, not just that the
 *   request went out.
 *
 * The request BODY is asserted too. A test that only checks the notice text
 * would pass against a button that posted the wrong ids - the sentence on
 * screen is generated from the response, so the response is the only thing it
 * proves.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { Health } from "../api/client";
import { DocumentsView } from "./DocumentsView";
import type { DocumentClassification, DocumentRecord } from "../types/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

function makeDoc(id: string, filename: string): DocumentRecord {
  return {
    id,
    filename,
    sha256: `sha-${id}`,
    size_bytes: 1000,
    page_count: 2,
    pages_done: 2,
    chunk_count: 2,
    chunk_count_total: 2,
    disciplines: [],
    embedded_count: 2,
    status: "ready",
    needs_ocr_pages: 0,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    uploaded_at: "2026-09-19T00:00:00Z",
    indexed_at: "2026-09-19T00:01:00Z",
  };
}

/** THE TWO DOCUMENTS DELIBERATELY LAND IN DIFFERENT GROUPS.
 *
 *  The page renders `DocumentCard` from TWO places - once per register type
 *  group, and once for the "awaiting a type" group - and the selection props
 *  have to be passed at both. The first version of this file gave both
 *  documents a null type, so every assertion was about the awaiting-a-type
 *  path and the typed path was never rendered at all; mutation M82 patched it
 *  and nothing failed. `d1` is typed and `d2` is not, so a checkbox missing
 *  from either site is now a failing test.
 */
function classificationFor(id: string): DocumentClassification {
  return {
    document_id: id,
    doc_type: id === "d1" ? "Document" : null,
    discipline: null,
    doc_class: null,
    register_id: null,
    suggested_by: "none",
    confirmed_by: null,
    confirmed_at: null,
    confirmed: false,
    subjects: [],
  } as DocumentClassification;
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const DOCS = [makeDoc("d1", "SAES-A-105.pdf"), makeDoc("d2", "SAES-B-005.pdf")];

/** Records every bulk POST so a test can assert what was actually sent. */
function mockApi(bulk: { status: number; body: unknown }) {
  const posted: Array<Record<string, unknown>> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/documents/bulk/role")) {
        posted.push(JSON.parse((init?.body as string) ?? "{}"));
        return jsonResponse(bulk.body, bulk.status);
      }
      if (url.includes("/auth/me")) return jsonResponse({ required: false, user: null });
      if (url.includes("/health")) return jsonResponse(health);
      if (url.includes("/metrics")) return jsonResponse({ worker: null });
      if (url.includes("/classification/vocabulary")) {
        return jsonResponse({
          register_revision: "r1", types: ["Document"], disciplines: [],
          subjects: [], needs_classification: 0,
        });
      }
      if (url.includes("/classification/coverage")) {
        return jsonResponse({
          register_loaded: true, register_revision: "r1", by_type: [],
          by_discipline: [], by_subject: [], needs_classification: 0,
        });
      }
      const perDoc = url.match(/\/documents\/([^/]+)\/classification/);
      if (perDoc) return jsonResponse(classificationFor(decodeURIComponent(perDoc[1])));
      if (url.includes("/documents")) {
        return Promise.resolve(
          new Response(JSON.stringify(DOCS), {
            status: 200,
            headers: { "Content-Type": "application/json", "X-Total-Count": "2" },
          }),
        );
      }
      return jsonResponse({});
    },
  );
  return posted;
}

function renderDocuments(isAdmin: boolean) {
  render(
    <DocumentsView
      connection={{ state: "online", health, at: Date.now() }}
      onRetryConnection={() => {}}
      isAdmin={isAdmin}
      polling={false}
    />,
  );
}

it("offers no selection at all to a non-admin", async () => {
  mockApi({ status: 200, body: {} });
  renderDocuments(false);

  await screen.findByText("SAES-A-105.pdf");
  expect(screen.queryByLabelText("Select SAES-A-105.pdf")).not.toBeInTheDocument();
  // And the bar cannot appear, because there is nothing to select with.
  expect(screen.queryByLabelText("Role to apply")).not.toBeInTheDocument();
});

it("sets the role on the documents an admin selected", async () => {
  const posted = mockApi({
    status: 200,
    body: {
      document_role: "COMPANY_STANDARD", requested: 2,
      updated: ["d1", "d2"], unchanged: [], failed: [],
    },
  });
  renderDocuments(true);

  await screen.findByText("SAES-A-105.pdf");
  fireEvent.click(screen.getByLabelText("Select SAES-A-105.pdf"));
  fireEvent.click(screen.getByLabelText("Select SAES-B-005.pdf"));
  fireEvent.change(screen.getByLabelText("Role to apply"), {
    target: { value: "COMPANY_STANDARD" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Apply to 2/ }));

  await waitFor(() => expect(posted).toHaveLength(1));
  // THE BODY, not just the fact that a request happened. The notice on screen
  // is built from the response, so it would read correctly even if this sent
  // the wrong ids or no ids at all.
  expect(posted[0]).toEqual({
    document_ids: ["d1", "d2"],
    document_role: "COMPANY_STANDARD",
  });
  expect(await screen.findByText(/2 set to Company standard/)).toBeInTheDocument();
});

it("says which documents were not updated when only some were", async () => {
  mockApi({
    status: 207,
    body: {
      document_role: "COMPANY_STANDARD", requested: 2,
      updated: ["d1"], unchanged: [],
      failed: [{ document_id: "d2", reason: "not_found" }],
    },
  });
  renderDocuments(true);

  await screen.findByText("SAES-A-105.pdf");
  fireEvent.click(screen.getByLabelText("Select SAES-A-105.pdf"));
  fireEvent.click(screen.getByLabelText("Select SAES-B-005.pdf"));
  fireEvent.change(screen.getByLabelText("Role to apply"), {
    target: { value: "COMPANY_STANDARD" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Apply to 2/ }));

  // 207 is a 2xx, so `result.ok` is true and a screen that trusted it would
  // report unqualified success. The failure has to be read out of the body.
  expect(
    await screen.findByText(/1 could not be updated and were left unchanged/),
  ).toBeInTheDocument();
  // The one that failed STAYS selected, so the person can see which and retry
  // rather than rebuilding a selection the screen silently discarded.
  await waitFor(() =>
    expect((screen.getByLabelText("Select SAES-B-005.pdf") as HTMLInputElement).checked)
      .toBe(true));
  expect((screen.getByLabelText("Select SAES-A-105.pdf") as HTMLInputElement).checked)
    .toBe(false);
});

it("cannot apply an empty role", async () => {
  const posted = mockApi({ status: 200, body: {} });
  renderDocuments(true);

  await screen.findByText("SAES-A-105.pdf");
  fireEvent.click(screen.getByLabelText("Select SAES-A-105.pdf"));

  // The button exists and is disabled. An "apply" that sent the empty option
  // would be a request to CLEAR the role on everything selected, one click
  // away from a person who simply had not chosen yet.
  const apply = screen.getByRole("button", { name: /Apply to 1/ });
  expect(apply).toBeDisabled();
  fireEvent.click(apply);
  expect(posted).toHaveLength(0);
});
