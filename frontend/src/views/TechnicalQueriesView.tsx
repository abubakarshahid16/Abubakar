import { InfoFold } from "../components/look/LookParts";
import { LIST_FOUND, groupByItem, matchWords, replyBeingRewritten, countLine, mailboxChip, problemChips, queryTag, quickMatch, statusChip, type QuickView, askWords, boldSplit, decisionFor, fromSubjectHint, historyWords, markedPieces, shortQuote, wordReplyWhyNot, plainMark, citedSplit, currentSources, draftAuthor, honestMarks, plainStatus, queryHeadline, querySteps, sharedSource, notInText, readableLines, readyLine, staleSources, startingText, withRequest } from "./technicalQueryQuestion";
import { classification } from "../api/client";
import { confirmBody } from "../components/classification/metadataBody";
import { useEffect, useRef, useState } from "react";

import { formatWhen } from "../format/when";
import { attachmentsRead, importDoneWords, isInlinePicture, notReadWhy, peopleLine, prepareAllWords, proposalNoteWords, type PrepareAll } from "../api/technicalQueries";
import { technicalQueriesApi, type GmailLabel, type RoutingRule, type RoutingRuleType, type Result, type TechnicalQuery, type TechnicalQueryAssignee, type TechnicalQueryMailbox } from "../api/client";

