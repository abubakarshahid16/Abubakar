import { useEffect, useState } from "react";

import { technicalQueriesApi, type GmailLabel, type Result, type TechnicalQuery, type TechnicalQueryAssignee, type TechnicalQueryMailbox } from "../api/client";

function draftCitations(raw: string | undefined): Array<{ label: string; document_id: string; page: number; exact_quote: string }> {
  try {
    const value: unknown = JSON.parse(raw || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function TechnicalQueriesView({ queryId }: { queryId?: string }) {
  const [items, setItems] = useState<TechnicalQuery[]>([]);
  const [selected, setSelected] = useState<TechnicalQuery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editedAnswer, setEditedAnswer] = useState("");
  const [contractorFilter, setContractorFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [triageContractor, setTriageContractor] = useState("");
  const [triageDepartment, setTriageDepartment] = useState("");
  const [triagePriority, setTriagePriority] = useState("normal");
  const [triageDue, setTriageDue] = useState("");
  const [visibleTotal, setVisibleTotal] = useState<number | null>(null);
  const [mailboxes, setMailboxes] = useState<TechnicalQueryMailbox[]>([]);
  const [assignees, setAssignees] = useState<TechnicalQueryAssignee[]>([]);
  const [chosenAssignee, setChosenAssignee] = useState("");
  const [mailboxId, setMailboxId] = useState("");
  const [sendKey, setSendKey] = useState(() => crypto.randomUUID());
  const [labels, setLabels] = useState<GmailLabel[]>([]);
  const [labelId, setLabelId] = useState("");
  const activeMailboxes = mailboxes.filter((mailbox) => mailbox.connection_state === "active");
  const pendingMailbox = mailboxes.find((mailbox) => mailbox.connection_state === "needs_label");

  useEffect(() => {
    setTriageContractor(selected?.contractor_name || "");
    setTriageDepartment(selected?.department || "");
    setTriagePriority(selected?.priority || "normal");
    setTriageDue(selected?.due_at?.slice(0, 10) || "");
    setChosenAssignee(selected?.assignee_user_id || "");
  }, [selected?.id, selected?.contractor_name, selected?.department, selected?.priority, selected?.due_at, selected?.assignee_user_id]);

  const sendApproved = () => {
    if (!selected || !selected.drafts?.length || !mailboxId) return;
    if (!window.confirm("Send the approved response and Word file to the original email sender?")) return;
    setBusy(true);
    void technicalQueriesApi.send(selected.id, selected.drafts.at(-1)!.id, mailboxId, sendKey).then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error.message); return; }
      setSelected(result.data.item);
      setItems((current) => current.map((item) => item.id === result.data.item.id ? result.data.item : item));
      setSendKey(crypto.randomUUID());
    });
  };

  const applyFilters = () => {
    const common = { contractor: contractorFilter.trim(), department: departmentFilter.trim() };
    void technicalQueriesApi.list({ ...common, status: statusFilter }).then((result) => {
      if (!result.ok) { setError(result.error.message); return; }
      setItems(result.data.items);
      if (selected && !result.data.items.some((item) => item.id === selected.id)) setSelected(null);
    });
    void technicalQueriesApi.metrics(common).then((result) => {
      if (result.ok) setVisibleTotal(result.data.total);
    });
  };

  const act = (action: () => Promise<Result<TechnicalQuery>>) => {
    if (!selected) return;
    setBusy(true);
    void action().then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error?.message || "The action could not be completed."); return; }
      if (result.data) { setSelected(result.data); setEditedAnswer(result.data.drafts?.at(-1)?.answer || ""); setItems((current) => current.map((item) => item.id === result.data?.id ? result.data : item)); }
    });
  };

  useEffect(() => {
    let alive = true;
    void technicalQueriesApi.list().then((result) => {
      if (!alive) return;
      if (!result.ok) { setError(result.error.message); return; }
      setItems(result.data.items);
      setVisibleTotal(result.data.items.length);
      const first = queryId ? result.data.items.find((item) => item.id === queryId) : result.data.items[0];
      if (first) void technicalQueriesApi.get(first.id).then((detail) => { if (alive && detail.ok) { setSelected(detail.data); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } });
    });
    void technicalQueriesApi.mailboxes().then((result) => {
      if (!alive || !result.ok) return;
      setMailboxes(result.data.items);
      setMailboxId(result.data.items.find((mailbox) => mailbox.connection_state === "active")?.id || "");
    });
    void technicalQueriesApi.assignees().then((result) => {
      if (alive && result.ok) setAssignees(result.data.items);
    });
    return () => { alive = false; };
  }, [queryId]);

  return (
    <main className="mx-auto grid w-full max-w-7xl gap-5 px-4 py-6 lg:grid-cols-[20rem_1fr]" aria-labelledby="technical-queries-title">
      <section>
        <h1 id="technical-queries-title" className="text-xl font-semibold text-slateish-100">Technical Queries</h1>
        <p className="mt-1 text-sm text-slateish-400">Incoming questions, evidence and engineer decisions.</p>
        <p className="mt-2 text-xs text-slateish-400">{visibleTotal === null ? "Loading queries" : `${items.length} matching · ${visibleTotal} in selected contractor and department`}</p>
        <div className="mt-4 space-y-2">
          <label className="block text-xs text-slateish-300" htmlFor="query-status-filter">Status</label>
          <select id="query-status-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100">
            <option value="">All statuses</option><option value="received">Received</option><option value="triage">Triage</option><option value="drafting">Drafting</option><option value="awaiting_review">Awaiting review</option><option value="changes_requested">Changes requested</option><option value="approved">Approved</option><option value="sent">Sent</option><option value="resolved">Resolved</option>
          </select>
          <label className="block text-xs text-slateish-300" htmlFor="query-contractor-filter">Contractor</label>
          <input id="query-contractor-filter" value={contractorFilter} onChange={(event) => setContractorFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
          <label className="block text-xs text-slateish-300" htmlFor="query-department-filter">Department</label>
          <input id="query-department-filter" value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
          <button type="button" onClick={applyFilters} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">Refresh and apply filters</button>
        </div>
        {pendingMailbox && <div className="mt-4 rounded border border-warn-600 p-3 text-xs text-slateish-200">
          <p>Gmail account {pendingMailbox.email} is connected but waiting for a dedicated technical-query label. Only messages under that label will be imported.</p>
          <button type="button" onClick={() => void technicalQueriesApi.gmailLabels(pendingMailbox.id).then((result) => { if (result.ok) { setLabels(result.data.items); setLabelId(result.data.items[0]?.id || ""); } else setError(result.error.message); })} className="mt-2 rounded bg-ink-700 px-2 py-1">Choose label</button>
          {labels.length > 0 && <div className="mt-2"><label htmlFor="gmail-query-label">Gmail label</label><select id="gmail-query-label" value={labelId} onChange={(event) => setLabelId(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2">{labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}</select><button type="button" disabled={busy || !labelId} onClick={() => { if (!window.confirm("Import existing messages under this label and begin automatic sync?")) return; setBusy(true); void technicalQueriesApi.activateGmailLabel(pendingMailbox.id, labelId).then((result) => { setBusy(false); if (!result.ok) { setError(result.error.message); return; } setMailboxes((current) => current.map((mailbox) => mailbox.id === pendingMailbox.id ? { ...mailbox, connection_state: "active", label_id: labelId } : mailbox)); setMailboxId(pendingMailbox.id); setLabels([]); void technicalQueriesApi.list().then((listed) => { if (listed.ok) setItems(listed.data.items); }); }); }} className="mt-2 rounded bg-signal-700 px-2 py-1 text-white disabled:opacity-50">Activate selected label</button></div>}
        </div>}
        {error && <p role="alert" className="mt-4 text-sm text-danger-400">{error}</p>}
        <div className="mt-5 space-y-2" aria-label="Technical query queue">
          {items.length === 0 && <p className="text-sm text-slateish-500">No technical queries have been imported.</p>}
          {items.map((item) => (
            <button key={item.id} type="button" onClick={() => void technicalQueriesApi.get(item.id).then((detail) => { if (detail.ok) { setSelected(detail.data); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } })} className={`w-full rounded border p-3 text-left ${selected?.id === item.id ? "border-signal-500 bg-ink-800" : "border-ink-700 bg-ink-850"}`}>
              <span className="block text-sm font-medium text-slateish-100">{item.subject}</span>
              <span className="mt-1 block text-xs text-slateish-400">{item.contractor_name || "Unknown contractor"} · {item.status}{item.assignee_user_id ? ` · assigned to ${item.assignee_user_id}` : " · unassigned"}</span>
            </button>
          ))}
        </div>
      </section>
      <section className="rounded border border-ink-700 bg-ink-850 p-5">
        {!selected ? <p className="text-sm text-slateish-500">Select a query to inspect its original message and review history.</p> : <>
          <h2 className="text-lg font-semibold text-slateish-100">{selected.subject}</h2>
          <p className="mt-1 text-xs uppercase tracking-wide text-slateish-500">{selected.status} · {selected.priority}</p>
          <div className="mt-4 grid gap-2 rounded border border-ink-700 p-3 sm:grid-cols-2" aria-label="Query routing">
            <label className="text-xs text-slateish-300">Contractor<input value={triageContractor} onChange={(event) => setTriageContractor(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            <label className="text-xs text-slateish-300">Department<input value={triageDepartment} onChange={(event) => setTriageDepartment(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            <label className="text-xs text-slateish-300">Priority<select value={triagePriority} onChange={(event) => setTriagePriority(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
            <label className="text-xs text-slateish-300">Due date<input type="date" value={triageDue} onChange={(event) => setTriageDue(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.triage(selected.id, { contractor_name: triageContractor.trim() || null, department: triageDepartment.trim() || null, priority: triagePriority, due_at: triageDue || null }))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Save routing</button>
            {assignees.length > 0 && <label className="text-xs text-slateish-300">Responsible person<select value={chosenAssignee} onChange={(event) => setChosenAssignee(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm"><option value="">Select a person</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label>}
            {assignees.length > 0 && <button type="button" disabled={busy || !chosenAssignee} onClick={() => act(() => technicalQueriesApi.assign(selected.id, chosenAssignee))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Assign person</button>}
          </div>
          {selected.source_access_revoked && <p role="alert" className="mt-3 text-sm text-warn-400">Access to a cited source changed. The draft is hidden until an authorised reviewer checks it again.</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.prepareEvidence(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Prepare evidence</button>
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id))} className="rounded bg-signal-700 px-3 py-1.5 text-xs text-white disabled:opacity-50">Generate draft</button>
            {selected.status === "awaiting_review" && <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.decide(selected.id, "approve", selected.drafts?.at(-1)?.id))} className="rounded bg-signal-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">Approve latest draft</button>}
            {selected.status === "awaiting_review" && <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.decide(selected.id, "request_changes", selected.drafts?.at(-1)?.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Request changes</button>}
            {selected.status === "approved" && activeMailboxes.length > 0 && <div className="flex items-center gap-2"><label htmlFor="query-send-mailbox" className="text-xs text-slateish-300">Send from</label><select id="query-send-mailbox" value={mailboxId} onChange={(event) => setMailboxId(event.target.value)} className="rounded border border-ink-600 bg-ink-900 p-1.5 text-xs text-slateish-100">{activeMailboxes.map((mailbox) => <option key={mailbox.id} value={mailbox.id}>{mailbox.email}</option>)}</select><button type="button" disabled={busy} onClick={sendApproved} className="rounded bg-signal-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">Send approved response</button></div>}
            {selected.status === "approved" && mailboxes.length === 0 && <button type="button" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Connect Gmail to send</button>}
            {selected.status === "sent" || selected.status === "awaiting_confirmation" ? <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.confirmResolution(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Confirm resolved</button> : null}
            {selected.drafts?.length ? <a className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200" href={`/api/technical-queries/${selected.id}/response.docx`}>Download Word response</a> : null}
          </div>
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Question</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.extracted_question || "Not extracted yet."}</p>
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Original email and attachments</h3>
          {selected.messages?.map((message, index) => <article key={`${message.received_at}-${index}`} className="mt-3 rounded border border-ink-700 p-3 text-sm text-slateish-300">
            <p>From: {message.from_address}</p><p>To: {message.to_addresses.join(", ")}</p>
            {message.cc_addresses.length > 0 && <p>CC: {message.cc_addresses.join(", ")}</p>}
            <p>Received: {message.received_at}</p>
            {message.raw_message_hash && <a className="mt-1 inline-block text-xs text-signal-300 underline" href={`/api/technical-queries/${encodeURIComponent(selected.id)}/messages/${encodeURIComponent(message.id)}/original.eml`}>Download original email</a>}
            <p className="mt-2 whitespace-pre-wrap">{message.body}</p>
            {message.attachments.length > 0 && <ul className="mt-2 list-disc pl-5">{message.attachments.map((attachment) => <li key={attachment.filename}>{attachment.document_id ? <a className="underline" href={`/api/documents/${encodeURIComponent(attachment.document_id)}/original`} target="_blank" rel="noreferrer">{attachment.filename}</a> : attachment.filename} ({attachment.size_bytes} bytes) · {attachment.document_id ? attachment.parse_status : "pending upload"} · scan: {attachment.scan_status.replaceAll("_", " ")}</li>)}</ul>}
          </article>)}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Evidence</h3>
          {selected.evidence?.length ? selected.evidence.map((evidence) => <blockquote key={evidence.id} className="mt-2 border-l-2 border-signal-500 pl-3 text-sm text-slateish-300">{evidence.exact_quote}<footer className="mt-1 text-xs text-slateish-500"><a className="underline" href={`/api/documents/${encodeURIComponent(evidence.document_id)}/original${evidence.page_start ? `#page=${evidence.page_start}` : ""}`} target="_blank" rel="noreferrer">Open source, page {evidence.page_start ?? "unknown"}</a> · {evidence.evidence_state} · {evidence.supersession_state}</footer></blockquote>) : <p className="mt-2 text-sm text-warn-400">No verified evidence attached.</p>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Proposed response</h3>
          {selected.drafts?.length ? <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.drafts.at(-1)?.answer}</p> : <p className="mt-2 text-sm text-slateish-500">No draft yet.</p>}
          {draftCitations(selected.drafts?.at(-1)?.citations_json).map((citation) => <p key={citation.label} className="mt-2 text-xs text-slateish-400">[{citation.label}] <a className="underline" href={`/api/documents/${encodeURIComponent(citation.document_id)}/original#page=${citation.page}`} target="_blank" rel="noreferrer">Source page {citation.page}</a>: {citation.exact_quote}</p>)}
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-3">
            <label htmlFor="technical-query-answer" className="block text-sm text-slateish-300">Write or revise the answer for engineer review</label>
            <textarea id="technical-query-answer" value={editedAnswer} onChange={(event) => setEditedAnswer(event.target.value)} rows={8} className="mt-2 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <button type="button" disabled={busy || !editedAnswer.trim()} onClick={() => act(() => technicalQueriesApi.createDraft(selected.id, editedAnswer.trim()))} className="mt-2 rounded bg-signal-700 px-3 py-1.5 text-xs text-white disabled:opacity-50">Submit draft for review</button>
          </div>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Review history</h3>
          {selected.decisions?.length ? selected.decisions.map((decision) => <p key={decision.created_at} className="mt-2 text-sm text-slateish-300">{decision.decision}: {decision.comment || "No comment"}</p>) : <p className="mt-2 text-sm text-slateish-500">No engineer decision yet.</p>}
        </>}
      </section>
    </main>
  );
}
