import { InfoFold } from "../components/look/LookParts";
import { LIST_FOUND, groupByItem, leadParagraphs, matchWords, replyBeingRewritten, mailboxChip, problemChips, quickMatch, type QuickView, askWords, boldSplit, decisionFor, fromSubjectHint, historyWords, markedPieces, shortQuote, wordReplyWhyNot, plainMark, citedSplit, currentSources, draftAuthor, honestMarks, plainStatus, queryHeadline, querySteps, sharedSource, notInText, readableLines, readyLine, staleSources, startingText, withRequest } from "./technicalQueryQuestion";
import { classification } from "../api/client";
import { confirmBody } from "../components/classification/metadataBody";
import { useEffect, useRef, useState } from "react";

import { formatWhen } from "../format/when";
import { REFS_MARK, TechnicalQueryCrossRefs } from "./TechnicalQueryCrossRefs";
import { TechnicalQueryPosition, withPositionLine } from "./TechnicalQueryPosition";

import { TechnicalQueriesList } from "./TechnicalQueriesList";
import { Button, LinkButton, StatusChip } from "../components/kit/Kit";
import { attachmentsRead, importDoneWords, isInlinePicture, notReadWhy, peopleLine, prepareAllWords, proposalNoteWords, type PrepareAll } from "../api/technicalQueries";
import { technicalQueriesApi, type GmailLabel, type RoutingRule, type RoutingRuleType, type Result, type TechnicalQuery, type TechnicalQueryAssignee, type TechnicalQueryMailbox } from "../api/client";

/** The states in which the engineer's own reply can be written (the server's add_draft rule). A reply that awaits approval can be replaced by
 *  the engineer's own typed reply too (lead-4, 27 Nov 2026): it becomes the new version awaiting approval; approving is unchanged. */
const EDITABLE = ["received", "triage", "drafting", "changes_requested", "awaiting_review"];

/** A source's state and its document's revision, in words (H's review of the owner's file, Q2: a bare "unknown" ended the line). */
const SOURCE_STATE_WORDS: Record<string, string> = {
  verified: "kept", proposed: "suggested, not kept yet", needs_review: "needs review", rejected: "rejected",
  conflicting: "conflicts with another source", ambiguous: "unclear",
};
const REVISION_WORDS: Record<string, string> = {
  current: "latest revision", superseded: "replaced by a later revision", unknown: "revision not confirmed",
};

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
  static_check_clean: "no macros or scripts found (not a virus scan)",
  static_check_flagged: "macros or scripts found: its text is not used",
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
export const CONFIRM_SOURCE_HINT = "Confirm marks this document as checked, so its quotes can be used in a reply. Check it is the latest revision first.";

/** A source link's own words: the document's name (and kind) and the place, never only "page N" beside a raw address (owner, 27 Nov 2026).
 *  A source with no recorded name keeps "Open source". */
export function sourceLinkLabel(name?: string | null, kind?: string | null): string {
  return name || kind ? `${name || "Unnamed document"}${kind ? ` (${kind})` : ""}` : "Open source";
}

const QUICK_VIEWS: readonly QuickView[] = ["waiting", "progress", "person", "approved", "sent", "closed", "stopped"];
/** The count line's filter named in the address, if it is one the page knows. */
function readQuick(): QuickView | null {
  try {
    const show = new URL(window.location.href).searchParams.get("show");
    return show && (QUICK_VIEWS as readonly string[]).includes(show) ? (show as QuickView) : null;
  } catch { return null; }
}