function draftCitations(raw: string | undefined): Array<{ label: string; document_id: string; page: number; exact_quote: string }> {
  try {
    const value: unknown = JSON.parse(raw || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

/** The routing rules, the codes in the document number first (lead-4, 26 Nov 2026); a domain or address is the fallback. */
const RULE_WORDS: Record<RoutingRuleType, string> = {
  contractor_code: "Contractor code in the number",
  discipline: "Discipline code",
  domain: "Company domain",
  address: "Exact address",
};

const SCAN_LABELS: Record<string, string> = {
  static_check_clean: "static check found no active content (not an antivirus scan)",
  static_check_flagged: "static check found active content: its text is not used automatically",
  static_check_unreadable: "could not be checked",
  not_scanned: "not checked",
  pending: "not checked yet",
};

/** A mail's signature, legal notices and quoted earlier mail, folded behind "show" (the server decides the cut; the full text stays stored). */
function Folded({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <details className="mt-1 text-xs text-slateish-500" data-testid="mail-folded">
      <summary className="cursor-pointer">show signature, notices and earlier mail</summary>
      <p className="mt-1 whitespace-pre-wrap">{text}</p>
    </details>
  );
}

/** How many found questions start in the question box; the rest are folded under "N more found", to be ticked (lead-4, 26 Nov 2026). */
export const BOX_FOUND = 6;

/** A source passage, short: about three lines with the ask's words marked, and the whole passage one click away (never cut unmarked). */
function Quote({ text, words }: { text: string; words: string[] }) {
  const { short, cut } = shortQuote(text);
  const pieces = (t: string) => markedPieces(t, words).map((p, i) => p.hit ? <strong key={i} data-testid="quote-mark" className="font-semibold text-slateish-100 underline decoration-signal-500 decoration-2 underline-offset-2">{p.text}</strong> : <span key={i}>{p.text}</span>);
  return <>
    <p data-testid="quote-short" className="text-slateish-300">{pieces(short)}{cut && <span aria-label="the quote goes on">{" \u2026"}</span>}</p>
    {cut && <details data-testid="quote-full" className="mt-1"><summary className="cursor-pointer text-xs font-semibold text-signal-300">Show the whole quote</summary><p className="mt-1 whitespace-pre-wrap text-slateish-300">{pieces(text)}</p></details>}
  </>;
}

/** What "Confirm source document" does, in one line beside it (owner's live walk, 27 Nov 2026, via lead-4). */
export const CONFIRM_SOURCE_HINT = "Marks this paper's details as checked by an engineer, so its quotes can be used in a draft. Check it is the current revision first.";

/** A source link's own words: the document's name (and kind) and the place, never only "page N" beside a raw address (owner, 27 Nov 2026).
 *  A source with no recorded name keeps "Open source". */
export function sourceLinkLabel(name?: string | null, kind?: string | null): string {
  return name || kind ? `${name || "Unnamed document"}${kind ? ` (${kind})` : ""}` : "Open source";
}

export function TechnicalQueriesView({ queryId, isAdmin = false }: { queryId?: string; isAdmin?: boolean }) {
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
  const [ruleType, setRuleType] = useState<RoutingRuleType>("contractor_code");
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
  /** The mailbox chip's panel (address, import counts, the import buttons) and the count line's quick filter (owner, 27 Nov 2026). */
  const [mailboxOpen, setMailboxOpen] = useState(false);
  const [quick, setQuick] = useState<QuickView | null>(null);
  const [assignees, setAssignees] = useState<TechnicalQueryAssignee[]>([]);
  const [chosenAssignee, setChosenAssignee] = useState("");
  const [labels, setLabels] = useState<GmailLabel[]>([]);
  const [labelId, setLabelId] = useState("");
  const returnedOnce = useRef(false); // StrictMode runs an effect twice in development: the one-time code is posted once
  const [gmailReturn, setGmailReturn] = useState<"working" | "connected" | "admin_must_allow" | null>(null);
  const [engine, setEngine] = useState<"local" | "claude">("local");
  /** "Send back with a note": the note box is open, and what it says. */
  const [sendingBack, setSendingBack] = useState(false);
  const [backNote, setBackNote] = useState("");
  const [fileRole, setFileRole] = useState("SUPPORTING_DOCUMENT");
  // IN-PAGE confirmation (house rule: never the browser's own confirm box)
  const [confirming, setConfirming] = useState<null | { kind: "activate" } | { kind: "file"; attachmentId: string } | { kind: "again"; mailboxId: string }>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [disciplineFilter, setDisciplineFilter] = useState("");
  const [numberFilter, setNumberFilter] = useState("");
  const [needsPersonFilter, setNeedsPersonFilter] = useState(false);
  const [claudeDocs, setClaudeDocs] = useState<string[]>([]);
  const [editingQuestion, setEditingQuestion] = useState(false);
  const [handOpen, setHandOpen] = useState(false);
  const [handSubject, setHandSubject] = useState("");
  const [handContractor, setHandContractor] = useState("");
  const [handBody, setHandBody] = useState("");
  const [handFiles, setHandFiles] = useState<File[]>([]);
  const pendingMailbox = mailboxes.find((mailbox) => mailbox.connection_state === "needs_label");
  const [prepareAll, setPrepareAll] = useState<null | { plan: PrepareAll; asking: boolean }>(null);
  const [filtersOpen, setFiltersOpen] = useState(false); // the filters are folded by default: the mailbox and the list come first
  const activeFilters = [statusFilter, contractorFilter.trim(), departmentFilter.trim(), assigneeFilter, fromFilter, toFilter, evidenceFilter, typeFilter, disciplineFilter.trim(), numberFilter.trim()].filter(Boolean).length + (needsPersonFilter ? 1 : 0);
  const topRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  // On a narrow window the detail sits below the list: a click on a query brings it into view (otherwise the click seems to do nothing).
  const showDetail = () => {
    if (typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1023px)").matches) detailRef.current?.scrollIntoView?.({ block: "start" });
  };

  useEffect(() => {
    // The page always opens at its top (the shared scroll area can arrive halfway down from the page before).
    topRef.current?.scrollIntoView?.({ block: "start" }); // scrolls every scrollable parent, the shared page area included
  }, []);

  useEffect(() => {
    // With model proposals the text starts as the email's own question AND every question found in the attachment (owner, 26 Nov 2026:
    // the questions found on a form were listed but never placed in the box, which opened empty). Still a proposal: the engineer deletes
    // what is not a real question and confirms; nothing is confirmed by itself.
    // the readable ask (owner, 26 Nov 2026 21:29): a lead-in and the requests found on the form, numbered (technicalQueryQuestion)
    setQuestionDraft(selected ? startingText(selected) : "");
    setEditingQuestion(false);
  }, [selected?.id, selected?.confirmed_question, selected?.proposed_question, selected?.proposed_questions, selected?.extracted_question, selected?.extracted_question_main]);

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
    // a server that reports `ready` finds the sources again by itself when the wording changed (builder A); an older one is asked
    if (confirmed.data.ready) return confirmed;
    const prepared = await technicalQueriesApi.prepareEvidence(selected!.id);
    return prepared.ok ? prepared : confirmed;
  });
  /** KEEP THE CITED, REJECT THE OTHERS (lead-4, 26 Nov 2026): the same calls as each source's own Keep and Reject, one per source, then
   *  the query read again; what was done is said on the page and every source stays changeable before Approve. */
  const [bulkNote, setBulkNote] = useState<{ queryId: string; kept: number; rejected: number } | null>(null);
  const keepCited = () => {
    const split = citedSplit(selected?.evidence, selected?.drafts?.at(-1)?.citations_json);
    const id = selected!.id;
    act(async () => {
      for (const e of split.keep) {
        const r = await technicalQueriesApi.classifyEvidence(id, e.id, "verified", e.supersession_state);
        if (!r.ok) return r;
      }
      for (const e of split.reject) {
        const r = await technicalQueriesApi.classifyEvidence(id, e.id, "rejected", e.supersession_state);
        if (!r.ok) return r;
      }
      setBulkNote({ queryId: id, kept: split.keep.length, rejected: split.reject.length });
      return technicalQueriesApi.get(id);
    });
  };
  /** APPROVE ONCE (owner, 26 Nov 2026 22:41; lead-4's keep-cited decision): the cited sources kept and the others for this question
   *  rejected (the same calls as their own buttons, said on the page before the press), then the reply approved. */
  const approveOnce = () => {
    const split = citedSplit(selected?.evidence, selected?.drafts?.at(-1)?.citations_json);
    const id = selected!.id;
    const draftId = selected?.drafts?.at(-1)?.id;
    act(async () => {
      for (const e of split.keep) { const r = await technicalQueriesApi.classifyEvidence(id, e.id, "verified", e.supersession_state); if (!r.ok) return r; }
      for (const e of split.reject) { const r = await technicalQueriesApi.classifyEvidence(id, e.id, "rejected", e.supersession_state); if (!r.ok) return r; }
      if (split.keep.length + split.reject.length) setBulkNote({ queryId: id, kept: split.keep.length, rejected: split.reject.length });
      return technicalQueriesApi.decide(id, "approve", draftId);
    });
  };
  /** Save the wording without confirming it: the sources and a draft follow by themselves (builder A's POST /question). */
  const saveQuestion = () => act(() => technicalQueriesApi.saveQuestion(selected!.id, questionDraft.trim()));
  /** WHO HANDLES IT, one Save (owner, 27 Nov 2026 00:02: two buttons for one job): the routing fields, then the person when it changed. */
  const saveWho = () => {
    const id = selected!.id;
    const person = chosenAssignee;
    const changed = Boolean(person) && person !== (selected!.assignee_user_id || "");
    act(async () => {
      const saved = await technicalQueriesApi.triage(id, { contractor_name: triageContractor.trim() || null, department: triageDepartment.trim() || null, priority: triagePriority, due_at: triageDue || null });
      if (!saved.ok || !changed) return saved;
      return technicalQueriesApi.assign(id, person);
    });
  };

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
    void technicalQueriesApi.list({
      ...common, status: statusFilter, ref_type: typeFilter, discipline: disciplineFilter.trim(), number: numberFilter.trim(), needs_person: needsPersonFilter || undefined,
    }).then((result) => {
      if (!result.ok) { setError(result.error.message); return; }
      setItems(result.data.items);
      if (selected && !result.data.items.some((item) => item.id === selected.id)) setSelected(null);
    });
    void technicalQueriesApi.metrics(common).then((result) => {
      if (result.ok) setVisibleTotal(result.data.total);
    });
  };

  const refreshList = useRef(applyFilters);
  refreshList.current = applyFilters;
  const wasImporting = useRef(false);

  /** CONFIRM A SOURCE DOCUMENT IN PLACE (F's click count, 26 Nov 2026: a 5-click round trip to Documents per source): the same request as
   *  Documents, Details, Save metadata (metadataBody.confirmBody), with the values already recorded; the server's admin rule decides.
   *  The query is then read again, so every passage of that document shows its new standing. */
  const confirmSource = (documentId: string) => act(async () => {
    const record = await classification.ofDocument(documentId);
    if (!record.ok) return record;
    const saved = await classification.confirm(documentId, confirmBody(record.data) as never);
    if (!saved.ok) return saved;
    return technicalQueriesApi.get(selected!.id);
  });

  const questionMarks = selected ? [...new Set([...honestMarks(selected, questionDraft).question, ...(selected.ready?.marks ?? []).map(plainMark)])] : [];
  const searching = selected?.evidence_job?.state === "queued" || selected?.evidence_job?.state === "running";
  // the ask as shown differs from what the sources were found for (the confirmed wording, else the proposal)
  const questionEdited = Boolean(selected) && questionDraft.trim() !== (selected ? startingText(selected) : "").trim();

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

  const preparingAll = (prepareAll?.plan.waiting_or_running ?? 0) > 0 && !prepareAll?.asking;
  useEffect(() => {
    // a started round: how many are still waiting or running, every 5 s until none
    if (!preparingAll) return;
    const timer = window.setInterval(() => {
      void technicalQueriesApi.prepareAllPlan().then((result) => { if (result.ok) setPrepareAll({ plan: result.data, asking: false }); });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [preparingAll]);

  const importing = mailboxes.some((mailbox) => mailbox.import_job && (mailbox.import_job.state === "running" || (mailbox.import_job.state === "queued" && !mailbox.import_job.error)));
  useEffect(() => {
    // The mailbox import is a background job: ask again every few seconds while it is queued or running ("imported N of M", "last checked at").
    // The list below fills as messages arrive (and once more when the import ends), with the filters chosen.
    if (!importing) {
      if (wasImporting.current) refreshList.current();
      wasImporting.current = false;
      return;
    }
    wasImporting.current = true;
    const timer = window.setInterval(() => {
      void technicalQueriesApi.mailboxes().then((result) => { if (result.ok) setMailboxes(result.data.items); });
      refreshList.current();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [importing]);

  const jobState = selected?.evidence_job?.state;
  const refreshing = selected?.ready?.evidence === "refreshing" || selected?.ready?.draft === "refreshing";
  useEffect(() => {
    // The evidence (and now the draft) is prepared by a background job: ask again every few seconds while it is under way, then show it.
    if (!selected || (jobState !== "queued" && jobState !== "running" && !refreshing)) return;
    const id = selected.id;
    const timer = window.setInterval(() => {
      void technicalQueriesApi.get(id).then((detail) => {
        if (detail.ok) { setSelected((current) => (current?.id === id ? detail.data : current)); setItems((current) => current.map((item) => item.id === id ? { ...item, status: detail.data.status } : item)); }
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selected?.id, jobState, refreshing]);

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

  // the sources found for the wording the page works from first; ones found for an earlier wording folded (builder A's for_current_question)
  type EvidenceRow = NonNullable<TechnicalQuery["evidence"]>[number];
  const currentEvidence = (selected?.evidence ?? []).filter((e) => e.for_current_question !== false);
  const earlierEvidence = (selected?.evidence ?? []).filter((e) => e.for_current_question === false);
  const renderEvidence = (evidence: EvidenceRow) => <blockquote key={evidence.id} className="mt-2 border-l-2 border-signal-500 pl-3 text-sm text-slateish-300">{evidence.exact_quote}<footer className="mt-1 text-xs text-slateish-500"><a className={`underline ${evidence.locator ? "" : "whitespace-nowrap"}`} href={`/api/documents/${encodeURIComponent(evidence.document_id)}/original${evidence.page_start ? `#page=${evidence.page_start}` : ""}`} title={`Open ${evidence.source_name || "the source document"}, page ${evidence.page_start ?? "unknown"}`} target="_blank" rel="noreferrer">{evidence.source_name || evidence.source_kind ? <span data-testid="evidence-source">{sourceLinkLabel(evidence.source_name, evidence.source_kind)}</span> : sourceLinkLabel()}, {evidence.locator ? `${evidence.locator}, ` : ""}{`page\u00a0${evidence.page_start ?? "unknown"}`}</a>{matchWords(evidence) ? <> · <span data-testid="evidence-match" title={matchWords(evidence)!.counts}>{matchWords(evidence)!.words}</span></> : null} · {evidence.evidence_state === "needs_review" ? "needs review" : evidence.evidence_state === "proposed" ? "found by the system, not yet kept" : evidence.evidence_state} · {evidence.supersession_state}{evidence.supersession_state === "unknown" && ["verified", "proposed", "needs_review", "conflicting", "ambiguous"].includes(evidence.evidence_state) ? <span data-testid="evidence-needs-confirm" className="block text-warn-500">{evidence.evidence_state === "verified" ? (isAdmin ? "Counts for a draft once its source document is confirmed." : "Counts for a draft once its source document is confirmed: Documents, Details, Save metadata.") : (isAdmin ? "To count for a draft: keep it as evidence, and confirm its source document." : "To count for a draft: keep it as evidence, and confirm its source document (Documents, Details, Save metadata).")}{isAdmin && <><button type="button" data-testid="confirm-source" disabled={busy} onClick={() => confirmSource(evidence.document_id)} className="ml-2 rounded border border-ink-500 px-2 py-0.5 text-xs text-slateish-100 disabled:opacity-50">Confirm source document</button><span data-testid="confirm-source-hint" className="ml-2 text-slateish-400">{CONFIRM_SOURCE_HINT}</span></>}</span> : null}</footer>
              {(evidence.evidence_state === "needs_review" || evidence.evidence_state === "proposed") && <div className="mt-2 text-xs text-warn-500"><p>{evidence.evidence_state === "proposed" ? "Found by the system; the words are checked to stand on that page, but nobody has judged that they answer the question. A reviewer keeps it as evidence or rejects it before a draft uses it or the response is approved." : "This quote comes from a contractor's attachment. A reviewer must decide before the response is approved or sent."}</p>
                {selected!.can_review ? <div className="mt-1 flex gap-2"><button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected!.id, evidence.id, "verified", evidence.supersession_state))} className="rounded bg-ink-700 px-2 py-1 text-slateish-100 disabled:opacity-50">Keep as evidence</button><button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected!.id, evidence.id, "rejected", evidence.supersession_state))} className="rounded bg-ink-700 px-2 py-1 text-slateish-100 disabled:opacity-50">Reject</button></div> : <p className="mt-1">Only a qualified reviewer can decide.</p>}</div>}
            </blockquote>;

  const evidenceBlock = selected && (
    <>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-evidence">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">All sources found for this question ({currentEvidence.length}): keep or reject each</summary>
            {honestMarks(selected, questionDraft).evidence.map((mark) => <p key={mark} data-testid="evidence-mark" className="mt-1 text-xs text-warn-500">{mark}</p>)}
            {selected.evidence_coverage && <p className="mt-1 text-xs text-slateish-400" data-testid="evidence-coverage">{selected.evidence_coverage.line}</p>}
            {selected.evidence_coverage?.top_rerank_score != null && <p className="mt-1 text-xs text-slateish-400" data-testid="evidence-top-score">Best quote's relevance score (the search's own score, a number and not a verdict): {selected.evidence_coverage.top_rerank_score}.</p>}
            {/* BY REQUEST (builder A's search per numbered item, 27 Nov 2026): each request's sources under it, the rest "For the whole request" */}
            {currentEvidence.length ? groupByItem(currentEvidence, selected.ready?.items).map((group) => group.title === null
              ? group.rows.map((evidence) => renderEvidence(evidence))
              : <section key={group.title} data-testid="evidence-group" className="mt-3">
                  <h4 className="text-sm font-semibold text-slateish-200">{group.title} <span className="font-normal text-slateish-400">({group.rows.length} source{group.rows.length === 1 ? "" : "s"})</span></h4>
                  {group.rows.length ? group.rows.map((evidence) => renderEvidence(evidence)) : <p className="mt-1 text-xs text-warn-500">No source found for this request yet.</p>}
                </section>) : <p className="mt-2 text-sm text-warn-500">No verified evidence attached.</p>}
            {earlierEvidence.length > 0 && <details data-testid="evidence-earlier" className="mt-2"><summary className="cursor-pointer text-xs text-slateish-400">{earlierEvidence.length} source{earlierEvidence.length === 1 ? "" : "s"} found for an earlier wording of the question</summary>{earlierEvidence.map((evidence) => renderEvidence(evidence))}</details>}
          </details>
    </>
  );
  return (
    <div ref={topRef} className="mx-auto grid w-full min-w-0 gap-5 px-4 py-6 lg:grid-cols-[20rem_minmax(0,1fr)]" aria-labelledby="technical-queries-title" role="region">
      <section className="min-w-0 [overflow-wrap:anywhere]">
        <h1 id="technical-queries-title" className="text-xl font-semibold text-slateish-100">Technical Queries and CFCs</h1>
        {/* THE MAILBOX IN ONE CHIP (owner, 27 Nov 2026: "a manager never needs that arithmetic on the first screen"): the address, the
            import counts and the import buttons are one click away, in the chip's own panel */}
        {(() => {
          const chip = mailboxChip(mailboxes, canManageGmail);
          if (!chip) return null;
          return <div className="mt-2">
            <button type="button" data-testid="mailbox-chip" aria-expanded={mailboxOpen} aria-controls="mailbox-panel" onClick={() => setMailboxOpen((open) => !open)} className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs ${chip.tone === "ok" ? "border-ink-600 text-slateish-200" : chip.tone === "problem" ? "border-danger-500 text-danger-500" : "border-warn-500 text-warn-500"}`}><span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${chip.tone === "ok" ? "bg-signal-500" : chip.tone === "problem" ? "bg-danger-500" : "bg-warn-500"}`} />{chip.words}</button>
            {mailboxOpen && <div id="mailbox-panel" data-testid="mailbox-panel">
        {canManageGmail && mailboxes.length === 0 && <div className="mt-4 rounded border border-ink-700 p-3 text-xs text-slateish-200">
          <p>No Gmail mailbox is connected. Connect one to import technical queries from a selected label.</p>
          <button type="button" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })} className="mt-2 rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Connect Gmail</button>
        </div>}
        {pendingMailbox && <div className="mt-4 rounded border border-warn-500 p-3 text-xs text-slateish-200">
          <p>Gmail account {pendingMailbox.email} is connected but waiting for a dedicated technical-query label. Only messages under that label will be imported.</p>
          <button type="button" onClick={() => void technicalQueriesApi.gmailLabels(pendingMailbox.id).then((result) => { if (result.ok) { setLabels(result.data.items); setLabelId(result.data.items[0]?.id || ""); } else setError(result.error.message); })} className="mt-2 rounded bg-ink-700 px-2 py-1">Choose label</button>
          {labels.length > 0 && <div className="mt-2"><label htmlFor="gmail-query-label">Gmail label</label><select id="gmail-query-label" value={labelId} onChange={(event) => setLabelId(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2">{labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}</select><button type="button" disabled={busy || !labelId} onClick={() => setConfirming({ kind: "activate" })} className="mt-2 rounded bg-signal-500 px-2 py-1 text-white disabled:opacity-50">Activate selected label</button>
            {confirming?.kind === "activate" && <div role="alertdialog" aria-label="Confirm the label" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-activate">
              <p>Start importing the existing mail under this label, and keep checking it for new mail? The label is saved first; the import then runs in the background and you can leave this page.</p>
              <button type="button" disabled={busy} onClick={() => { setConfirming(null); setBusy(true); setError(null); void technicalQueriesApi.activateGmailLabel(pendingMailbox.id, labelId).then((result) => { setBusy(false); if (!result.ok) { setError(result.error.message); return; } setLabels([]); void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }} className="mt-1 mr-2 rounded bg-signal-500 px-2 py-1 text-white disabled:opacity-50">Yes, save and start the import</button>
              <button type="button" onClick={() => setConfirming(null)} className="mt-1 rounded bg-ink-700 px-2 py-1 text-slateish-100">Cancel</button>
            </div>}</div>}
        </div>}
        {mailboxes.filter((mailbox) => mailbox.connection_state === "error" || mailbox.connection_state === "revoked").map((mailbox) => <div key={mailbox.id} className="mt-4 rounded border border-warn-500 p-3 text-xs text-slateish-200" data-testid="mailbox-stopped">
          <p role="alert" className="text-warn-500">Mailbox {mailbox.email} is not being checked. {mailbox.status_note || "Connect it again."}</p>
          {mailbox.connection_state === "error" && <button type="button" disabled={busy} onClick={() => { setError(null); void technicalQueriesApi.checkNow(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }} className="mt-2 rounded bg-ink-700 px-3 py-1 text-slateish-100 disabled:opacity-50">Check now</button>}
          {canManageGmail && <button type="button" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })} className="mt-2 ml-2 rounded bg-ink-700 px-3 py-1 text-slateish-100 disabled:opacity-50">Connect Gmail again</button>}
        </div>)}
        {mailboxes.filter((mailbox) => mailbox.connection_state === "active").map((mailbox) => <div key={mailbox.id} className="mt-4 rounded border border-ink-700 p-3 text-xs text-slateish-200" data-testid="mailbox-status">
          <p>Mailbox {mailbox.email} is active. {mailbox.last_checked_at ? <>Last checked at <span data-testid="last-checked">{formatWhen(mailbox.last_checked_at)}</span>.</> : "Not checked yet."}</p>
          {mailbox.import_job && (mailbox.import_job.state === "running" || (mailbox.import_job.state === "queued" && !mailbox.import_job.error)) && <p role="status" data-testid="import-progress">{mailbox.import_job.kind === "poll" ? "Checking" : "Importing"}: read {mailbox.import_job.done} of {mailbox.import_job.total} messages, {mailbox.import_job.imported ?? mailbox.import_job.done} imported{mailbox.import_job.failed ? `, ${mailbox.import_job.failed} failed` : ""}. The list below fills as they arrive. You can leave this page; it carries on.</p>}
          {mailbox.import_job?.state === "done" && mailbox.import_job.kind === "import" && <p data-testid="import-done">{importDoneWords(mailbox.import_job)}</p>}
          {(mailbox.import_job?.state === "failed" || (mailbox.import_job?.state === "queued" && mailbox.import_job.error)) && <p role="alert" className="text-warn-500">{mailbox.import_job?.error}</p>}
          {mailbox.import_job && mailbox.import_job.failures.length > 0 && <ul className="mt-1 list-disc pl-5 text-warn-500" data-testid="import-failures">{mailbox.import_job.failures.map((failure, index) => <li key={index}>{failure.subject}: {failure.reason}</li>)}</ul>}
          <button type="button" disabled={busy || importing} onClick={() => { setError(null); void technicalQueriesApi.checkNow(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }} className="mt-2 rounded bg-ink-700 px-3 py-1 text-slateish-100 disabled:opacity-50">Check now</button>

          <button type="button" disabled={busy || importing} onClick={() => setConfirming({ kind: "again", mailboxId: mailbox.id })} className="mt-2 ml-2 rounded bg-ink-700 px-3 py-1 text-slateish-100 disabled:opacity-50">Import the label again</button>
          {confirming?.kind === "again" && confirming.mailboxId === mailbox.id && <div role="alertdialog" aria-label="Confirm importing the label again" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-import-again">
            <p>This reads all {mailbox.import_job?.total ? `${mailbox.import_job.total} ` : ""}messages of the label again and adds only what is not stored yet: messages, our own replies (to their query) and attachments not yet read. Nothing already stored is changed, and no query is made twice.</p>
            <button type="button" disabled={busy} onClick={() => { setConfirming(null); setError(null); void technicalQueriesApi.importAgain(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }} className="mt-1 mr-2 rounded bg-signal-500 px-2 py-1 text-white">Yes, read the label again</button>
            <button type="button" onClick={() => setConfirming(null)} className="mt-1 rounded bg-ink-700 px-2 py-1 text-slateish-100">Cancel</button>
          </div>}
        </div>)}
            </div>}
          </div>;
        })()}
        {gmailReturn === "admin_must_allow" && <p role="alert" className="mt-4 text-sm text-warn-500">Your company's Google admin must allow this app.</p>}
        {gmailReturn === "working" && <p role="status" className="mt-4 text-sm text-slateish-300">Finishing the Gmail connection.</p>}
        {gmailReturn === "connected" && !mailboxes.some((mailbox) => mailbox.connection_state === "active") && <p role="status" className="mt-4 text-sm text-slateish-300">Gmail is connected. Choose the label to import below.</p>}
        {error && <p role="alert" className="mt-4 text-sm text-danger-500">{error}</p>}
        {/* THE COUNT LINE IS A FILTER (owner, 27 Nov 2026): only the states that exist right now, each a click away */}
        {visibleTotal === null ? <p className="mt-3 text-sm text-slateish-400">Loading queries</p> : (() => {
          const line = countLine(items);
          return <p data-testid="count-line" className="mt-3 text-sm text-slateish-300"><span className="font-semibold text-slateish-100">{line.total} quer{line.total === 1 ? "y" : "ies"}{activeFilters > 0 ? " match the filters" : ""}</span>{line.parts.length ? ": " : ""}{line.parts.map((part, index) => <span key={part.view}>{index ? ", " : ""}<button type="button" aria-pressed={quick === part.view} onClick={() => setQuick((current) => current === part.view ? null : part.view)} className={`underline decoration-dotted underline-offset-2 ${quick === part.view ? "font-semibold text-slateish-100" : ""}`}>{part.n} {part.words}</button></span>)}{quick && <> · <button type="button" onClick={() => setQuick(null)} className="underline">show all</button></>}</p>;
        })()}
        {/* ONE TOOLBAR: New query, Filters, and More for the rest */}
        <div className="mt-3 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Query actions">
          <button type="button" onClick={() => setHandOpen((open) => !open)} aria-expanded={handOpen} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">New query</button>
          <button type="button" onClick={() => setFiltersOpen((open) => !open)} aria-expanded={filtersOpen} aria-controls="query-filters" className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">{activeFilters > 0 ? `Filters (${activeFilters} active)` : "Filters"}</button>
          {(canManageGmail || rules !== null) && <details data-testid="more-menu" className="text-xs"><summary className="cursor-pointer rounded bg-ink-700 px-3 py-1.5 text-slateish-100">More</summary>
            <div className="mt-2 w-full space-y-3 rounded border border-ink-700 bg-ink-850 p-2">
        {canManageGmail && <div className="text-xs text-slateish-200" data-testid="prepare-all">
          <button type="button" disabled={busy || preparingAll} onClick={() => { setError(null); void technicalQueriesApi.prepareAllPlan().then((result) => { if (result.ok) setPrepareAll({ plan: result.data, asking: true }); else setError(result.error.message); }); }} className="rounded bg-ink-700 px-3 py-1.5 text-slateish-100 disabled:opacity-50">Find the sources for every query not prepared yet</button>
          {prepareAll?.asking && <div role="alertdialog" aria-label="Confirm preparing all" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-prepare-all">
            <p>{prepareAllWords(prepareAll.plan)}</p>
            {prepareAll.plan.unprepared > 0 && <button type="button" onClick={() => void technicalQueriesApi.prepareAllStart().then((result) => { if (result.ok) setPrepareAll({ plan: result.data, asking: false }); else { setPrepareAll(null); setError(result.error.message); } })} className="mt-1 mr-2 rounded bg-signal-500 px-2 py-1 text-white">Yes, prepare them</button>}
            <button type="button" onClick={() => setPrepareAll(null)} className="mt-1 rounded bg-ink-700 px-2 py-1 text-slateish-100">{prepareAll.plan.unprepared > 0 ? "Cancel" : "Close"}</button>
          </div>}
          {prepareAll && !prepareAll.asking && <p role="status" className="mt-1" data-testid="prepare-all-progress">{prepareAll.plan.waiting_or_running > 0 ? `Preparing evidence in the background: ${prepareAll.plan.waiting_or_running} still waiting or running.` : "Every query that can be prepared has been prepared."}</p>}
        </div>}
          {rules !== null && <details className="rounded border border-ink-700 p-2 text-xs text-slateish-300"><summary className="cursor-pointer">Rules for who it goes to ({rules.length})</summary>
            <p className="mt-2 text-slateish-400">Set once: the contractor code inside the document number names the contractor; the discipline code after the number names the department; the sender's domain or exact address is used when the number carries no code. A rule fills only blank fields, now and for every query already held. A public mail domain cannot be used for this; an exact address can.</p>
            <ul className="mt-2 space-y-1">{rules.map((rule) => <li key={rule.id} className="flex items-center justify-between gap-2"><span>{RULE_WORDS[rule.match_type] ?? rule.match_type} {rule.match_value} → {rule.contractor_name || "—"} / {rule.department || "—"}</span><button type="button" onClick={() => void technicalQueriesApi.deleteRoutingRule(rule.id).then((result) => { if (result.ok) setRules(result.data.items); else setError(result.error.message); })} className="rounded bg-ink-700 px-2 py-1">Remove</button></li>)}</ul>
            <div className="mt-2 space-y-1">
              <select aria-label="Rule type" value={ruleType} onChange={(event) => setRuleType(event.target.value as RoutingRuleType)} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5">{(Object.keys(RULE_WORDS) as RoutingRuleType[]).map((type) => <option key={type} value={type}>{RULE_WORDS[type]}</option>)}</select>
              <input aria-label="Rule value" value={ruleValue} onChange={(event) => setRuleValue(event.target.value)} placeholder={{ contractor_code: "the contractor code in the number, e.g. ABC", discipline: "a discipline code, e.g. PRO", domain: "company.example", address: "person@company.example" }[ruleType]} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule contractor" value={ruleContractor} onChange={(event) => setRuleContractor(event.target.value)} placeholder="Contractor" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule department" value={ruleDepartment} onChange={(event) => setRuleDepartment(event.target.value)} placeholder="Department" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <button type="button" disabled={!ruleValue.trim()} onClick={() => { setError(null); void technicalQueriesApi.saveRoutingRule({ match_type: ruleType, match_value: ruleValue.trim(), contractor_name: ruleContractor.trim() || null, department: ruleDepartment.trim() || null }).then((result) => { if (result.ok) { setRules(result.data.items); setRuleValue(""); setRuleContractor(""); setRuleDepartment(""); } else setError(result.error.message); }); }} className="rounded bg-ink-700 px-2 py-1 disabled:opacity-50">Save rule</button>
            </div></details>}
            </div>
          </details>}
        </div>
          {handOpen && <div className="mt-2 space-y-1 rounded border border-ink-700 p-3 text-xs text-slateish-300" aria-label="New query by hand">
            <p className="text-slateish-400">For a query that did not come by email. Papers you upload are checked for active content like any emailed attachment.</p>
            <label className="block">Subject<input value={handSubject} onChange={(event) => setHandSubject(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Contractor<input value={handContractor} onChange={(event) => setHandContractor(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">The question, as asked<textarea value={handBody} onChange={(event) => setHandBody(event.target.value)} rows={4} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Papers (optional)<input type="file" multiple onChange={(event) => setHandFiles(Array.from(event.target.files ?? []))} className="mt-1 w-full" /></label>
            <button type="button" disabled={busy || !handSubject.trim() || !handBody.trim()} onClick={createByHand} className="rounded bg-signal-500 px-2 py-1 text-white disabled:opacity-50">Create query</button>
          </div>}
        <div className="mt-2">
          {filtersOpen && (
        <div id="query-filters" className="mt-2 space-y-2" role="group" aria-label="Query filters">
            <label className="block text-xs text-slateish-300" htmlFor="query-status-filter">Status</label>
            <select id="query-status-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100">
              <option value="">All statuses</option><option value="received">Received</option><option value="triage">Triage</option><option value="drafting">Drafting</option><option value="awaiting_review">Awaiting review</option><option value="changes_requested">Changes requested</option><option value="approved">Approved</option><option value="resolved">Resolved</option>
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
            <label className="block text-xs text-slateish-300" htmlFor="query-type-filter">Type</label>
            <select id="query-type-filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100"><option value="">Any</option><option value="TQ">TQ: technical query</option><option value="CFC">CFC: conflict finding clarification</option></select>
            <label className="block text-xs text-slateish-300" htmlFor="query-discipline-filter">Discipline code</label>
            <input id="query-discipline-filter" value={disciplineFilter} onChange={(event) => setDisciplineFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <label className="block text-xs text-slateish-300" htmlFor="query-number-filter">Running number</label>
            <input id="query-number-filter" value={numberFilter} onChange={(event) => setNumberFilter(event.target.value)} inputMode="numeric" className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <label className="flex items-center gap-2 text-xs text-slateish-300"><input type="checkbox" checked={needsPersonFilter} onChange={(event) => setNeedsPersonFilter(event.target.checked)} />Needs a person (no full number in the subject)</label>
            <button type="button" onClick={applyFilters} className="rounded bg-ink-700 px-3 py-1.5 text-xs text-slateish-100">Refresh and apply filters</button>
          </div>
          )}
        </div>
        {/* each query in one or two lines: its tag, discipline and short title; then where it stands, who has it, its due date and any problem
            as a short chip, the full sentence on hover (owner, 27 Nov 2026) */}
        <div className="mt-4 space-y-2" aria-label="Technical query list">
          {items.length === 0 && <p className="text-sm text-slateish-500">{importing ? "The import is running: queries appear here as their messages arrive." : "No technical queries have been imported."}</p>}
          {items.length > 0 && quick && !items.some((item) => quickMatch(quick, item)) && <p className="text-sm text-slateish-400">None right now.</p>}
          {(quick ? items.filter((item) => quickMatch(quick, item)) : items).map((item) => {
            const tag = queryTag(item);
            const chip = statusChip(item.status);
            const who = item.assignee_user_id ? (assignees.find((p) => p.id === item.assignee_user_id)?.display_name ?? "a person") : "Nobody assigned";
            return <button key={item.id} type="button" onClick={() => void technicalQueriesApi.get(item.id).then((detail) => { if (detail.ok) { setSelected(detail.data); showDetail(); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } })} className={`w-full rounded border px-3 py-2 text-left ${selected?.id === item.id ? "border-signal-500 bg-ink-800" : "border-ink-700 bg-ink-850"}`}>
              <span className="flex min-w-0 items-center gap-1.5">
                {tag && <span data-testid="query-tag" className="shrink-0 whitespace-nowrap rounded bg-ink-700 px-1.5 text-xs font-semibold text-slateish-100">{tag}</span>}
                {item.discipline_code && <span className="shrink-0 whitespace-nowrap rounded border border-ink-600 px-1.5 text-xs text-slateish-300">{item.discipline_code}</span>}
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-slateish-100" title={item.title_short ?? item.subject}>{item.title_short ?? item.subject}</span>
              </span>
              <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slateish-400">
                <span data-testid="status-chip" className={`whitespace-nowrap rounded border px-1.5 ${chip.tone === "wait" ? "border-signal-500 text-slateish-100" : chip.tone === "done" ? "border-ink-500 text-slateish-100" : chip.tone === "problem" ? "border-danger-500 text-danger-500" : "border-ink-600 text-slateish-300"}`}>{chip.words}</span>
                <span className="whitespace-nowrap">{item.contractor_name ? `${item.contractor_name} \u00b7 ` : ""}{who}</span>
                {item.due_at && <span className="whitespace-nowrap">due {formatWhen(item.due_at).split(",")[0]}</span>}
                {problemChips(item).map((p) => <span key={p.words} data-testid="problem-chip" title={p.why} className="whitespace-nowrap rounded border border-warn-500 px-1.5 text-warn-500">{p.words}</span>)}
              </span>
            </button>;
          })}
        </div>

      </section>
      {/* min-w-0 + wrapping anywhere: a long unbroken line in a mail (a link, a disclaimer) can never widen the page past the window */}
      <section ref={detailRef} className="min-w-0 overflow-x-hidden rounded border border-ink-700 bg-ink-850 p-5 [overflow-wrap:anywhere]">
        {!selected ? <p className="text-sm text-slateish-500">Select a query to inspect its original message and review history.</p> : <>
          {/* READ IN TEN SECONDS (owner, 26 Nov 2026 22:41): one plain sentence first, then where it stands as four marks */}
          <p data-testid="query-headline" className="text-xl font-semibold leading-snug text-slateish-100">{queryHeadline(selected, questionDraft)}</p>
          <h2 className="mt-1 text-sm font-medium text-slateish-400">{selected.subject}</h2>
          <p data-testid="query-status" className="mt-1 text-sm text-slateish-300">{plainStatus(selected.status, selected.priority)}</p>
          <ol data-testid="query-summary" aria-label="Where this query stands" className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {querySteps(selected, questionDraft).map((step) => <li key={step.label} className={step.state === "done" ? "text-slateish-100" : "text-slateish-400"}><span aria-hidden="true" className="mr-1 font-semibold">{step.state === "done" ? "✓" : step.state === "working" ? "…" : "○"}</span>{step.label}{step.state === "working" ? " (working)" : step.state === "todo" ? " (not yet)" : ""}</li>)}
          </ol>
          {/* WHAT THE CONTRACTOR'S FORM CITES, first (owner via builder A, 27 Nov 2026): each citation and whether we hold it */}
          {selected.ready?.cited?.length ? <div data-testid="contractor-cites" className="mt-3 text-sm">
            <p className="font-semibold text-slateish-200">What the contractor&rsquo;s form cites</p>
            <ul className="mt-1 space-y-0.5">{selected.ready.cited.map((c, i) => <li key={`${i}-${c.line}`} className={c.held ? "text-slateish-300" : "text-warn-500"}><span aria-hidden="true" className="mr-1 font-semibold">{c.held ? "\u2713" : "!"}</span>{c.line}</li>)}</ul>
          </div> : null}
          {selected.source_access_revoked && <p role="alert" className="mt-3 text-sm text-warn-500">Access to a cited source changed. The draft is hidden until an authorised reviewer checks it again.</p>}
          {/* ANSWER FIRST (owner's G9 "easy to use", E5, 26 Nov 2026): the question, the proposed response and the decisions
              come first; the email, its attachments and the evidence are folded below. Reorder only: the same parts, words and actions. */}
          {/* WHAT THE CONTRACTOR IS ASKING (owner, 26 Nov 2026 21:29 and 21:36): one readable ask, already filled, with where each
              request was found; edit only if a line is wrong; confirming is a check, it sends nothing. Honest marks, never a gate. */}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">What the contractor is asking</h3>
          {selected.confirmed_question
            ? <p className="mt-1 text-xs text-slateish-400">Checked by an engineer{selected.confirmed_question_at ? ` on ${formatWhen(selected.confirmed_question_at)}` : ""}.</p>
            : (selected.ready && questionDraft.trim()) ? null // the server's own mark says it ("proposed by the system; no engineer has confirmed it yet")
            : <p className="mt-1 text-xs text-warn-500">{questionDraft.trim() ? "Proposed by the system from the mail and its attachments, not yet checked by an engineer." : "No question was found: write it below."}</p>}
          {proposalNoteWords(selected.proposal_note, Boolean(selected.proposed_question)) && <p className="mt-1 text-xs text-warn-500" data-testid="proposal-note">{proposalNoteWords(selected.proposal_note, Boolean(selected.proposed_question))}</p>}
          {!editingQuestion && questionDraft.trim() ? (
            <div data-testid="question-readable" className="mt-2 rounded border border-ink-700 p-3 text-sm text-slateish-100">
              {(() => {
                const lines = readableLines(questionDraft, selected.proposed_questions);
                const lead = lines.filter((l) => l.kind === "lead");
                const items = lines.filter((l) => l.kind === "item");
                return <>
                  {lead.map((l, i) => <p key={`lead-${i}`} className="whitespace-pre-wrap">{l.text}</p>)}
                  {(() => {
                    const shared = sharedSource(lines);
                    const row = (l: (typeof items)[number]) => { const [head, rest] = boldSplit(l.text); return <li key={`item-${l.n}-${l.text}`} className="flex gap-2"><span className="w-6 shrink-0 whitespace-nowrap text-right font-semibold">{l.n}.</span><span><strong className="font-semibold text-slateish-100">{head}</strong><span className="text-slateish-300">{rest}</span>{l.source && !shared && <span className="block text-xs text-slateish-400">found in {l.source}</span>}</span></li>; };
                    // a long list folds after LIST_FOUND with its count in view: every request stays on the page, none is dropped
                    return items.length > 0 && <>
                      <ol className="mt-2 space-y-1">{items.slice(0, LIST_FOUND).map(row)}</ol>
                      {items.length > LIST_FOUND && <details data-testid="question-more" className="mt-1"><summary className="cursor-pointer text-xs font-semibold text-signal-300">{items.length - LIST_FOUND} more request{items.length - LIST_FOUND === 1 ? "" : "s"}</summary><ol className="mt-1 space-y-1">{items.slice(LIST_FOUND).map(row)}</ol></details>}
                      {shared && <p data-testid="question-source" className="mt-2 text-xs text-slateish-400">All found in {shared}.</p>}
                    </>;
                  })()}
                </>;
              })()}
            </div>
          ) : null}
          {questionMarks.map((mark) => <p key={mark} data-testid="question-mark" className="mt-1 text-xs text-warn-500">{mark}</p>)}
          {!selected.confirmed_question && notInText(questionDraft, selected.proposed_questions).length > 0 && <details className="mt-1" data-testid="found-more"><summary className="cursor-pointer text-xs text-slateish-300">Show the other lines found on the form</summary>
            {notInText(questionDraft, selected.proposed_questions).map((part, index) => <p key={`${part.filename}-${part.page}-${index}`} className="mt-1 text-sm text-slateish-300">{part.question}<span className="block text-xs text-slateish-500">found in {part.filename}, page {part.page} · <button type="button" className="underline" onClick={() => setQuestionDraft((current) => withRequest(current, part.question))}>Add to the list</button></span></p>)}
          </details>}
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-2">
            {editingQuestion || !questionDraft.trim() ? <>
              <label htmlFor="technical-query-question" className="block text-xs text-slateish-300">Edit what the contractor is asking (one request per numbered line)</label>
              <textarea id="technical-query-question" value={questionDraft} onChange={(event) => setQuestionDraft(event.target.value)} rows={6} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            </> : <button type="button" onClick={() => setEditingQuestion(true)} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100">Edit</button>}
            {selected.ready && questionDraft.trim() && questionDraft.trim() !== selected.ready.question.trim() && <button type="button" disabled={busy} onClick={saveQuestion} className="ml-2 mt-2 rounded border border-signal-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Save and find the sources again</button>}
            <button type="button" disabled={busy || !selected.can_review || !questionDraft.trim() || questionDraft.trim() === (selected.confirmed_question || "")} title={selected.can_review ? undefined : "Only a qualified reviewer can confirm the question"} onClick={confirmQuestion} className="ml-2 mt-2 rounded bg-signal-500 px-3 py-1.5 text-xs text-white disabled:opacity-50">Confirm</button>
            <p className="mt-1 text-xs text-slateish-400">Confirming only records that you checked it. Nothing is sent.</p>
            <InfoFold title="About checking the question" className="mt-1 text-xs">Confirm means you have checked this is what the contractor is asking. It does not send anything to the contractor, and approving the reply also records the wording it answers, so Confirm is optional. Edit changes the wording; the sources and a new draft follow by themselves.</InfoFold>
            {!selected.can_review && <p className="mt-1 text-xs text-slateish-500">Only a qualified reviewer can confirm the question.</p>}
          </div>}
          {/* WHAT THE CONTRACT OR STANDARD SAYS (owner, 26 Nov 2026 22:41): the sources the reply stands on, each with its source, clause
              and page, before the reply; a cited source not yet confirmed can be confirmed right here */}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">What the contract or standard says</h3>
          {honestMarks(selected, questionDraft).evidence.map((mark) => <p key={mark} data-testid="evidence-mark" className="mt-1 text-xs text-warn-500">{mark}</p>)}
          {(() => {
            const byId = new Map((selected.evidence ?? []).map((e) => [e.id, e]));
            const cites = draftCitations(selected.drafts?.at(-1)?.citations_json);
            if (!cites.length) return <p className="mt-1 text-sm text-slateish-400">{currentSources(selected.evidence).length ? "The sources found are listed under \u201cAll sources found\u201d below; no reply cites any yet." : "No source found yet."}</p>;
            return <ul data-testid="reply-sources" className="mt-2 space-y-3">{cites.map((citation) => { const e = (citation as { evidence_id?: string }).evidence_id ? byId.get((citation as { evidence_id?: string }).evidence_id!) : undefined; return <li key={citation.label} className="border-l-2 border-signal-500 pl-3 text-sm">
              <Quote text={citation.exact_quote} words={askWords(questionDraft)} />
              <p className="mt-1 text-xs text-slateish-400">[{citation.label}] <a className="underline" href={`/api/documents/${encodeURIComponent(citation.document_id)}/original#page=${citation.page}`} title={`Open ${e?.source_name || "the source document"}, page ${citation.page}`} target="_blank" rel="noreferrer">{e?.source_name || e?.source_kind ? `${sourceLinkLabel(e?.source_name, e?.source_kind)}, ` : ""}{e?.locator ? `${e.locator}, ` : ""}page {citation.page}</a>
                {e && e.supersession_state === "unknown" && isAdmin && <><button type="button" data-testid="confirm-source" disabled={busy} onClick={() => confirmSource(e.document_id)} className="ml-2 rounded border border-ink-500 px-2 py-0.5 text-xs text-slateish-100 disabled:opacity-50">Confirm source document</button><span data-testid="confirm-source-hint" className="ml-2 text-slateish-400">{CONFIRM_SOURCE_HINT}</span></>}
                {e && e.supersession_state === "unknown" && !isAdmin && <span className="ml-2 text-warn-500">its revision is not confirmed yet</span>}</p>
            </li>; })}</ul>;
          })()}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Proposed reply{selected.status !== "approved" && selected.drafts?.length ? <span className="ml-2 rounded border border-warn-500 px-2 py-0.5 text-xs font-normal text-warn-500">AI, to be checked</span> : null}</h3>
          {readyLine(selected.ready) && <p role="status" data-testid="ready-line" className="mt-1 text-xs text-slateish-300">{readyLine(selected.ready)}</p>}
          {draftAuthor(selected.drafts?.at(-1)) && <p data-testid="draft-author" className="mt-1 text-xs text-slateish-400">{draftAuthor(selected.drafts?.at(-1))}</p>}
          {/* THE OLD REPLY WHILE IT IS REWRITTEN (owner's live walk, 27 Nov 2026 01:15): greyed and said, never shown as the current one */}
          {selected.drafts?.length ? (replyBeingRewritten(selected.ready)
            ? <div data-testid="reply-being-rewritten" className="mt-2 rounded border border-dashed border-ink-600 p-2"><p className="text-xs font-semibold text-slateish-200">Old reply, being rewritten: the new one replaces it when it is ready.</p><p className="mt-1 whitespace-pre-wrap text-sm text-slateish-400">{selected.drafts.at(-1)?.answer}</p></div>
            : <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.drafts.at(-1)?.answer}</p>) : <p className="mt-2 text-sm text-slateish-500">No draft yet.</p>}
          {!selected.drafts?.length && !searching && <div className="mt-3"><button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id, "local", []))} className="rounded border border-signal-500 px-3 py-1.5 text-sm text-slateish-100 disabled:opacity-50">Write the reply</button><p className="mt-1 text-xs text-slateish-400">The AI on this computer writes a reply from the sources found. Nothing is sent.</p></div>}
          {/* THE DECISION FIRST (owner, 27 Nov 2026 00:02: "it is difficult to understand these buttons"): the one coloured button is the
              decision (Approve, or Send back with a note); writing the reply again is quiet, in the Redo fold, and says it replaces the reply.
              Approve keeps the sources the reply cites and rejects the others found for this question (lead-4's decision), then approves. */}
          {(() => {
            const decision = decisionFor(selected);
            if (decision.kind === "no_role") return <p data-testid="decision-no-role" className="mt-4 text-sm text-slateish-300">{decision.hint}</p>;
            if (decision.kind !== "decide") return null;
            const split = citedSplit(selected.evidence, selected.drafts?.at(-1)?.citations_json);
            return <div className="mt-4" data-testid="approve-once">
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" disabled={busy} onClick={approveOnce} className="rounded bg-signal-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Approve the reply</button>
                <button type="button" disabled={busy} onClick={() => setSendingBack(true)} className="rounded border border-ink-500 px-4 py-2 text-sm text-slateish-100 disabled:opacity-50">Send back with a note</button>
              </div>
              <p data-testid="decision-hint" className="mt-1 text-xs text-slateish-400">{decision.hint}</p>
              {split.keep.length + split.reject.length > 0 && <p className="mt-1 text-xs text-slateish-400">Approving keeps the {split.keep.length} source{split.keep.length === 1 ? "" : "s"} the reply cites and rejects the other {split.reject.length} found for this question. You can change any of them under &ldquo;All sources found&rdquo; first.</p>}
              {sendingBack && <div data-testid="send-back" className="mt-2 rounded border border-ink-700 p-2">
                <label htmlFor="technical-query-send-back" className="block text-xs text-slateish-300">What should change in the reply?</label>
                <textarea id="technical-query-send-back" value={backNote} onChange={(event) => setBackNote(event.target.value)} rows={3} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <button type="button" disabled={busy || !backNote.trim()} onClick={() => { const note = backNote.trim(); setSendingBack(false); setBackNote(""); act(() => technicalQueriesApi.decide(selected.id, "request_changes", selected.drafts?.at(-1)?.id, note)); }} className="rounded border border-signal-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Send back</button>
                  <button type="button" onClick={() => { setSendingBack(false); setBackNote(""); }} className="rounded px-3 py-1.5 text-xs text-slateish-300">Cancel</button>
                </div>
                <p className="mt-1 text-xs text-slateish-400">The reply goes back to be written again, with your note kept beside it. Nothing is sent to the contractor.</p>
              </div>}
            </div>;
          })()}
            {bulkNote && bulkNote.queryId === selected.id && <p role="status" data-testid="keep-cited-done" className="w-full text-xs text-slateish-300">Kept {bulkNote.kept} source{bulkNote.kept === 1 ? "" : "s"} the draft cites and rejected {bulkNote.rejected} other{bulkNote.rejected === 1 ? "" : "s"}. Each can still be changed below before you approve.</p>}
          {/* THE WORD REPLY (owner, 27 Nov 2026 00:02): what it is, in one line, and why it cannot be downloaded yet */}
          {selected.drafts?.length || ["approved", "sent", "awaiting_confirmation"].includes(selected.status) ? (() => {
            const whyNot = wordReplyWhyNot(selected);
            return <div className="mt-4" data-testid="word-reply">
              <div className="flex flex-wrap items-center gap-2">
                {whyNot
                  ? <button type="button" disabled aria-describedby="word-reply-hint" className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200 disabled:opacity-50">Download the reply as a Word file</button>
                  : <a className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200" href={`/api/technical-queries/${selected.id}/response.docx`}>Download the reply as a Word file</a>}
                {["approved", "sent", "awaiting_confirmation"].includes(selected.status) && selected.can_review ? <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.confirmResolution(selected.id))} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Mark as answered</button> : null}
              </div>
              <p id="word-reply-hint" className="mt-1 text-xs text-slateish-400">{whyNot ? `${whyNot} ` : ""}A Word file of the approved reply, for you to send to the contractor yourself: the app does not send email.{["approved", "sent", "awaiting_confirmation"].includes(selected.status) && selected.can_review ? " After you have sent it, press Mark as answered." : ""}</p>
            </div>;
          })() : null}
          {/* REDO, folded and quiet (owner, 27 Nov 2026 00:02): each line says what it does and that it replaces the reply above */}
          <details data-testid="more-actions" className="mt-4 rounded border border-ink-700 p-2">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Redo: change the reply or write it again</summary>
            <p className="mt-1 text-xs text-slateish-400">Each of these replaces the reply above. Nothing is sent.</p>
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-3">
            <label htmlFor="technical-query-answer" className="block text-sm text-slateish-300">Write the reply yourself</label>
            <textarea id="technical-query-answer" value={editedAnswer} onChange={(event) => setEditedAnswer(event.target.value)} rows={8} className="mt-2 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <button type="button" disabled={busy || !editedAnswer.trim()} onClick={() => act(() => technicalQueriesApi.createDraft(selected.id, editedAnswer.trim()))} className="mt-2 rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Save my reply for approval</button>
            <p className="mt-1 text-xs text-slateish-400">Your words replace the reply above and wait for a reviewer to approve them.</p>
          </div>}
            {(() => {
              const claude = selected.draft_engines?.claude;
              const claudeWhy = claude && !claude.available ? (claude.why || "it cannot be used on this computer now") : null;
              return <fieldset className="mt-3 text-xs text-slateish-300" aria-label="Who writes the reply"><legend className="font-semibold text-slateish-200">Who writes the reply</legend>
                <label className="mt-1 flex items-center gap-2"><input type="radio" name="tq-engine" value="local" checked={engine === "local"} onChange={() => setEngine("local")} />The AI on this computer (free)</label>
                <label className="mt-1 flex items-center gap-2"><input type="radio" name="tq-engine" value="claude" checked={engine === "claude"} disabled={Boolean(claudeWhy)} onChange={() => setEngine("claude")} />Claude (paid, better: only the documents you tick go to Claude){claudeWhy && <span data-testid="claude-why" className="text-slateish-400">: not available now, {claudeWhy}</span>}</label>
              </fieldset>;
            })()}
            {engine === "claude" && <fieldset className="mt-2 w-full rounded border border-ink-700 p-2 text-xs text-slateish-300" aria-label="Documents Claude may read for this query"><legend className="px-1">Contract documents Claude may read for this one query</legend>
              {[...new Set((selected.evidence ?? []).filter((e) => e.evidence_state === "verified").map((e) => e.document_id))].map((documentId) => <label key={documentId} className="mr-4 inline-flex items-center gap-1"><input type="checkbox" checked={claudeDocs.includes(documentId)} onChange={(event) => setClaudeDocs((current) => event.target.checked ? [...current, documentId] : current.filter((d) => d !== documentId))} />{documentId}</label>)}
              <p className="mt-1 text-slateish-400">Only the ticked documents and this query's question are sent. Choose none and nothing is sent.</p></fieldset>}
            <div className="mt-2">
              <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id, engine, engine === "claude" ? claudeDocs : []))} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Write the reply again</button>
              <p className="mt-1 text-xs text-slateish-400">The AI chosen above writes a new reply from the sources found and replaces the reply above.</p>
            </div>
            {/* not on the happy path (owner, 26 Nov 2026): the sources are found by themselves; this is for a query with none yet, or
                when the ask was edited since they were found */}
            {!searching && !refreshing && (!(selected.evidence?.length) || questionEdited || staleSources(selected) || selected.ready?.evidence_fresh === false || selected.ready?.evidence === "failed") && <div className="mt-2">
              <button type="button" disabled={busy} onClick={() => act(() => technicalQueriesApi.prepareEvidence(selected.id))} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">{selected.evidence?.length ? "Find the sources again" : "Find the sources"}</button>
              <p className="mt-1 text-xs text-slateish-400">Searches the contract and the standards again for this question. A new reply follows by itself and replaces the reply above.</p>
            </div>}
            {(() => {
              const split = citedSplit(selected.evidence, selected.drafts?.at(-1)?.citations_json);
              const any = split.keep.length + split.reject.length > 0;
              return selected.can_review && selected.drafts?.length && any ? <div className="mt-2" data-testid="keep-cited">
                <button type="button" disabled={busy} onClick={keepCited} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Keep the sources the reply cites, reject the others</button>
                <p className="mt-1 text-xs text-slateish-400">Keeps {split.keep.length} the reply cites and rejects the other {split.reject.length} found for this question. Approving does this too. You can change any of them below.</p>
              </div> : null;
            })()}
          </details>
          {selected.evidence_job && (selected.evidence_job.state === "queued" || selected.evidence_job.state === "running") && <p role="status" className="mt-3 text-xs text-slateish-300" data-testid="evidence-progress">Preparing the evidence: {selected.evidence_job.label ?? "queued"}{selected.evidence_job.progress_total > 0 ? ` (${selected.evidence_job.progress_done} of ${selected.evidence_job.progress_total})` : ""}. You can leave this page; it carries on.</p>}
          {selected.evidence_job?.state === "failed" && <p role="alert" className="mt-3 text-xs text-warn-500">The evidence could not be prepared: {selected.evidence_job.error}</p>}
          {evidenceBlock}
          {/* WHO HANDLES IT (owner, 27 Nov 2026 00:02): one form and one Save; an empty field says what the subject holds */}
          <details data-testid="who-it-goes-to" className="mt-6 rounded border border-ink-700 p-2"><summary className="cursor-pointer text-sm font-semibold text-slateish-200">Who handles it: contractor, department, person, due date</summary>
          <div className="mt-2 grid gap-2 rounded border border-ink-700 p-3 sm:grid-cols-2" aria-label="Who handles it">
            <label className="text-xs text-slateish-300">Contractor<input value={triageContractor} onChange={(event) => setTriageContractor(event.target.value)} placeholder={selected.contractor_code ? `code ${selected.contractor_code} in the subject` : "not named in the subject"} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            <label className="text-xs text-slateish-300">Department<input value={triageDepartment} onChange={(event) => setTriageDepartment(event.target.value)} placeholder={selected.discipline_code ? `discipline ${selected.discipline_code} in the subject` : "not named in the subject"} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            {(!triageContractor.trim() || !triageDepartment.trim()) && fromSubjectHint(selected) && <p data-testid="from-subject" className="text-xs text-slateish-400 sm:col-span-2">{fromSubjectHint(selected)}</p>}
            <label className="text-xs text-slateish-300">Priority<select value={triagePriority} onChange={(event) => setTriagePriority(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
            <label className="text-xs text-slateish-300">Due date<input type="date" value={triageDue} onChange={(event) => setTriageDue(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm" /></label>
            {assignees.length > 0 && <label className="text-xs text-slateish-300">Responsible person<select value={chosenAssignee} onChange={(event) => setChosenAssignee(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm"><option value="">Nobody yet</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label>}
            {selected.routing_source?.startsWith("rule:") && <p className="text-xs text-slateish-400 sm:col-span-2">Contractor and department were filled from a rule. Save to confirm or change them.</p>}
            <div className="sm:col-span-2">
              <button type="button" disabled={busy} onClick={saveWho} className="rounded border border-ink-500 px-3 py-1.5 text-xs text-slateish-100 disabled:opacity-50">Save who handles it</button>
              <p className="mt-1 text-xs text-slateish-400">Saves everything above at once. Nothing is sent to anyone.</p>
            </div>
          </div>
          </details>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-email-question">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Show original: the question as written in the email</summary>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{(selected.extracted_question_main ?? selected.extracted_question) || selected.email_question_note || "Not stated in the email text."}</p>
            <Folded text={selected.extracted_question_folded} />
            {selected.attachment_reading?.map((part) => <p key={part.filename} className="mt-6 text-xs text-slateish-400" data-testid="attachment-reading">{part.line}</p>)}
            {selected.attachment_text_hidden && <p className="mt-6 text-xs text-warn-500">The attachment text is hidden: you may not read that attachment.</p>}
            {selected.attachment_context?.length ? <>
              <h3 className="mt-6 text-sm font-semibold text-slateish-200">Attachment text</h3>
              {selected.attachment_context.map((part) => <div key={`${part.filename}-${part.page}`} className="mt-2 rounded border border-ink-700 p-2 text-sm text-slateish-300"><p className="text-xs text-slateish-500">{part.filename}, page {part.page}</p><p className="mt-1 whitespace-pre-wrap">{part.text}</p></div>)}
            </> : null}
          </details>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-mail">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Show original: the email and its attachments</summary>
            {(() => {
              const read = attachmentsRead(selected.messages);
              return read && <div className="mt-2 text-xs text-slateish-300" data-testid="attachments-read"><p>{read.line}.</p>
                {read.notRead.length > 0 && <ul className="mt-1 list-disc pl-5 text-warn-500">{read.notRead.map((item, index) => <li key={`${item.filename}-${index}`}>{item.filename}: {item.why}</li>)}</ul>}</div>;
            })()}
            {selected.messages?.map((message, index) => <article key={`${message.received_at}-${index}`} className="mt-3 rounded border border-ink-700 p-3 text-sm text-slateish-300">
              {(message.is_inbound === 0 || message.is_inbound === false) && <p className="mb-1 inline-block rounded border border-signal-500 px-1 text-xs text-signal-300" data-testid="sent-by-us">Sent by us</p>}
              <p>From: {message.from_address}</p>{(({ lines, folded }) => <>{lines.map((line) => <p key={line} data-testid="mail-people">{line}</p>)}{folded && <details className="text-xs text-slateish-500"><summary className="cursor-pointer">show everyone</summary><p className="whitespace-pre-wrap">{folded}</p></details>}</>)(peopleLine(message.to_addresses, message.cc_addresses))}
              <p>Received: {formatWhen(message.received_at)}</p>
              {message.raw_message_hash && <a className="mt-1 inline-block text-xs text-signal-300 underline" href={`/api/technical-queries/${encodeURIComponent(selected.id)}/messages/${encodeURIComponent(message.id)}/original.eml`}>Download original email</a>}
              <p className="mt-2 whitespace-pre-wrap">{message.body_main ?? message.body}</p>
              <Folded text={message.body_folded} />
              {message.attachments.some((a) => !isInlinePicture(a)) && <ul className="mt-2 list-disc pl-5">{message.attachments.filter((a) => !isInlinePicture(a)).map((attachment) => <li key={attachment.filename}>{attachment.document_id ? <a className="underline" href={`/api/technical-queries/${encodeURIComponent(selected.id)}/attachments/${encodeURIComponent(attachment.id)}/original`} target="_blank" rel="noreferrer">{attachment.filename}</a> : attachment.filename} ({attachment.size_bytes} bytes) · <span data-testid="attachment-state">{notReadWhy(attachment) ? `not read: ${notReadWhy(attachment)}` : `read · ${SCAN_LABELS[attachment.scan_status] ?? attachment.scan_status.replaceAll("_", " ")}`}</span>
                {attachment.document_id && !attachment.filed_at && <span data-testid="attachment-unfiled"> · kept out of the library: not found by search, Chat or the review list{selected.can_review ? <> <select aria-label="Role to file this attachment under" value={fileRole} onChange={(event) => setFileRole(event.target.value)} className="ml-1 rounded border border-ink-600 bg-ink-900 p-1 text-xs"><option value="SUPPORTING_DOCUMENT">Supporting document</option><option value="CONTRACTOR_SUBMITTAL">Contractor submittal</option><option value="SPECIFICATION">Specification</option><option value="CONTRACT_DOCUMENT">Contract document</option><option value="COMPANY_STANDARD">Company standard</option></select> <button type="button" disabled={busy} onClick={() => setConfirming({ kind: "file", attachmentId: attachment.id })} className="ml-1 rounded bg-ink-700 px-2 py-0.5 text-xs text-slateish-100 disabled:opacity-50">File into the library</button>{confirming?.kind === "file" && confirming.attachmentId === attachment.id && <span role="alertdialog" aria-label="Confirm filing" className="ml-2 rounded border border-warn-500 p-1" data-testid="confirm-file">File this attachment into the library? It then appears in search, Chat and the review list under the chosen role. <button type="button" disabled={busy} onClick={() => { setConfirming(null); act(() => technicalQueriesApi.fileIntoLibrary(selected.id, attachment.id, fileRole)); }} className="ml-1 rounded bg-signal-500 px-2 py-0.5 text-white">Yes, file it</button> <button type="button" onClick={() => setConfirming(null)} className="ml-1 rounded bg-ink-700 px-2 py-0.5 text-slateish-100">Cancel</button></span>}</> : null}</span>}
              </li>)}</ul>}
            </article>)}
          </details>
          <details data-testid="review-history" className="mt-6 rounded border border-ink-700 p-2"><summary className="cursor-pointer text-sm font-semibold text-slateish-200">Approvals and notes</summary>
          {historyWords(selected.decisions).map((line, index) => <p key={`${index}-${line}`} className="mt-2 text-sm text-slateish-300">{line}</p>)}
          </details>
        </>}
      </section>
    </div>
  );
}
