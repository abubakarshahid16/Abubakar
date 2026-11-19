import { useEffect, useState } from "react";

import { technicalQueriesApi, type Result, type TechnicalQuery } from "../api/client";

export function TechnicalQueriesView({ queryId }: { queryId?: string }) {
  const [items, setItems] = useState<TechnicalQuery[]>([]);
  const [selected, setSelected] = useState<TechnicalQuery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act = (action: () => Promise<Result<TechnicalQuery>>) => {
    if (!selected) return;
    setBusy(true);
    void action().then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error?.message || "The action could not be completed."); return; }
      if (result.data) { setSelected(result.data); setItems((current) => current.map((item) => item.id === result.data?.id ? result.data : item)); }
    });
  };

  useEffect(() => {
    let alive = true;
    void technicalQueriesApi.list().then((result) => {
      if (!alive) return;
      if (!result.ok) { setError(result.error.message); return; }
      setItems(result.data.items);
      const first = queryId ? result.data.items.find((item) => item.id === queryId) : result.data.items[0];
      if (first) void technicalQueriesApi.get(first.id).then((detail) => { if (alive && detail.ok) setSelected(detail.data); });
    });
    return () => { alive = false; };
  }, [queryId]);

  return (
    <main className="mx-auto grid w-full max-w-7xl gap-5 px-4 py-6 lg:grid-cols-[20rem_1fr]" aria-labelledby="technical-queries-title">
      <section>
        <h1 id="technical-queries-title" className="text-xl font-semibold text-slateish-100">Technical Queries</h1>
        <p className="mt-1 text-sm text-slateish-400">Incoming questions, evidence and engineer decisions.</p>
        {error && <p role="alert" className="mt-4 text-sm text-danger-400">{error}</p>}
        <div className="mt-5 space-y-2" aria-label="Technical query queue">
          {items.length === 0 && <p className="text-sm text-slateish-500">No technical queries have been imported.</p>}
          {items.map((item) => (
            <button key={item.id} type="button" onClick={() => void technicalQueriesApi.get(item.id).then((detail) => { if (detail.ok) setSelected(detail.data); })} className={`w-full rounded border p-3 text-left ${selected?.id === item.id ? "border-signal-500 bg-ink-800" : "border-ink-700 bg-ink-850"}`}>
              <span className="block text-sm font-medium text-slateish-100">{item.subject}</span>
              <span className="mt-1 block text-xs text-slateish-400">{item.contractor_name || "Unknown contractor"} · {item.status}</span>
            </button>
          ))}
        </div>
      </section>
      <section className="rounded border border-ink-700 bg-ink-850 p-5">
        {!selected ? <p className="text-sm text-slateish-500">Select a query to inspect its original message and review history.</p> : <>
          <h2 className="text-lg font-semibold text-slateish-100">{selected.subject}</h2>
          <p className="mt-1 text-xs uppercase tracking-wide text-slateish-500">{selected.status} · {selected.priority}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.prepareEvidence(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Prepare evidence</button>
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id))} className="rounded bg-signal-700 px-3 py-1.5 text-xs text-white disabled:opacity-50">Generate draft</button>
            {selected.status === "awaiting_review" && <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.decide(selected.id, "approve", selected.drafts?.at(-1)?.id))} className="rounded bg-signal-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">Approve</button>}
            {selected.status === "sent" || selected.status === "awaiting_confirmation" ? <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.confirmResolution(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Confirm resolved</button> : null}
            {selected.drafts?.length ? <a className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200" href={`/api/technical-queries/${selected.id}/response.docx`}>Download Word response</a> : null}
          </div>
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Question</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.extracted_question || "Not extracted yet."}</p>
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Evidence</h3>
          {selected.evidence?.length ? selected.evidence.map((evidence) => <blockquote key={evidence.document_id + evidence.exact_quote} className="mt-2 border-l-2 border-signal-500 pl-3 text-sm text-slateish-300">{evidence.exact_quote}<footer className="mt-1 text-xs text-slateish-500">{evidence.document_id} · page {evidence.page_start ?? "not recorded"}</footer></blockquote>) : <p className="mt-2 text-sm text-warn-400">No verified evidence attached.</p>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Review history</h3>
          {selected.decisions?.length ? selected.decisions.map((decision) => <p key={decision.created_at} className="mt-2 text-sm text-slateish-300">{decision.decision}: {decision.comment || "No comment"}</p>) : <p className="mt-2 text-sm text-slateish-500">No engineer decision yet.</p>}
        </>}
      </section>
    </main>
  );
}