export function TechnicalQueriesView({ queryId, isAdmin = false }: { queryId?: string; isAdmin?: boolean }) {
  const [items, setItems] = useState<TechnicalQuery[]>([]);
  const [selected, setSelected] = useState<TechnicalQuery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editedAnswer, setEditedAnswer] = useState("");
  const redoRef = useRef<HTMLDetailsElement>(null);
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
  // the count line's filter lives in the address (?show=waiting), so a bookmark or a reload keeps it (F's walk, 27 Nov 2026)
  const [quick, setQuick] = useState<QuickView | null>(() => readQuick());
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
    if (typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1279px)").matches) detailRef.current?.scrollIntoView?.({ block: "start" });
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

  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      if (quick) url.searchParams.set("show", quick); else url.searchParams.delete("show");
      if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
    } catch { /* an address that cannot be rewritten keeps the filter on the page only */ }
  }, [quick]);
  // the open query follows the filter (F's walk, 27 Nov 2026): one that is not among the matches gives way to the first that is, or to none
  useEffect(() => {
    if (!quick || !selected || quickMatch(quick, selected)) return;
    const first = items.find((item) => quickMatch(quick, item));
    if (!first) { setSelected(null); return; }
    void technicalQueriesApi.get(first.id).then((detail) => { if (detail.ok) { setSelected(detail.data); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } });
  }, [quick]); // on a filter change only, not on every reload of the list

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

  // the references' own mark is shown as the references themselves (TechnicalQueryCrossRefs), one sentence each, never twice
  const refsShown = Boolean(selected?.cross_refs?.length);
  const questionMarks = selected ? [...new Set([...honestMarks(selected, questionDraft).question, ...(selected.ready?.marks ?? []).filter((m) => !(refsShown && REFS_MARK.test(m))).map(plainMark)])] : [];
  const openQuery = (id: string) => void technicalQueriesApi.get(id).then((detail) => { if (detail.ok) { setSelected(detail.data); showDetail(); setEditedAnswer(detail.data.drafts?.at(-1)?.answer || ""); } });
  const searching = selected?.evidence_job?.state === "queued" || selected?.evidence_job?.state === "running";
  // the ask as shown differs from what the sources were found for (the confirmed wording, else the proposal)
  const questionEdited = Boolean(selected) && questionDraft.trim() !== (selected ? startingText(selected) : "").trim();

  const act = (action: () => Promise<Result<TechnicalQuery>>) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    void action().then((result) => {
      setBusy(false);
      if (!result.ok) { setError(result.error?.message || "That did not work. Please try again."); return; }
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
  // "Confirm source document" once per source document, where it first shows (H's audit #53, 27 Nov 2026: it stood under every passage)
  const confirmShown = new Set<string>();
  const confirmOnce = (documentId: string) => {
    if (confirmShown.has(documentId)) return false;
    confirmShown.add(documentId);
    return true;
  };
  const renderEvidence = (evidence: EvidenceRow) => <blockquote key={evidence.id} className="mt-2 border-l-2 border-signal-500 pl-3 text-sm text-slateish-300">{evidence.exact_quote}<footer className="mt-1 text-xs text-slateish-500"><a className={`underline ${evidence.locator ? "" : "whitespace-nowrap"}`} href={`/api/documents/${encodeURIComponent(evidence.document_id)}/original${evidence.page_start ? `#page=${evidence.page_start}` : ""}`} title={`Open ${evidence.source_name || "the source document"}, page ${evidence.page_start ?? "unknown"}`} target="_blank" rel="noreferrer">{evidence.source_name || evidence.source_kind ? <span data-testid="evidence-source">{sourceLinkLabel(evidence.source_name, evidence.source_kind)}</span> : sourceLinkLabel()}, {evidence.locator ? `${evidence.locator}, ` : ""}{`page\u00a0${evidence.page_start ?? "unknown"}`}</a>{matchWords(evidence) ? <> · <span data-testid="evidence-match" title={matchWords(evidence)!.counts}>{matchWords(evidence)!.words}</span></> : null} · {SOURCE_STATE_WORDS[evidence.evidence_state] ?? evidence.evidence_state.replaceAll("_", " ")} · {REVISION_WORDS[evidence.supersession_state] ?? evidence.supersession_state.replaceAll("_", " ")}{evidence.supersession_state === "unknown" && ["verified", "proposed", "needs_review", "conflicting", "ambiguous"].includes(evidence.evidence_state) ? (confirmOnce(evidence.document_id) ? <span data-testid="evidence-needs-confirm" className="block text-warn-500">{evidence.evidence_state === "verified" ? (isAdmin ? "It is used in a reply once its document is confirmed." : "It is used in a reply once its document is confirmed under Documents, Details.") : (isAdmin ? "To use it in a reply: keep it, and confirm its document." : "To use it in a reply: keep it, and confirm its document under Documents, Details.")}{isAdmin && <><Button variant="secondary" size="sm" data-testid="confirm-source" disabled={busy} onClick={() => confirmSource(evidence.document_id)}>Confirm source document</Button><span data-testid="confirm-source-hint" className="ml-2 text-slateish-400">{CONFIRM_SOURCE_HINT}</span></>}</span> : <span data-testid="evidence-needs-confirm-again" className="block text-slateish-400">Its document is not confirmed yet (see above).</span>) : null}</footer>
              {(evidence.evidence_state === "needs_review" || evidence.evidence_state === "proposed") && <div className="mt-2 text-xs text-warn-500"><p>{evidence.evidence_state === "proposed" ? "Found by the search. The words are on that page, but nobody has checked they answer the question. Keep or reject it before the reply uses it." : "This quote is from the contractor's own file. A reviewer decides before the reply is approved."}</p>
                {selected!.can_review ? <div className="mt-1 flex gap-2"><Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected!.id, evidence.id, "verified", evidence.supersession_state))}>Keep</Button><Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => technicalQueriesApi.classifyEvidence(selected!.id, evidence.id, "rejected", evidence.supersession_state))}>Reject</Button></div> : <p className="mt-1">Only a reviewer can decide.</p>}</div>}
            </blockquote>;

  const evidenceBlock = selected && (
    <>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-evidence">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">All sources found for this question ({currentEvidence.length}): keep or reject each</summary>
            {honestMarks(selected, questionDraft).evidence.map((mark) => <p key={mark} data-testid="evidence-mark" className="mt-1 text-xs text-warn-500">{mark}</p>)}
            {selected.evidence_coverage && <p className="mt-1 text-xs text-slateish-400" data-testid="evidence-coverage">{selected.evidence_coverage.line}</p>}
            {/* the best quote's raw relevance score is not shown (H's review of the owner's file, Q1): a negative number reads as nothing */}
            {/* BY REQUEST (builder A's search per numbered item, 27 Nov 2026): each request's sources under it, the rest "For the whole request" */}
            {currentEvidence.length ? groupByItem(currentEvidence, selected.ready?.items).map((group) => group.title === null
              ? group.rows.map((evidence) => renderEvidence(evidence))
              : <section key={group.title} data-testid="evidence-group" className="mt-3">
                  <h4 className="text-sm font-semibold text-slateish-200">{group.title} <span className="font-normal text-slateish-400">({group.rows.length} source{group.rows.length === 1 ? "" : "s"})</span></h4>
                  {group.rows.length ? group.rows.map((evidence) => renderEvidence(evidence)) : <p className="mt-1 text-xs text-warn-500">No source found for this question yet.</p>}
                </section>) : <p className="mt-2 text-sm text-warn-500">No source kept yet.</p>}
            {earlierEvidence.length > 0 && <details data-testid="evidence-earlier" className="mt-2"><summary className="cursor-pointer text-xs text-slateish-400">{earlierEvidence.length} source{earlierEvidence.length === 1 ? "" : "s"} found for an earlier wording of the question</summary>{earlierEvidence.map((evidence) => renderEvidence(evidence))}</details>}
          </details>
    </>
  );
  return (
    <div ref={topRef} className="mx-auto grid w-full min-w-0 gap-5 px-4 py-6 xl:grid-cols-[20rem_minmax(0,1fr)]" aria-labelledby="technical-queries-title" role="region">
      <section className="min-w-0 [overflow-wrap:anywhere]">
        {/* THE LIST COLUMN, built only from the shared kit (TechnicalQueriesList.tsx, R1); the page's own panels come in as they were */}
        <TechnicalQueriesList chip={mailboxChip(mailboxes, canManageGmail)} mailboxOpen={mailboxOpen} onToggleMailbox={() => setMailboxOpen((open) => !open)}
          loading={visibleTotal === null} items={items} activeFilters={activeFilters} quick={quick} onQuick={setQuick}
          handOpen={handOpen} onHand={() => setHandOpen((open) => !open)} filtersOpen={filtersOpen} onFilters={() => setFiltersOpen((open) => !open)}
          importing={importing} selectedId={selected?.id ?? null} assignees={assignees}
          onOpen={openQuery}
          panels={{
            mailbox: <>
        {canManageGmail && mailboxes.length === 0 && <div className="mt-4 rounded border border-ink-700 p-3 text-xs text-slateish-200">
          <p>Connect a Gmail mailbox to import queries from one of its labels.</p>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })}>Connect Gmail</Button>
        </div>}
        {pendingMailbox && <div className="mt-4 rounded border border-warn-500 p-3 text-xs text-slateish-200">
          <p>Gmail account {pendingMailbox.email} is connected but waiting for a dedicated technical-query label. Only messages under that label will be imported.</p>
          <Button variant="secondary" size="sm" onClick={() => void technicalQueriesApi.gmailLabels(pendingMailbox.id).then((result) => { if (result.ok) { setLabels(result.data.items); setLabelId(result.data.items[0]?.id || ""); } else setError(result.error.message); })}>Choose label</Button>
          {labels.length > 0 && <div className="mt-2"><label htmlFor="gmail-query-label">Gmail label</label><select id="gmail-query-label" value={labelId} onChange={(event) => setLabelId(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2">{labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}</select><Button variant="primary" size="sm" disabled={busy || !labelId} onClick={() => setConfirming({ kind: "activate" })}>Activate selected label</Button>
            {confirming?.kind === "activate" && <div role="alertdialog" aria-label="Confirm the label" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-activate">
              <p>Import the emails under this label, and keep checking for new ones? You can leave this page while it runs.</p>
              <Button variant="primary" size="sm" disabled={busy} onClick={() => { setConfirming(null); setBusy(true); setError(null); void technicalQueriesApi.activateGmailLabel(pendingMailbox.id, labelId).then((result) => { setBusy(false); if (!result.ok) { setError(result.error.message); return; } setLabels([]); void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }}>Yes, save and start the import</Button>
              <Button variant="secondary" size="sm" onClick={() => setConfirming(null)}>Cancel</Button>
            </div>}</div>}
        </div>}
        {mailboxes.filter((mailbox) => mailbox.connection_state === "error" || mailbox.connection_state === "revoked").map((mailbox) => <div key={mailbox.id} className="mt-4 rounded border border-warn-500 p-3 text-xs text-slateish-200" data-testid="mailbox-stopped">
          <p role="alert" className="text-warn-500">Mailbox {mailbox.email} is not being checked. {mailbox.status_note || "Connect it again."}</p>
          {mailbox.connection_state === "error" && <Button variant="secondary" size="sm" disabled={busy} onClick={() => { setError(null); void technicalQueriesApi.checkNow(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }}>Check now</Button>}
          {canManageGmail && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void technicalQueriesApi.startGmail().then((result) => { if (result.ok) window.location.assign(result.data.authorization_url); else setError(result.error.message); })}>Connect Gmail again</Button>}
        </div>)}
        {mailboxes.filter((mailbox) => mailbox.connection_state === "active").map((mailbox) => <div key={mailbox.id} className="mt-4 rounded border border-ink-700 p-3 text-xs text-slateish-200" data-testid="mailbox-status">
          <p>Mailbox {mailbox.email} is active. {mailbox.last_checked_at ? <>Last checked at <span data-testid="last-checked">{formatWhen(mailbox.last_checked_at)}</span>.</> : "Not checked yet."}</p>
          {mailbox.import_job && (mailbox.import_job.state === "running" || (mailbox.import_job.state === "queued" && !mailbox.import_job.error)) && <p role="status" data-testid="import-progress">{mailbox.import_job.kind === "poll" ? "Checking" : "Importing"}: read {mailbox.import_job.done} of {mailbox.import_job.total} messages, {mailbox.import_job.imported ?? mailbox.import_job.done} imported{mailbox.import_job.failed ? `, ${mailbox.import_job.failed} failed` : ""}. The list below fills as they arrive. You can leave this page; it carries on.</p>}
          {mailbox.import_job?.state === "done" && mailbox.import_job.kind === "import" && <p data-testid="import-done">{importDoneWords(mailbox.import_job)}</p>}
          {(mailbox.import_job?.state === "failed" || (mailbox.import_job?.state === "queued" && mailbox.import_job.error)) && <p role="alert" className="text-warn-500">{mailbox.import_job?.error}</p>}
          {mailbox.import_job && mailbox.import_job.failures.length > 0 && <ul className="mt-1 list-disc pl-5 text-warn-500" data-testid="import-failures">{mailbox.import_job.failures.map((failure, index) => <li key={index}>{failure.subject}: {failure.reason}</li>)}</ul>}
          <Button variant="secondary" size="sm" disabled={busy || importing} onClick={() => { setError(null); void technicalQueriesApi.checkNow(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }}>Check now</Button>

          <Button variant="secondary" size="sm" disabled={busy || importing} onClick={() => setConfirming({ kind: "again", mailboxId: mailbox.id })}>Import the label again</Button>
          {confirming?.kind === "again" && confirming.mailboxId === mailbox.id && <div role="alertdialog" aria-label="Confirm importing the label again" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-import-again">
            <p>This reads all {mailbox.import_job?.total ? `${mailbox.import_job.total} ` : ""}emails of the label again. Only new emails, our own replies and unread files are added. Nothing already here changes, and no query is made twice.</p>
            <Button variant="primary" size="sm" disabled={busy} onClick={() => { setConfirming(null); setError(null); void technicalQueriesApi.importAgain(mailbox.id).then((result) => { if (!result.ok) { setError(result.error.message); return; } void technicalQueriesApi.mailboxes().then((listed) => { if (listed.ok) setMailboxes(listed.data.items); }); }); }}>Yes, read the label again</Button>
            <Button variant="secondary" size="sm" onClick={() => setConfirming(null)}>Cancel</Button>
          </div>}
        </div>)}
            </>,
            messages: <>
        {gmailReturn === "admin_must_allow" && <p role="alert" className="mt-4 text-sm text-warn-500">Your company's Google admin must allow this app.</p>}
        {gmailReturn === "working" && <p role="status" className="mt-4 text-sm text-slateish-300">Finishing the Gmail connection.</p>}
        {gmailReturn === "connected" && !mailboxes.some((mailbox) => mailbox.connection_state === "active") && <p role="status" className="mt-4 text-sm text-slateish-300">Gmail is connected. Choose the label to import below.</p>}
        {error && <p role="alert" className="mt-4 text-sm text-danger-500">{error}</p>}
            </>,
            more: (canManageGmail || rules !== null) ? <>
        {canManageGmail && <div className="text-xs text-slateish-200" data-testid="prepare-all">
          <Button variant="secondary" size="sm" disabled={busy || preparingAll} onClick={() => { setError(null); void technicalQueriesApi.prepareAllPlan().then((result) => { if (result.ok) setPrepareAll({ plan: result.data, asking: true }); else setError(result.error.message); }); }}>Find the sources for every query not prepared yet</Button>
          {prepareAll?.asking && <div role="alertdialog" aria-label="Confirm preparing all" className="mt-2 rounded border border-warn-500 p-2" data-testid="confirm-prepare-all">
            <p>{prepareAllWords(prepareAll.plan)}</p>
            {prepareAll.plan.unprepared > 0 && <Button variant="primary" size="sm" onClick={() => void technicalQueriesApi.prepareAllStart().then((result) => { if (result.ok) setPrepareAll({ plan: result.data, asking: false }); else { setPrepareAll(null); setError(result.error.message); } })}>Yes, prepare them</Button>}
            <Button variant="secondary" size="sm" onClick={() => setPrepareAll(null)}>{prepareAll.plan.unprepared > 0 ? "Cancel" : "Close"}</Button>
          </div>}
          {prepareAll && !prepareAll.asking && <p role="status" className="mt-1" data-testid="prepare-all-progress">{prepareAll.plan.waiting_or_running > 0 ? `Finding sources in the background: ${prepareAll.plan.waiting_or_running} still to do.` : "Every query has been searched."}</p>}
        </div>}
          {rules !== null && <details className="rounded border border-ink-700 p-2 text-xs text-slateish-300"><summary className="cursor-pointer">Rules for who it goes to ({rules.length})</summary>
            <p className="mt-2 text-slateish-400">Set each rule once. A contractor code in the query number sets the contractor. A discipline code sets the department. If the number has no code, the sender's email address or domain is used. A rule fills only empty fields, for new and existing queries. A public email domain cannot be used; an exact address can.</p>
            <ul className="mt-2 space-y-1">{rules.map((rule) => <li key={rule.id} className="flex items-center justify-between gap-2"><span>{RULE_WORDS[rule.match_type] ?? rule.match_type} {rule.match_value} → {rule.contractor_name || "—"} / {rule.department || "—"}</span><Button variant="secondary" size="sm" onClick={() => void technicalQueriesApi.deleteRoutingRule(rule.id).then((result) => { if (result.ok) setRules(result.data.items); else setError(result.error.message); })}>Remove</Button></li>)}</ul>
            <div className="mt-2 space-y-1">
              <select aria-label="Rule type" value={ruleType} onChange={(event) => setRuleType(event.target.value as RoutingRuleType)} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5">{(Object.keys(RULE_WORDS) as RoutingRuleType[]).map((type) => <option key={type} value={type}>{RULE_WORDS[type]}</option>)}</select>
              <input aria-label="Rule value" value={ruleValue} onChange={(event) => setRuleValue(event.target.value)} placeholder={{ contractor_code: "the contractor code in the number, e.g. ABC", discipline: "a discipline code, e.g. PRO", domain: "company.example", address: "person@company.example" }[ruleType]} className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule contractor" value={ruleContractor} onChange={(event) => setRuleContractor(event.target.value)} placeholder="Contractor" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <input aria-label="Rule department" value={ruleDepartment} onChange={(event) => setRuleDepartment(event.target.value)} placeholder="Department" className="w-full rounded border border-ink-600 bg-ink-900 p-1.5" />
              <Button variant="secondary" size="sm" disabled={!ruleValue.trim()} onClick={() => { setError(null); void technicalQueriesApi.saveRoutingRule({ match_type: ruleType, match_value: ruleValue.trim(), contractor_name: ruleContractor.trim() || null, department: ruleDepartment.trim() || null }).then((result) => { if (result.ok) { setRules(result.data.items); setRuleValue(""); setRuleContractor(""); setRuleDepartment(""); } else setError(result.error.message); }); }}>Save rule</Button>
            </div></details>}
            </> : null,
            handForm: <>
          {handOpen && <div className="mt-2 space-y-1 rounded border border-ink-700 p-3 text-xs text-slateish-300" aria-label="New query by hand">
            <p className="text-slateish-400">For a query that did not come by email. Files you add are checked for macros and scripts. This is not a virus scan.</p>
            <label className="block">Subject<input value={handSubject} onChange={(event) => setHandSubject(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Contractor<input value={handContractor} onChange={(event) => setHandContractor(event.target.value)} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">The question, as asked<textarea value={handBody} onChange={(event) => setHandBody(event.target.value)} rows={4} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-1.5" /></label>
            <label className="block">Papers (optional)<input type="file" multiple onChange={(event) => setHandFiles(Array.from(event.target.files ?? []))} className="mt-1 w-full" /></label>
            <Button variant="primary" size="sm" disabled={busy || !handSubject.trim() || !handBody.trim()} onClick={createByHand}>Create query</Button>
          </div>}
            </>,
            filters: <>
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
            <label className="block text-xs text-slateish-300" htmlFor="query-evidence-filter">Sources</label>
            <select id="query-evidence-filter" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100"><option value="">Any</option><option value="verified">Verified</option><option value="needs_review">Needs review</option><option value="conflicting">Conflicting</option><option value="ambiguous">Ambiguous</option><option value="missing">Missing</option><option value="rejected">Rejected</option></select>
            <label className="block text-xs text-slateish-300" htmlFor="query-type-filter">Type</label>
            <select id="query-type-filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100"><option value="">Any</option><option value="TQ">TQ: technical query</option><option value="CFC">CFC: conflict finding clarification</option></select>
            <label className="block text-xs text-slateish-300" htmlFor="query-discipline-filter">Discipline code</label>
            <input id="query-discipline-filter" value={disciplineFilter} onChange={(event) => setDisciplineFilter(event.target.value)} className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <label className="block text-xs text-slateish-300" htmlFor="query-number-filter">Running number</label>
            <input id="query-number-filter" value={numberFilter} onChange={(event) => setNumberFilter(event.target.value)} inputMode="numeric" className="w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <label className="flex items-center gap-2 text-xs text-slateish-300"><input type="checkbox" checked={needsPersonFilter} onChange={(event) => setNeedsPersonFilter(event.target.checked)} />Needs a person: the subject has no full number</label>
            <Button variant="secondary" size="sm" onClick={applyFilters}>Refresh and apply filters</Button>
          </div>
          )}
        </div>
            </>,
          }} />

      </section>
      {/* min-w-0 + wrapping anywhere: a long unbroken line in a mail (a link, a disclaimer) can never widen the page past the window */}
      <section ref={detailRef} className="min-w-0 overflow-x-hidden rounded border border-ink-700 bg-ink-850 p-5 [overflow-wrap:anywhere]">
        {!selected ? <p className="text-sm text-slateish-500">Choose a query to see its email and history.</p> : <>
          {/* READ IN TEN SECONDS (owner, 26 Nov 2026 22:41): one plain sentence first, then where it stands as four marks */}
          <p data-testid="query-headline" className="text-xl font-semibold leading-snug text-slateish-100">{queryHeadline(selected, questionDraft)}</p>
          <h2 className="mt-1 text-sm font-medium text-slateish-400">{selected.subject}</h2>
          <p data-testid="query-status" className="mt-1 text-sm text-slateish-300">{plainStatus(selected.status, selected.priority)}</p>
          {problemChips(selected).map((p) => <p key={p.words} data-testid="query-problem" className="mt-1 text-sm text-warn-500"><strong className="font-semibold">{p.words}.</strong> {p.why}</p>)}
          <ol data-testid="query-summary" aria-label="Where this query stands" className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {querySteps(selected, questionDraft).map((step) => <li key={step.label} className={step.state === "done" ? "text-slateish-100" : "text-slateish-400"}><span aria-hidden="true" className="mr-1 font-semibold">{step.state === "done" ? "✓" : step.state === "working" ? "…" : "○"}</span>{step.label}{step.state === "working" ? " (working)" : step.state === "todo" ? " (not yet)" : ""}</li>)}
          </ol>
          {/* WHAT THE CONTRACTOR'S FORM CITES, first (owner via builder A, 27 Nov 2026): each citation and whether we hold it */}
          {selected.ready?.cited?.length ? <div data-testid="contractor-cites" className="mt-3 text-sm">
            <p className="font-semibold text-slateish-200">What the contractor&rsquo;s form cites</p>
            <ul className="mt-1 space-y-0.5">{selected.ready.cited.map((c, i) => <li key={`${i}-${c.line}`} className={c.held ? "text-slateish-300" : "text-warn-500"}><span aria-hidden="true" className="mr-1 font-semibold">{c.held ? "\u2713" : ""}</span>{c.line}</li>)}</ul>
          </div> : null}
          {selected.source_access_revoked && <p role="alert" className="mt-3 text-sm text-warn-500">Access to a source changed. A reviewer must check the reply before it shows again.</p>}
          {/* ANSWER FIRST (owner's G9 "easy to use", E5, 26 Nov 2026): the question, the proposed response and the decisions
              come first; the email, its attachments and the evidence are folded below. Reorder only: the same parts, words and actions. */}
          {/* WHAT THE CONTRACTOR IS ASKING (owner, 26 Nov 2026 21:29 and 21:36): one readable ask, already filled, with where each
              request was found; edit only if a line is wrong; confirming is a check, it sends nothing. Honest marks, never a gate. */}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">What the contractor is asking</h3>
          {selected.confirmed_question
            ? <p className="mt-1 text-xs text-slateish-400">Checked by an engineer{selected.confirmed_question_at ? ` on ${formatWhen(selected.confirmed_question_at)}` : ""}.</p>
            : (selected.ready && questionDraft.trim()) ? null // the server's own mark says it ("proposed by the system; no engineer has confirmed it yet")
            : <p className="mt-1 text-xs text-warn-500">{questionDraft.trim() ? "Suggested by the AI from the email and its files. Nobody has checked it yet." : "No question found. Type it below."}</p>}
          {proposalNoteWords(selected.proposal_note, Boolean(selected.proposed_question)) && <p className="mt-1 text-xs text-warn-500" data-testid="proposal-note">{proposalNoteWords(selected.proposal_note, Boolean(selected.proposed_question))}</p>}
          {!editingQuestion && questionDraft.trim() ? (
            <div data-testid="question-readable" className="mt-2 rounded border border-ink-700 p-3 text-sm text-slateish-100">
              {(() => {
                const lines = readableLines(questionDraft, selected.proposed_questions);
                const lead = lines.filter((l) => l.kind === "lead");
                const items = lines.filter((l) => l.kind === "item");
                return <>
                  {lead.flatMap((l, i) => leadParagraphs(l.text).map((part, j) => <p key={`lead-${i}-${j}`} className={`whitespace-pre-wrap${i + j > 0 ? " mt-2" : ""}`}>{part}</p>))}
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
          <TechnicalQueryCrossRefs refs={selected.cross_refs} onOpen={openQuery} />
          {!selected.confirmed_question && notInText(questionDraft, selected.proposed_questions).length > 0 && <details className="mt-1" data-testid="found-more"><summary className="cursor-pointer text-xs text-slateish-300">Show the other lines found on the form</summary>
            {notInText(questionDraft, selected.proposed_questions).map((part, index) => <p key={`${part.filename}-${part.page}-${index}`} className="mt-1 text-sm text-slateish-300">{part.question}<span className="block text-xs text-slateish-500">found in {part.filename}, page {part.page} · <LinkButton onClick={() => setQuestionDraft((current) => withRequest(current, part.question))}>Add to the list</LinkButton></span></p>)}
          </details>}
          {(["received", "triage", "drafting", "changes_requested"].includes(selected.status)) && <div className="mt-2">
            {editingQuestion || !questionDraft.trim() ? <>
              <label htmlFor="technical-query-question" className="block text-xs text-slateish-300">Edit the question (one question per numbered line)</label>
              <textarea id="technical-query-question" value={questionDraft} onChange={(event) => setQuestionDraft(event.target.value)} rows={6} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            </> : <Button variant="secondary" size="sm" onClick={() => setEditingQuestion(true)}>Edit</Button>}
            {selected.ready && questionDraft.trim() && questionDraft.trim() !== selected.ready.question.trim() && <Button variant="secondary" size="sm" disabled={busy} onClick={saveQuestion}>Save and find the sources again</Button>}
            <Button variant="primary" size="sm" disabled={busy || !selected.can_review || !questionDraft.trim() || questionDraft.trim() === (selected.confirmed_question || "")} title={selected.can_review ? undefined : "Only a qualified reviewer can confirm the question"} onClick={confirmQuestion}>Confirm</Button>
            <p className="mt-1 text-xs text-slateish-400">Confirm means you checked it. Nothing is sent.</p>
            <InfoFold title="About checking the question" className="mt-1 text-xs">Confirm means you checked this is the contractor's question. Nothing is sent. Confirm is optional: approving the reply also records the question. If you edit it, the sources are found again and the reply is written again.</InfoFold>
            {!selected.can_review && <p className="mt-1 text-xs text-slateish-500">Only a reviewer can confirm the question.</p>}
          </div>}
          {/* WHAT THE CONTRACT OR STANDARD SAYS (owner, 26 Nov 2026 22:41): the sources the reply stands on, each with its source, clause
              and page, before the reply; a cited source not yet confirmed can be confirmed right here */}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">What the contract or standard says</h3>
          {honestMarks(selected, questionDraft).evidence.map((mark) => <p key={mark} data-testid="evidence-mark" className="mt-1 text-xs text-warn-500">{mark}</p>)}
          {(() => {
            const byId = new Map((selected.evidence ?? []).map((e) => [e.id, e]));
            const cites = draftCitations(selected.drafts?.at(-1)?.citations_json);
            if (!cites.length) return <p className="mt-1 text-sm text-slateish-400">{currentSources(selected.evidence).length ? "No reply uses a source yet. All sources found are listed below." : "No source found yet."}</p>;
            return <ul data-testid="reply-sources" className="mt-2 space-y-3">{cites.map((citation) => { const e = (citation as { evidence_id?: string }).evidence_id ? byId.get((citation as { evidence_id?: string }).evidence_id!) : undefined; return <li key={citation.label} className="border-l-2 border-signal-500 pl-3 text-sm">
              <Quote text={citation.exact_quote} words={askWords(questionDraft)} />
              <p className="mt-1 text-xs text-slateish-400">[{citation.label}] <a className="underline" href={`/api/documents/${encodeURIComponent(citation.document_id)}/original#page=${citation.page}`} title={`Open ${e?.source_name || "the source document"}, page ${citation.page}`} target="_blank" rel="noreferrer">{e?.source_name || e?.source_kind ? `${sourceLinkLabel(e?.source_name, e?.source_kind)}, ` : ""}{e?.locator ? `${e.locator}, ` : ""}page {citation.page}</a>
                {e && e.supersession_state === "unknown" && isAdmin && confirmOnce(e.document_id) && <><Button variant="secondary" size="sm" data-testid="confirm-source" disabled={busy} onClick={() => confirmSource(e.document_id)}>Confirm source document</Button><span data-testid="confirm-source-hint" className="ml-2 text-slateish-400">{CONFIRM_SOURCE_HINT}</span></>}
                {e && e.supersession_state === "unknown" && !isAdmin && <span className="ml-2 text-warn-500">its revision is not confirmed yet</span>}</p>
            </li>; })}</ul>;
          })()}
          <h3 className="mt-6 text-sm font-semibold text-slateish-200">Proposed reply{selected.status !== "approved" && selected.drafts?.length ? <span className="ml-2"><StatusChip word="AI, to be checked" testId="ai-to-check" /></span> : null}</h3>
          {readyLine(selected.ready) && <p role="status" data-testid="ready-line" className="mt-1 text-xs text-slateish-300">{readyLine(selected.ready)}</p>}
          {draftAuthor(selected.drafts?.at(-1)) && <p data-testid="draft-author" className="mt-1 text-xs text-slateish-400">{draftAuthor(selected.drafts?.at(-1))}</p>}
          {/* THE OLD REPLY WHILE IT IS REWRITTEN (owner's live walk, 27 Nov 2026 01:15): greyed and said, never shown as the current one */}
          {selected.drafts?.length ? (replyBeingRewritten(selected.ready)
            ? <div data-testid="reply-being-rewritten" className="mt-2 rounded border border-dashed border-ink-600 p-2"><p className="text-xs font-semibold text-slateish-200">Old reply. A new one is being written and will replace it.</p><p className="mt-1 whitespace-pre-wrap text-sm text-slateish-400">{selected.drafts.at(-1)?.answer}</p></div>
            : <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{selected.drafts.at(-1)?.answer}</p>) : <p className="mt-2 text-sm text-slateish-500">No draft yet.</p>}
          {/* COMPANY's usual cost / schedule sentence, OFFERED (lead-4's final design): the engineer adds it to their own reply, never the code */}
          {selected.drafts?.length ? <TechnicalQueryPosition position={selected.ready?.position} canEdit={EDITABLE.includes(selected.status)}
            onAdd={() => { setEditedAnswer((current) => withPositionLine(current || selected.drafts?.at(-1)?.answer || "", selected.ready?.position?.line ?? "")); if (redoRef.current) redoRef.current.open = true; window.setTimeout(() => document.getElementById("technical-query-answer")?.focus(), 0); }} /> : null}
          {!selected.drafts?.length && !searching && <div className="mt-3"><Button variant="secondary" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id, "local", []))}>Write the reply</Button><p className="mt-1 text-xs text-slateish-400">The AI on this computer writes a reply from the sources found. Nothing is sent.</p></div>}
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
                <Button variant="primary" disabled={busy} onClick={approveOnce}>Approve the reply</Button>
                <Button variant="secondary" disabled={busy} onClick={() => setSendingBack(true)}>Send back with a note</Button>
              </div>
              <p data-testid="decision-hint" className="mt-1 text-xs text-slateish-400">{decision.hint}</p>
              {split.keep.length + split.reject.length > 0 && <p className="mt-1 text-xs text-slateish-400">Approving keeps the {split.keep.length} source{split.keep.length === 1 ? "" : "s"} the reply cites and rejects the other {split.reject.length} found for this question. You can change any of them under &ldquo;All sources found&rdquo; first.</p>}
              {sendingBack && <div data-testid="send-back" className="mt-2 rounded border border-ink-700 p-2">
                <label htmlFor="technical-query-send-back" className="block text-xs text-slateish-300">What should change in the reply?</label>
                <textarea id="technical-query-send-back" value={backNote} onChange={(event) => setBackNote(event.target.value)} rows={3} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Button variant="secondary" size="sm" disabled={busy || !backNote.trim()} onClick={() => { const note = backNote.trim(); setSendingBack(false); setBackNote(""); act(() => technicalQueriesApi.decide(selected.id, "request_changes", selected.drafts?.at(-1)?.id, note)); }}>Send back</Button>
                  <Button variant="secondary" size="sm" onClick={() => { setSendingBack(false); setBackNote(""); }}>Cancel</Button>
                </div>
                <p className="mt-1 text-xs text-slateish-400">The reply is written again with your note. Nothing is sent to the contractor.</p>
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
                  ? <Button variant="secondary" size="sm" disabled aria-describedby="word-reply-hint">Download the reply as a Word file</Button>
                  : <a className="rounded border border-ink-600 px-3 py-1.5 text-xs text-slateish-200" href={`/api/technical-queries/${selected.id}/response.docx`}>Download the reply as a Word file</a>}
                {["approved", "sent", "awaiting_confirmation"].includes(selected.status) && selected.can_review ? <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => technicalQueriesApi.confirmResolution(selected.id))}>Mark as answered</Button> : null}
              </div>
              <p id="word-reply-hint" className="mt-1 text-xs text-slateish-400">{whyNot ? `${whyNot} ` : ""}A Word file of the approved reply. Send it to the contractor yourself: the app sends no email.{["approved", "sent", "awaiting_confirmation"].includes(selected.status) && selected.can_review ? " After you have sent it, press Mark as answered." : ""}</p>
            </div>;
          })() : null}
          {/* REDO, folded and quiet (owner, 27 Nov 2026 00:02): each line says what it does and that it replaces the reply above */}
          <details ref={redoRef} data-testid="more-actions" className="mt-4 rounded border border-ink-700 p-2">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Redo: change the reply or write it again</summary>
            <p className="mt-1 text-xs text-slateish-400">Each of these replaces the reply above. Nothing is sent.</p>
          {EDITABLE.includes(selected.status) && <div className="mt-3">
            <label htmlFor="technical-query-answer" className="block text-sm text-slateish-300">Write the reply yourself</label>
            <textarea id="technical-query-answer" value={editedAnswer} onChange={(event) => setEditedAnswer(event.target.value)} rows={8} className="mt-2 w-full rounded border border-ink-600 bg-ink-900 p-2 text-sm text-slateish-100" />
            <Button variant="secondary" size="sm" disabled={busy || !editedAnswer.trim()} onClick={() => act(() => technicalQueriesApi.createDraft(selected.id, editedAnswer.trim()))}>Save my reply for approval</Button>
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
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => technicalQueriesApi.generateDraft(selected.id, engine, engine === "claude" ? claudeDocs : []))}>Write the reply again</Button>
              <p className="mt-1 text-xs text-slateish-400">The AI chosen above writes a new reply. It replaces the one above.</p>
            </div>
            {/* not on the happy path (owner, 26 Nov 2026): the sources are found by themselves; this is for a query with none yet, or
                when the ask was edited since they were found */}
            {!searching && !refreshing && (!(selected.evidence?.length) || questionEdited || staleSources(selected) || selected.ready?.evidence_fresh === false || selected.ready?.evidence === "failed") && <div className="mt-2">
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => technicalQueriesApi.prepareEvidence(selected.id))}>{selected.evidence?.length ? "Find the sources again" : "Find the sources"}</Button>
              <p className="mt-1 text-xs text-slateish-400">Search the contract and standards again. A new reply then replaces the one above.</p>
            </div>}
            {(() => {
              const split = citedSplit(selected.evidence, selected.drafts?.at(-1)?.citations_json);
              const any = split.keep.length + split.reject.length > 0;
              return selected.can_review && selected.drafts?.length && any ? <div className="mt-2" data-testid="keep-cited">
                <Button variant="secondary" size="sm" disabled={busy} onClick={keepCited}>Keep the sources the reply cites, reject the others</Button>
                <p className="mt-1 text-xs text-slateish-400">Keeps {split.keep.length} the reply cites and rejects the other {split.reject.length} found for this question. Approving does this too. You can change any of them below.</p>
              </div> : null;
            })()}
          </details>
          {selected.evidence_job && (selected.evidence_job.state === "queued" || selected.evidence_job.state === "running") && <p role="status" className="mt-3 text-xs text-slateish-300" data-testid="evidence-progress">Finding the sources: {selected.evidence_job.label ?? "queued"}{selected.evidence_job.progress_total > 0 ? ` (${selected.evidence_job.progress_done} of ${selected.evidence_job.progress_total})` : ""}. You can leave this page; it carries on.</p>}
          {selected.evidence_job?.state === "failed" && <p role="alert" className="mt-3 text-xs text-warn-500">The sources could not be found: {selected.evidence_job.error}</p>}
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
            {selected.routing_source?.startsWith("rule:") && <p className="text-xs text-slateish-400 sm:col-span-2">A rule set the contractor and department. Save to confirm them, or change them.</p>}
            <div className="sm:col-span-2">
              <Button variant="secondary" size="sm" disabled={busy} onClick={saveWho}>Save who handles it</Button>
              <p className="mt-1 text-xs text-slateish-400">Saves everything above at once. Nothing is sent to anyone.</p>
            </div>
          </div>
          </details>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-email-question">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Show the question as written in the email</summary>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-300">{(selected.extracted_question_main ?? selected.extracted_question) || selected.email_question_note || "Not stated in the email text."}</p>
            <Folded text={selected.extracted_question_folded} />
            {selected.attachment_reading?.map((part) => <p key={part.filename} className="mt-6 text-xs text-slateish-400" data-testid="attachment-reading">{part.line}</p>)}
            {selected.attachment_text_hidden && <p className="mt-6 text-xs text-warn-500">The attached file's text is hidden: you cannot open that file.</p>}
            {selected.attachment_context?.length ? <>
              <h3 className="mt-6 text-sm font-semibold text-slateish-200">Text of the attached files</h3>
              {selected.attachment_context.map((part) => <div key={`${part.filename}-${part.page}`} className="mt-2 rounded border border-ink-700 p-2 text-sm text-slateish-300"><p className="text-xs text-slateish-500">{part.filename}, page {part.page}</p><p className="mt-1 whitespace-pre-wrap">{part.text}</p></div>)}
            </> : null}
          </details>
          <details className="mt-6 rounded border border-ink-700 p-2" data-testid="tq-folded-mail">
            <summary className="cursor-pointer text-sm font-semibold text-slateish-200">Show the original email and its files</summary>
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
                {attachment.document_id && !attachment.filed_at && <span data-testid="attachment-unfiled"> · kept out of the library: not found by search, Chat or the review list{selected.can_review ? <> <select aria-label="Role to add this file under" value={fileRole} onChange={(event) => setFileRole(event.target.value)} className="ml-1 rounded border border-ink-600 bg-ink-900 p-1 text-xs"><option value="SUPPORTING_DOCUMENT">Supporting document</option><option value="CONTRACTOR_SUBMITTAL">Contractor submittal</option><option value="SPECIFICATION">Specification</option><option value="CONTRACT_DOCUMENT">Contract document</option><option value="COMPANY_STANDARD">Company standard</option></select> <Button variant="secondary" size="sm" disabled={busy} onClick={() => setConfirming({ kind: "file", attachmentId: attachment.id })}>File into the library</Button>{confirming?.kind === "file" && confirming.attachmentId === attachment.id && <span role="alertdialog" aria-label="Confirm filing" className="ml-2 rounded border border-warn-500 p-1" data-testid="confirm-file">Add this file to the library? It then shows in search, Chat and the review list, for the role you choose. <Button variant="primary" size="sm" disabled={busy} onClick={() => { setConfirming(null); act(() => technicalQueriesApi.fileIntoLibrary(selected.id, attachment.id, fileRole)); }}>Yes, file it</Button> <Button variant="secondary" size="sm" onClick={() => setConfirming(null)}>Cancel</Button></span>}</> : null}</span>}
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
