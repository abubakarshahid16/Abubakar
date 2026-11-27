import { InfoFold } from "../components/look/LookParts";
import { NEW_LOOK } from "../look";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, InlineErrorState, Spinner, StatusBadge } from "../components/states";

import { deliverables as deliverablesApi, management, risks as risksApi } from "../api/client";
import type { Deliverable, DeliverableCreate, DeliverableStatus, DeliverableStakeholder, StakeholderRole } from "../types/api";
import type { EscalationRule } from "../types/api";
import { Button, Fold, LinkButton, PageHeader, SectionTitle, Tag, TextField } from "../components/kit/Kit";

/** Expected deliverables shown before the fold (H's audit #45, 27 Nov 2026: 41 rows made a 7,330 px page); the rest stay one click away, counted. */
export const EXPECTED_SHOWN = 8;

const statuses: DeliverableStatus[] = ["planned", "in_progress", "submitted", "under_review", "approved", "rejected", "superseded"];

type Panel = "register" | "alerts" | "rules" | "expected" | "risks";
type Settled<T> = { ok: true; data: T } | { ok: false; error: { message: string } };

/** An expected deliverable's title as shown: the server's "Inferred ..." titles lose the word "Inferred" (the "AI suggested" label beside
 *  them already says it, in everyday words); the stored title stays as it is. */
export function expectedTitle(title: string): string {
  const rest = title.replace(/^inferred\s+/i, "");
  return rest === title ? title : rest.charAt(0).toUpperCase() + rest.slice(1);
}

/** A status in everyday words (the stored value stays as it is). */
export function statusWords(status: string): string {
  return status === "superseded" ? "replaced by a later revision" : status.replaceAll("_", " ");
}

/** The new look's one line: how many are listed and how many are LATE: past the due date (an item due today is not late yet, as on the
 *  Dashboard), out of the open ones with a due date; with none, "late" is not counted (rule 4: a count states its boundary). */
export function deliverablesSummary(items: Deliverable[], alerts: { days_overdue: number }[]): string {
  if (items.length === 0) return "No deliverable is listed yet: add the first one below.";
  const listed = `${items.length} deliverable${items.length === 1 ? "" : "s"} listed`;
  const withDue = items.filter((d) => d.status !== "approved" && d.status !== "superseded" && /^\d{4}-\d{2}-\d{2}/.test((d.due_date ?? "").trim())).length;
  if (withDue === 0) return `${listed}; late: not counted, none open has a due date.`;
  const late = alerts.filter((a) => a.days_overdue > 0).length;
  return `${listed}; ${late} late, of ${withDue} open with a due date.`;
}

