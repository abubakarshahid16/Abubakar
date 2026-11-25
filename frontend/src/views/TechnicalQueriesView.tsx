import { useEffect, useRef, useState } from "react";

import { technicalQueriesApi, type GmailLabel, type RoutingRule, type Result, type TechnicalQuery, type TechnicalQueryAssignee, type TechnicalQueryMailbox } from "../api/client";

function draftCitations(raw: string | undefined): Array<{ label: string; document_id: string; page: number; exact_quote: string }> {
  try {
    const value: unknown = JSON.parse(raw || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

const SCAN_LABELS: Record<string, string> = {
  static_check_clean: "static check found no active content (not an antivirus scan)",
  static_check_flagged: "static check found active content: its text is not used automatically",
  static_check_unreadable: "could not be checked",
  not_scanned: "not checked",
  pending: "not checked yet",
};

export function TechnicalQueriesView({ queryId }: { queryId?: string }) {
  const [items, setItems] = useState<TechnicalQuery[]>([]);
  const [selected, setSelected] = useState<TechnicalQuery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editedAnswer, setEditedAnswer] = useState("");
  const [questionDraft, setQuestionDraft] = useState("");
  const [contractorFilter, setContractorFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [fromFilter, setFromFilter] = useState("");
  const [toFilter, setToFilter] = useState("");
  const [evidenceFilter, setEvidenceFilter] = useState("");
  const [rules, setRules] = useState<RoutingRule[] | null>(null);
  const [ruleType, setRuleType] = useState<"address" | "domain">("domain");
  const [ruleValue, setRuleValue] = useState("");
  const [ruleContractor, setRuleContractor] = useState("");
  const [ruleDepartment, setRuleDepartment] = useState("");
  const [triageContractor, setTriageContractor] = useState("");
  const [triageDepartment, setTriageDepartment] = useState("");
  const [triagePriority, setTriagePriority] = useState("normal");
  const [triageDue, setTriageDue] = useState("");
  const [visibleTotal, setVisibleTotal] = useState<number | null>(null);
  const [mailboxes, setMailboxes] = useState<TechnicalQueryMailbox[]>([]);
  const [canManageGmail, setCanManageGmail] = useState(false);
  const [assignees, setAssignees] = useState<TechnicalQueryAssignee[]>([]);
  const [chosenAssignee, setChosenAssignee] = useState("");
  const [labels, setLabels] = useState<GmailLabel[]>([]);
  const [labelId, setLabelId] = useState("");
  const returnedOnce = useRef(false); // StrictMode runs an effect twice in development: the one-time code is posted once
  const [gmailReturn, setGmailReturn] = useState<"working" | "connected" | "admin_must_allow" | null>(null);
  const [engine, setEngine] = useState<"local" | "claude">("local");
  const [fileRole, setFileRole] = useState("SUPPORTING_DOCUMENT");
  const [claudeDocs, setClaudeDocs] = useState<string[]>([]);
  const [ticked, setTicked] = useState<number[]>([]);
  const [handOpen, setHandOpen] = useState(false);
  const [handSubject, setHandSubject] = useState("");
  const [handContractor, setHandContractor] = useState("");
  const [handBody, setHandBody] = useState("");
  const [handFiles, setHandFiles] = useState<File[]>([]);
  const pendingMailbox = mailboxes.find((mailbox) => mailbox.connection_state === "needs_label");

  useEffect(() => {
    // With model proposals the text starts as the email's own question; the engineer ticks the proposals that are real.
    const proposed = selected?.proposed_questions?.length ? selected?.extracted_question : selected?.proposed_question;
    setQuestionDraft(selected?.confirmed_question || proposed || selected?.extracted_question || "");
    setTicked([]);
  }, [selected?.id, selected?.confirmed_question, selected?.proposed_question, selected?.proposed_questions, selected?.extracted_question]);

  const addTicked = () => {
    const picked = (selected?.proposed_questions ?? []).filter((_, index) => ticked.includes(index)).map((part) => part.question);
    if (picked.length) setQuestionDraft((current) => [current.trim(), ...picked].filter(Boolean).join("\n"));
    setTicked([]);
  };

  const createByHand = () => {
    const form = new FormData();
    form.append("subject", handSubject.trim());
    form.append("body", handBody.trim());
    if (handContractor.trim()) form.append("contractor_name", handContractor.trim());
    handFiles.forEach((file) => form.append("files", file));
    setBusy(true);
    setError(null);
    void technicalQueriesApi.createByHand(form).then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error.message); return; }
      setItems((current) => [result.data.item, ...current]);
      setSelected(result.data.item);
      setHandOpen(false); setHandSubject(""); setHandContractor(""); setHandBody(""); setHandFiles([]);
    });
  };

  const confirmQuestion = () => act(async () => {
    const confirmed = await technicalQueriesApi.confirmQuestion(selected!.id, questionDraft.trim());
    if (!confirmed.ok) return confirmed;
    // Evidence is then found for the confirmed wording, not for the first proposal.
    const prepared = await technicalQueriesApi.prepareEvidence(selected!.id);
    return prepared.ok ? prepared : confirmed;
  });

  useEffect(() => {
    setTriageContractor(selected?.contractor_name || "");
    setTriageDepartment(selected?.department || "");
    setTriagePriority(selected?.priority || "normal");
    setTriageDue(selected?.due_at?.slice(0, 10) || "");
    setChosenAssignee(selected?.assignee_user_id || "");
  }, [selected?.id, selected?.contractor_name, selected?.department, selected?.priority, selected?.due_at, selected?.assignee_user_id]);

  const applyFilters = () => {
    const common = {
      contractor: contractorFilter.trim(), department: departmentFilter.trim(),
      assignee_user_id: assigneeFilter, received_from: fromFilter, received_to: toFilter, evidence_state: evidenceFilter,
    };
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
    setError(null);
    void action().then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error?.message || "The action could not be completed."); return; }
      if (result.data) { setSelected(result.data); setEditedAnswer(result.data.drafts?.at(-1)?.answer || ""); setItems((current) => current.map((item) => item.id === result.data?.id ? result.data : item)); }
    });
  };

  const jobState = selected?.evidence_job?.state;
  useEffect(() => {
    // The evidence is prepared by a background job: ask again every few seconds while it is queued or running, then show what it found.
    if (!selected || (jobState !== "queued" && jobState !== "running")) return;
    const id = selected.id;
    const timer = window.setInterval(() => {
      void technicalQueriesApi.get(id).then((detail) => {
        if (detail.ok) { setSelected((current) => (current?.id === id ? detail.data : current)); setItems((current) => current.map((item) => item.id === id ? { ...item, status: detail.data.status } : item)); }
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selected?.id, jobState]);

  useEffect(() => {
    // Google sends the person to /technicalQueries/gmail-return: read what it sent, clear it from the address bar at once, then post it on
    // from this same site (so the sign-in cookie goes with it).
    if (queryId !== "gmail-return" || returnedOnce.current) return;
    returnedOnce.current = true;
    const params = new URLSearchParams(window.location.search);
    const sent = { code: params.get("code"), state: params.get("state"), error: params.get("error") };
    window.history.replaceState(null, "", "/technicalQueries");
    setGmailReturn("working");
    void technicalQueriesApi.completeGmail(sent).then((result) => {
      if (!result.ok) { setGmailReturn(null); setError(result.error.message); return; }
      setGmailReturn(result.data.result);
      void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) { setCanManageGmail(true); setMailboxes(listed.data.items); } });
    });
  }, [queryId]);

  useEffect(() => {
    let alive = true;
    void technicalQueriesApi.list().then((result) => {
      if (!alive) return;
      if (!result.ok) { setError(result.error.message); return; }
      setItems(result.data.items);
      setVisibleTotal(result.data.items.length);
      const first = queryId && queryId !== "gmail-return" ? result.data.items.find((item) => item.id === queryId) : result.data.items[0];
      if (first) void technicalQueriesApi.get(first.id).then((detail) => { if (alive && detail.ok) { setSelected(detail.data); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } });
    });
    void technicalQueriesApi.mailboxes().then((result) => {
      if (!alive || !result.ok) return;
      setCanManageGmail(true);
      setMailboxes(result.data.items);
    });
    void technicalQueriesApi.assignees().then((result) => {
      if (alive && result.ok) setAssignees(result.data.items);
    });
    void technicalQueriesApi.routingRules().then((result) => {
      if (alive && result.ok) setRules(result.data.items);
    });
    return () => { alive = false; };
  }, [queryId]);

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5 px-4 py-6 lg:grid-cols-[20rem_1fr]" aria-labelledby="technical-queries-title" role="region">
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
          {assignees.length > 0 && <><label className="block text-xs text-slateish-300" htmlFor="query-responsible-filter">Responsible person</label>
          <select id="query-responsible-filter" value={assigneeFilter} onChange={(event) => setAssigneeFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100"><option value="">Anyone</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></>}
          <label className="block text-xs text-slateish-300" htmlFor="query-from-filter">Received from</label>
          <input id="query-from-filter" type="date" value={fromFilter} onChange={(event) => setFromFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
          <label className="block text-xs text-slateish-300" htmlFor="query-to-filter">Received to</label>
          <input id="query-to-filter" type="date" value={toFilter} onChange={(event) => setToFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
          <label className="block text-xs text-slateish-300" htmlFor="query-evidence-filter">Evidence</label>
          <select id="query-evidence-filter" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100"><option value="">Any</option><option value="verified">Verified</option><option value="needs_review">Needs review</option><option value="conflicting">Conflicting</option><option value="ambiguous">Ambiguous</option><option value="missing">Missing</option><option value="rejected">Rejected</option></select>
          <button type="button" onClick={applyFilters} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">Refresh and apply filters</button>
          {rules !== null && <details className="mt-4 rounded border border-ink-700 p-2 text-xs text-slateish-300"><summary className="cursor-pointer">Routing rules ({rules.length})</summary>
            <p className="mt-2 text-slateish-400">A match fills a blank contractor or department when an email arrives. A public mail domain cannot be routed; an exact address can.</p>
            <ul className="mt-2 space-y-1">{rules.map((rule) => <li key={rule.id} className="flex items-center justify-between gap-2"><span>{rule.match_type} {rule.match_value} → {rule.contractor_name || "—"} / {rule.department || "—"}</span><button type="button" onClick={() => void technicalQueriesApi.deleteRoutingRule(rule.id).then((result) => { if (result.ok) setRules(result.data.items); else setError(result.error.message); })} className="rounded bg-ink-700 px-2 py-1">Remove</button></li>)}</ul>
            <div className="mt-2 space-y-1">
              <select aria-label="Rule type" value={ruleType} onChange={(event) => setRuleType(event.target.value as "address" | "domain")} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5"><option value="domain">Company domain</option><option value="address">Exact address</option></select>
              <input aria-label="Rule value" value={ruleValue} onChange={(event) => setRuleValue(event.target.value)} placeholder={ruleType === "domain" ? "company.example" : "person@company.example"} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule contractor" value={ruleContractor} onChange={(event) => setRuleContractor(event.target.value)} placeholder="Contractor" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule department" value={ruleDepartment} onChange={(event) => setRuleDepartment(event.target.value)} placeholder="Department" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <button type="button" disabled={!ruleValue.trim()} onClick={() => { setError(null); void technicalQueriesApi.saveRoutingRule({ match_type: ruleType, match_value: ruleValue.trim(), contractor_name: ruleContractor.trim() || null, department: ruleDepartment.trim() || null }).then((result) => { if (result.ok) { setRules(result.data.items); setRuleValue(""); setRuleContractor(""); setRuleDepartment(""); } else setError(result.error.message); }); }} className="rounded bg-ink-700 px-2 py-1 disabled:opacity-50">Save rule</button>
            </div></details>}
        </div>
        {canManageGmail && mailboxes.length === 0 && <div className="mt-4 rounded border border-ink-700 p-3 text-xs text-slateish-200">
          <p>No Gmail mailbox is connected. Connect one to import technical queries from a selected label.</p>
          <button type="button" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })} className="mt-2 rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Connect Gmail</button>
        </div>}
        {pendingMailbox && <div className="mt-4 rounded border border-warn-500 p-3 text-xs text-slateish-200">
          <p>Gmail account {pendingMailbox.email} is connected but waiting for a dedicated technical-query label. Only messages under that label will be imported.</p>
          <button type="button" onClick={() => void technicalQueriesApi.gmailLabels(pendingMailbox.id).then((result) => { if (result.ok) { setLabels(result.data.items); setLabelId(result.data.items[0]?.id || ""); } else setError(result.error.message); })} className="mt-2 rounded bg-ink-700 px-2 py-1">Choose label</button>
          {labels.length > 0 && <div className="mt-2"><label htmlFor="gmail-query-label">Gmail label</label><select id="gmail-query-label" value={labelId} onChange={(event) => setLabelId(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2">{labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}</select><button type="button" disabled={busy || !labelId} onClick={() => { if (!window.confirm("Import existing messages under this label and begin automatic sync?")) return; setBusy(true); void technicalQueriesApi.activateGmailLabel(pendingMailbox.id, labelId).then((result) => { setBusy(false); if (!result.ok) { setError(result.error.message); return; } setMailboxes((current) => current.map((mailbox) => mailbox.id === pendingMailbox.id ? { ...mailbox, connection_state: "active", label_id: labelId } : mailbox)); setLabels([]); void technicalQueriesApi.list().then((listed) => { if (listed.ok) setItems(listed.data.items); }); }); }} className="mt-2 rounded bg-signal-500 px-2 py-1 text-white disabled:opacity-50">Activate selected label</button></div>}
        </div>}
        <div className="mt-4">
          <button type="button" onClick={() => setHandOpen((open) => !open)} aria-expanded={handOpen} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">New query by hand / upload</button>
          {handOpen && <div className="mt-2 space-y-1 rounded border border-ink-700 p-3 text-xs text-slateish-300" aria-label="New query by hand">
            <p className="text-slateish-400">For a query that did not come by email. Papers you upload are checked for active content like any emailed attachment.</p>
            <label className="block">Subject<input value={handSubject} onChange={(event) => setHandSubject(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Contractor<input value={handContractor} onChange={(event) => setHandContractor(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">The question, as asked<textarea value={handBody} onChange={(event) => setHandBody(event.target.value)} rows={4} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Papers (optional)<input type="file" multiple onChange={(event) => setHandFiles(Array.from(event.target.files ?? []))} className="mt-1 w-full" /></label>
            <button type="button" disabled={busy || !handSubject.trim() || !handBody.trim()} onClick={createByHand} className="rounded bg-signal-500 px-2 py-1 text-white disabled:opacity-50">Create query</button>
          </div>}
        </div>
        {gmailReturn === "admin_must_allow" && <p role="alert" className="mt-4 text-sm text-warn-500">Your company's Google admin must allow this app.</p>}
        {gmailReturn === "working" && <p role="status" className="mt-4 text-sm text-slateish-300">Finishing the Gmail connection.</p>}
        {gmailReturn === "connected" && <p role="status" className="mt-4 text-sm text-slateish-300">Gmail is connected. Choose the label to import below.</p>}
        {error && <p role="alert" className="mt-4 text-sm text-danger-500">{error}</p>}
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
            {selected.routing_source?.startsWith("rule:") && <p className="text-xs text-slateish-400">Contractor and department were filled from a routing rule. Save routing to confirm or change them.</p>}
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.triage(selected.id, { contractor_name: triageContractor.trim() || null, department: triageDepartment.trim() || null, priority: triagePriority, due_at: triageDue || null }))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Save routing</button>
            {assignees.length > 0 && <label className="text-xs text-slateish-300">Responsible person<select value={chosenAssignee} onChange={(event) => setChosenAssignee(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm"><option value="">Select a person</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label>}
            {assignees.length > 0 && <button type="button" disabled={busy || !chosenAssignee} onClick={() => act(() => technicalQueriesApi.assign(selected.id, chosenAssignee))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Assign person</button>}
          </div>
          {selected.source_access_revoked && <p role="alert" className="mt-3 text-sm text-warn-500">Access to a cited source changed. The draft is hidden until an authorised reviewer checks it again.</p>}
          {selected.can_review === false && <p className="mt-3 text-xs text-slateish-500">You can prepare evidence and write drafts. Confirming the question, deciding on evidence, approving and sending need the technical-query reviewer role.</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.prepareEvidence(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Prepare evidence</button>
            <label className="flex items-center gap-1 text-xs text-slateish-300">Written by
              <select value={engine} onChange={(event) => setEngine(event.target.value as "local" | "claude")} className="rounded border border-ink-600 bg-ink-900 p-1.5 text-xs text-slateish-100"><option value="local">Local model</option><option value="claude">Claude (the documents you choose go to Claude)</option></select></label>
            {engine === "claude" && <fieldset className="w-full rounded border border-ink-700 p-2 text-xs text-slateish-300" aria-label="Documents Claude may read for this query"><legend className="px-1">Contract documents Claude may read for this one query</legend>
              {[...new Set((selected.evidence ?? []).filter((e) => e.evidence_state === "verified").map((e) => e.document_id))].map((documentId) => <label key={documentId} className="mr-4 inline-flex items-center gap-1"><input type="checkbox" checked={claudeDocs.includes(documentId)} onChange={(event) => setClaudeDocs((current) => event.target.checked ? [...current, documentId] : current.filter((d) => d !== documentId))} />{documentId}</label>)}
              <p className="mt-1 text-slateish-400">Only the ticked documents and this query's question are sent. Choose none and nothing is sent.</p></fieldset>}
            <button type="button" disabled={busy || !selected.confirmed_question} title={selected.confirmed_question ? undefined : "Confirm the question first"} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id, engine, engine === "claude" ? claudeDocs : []))} className="rounded bg-signal-500 px-3 py-1.5 text-xs text-white disabled:opacity-50">Generate draft</button>
            {selected.status === "awaiting_review" && selected.can_review && <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.decide(selected.id, "approve", selected.drafts?.at(-1)?.id))} className="rounded bg-signal-500 px-3 py-1.5 text-xs text-white disabled:opacity-50">Approve latest draft</button>}
            {selected.status === "awaiting_review" && selected.can_review && <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.decide(selected.id, "request_changes", selected.drafts?.at(-1)?.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Request changes</button>}
            {selected.status === "approved" && <span className="text-xs text-warn-500">Sending is not approved by the owner: download the Word response, send it yourself, then confirm it resolved.</span>}
            {(selected.status === "approved" || selected.status === "sent" || selected.status === "awaiting_confirmation") && selected.can_review ? <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.confirmResolution(selected.id))} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Confirm resolved</button> : null}
            {selected.drafts?.length ? <a className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200" href={`/api/technical-queries/${selected.id}/response.docx`}>Download Word response</a> : null}
          </div>
          {selected.evidence_job && (selected.evidence_job.state === "queued" || selected.evidence_job.state === "running") && <p role="status" className="mt-3 text-xs text-slateish-300" data-testid="evidence-progress">Preparing the evidence: {selected.evidence_job.label ?? "queued"}{selected.evidence_job.progress_total > 0 ? ` (${selected.evidence_job.progress_done} of ${selected.evidence_job.progress_total})` : ""}. You can leave this page; it carries on.</p>}
          {selected.evidence_job?.state === "failed" && <p role="alert" className="mt-3 text-xs text-warn-500">The evidence could not be prepared: {selected.evidence_job.error}</p>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Question in the email</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.extracted_question || "Not stated in the email text."}</p>
          {selected.attachment_reading?.map((part) => <p key={part.filename} className="mt-6 text-xs text-slateish-400" data-testid="attachment-reading">{part.line}</p>)}
          {selected.attachment_text_hidden && <p className="mt-6 text-xs text-warn-500">The attachment text is hidden: you may not read that attachment.</p>}
          {selected.attachment_context?.length ? <>
            <h3 className="mt-6 text-sm font-semibold text-slateish-200">Attachment text</h3>
            {selected.attachment_context.map((part) => <div key={`${part.filename}-${part.page}`} className="mt-2 rounded border border-ink-700 p-2 text-sm text-slateish-300"><p className="text-xs text-slateish-500">{part.filename}, page {part.page}</p><p className="mt-1 whitespace-pre-wrap">{part.text}</p></div>)}
          </> : null}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Question for the draft</h3>
          {selected.confirmed_question
            ? <p className="mt-1 text-xs text-slateish-400">Confirmed by an engineer{selected.confirmed_question_at ? ` on ${selected.confirmed_question_at}` : ""}. The draft answers exactly this wording.</p>
            : <p className="mt-1 text-xs text-warn-500">{selected.proposed_question ? "Proposed by the system and not yet confirmed. Edit it, then confirm." : "Prepare evidence to get a proposed question, or write one."}</p>}
          {selected.proposal_note === "model_unavailable" && <p className="mt-1 text-xs text-warn-500">The local model was not available, so no questions were proposed from the attachment. Read the attachment text above and write the question.</p>}
          {!selected.confirmed_question && selected.proposed_questions?.length ? <div className="mt-2 rounded border border-ink-700 p-2" aria-label="Questions found in the attachment">
            <p className="text-xs text-slateish-400">Questions the model found in the attachment, each as printed. Tick the ones that are real questions, then add them.</p>
            {selected.proposed_questions.map((part, index) => <label key={`${part.filename}-${part.page}-${index}`} className="mt-1 flex items-start gap-2 text-sm text-slateish-300"><input type="checkbox" checked={ticked.includes(index)} onChange={(event) => setTicked((current) => event.target.checked ? [...current, index] : current.filter((i) => i !== index))} className="mt-1" /><span>{part.question}<span className="block text-xs text-slateish-500">{part.filename}, page {part.page}</span></span></label>)}
            <button type="button" disabled={!ticked.length} onClick={addTicked} className="mt-2 rounded bg-ink-700 px-2 py-1 text-xs text-slateish-100 disabled:opacity-50">Add ticked questions to the text</button>
          </div> : null}
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-2">
            <label htmlFor="technical-query-question" className="block text-xs text-slateish-300">Question the draft will answer</label>
            <textarea id="technical-query-question" value={questionDraft} onChange={(event) => setQuestionDraft(event.target.value)} rows={4} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <button type="button" disabled={busy || !selected.can_review || !questionDraft.trim() || questionDraft.trim() === (selected.confirmed_question || "")} title={selected.can_review ? undefined : "Only a qualified reviewer can confirm the question"} onClick={confirmQuestion} className="mt-2 rounded bg-signal-500 px-3 py-1.5 text-xs text-white disabled:opacity-50">Confirm question</button>
            {!selected.can_review && <p className="mt-1 text-xs text-slateish-500">Only a qualified reviewer can confirm the question.</p>}
          </div>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Original email and attachments</h3>
          {selected.messages?.map((message, index) => <article key={`${message.received_at}-${index}`} className="mt-3 rounded border border-ink-700 p-3 text-sm text-slateish-300">
            <p>From: {message.from_address}</p><p>To: {message.to_addresses.join(", ")}</p>
            {message.cc_addresses.length > 0 && <p>CC: {message.cc_addresses.join(", ")}</p>}
            <p>Received: {message.received_at}</p>
            {message.raw_message_hash && <a className="mt-1 inline-block text-xs text-signal-300 underline" href={`/api/technical-queries/${encodeURIComponent(selected.id)}/messages/${encodeURIComponent(message.id)}/original.eml`}>Download original email</a>}
            <p className="mt-2 whitespace-pre-wrap">{message.body}</p>
            {message.attachments.length > 0 && <ul className="mt-2 list-disc pl-5">{message.attachments.map((attachment) => <li key={attachment.filename}>{attachment.document_id ? <a className="underline" href={`/api/technical-queries/${encodeURIComponent(selected.id)}/attachments/${encodeURIComponent(attachment.id)}/original`} target="_blank" rel="noreferrer">{attachment.filename}</a> : attachment.filename} ({attachment.size_bytes} bytes) · {attachment.document_id ? attachment.parse_status : "pending upload"} · {SCAN_LABELS[attachment.scan_status] ?? attachment.scan_status.replaceAll("_", " ")}
              {attachment.document_id && !attachment.filed_at && <span data-testid="attachment-unfiled"> · kept out of the library: not found by search, Chat or the review list{selected.can_review ? <> <select aria-label="Role to file this attachment under" value={fileRole} onChange={(event) => setFileRole(event.target.value)} className="ml-1 rounded border border-ink-600 bg-ink-900 p-1 text-xs"><option value="SUPPORTING_DOCUMENT">Supporting document</option><option value="CONTRACTOR_SUBMITTAL">Contractor submittal</option><option value="SPECIFICATION">Specification</option><option value="CONTRACT_DOCUMENT">Contract document</option><option value="COMPANY_STANDARD">Company standard</option></select> <button type="button" disabled={busy} onClick={() => { if (!window.confirm("File this attachment into the library? It then appears in search, Chat and the review list under the chosen role.")) return; act(() => technicalQueriesApi.fileIntoLibrary(selected.id, attachment.id, fileRole)); }} className="ml-1 rounded bg-ink-700 px-2 py-0.5 text-xs text-slateish-100 disabled:opacity-50">File into the library</button></> : null}</span>}
            </li>)}</ul>}
          </article>)}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Evidence</h3>
          {selected.evidence_coverage && <p className="mt-1 text-xs text-slateish-400" data-testid="evidence-coverage">{selected.evidence_coverage.line}</p>}
          {selected.evidence?.length ? selected.evidence.map((evidence) => <blockquote key={evidence.id} className="mt-2 border-l-2 border-signal-500 pl-3 text-sm text-slateish-300">{evidence.exact_quote}<footer className="mt-1 text-xs text-slateish-500"><a className="underline" href={`/api/documents/${encodeURIComponent(evidence.document_id)}/original${evidence.page_start ? `#page=${evidence.page_start}` : ""}`} target="_blank" rel="noreferrer">Open source, page {evidence.page_start ?? "unknown"}</a> · {evidence.evidence_state === "needs_review" ? "needs review" : evidence.evidence_state === "proposed" ? "found by the system, not yet kept" : evidence.evidence_state} · {evidence.supersession_state}</footer>
            {(evidence.evidence_state === "needs_review" || evidence.evidence_state === "proposed") && <div className="mt-2 text-xs text-warn-500"><p>{evidence.evidence_state === "proposed" ? "Found by the system; the words are checked to stand on that page, but nobody has judged that they answer the question. A reviewer keeps it as evidence or rejects it before a draft uses it or the response is approved." : "This passage comes from a contractor's attachment. A reviewer must decide before the response is approved or sent."}</p>
              {selected.can_review ? <div className="mt-1 flex gap-2"><button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected.id, evidence.id, "verified", evidence.supersession_state))} className="rounded bg-ink-700 px-2 py-1 text-slateish-100 disabled:opacity-50">Keep as evidence</button><button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected.id, evidence.id, "rejected", evidence.supersession_state))} className="rounded bg-ink-700 px-2 py-1 text-slateish-100 disabled:opacity-50">Reject</button></div> : <p className="mt-1">Only a qualified reviewer can decide.</p>}</div>}
          </blockquote>) : <p className="mt-2 text-sm text-warn-500">No verified evidence attached.</p>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Proposed response{selected.status !== "approved" && selected.drafts?.length ? <span className="ml-2 rounded border border-warn-500 px-2 py-0.5 text-xs font-normal text-warn-500">AI, to be checked</span> : null}</h3>
          {selected.drafts?.length ? <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.drafts.at(-1)?.answer}</p> : <p className="mt-2 text-sm text-slateish-500">No draft yet.</p>}
          {draftCitations(selected.drafts?.at(-1)?.citations_json).map((citation) => <p key={citation.label} className="mt-2 text-xs text-slateish-400">[{citation.label}] <a className="underline" href={`/api/documents/${encodeURIComponent(citation.document_id)}/original#page=${citation.page}`} target="_blank" rel="noreferrer">Source page {citation.page}</a>: {citation.exact_quote}</p>)}
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-3">
            <label htmlFor="technical-query-answer" className="block text-sm text-slateish-300">Write or revise the answer for engineer review</label>
            <textarea id="technical-query-answer" value={editedAnswer} onChange={(event) => setEditedAnswer(event.target.value)} rows={8} className="mt-2 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <button type="button" disabled={busy || !editedAnswer.trim()} onClick={() => act(() => technicalQueriesApi.createDraft(selected.id, editedAnswer.trim()))} className="mt-2 rounded bg-signal-500 px-3 py-1.5 text-xs text-white disabled:opacity-50">Submit draft for review</button>
          </div>}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Review history</h3>
          {selected.decisions?.length ? selected.decisions.map((decision) => <p key={decision.created_at} className="mt-2 text-sm text-slateish-300">{decision.decision}: {decision.comment || "No comment"}</p>) : <p className="mt-2 text-sm text-slateish-500">No engineer decision yet.</p>}
        </>}
      </section>
    </div>
  );
}