export function DeliverablesView() {
  const [items, setItems] = useState<Deliverable[]>([]);
  const [alerts, setAlerts] = useState<{ title: string; days_overdue: number; escalation_level: number; severity: string }[]>([]);
  // EACH PANEL LOADS ON ITS OWN (#608). One slow or failed request (the risk
  // register once hung the whole screen on "Loading deliverables") shows its
  // own spinner or error and never blocks the WBS register.
  const [pending, setPending] = useState<Record<Panel, boolean>>({ register: true, alerts: true, rules: true, expected: true, risks: true });
  const [panelErrors, setPanelErrors] = useState<Partial<Record<Panel, string>>>({});
  const [error, setError] = useState<string | null>(null);
  // WHICH LISTS ARE KNOWN. A list whose request failed is not an empty list
  // (audit 2026-09-30): the error box and "No deliverables have been
  // registered yet." used to show together. Its empty text now shows only
  // when it was loaded successfully.
  const [registerLoaded, setRegisterLoaded] = useState(false);
  const [expectedLoaded, setExpectedLoaded] = useState(false);
  const [risksLoaded, setRisksLoaded] = useState(false);
  const [risksTotal, setRisksTotal] = useState(0);
  const [rules, setRules] = useState<EscalationRule[]>([]);
  const [stakeholders, setStakeholders] = useState<Record<string, DeliverableStakeholder[]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<import("../types/api").WbsWorkspace | null>(null);
  const [expected, setExpected] = useState<import("../types/api").ExpectedDeliverable[]>([]);
  const [risks, setRisks] = useState<import("../types/api").Risk[]>([]);
  const [riskType, setRiskType] = useState<import("../types/api").RiskType>("schedule");
  const [riskTitle, setRiskTitle] = useState("");
  const [stakeholderUser, setStakeholderUser] = useState("");
  const [stakeholderRole, setStakeholderRole] = useState<StakeholderRole>("reviewer");
  const [form, setForm] = useState<DeliverableCreate>({ wbs_code: "1.0", title: "", deliverable_type: "Engineering submittal", due_date: "" });

  const load = useCallback(() => {
    setError(null); setPanelErrors({});
    setPending({ register: true, alerts: true, rules: true, expected: true, risks: true });
    const settle = <T,>(panel: Panel, request: Promise<Settled<T>>, onOk: (data: T) => void, onFail?: () => void) => {
      request
        .then((result) => {
          if (result.ok) onOk(result.data);
          else { onFail?.(); setPanelErrors((current) => ({ ...current, [panel]: result.error.message })); }
        })
        .catch(() => { onFail?.(); setPanelErrors((current) => ({ ...current, [panel]: "The app's server did not answer. Nothing changed. Reload the page to try again." })); })
        .finally(() => setPending((current) => ({ ...current, [panel]: false })));
    };
    settle("register", deliverablesApi.list(), (data) => { setItems(data.deliverables); setRegisterLoaded(true); }, () => { setItems([]); setRegisterLoaded(false); });
    settle("alerts", deliverablesApi.alerts(), (data) => setAlerts(data.alerts));
    settle("rules", management.escalationRules(), (data) => setRules(data.rules));
    settle("expected", deliverablesApi.expected(), (data) => { setExpected(data.deliverables); setExpectedLoaded(true); }, () => setExpectedLoaded(false));
    settle("risks", risksApi.list(riskType), (data) => { setRisks(data.risks); setRisksTotal(data.total); setRisksLoaded(true); }, () => setRisksLoaded(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function create() {
    if (!form.title.trim()) return;
    const result = await deliverablesApi.create({ ...form, title: form.title.trim() });
    if (!result.ok) { setError(result.error.message); return; }
    setItems((current) => [...current, result.data].sort((a, b) => a.wbs_code.localeCompare(b.wbs_code)));
    setForm((current) => ({ ...current, title: "", due_date: "" }));
  }

  async function changeStatus(item: Deliverable, status: DeliverableStatus) {
    const result = await deliverablesApi.update(item.id, { status });
    if (result.ok) setItems((current) => current.map((entry) => entry.id === item.id ? result.data : entry));
    else setError(result.error.message);
  }

  async function showStakeholders(item: Deliverable) {
    setSelected(item.id);
    if (stakeholders[item.id]) return;
    const result = await deliverablesApi.stakeholders(item.id);
    if (result.ok) setStakeholders((current) => ({ ...current, [item.id]: result.data.stakeholders }));
    else setError(result.error.message);
    const workspaceResult = await deliverablesApi.workspace(item.id);
    if (workspaceResult.ok) setWorkspace(workspaceResult.data);
    else setError(workspaceResult.error.message);
  }

  async function assignStakeholder() {
    if (!selected || !stakeholderUser.trim()) return;
    const existing = stakeholders[selected] ?? [];
    const result = await deliverablesApi.replaceStakeholders(selected, [
      ...existing.map((person) => ({ user_id: person.user_id, role: person.role })),
      { user_id: stakeholderUser.trim(), role: stakeholderRole },
    ]);
    if (result.ok) {
      setStakeholders((current) => ({ ...current, [selected]: result.data.stakeholders }));
      setStakeholderUser("");
    } else setError(result.error.message);
  }

  async function createRisk() {
    if (!riskTitle.trim()) return;
    const result = await risksApi.create({ risk_type: riskType, title: riskTitle.trim(), description: "Created from the project risk register." });
    if (result.ok) { if (result.data.risk_type === riskType) { setRisks((current) => [result.data, ...current]); setRisksTotal((n) => n + 1); } setRiskTitle(""); }
    else setError(result.error.message);
  }

  const shownError = [error, ...Object.values(panelErrors)].filter((message): message is string => Boolean(message)).join(" ");

  // SAID ONCE (H's gate of #1971, audit 44): when every row has the same state or the same origin, it is said once above the list and
  // not on each row; a state or an origin that differs between rows stays on its row
  const sameState = expected.length > 1 && expected.every((e) => e.state === expected[0].state);
  const sameOrigin = expected.length > 1 && expected.every((e) => e.origin === expected[0].origin);
  const saidOnce = [
    sameState ? `All ${expected.length} are ${expected[0].state === "missing" ? "not in the deliverables list yet" : expected[0].state.replaceAll("_", " ")}.` : null,
    sameOrigin ? (expected[0].origin === "inferred" ? "All were suggested by the AI: check each before accepting it." : "All were added by hand.") : null,
  ].filter(Boolean).join(" ");
  const expectedRow = (item: import("../types/api").ExpectedDeliverable) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="text-sm text-slateish-200">{expectedTitle(item.title)}{item.origin === "inferred" && item.source_name ? ` · from ${item.source_name}, ${item.source_page ? `page ${item.source_page}` : "page not recorded"}` : ""}</p><p className="text-xs text-slateish-500">Item {item.wbs_code} · {item.deliverable_type}{sameOrigin ? "" : ` · ${item.origin === "inferred" ? "suggested by the AI, check it before accepting" : "added by hand"}`}</p></div>{sameState ? null : <StatusBadge tone={item.state === "missing" ? "warn" : "good"}>{item.state === "missing" ? "not in the list yet" : item.state.replaceAll("_", " ")}</StatusBadge>}</div>;
  // the add form's one grid, the same in both looks (the grid-width check reads each grid once)
  const ADD_FORM_GRID = "xl:grid-cols-[130px_minmax(0,1fr)_180px_150px_auto]";
  const addForm = (
      <section>
        <SectionTitle>Add deliverable</SectionTitle>
        {NEW_LOOK ? (
        // each field says what it is above it, not only in a placeholder that vanishes once typed in (C's walk, 27 Nov 2026)
        <div className={`mt-3 grid items-end gap-2 ${ADD_FORM_GRID}`}>
          <TextField id="deliverable-number" label="Item number in the project list" value={form.wbs_code} onChange={(e) => setForm({ ...form, wbs_code: e.target.value })} placeholder="e.g. 1.1" />
          <TextField id="deliverable-title" label="Deliverable title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <TextField id="deliverable-type" label="Deliverable type" value={form.deliverable_type} onChange={(e) => setForm({ ...form, deliverable_type: e.target.value })} />
          <TextField id="deliverable-due" label="Due date" type="date" value={form.due_date ?? ""} onChange={(e) => setForm({ ...form, due_date: e.target.value || null })} />
          <Button variant="secondary" onClick={() => void create()}>Add</Button>
        </div>
        ) : (
        <div className={`mt-3 grid gap-2 ${ADD_FORM_GRID}`}>
          <input value={form.wbs_code} onChange={(e) => setForm({ ...form, wbs_code: e.target.value })} aria-label="Item number in the project list" placeholder="Number, e.g. 1.1" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} aria-label="Deliverable title" placeholder="Deliverable title" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.deliverable_type} onChange={(e) => setForm({ ...form, deliverable_type: e.target.value })} aria-label="Deliverable type" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input type="date" value={form.due_date ?? ""} onChange={(e) => setForm({ ...form, due_date: e.target.value || null })} aria-label="Due date" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <Button variant="secondary" onClick={() => void create()}>Add</Button>
        </div>
        )}
      </section>
  );
  const register = (
      <section>
        <SectionTitle>Deliverables list</SectionTitle>
      {pending.register ? <Spinner label="Loading deliverables" /> : !registerLoaded ? <p className="px-4 py-3 text-sm text-slateish-400">The deliverables list could not be loaded, so it is not known what is on it.</p> : items.length === 0 ? <EmptyState title="No deliverables have been registered yet." hint="Add one with the form on this page to start following it." /> : <div className="divide-y divide-ink-700/70">{items.map((item) => <div key={item.id} className="py-3"><div className={NEW_LOOK ? "grid gap-2 xl:grid-cols-[100px_minmax(0,1fr)_150px_170px_auto] xl:items-center" : "grid gap-2 xl:grid-cols-[100px_minmax(0,1fr)_150px_130px_150px_auto] xl:items-center"}>{NEW_LOOK ? <span><Tag>{item.wbs_code}</Tag></span> : <span className="font-mono text-xs text-signal-400">{item.wbs_code}</span>}<div><p className="text-sm text-slateish-200">{item.title}</p><p className="text-xs text-slateish-500">{item.deliverable_type} · revision {item.revision}</p></div><div className="flex flex-wrap items-center gap-3 xl:contents"><span className="text-xs text-slateish-400">Due {item.due_date || "not set"}</span>{/* the new look shows the status once: the drop-down that also changes it (builder H's pass, 26 Nov 2026: it read twice) */}{!NEW_LOOK && <StatusBadge tone={item.status === "approved" ? "good" : item.status === "rejected" ? "danger" : "neutral"}>{statusWords(item.status)}</StatusBadge>}<select value={item.status} onChange={(e) => void changeStatus(item, e.target.value as DeliverableStatus)} aria-label={`Status for ${item.title}`} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200">{statuses.map((status) => <option key={status} value={status}>{statusWords(status)}</option>)}</select><LinkButton tone="action" size="xs" onClick={() => void showStakeholders(item)}>People</LinkButton></div></div>{selected === item.id && <div className="mt-2 rounded-[var(--radius-xs)] border border-ink-700 bg-ink-900/60 px-3 py-2 text-xs text-slateish-400">{(stakeholders[item.id] ?? []).length === 0 ? "No one is assigned yet." : <div className="flex flex-wrap gap-2">{stakeholders[item.id].map((person) => <span key={`${person.user_id}-${person.role}`} className="rounded-full bg-ink-700 px-2 py-1"><strong className="text-signal-300">{person.role}</strong> · {person.display_name || person.email}</span>)}</div>}</div>}</div>)}</div>}
      </section>
  );
  const matrix = (
      <section className="mt-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div><h2 className="text-sm font-semibold text-slateish-200">Who is reminded when something is late</h2><p className="mt-1 text-xs text-slateish-500">The reminders sent, step by step, when a deliverable is late. Emails go out only when the email service is on.</p></div>
        </div>
        <div className="mt-3 divide-y divide-ink-700/70">
          {rules.map((rule) => <div key={rule.level} className="grid gap-2 py-3 lg:grid-cols-[70px_130px_180px_minmax(0,1fr)] lg:items-center"><span className={NEW_LOOK ? "text-xs" : "font-mono text-xs text-signal-400"}>Step {rule.level}</span><span className="text-xs text-slateish-400">{rule.trigger_days === 0 ? "On the due date" : `${rule.trigger_days} days late`}</span><span className="text-sm text-slateish-200">{rule.recipient_role}</span><span className="text-xs text-slateish-400">{rule.action}</span></div>)}
          {rules.length === 0 && <EmptyState title="No reminder steps are set up." hint="Set up the reminder steps before relying on automatic reminders." />}
        </div>
      </section>
  );

  return (
    // the new look starts at the same left edge as every other page (C's walk: 60 px against 44 px)
    <section id="deliverables" className={NEW_LOOK ? "w-full" : "w-full px-4 py-6"}>
      {/* the kit's own page header: no one-off green eyebrow line above the title (H's audit #28) */}
      <PageHeader title="Deliverables" lead={<>Every document the contractor must deliver: its number in the project list, its revision, where it stands and when it is due.{NEW_LOOK && <span data-testid="deliverables-summary" className="mt-2 block text-slateish-200">{deliverablesSummary(items, alerts)}</span>}</>} />

      {shownError !== "" && <InlineErrorState message={shownError} />}
      {alerts.length > 0 && <section className="mt-5 rounded-[var(--radius-md)] border border-warn-500/40 bg-warn-500/10 p-4"><h2 className="text-sm font-semibold text-warn-500">Late or due today</h2><ul className="mt-2 space-y-1 text-sm text-warn-500">{alerts.map((alert) => <li key={`${alert.title}-${alert.escalation_level}`}>{alert.days_overdue === 0 ? `${alert.title} is due today` : `${alert.title} is ${alert.days_overdue} day${alert.days_overdue === 1 ? "" : "s"} late`} · reminder step {alert.escalation_level} · {alert.severity}</li>)}</ul></section>}

      {NEW_LOOK ? <>{register}{addForm}</> : <>{addForm}{register}</>}

      <section aria-label="Expected deliverables">
        <div className="flex flex-wrap items-end justify-between gap-2 pb-2">
          <div><SectionTitle>Expected deliverables</SectionTitle><p className="-mt-2 text-xs text-slateish-500">Documents the contract and the standards say must be delivered, checked against the deliverables list.</p></div>
          {expectedLoaded && <StatusBadge tone={expected.some((item) => item.state === "missing") ? "warn" : "good"}>{expected.filter((item) => item.state === "missing").length} missing</StatusBadge>}
        </div>
        {expectedLoaded && saidOnce && <p data-testid="expected-said-once" className="text-sm text-slateish-300">{saidOnce}</p>}
        {!expectedLoaded ? (pending.expected ? <Spinner label="Loading expected deliverables" /> : <p className="px-4 py-3 text-sm text-slateish-400">The expected deliverables could not be loaded.</p>) : expected.length === 0 ? <EmptyState title="No expected deliverables yet." hint="They come from a contract or a standard in the library, or are added by hand." /> : <div className="divide-y divide-ink-700/70">{expected.slice(0, EXPECTED_SHOWN).map(expectedRow)}</div>}
        {expectedLoaded && expected.length > EXPECTED_SHOWN && <div className="border-t border-ink-700 py-3"><Fold testId="expected-more" title={`Show the other ${expected.length - EXPECTED_SHOWN} expected deliverables`}><div className="divide-y divide-ink-700/70">{expected.slice(EXPECTED_SHOWN).map(expectedRow)}</div></Fold></div>}
      </section>

      <section aria-label="Risk register">
        <div className="flex flex-wrap items-end justify-between gap-2 pb-2"><div><SectionTitle>Risk register</SectionTitle><p className="-mt-2 text-xs text-slateish-500">Risks to the timetable, to reviews, from other work, or to meeting the rules, linked to project records.</p></div><div className="flex flex-wrap gap-2"><select aria-label="Risk type filter" value={riskType} onChange={(e) => { const next = e.target.value as import("../types/api").RiskType; setRiskType(next); void risksApi.list(next).then((result) => { setRisksLoaded(result.ok); if (result.ok) { setRisks(result.data.risks); setRisksTotal(result.data.total); } else setError(result.error.message); }); }} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200"><option value="schedule">Schedule</option><option value="review">Review</option><option value="dependency">Depends on other work</option><option value="compliance">Meeting the rules</option></select><input aria-label="Risk title" value={riskTitle} onChange={(e) => setRiskTitle(e.target.value)} placeholder="Add risk" className="w-40 rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><Button variant="secondary" size="sm" onClick={() => void createRisk()}>Create</Button></div></div>
        {!risksLoaded ? (pending.risks ? <Spinner label="Loading the risk register" /> : <p className="px-4 py-3 text-sm text-slateish-400">The risk register could not be loaded.</p>) : risks.length === 0 ? <EmptyState title={`No ${riskType} risks are recorded.`} hint="Create a risk or choose another risk type." /> : <div className="divide-y divide-ink-700/70"><p data-testid="risk-count" className="py-2 text-xs text-slateish-500">Showing {risks.length} of {risksTotal} {riskType} risks you may see.</p>{risks.map((risk) => <div key={risk.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="text-sm text-slateish-200">{risk.title}</p><p className="text-xs text-slateish-500">{risk.description}</p>{(risk.finding_count ?? 1) > 1 ? <span className="mt-1 inline-block rounded-[var(--radius-xs)] bg-signal-500/15 px-2 py-0.5 text-xs text-signal-300">AI suggested · {risk.finding_count} review comments on this document</span> : risk.source_finding_id && <span className="mt-1 inline-block rounded-[var(--radius-xs)] bg-signal-500/15 px-2 py-0.5 text-xs text-signal-300">AI suggested · linked to a review comment</span>}</div><StatusBadge tone={risk.severity === "critical" ? "danger" : "warn"}>{risk.severity} · {risk.status}</StatusBadge></div>)}{risks.length < risksTotal && <button type="button" onClick={() => void risksApi.list(riskType, risks.length).then((result) => { if (result.ok) { setRisks((current) => [...current, ...result.data.risks]); setRisksTotal(result.data.total); } else setError(result.error.message); })} className="w-full py-2 text-left text-xs text-signal-300">Show more</button>}</div>}
      </section>

      {NEW_LOOK ? <InfoFold title="Who is reminded when something is late" className="mt-5">{matrix}</InfoFold> : matrix}

      {workspace && selected === workspace.node.id && <section className="mt-5 rounded-[var(--radius-md)] border border-signal-500/40 bg-ink-850 p-4"><div className="flex items-baseline justify-between"><h2 className="text-sm font-semibold text-slateish-200">Item {workspace.node.wbs_code} in detail</h2><Button variant="secondary" size="sm" onClick={() => setWorkspace(null)}>Close</Button></div><p className="mt-1 text-xs text-slateish-500">What is linked to this item and to the items directly under it.</p><div className="mt-3 grid gap-3 md:grid-cols-3"><div><p className="text-xs uppercase tracking-wide text-slateish-500">Items under it</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.children.length}</p></div><div><p className="text-xs uppercase tracking-wide text-slateish-500">Linked documents</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.documents.length}</p></div><div><p className="text-xs uppercase tracking-wide text-slateish-500">Reviews and reminders</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.reviews.length + workspace.escalations.length}</p></div></div><div className="mt-3 flex flex-wrap gap-2 text-xs text-slateish-400">{workspace.children.map((child) => <span key={child.id} className="rounded-full bg-ink-700 px-2 py-1"><strong className="text-signal-300">{child.wbs_code}</strong> · {child.title}</span>)}</div></section>}
      {selected && <section className="mt-3 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4"><h2 className="text-sm font-semibold text-slateish-200">Assign a person</h2><div className="mt-2 flex flex-wrap gap-2"><input value={stakeholderUser} onChange={(e) => setStakeholderUser(e.target.value)} placeholder="Their user ID" aria-label="User ID of the person" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><select value={stakeholderRole} onChange={(e) => setStakeholderRole(e.target.value as StakeholderRole)} aria-label="Their part" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200"><option value="owner">Owner</option><option value="reviewer">Reviewer</option><option value="approver">Approver</option><option value="informed">Informed</option></select><Button variant="secondary" size="sm" onClick={() => void assignStakeholder()}>Assign</Button></div></section>}
    </section>
  );
}
