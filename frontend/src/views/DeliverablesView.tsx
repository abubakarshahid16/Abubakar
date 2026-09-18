import { useCallback, useEffect, useState } from "react";
import { EmptyState, InlineErrorState, Spinner, StatusBadge } from "../components/states";

import { deliverables as deliverablesApi, management, risks as risksApi } from "../api/client";
import type { Deliverable, DeliverableCreate, DeliverableStatus, DeliverableStakeholder, StakeholderRole } from "../types/api";
import type { EscalationRule } from "../types/api";

const statuses: DeliverableStatus[] = ["planned", "in_progress", "submitted", "under_review", "approved", "rejected", "superseded"];

export function DeliverablesView() {
  const [items, setItems] = useState<Deliverable[]>([]);
  const [alerts, setAlerts] = useState<{ title: string; days_overdue: number; escalation_level: number; severity: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    const [list, alertResult, ruleResult, expectedResult, riskResult] = await Promise.all([deliverablesApi.list(), deliverablesApi.alerts(), management.escalationRules(), deliverablesApi.expected(), risksApi.list()]);
    if (!list.ok) { setError(list.error.message); setLoading(false); return; }
    setItems(list.data.deliverables);
    const secondaryErrors = [alertResult, ruleResult, expectedResult, riskResult].filter((result) => !result.ok).map((result) => result.error.message);
    if (alertResult.ok) setAlerts(alertResult.data.alerts);
    if (ruleResult.ok) setRules(ruleResult.data.rules);
    if (expectedResult.ok) setExpected(expectedResult.data.deliverables);
    if (riskResult.ok) setRisks(riskResult.data.risks);
    if (secondaryErrors.length > 0) setError(secondaryErrors.join(" "));
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

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
    if (result.ok) { setRisks((current) => [result.data, ...current]); setRiskTitle(""); }
    else setError(result.error.message);
  }

  return (
    <main id="deliverables" className="w-full px-4 py-6">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wider text-signal-400">EPC delivery control</p>
        <h1 className="mt-1 text-2xl font-semibold text-slateish-100">Deliverables &amp; timeline</h1>
        <p className="mt-1 max-w-2xl text-sm text-slateish-400">Track the WBS, revision, review status, and due-date risk for every engineering submittal.</p>
      </header>

      {error !== null && <InlineErrorState message={error} />}
      {alerts.length > 0 && <section className="mt-5 rounded-[var(--radius-md)] border border-warn-500/40 bg-warn-500/10 p-4"><h2 className="text-sm font-semibold text-warn-500">Escalation alerts</h2><ul className="mt-2 space-y-1 text-sm text-warn-500">{alerts.map((alert) => <li key={`${alert.title}-${alert.escalation_level}`}>{alert.title} is {alert.days_overdue} day{alert.days_overdue === 1 ? "" : "s"} overdue · level {alert.escalation_level} · {alert.severity}</li>)}</ul></section>}

      <section className="mt-5 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
        <h2 className="text-sm font-semibold text-slateish-200">Add deliverable</h2>
        <div className="mt-3 grid gap-2 md:grid-cols-[130px_1fr_180px_150px_auto]">
          <input value={form.wbs_code} onChange={(e) => setForm({ ...form, wbs_code: e.target.value })} aria-label="WBS code" placeholder="WBS 1.1" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} aria-label="Deliverable title" placeholder="Deliverable title" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.deliverable_type} onChange={(e) => setForm({ ...form, deliverable_type: e.target.value })} aria-label="Deliverable type" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input type="date" value={form.due_date ?? ""} onChange={(e) => setForm({ ...form, due_date: e.target.value || null })} aria-label="Due date" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <button type="button" onClick={() => void create()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30">Add</button>
        </div>
      </section>

      <section className="mt-5 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850">
        <div className="border-b border-ink-700 px-4 py-3"><h2 className="text-sm font-semibold text-slateish-200">WBS register</h2></div>
      {loading ? <Spinner label="Loading deliverables" /> : items.length === 0 ? <EmptyState title="No deliverables have been registered yet." hint="Add a deliverable above to start tracking the engineering submission." /> : <div className="divide-y divide-ink-700/70">{items.map((item) => <div key={item.id} className="px-4 py-3"><div className="grid gap-2 md:grid-cols-[100px_1fr_150px_130px_150px_auto] md:items-center"><span className="font-mono text-xs text-signal-400">{item.wbs_code}</span><div><p className="text-sm text-slateish-200">{item.title}</p><p className="text-xs text-slateish-500">{item.deliverable_type} · revision {item.revision}</p></div><span className="text-xs text-slateish-400">Due {item.due_date || "not set"}</span><StatusBadge tone={item.status === "approved" ? "good" : item.status === "rejected" ? "danger" : "neutral"}>{item.status.replaceAll("_", " ")}</StatusBadge><select value={item.status} onChange={(e) => void changeStatus(item, e.target.value as DeliverableStatus)} aria-label={`Status for ${item.title}`} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200">{statuses.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select><button type="button" onClick={() => void showStakeholders(item)} className="text-xs text-signal-400 hover:underline">Stakeholders</button></div>{selected === item.id && <div className="mt-2 rounded-[var(--radius-xs)] border border-ink-700 bg-ink-900/60 px-3 py-2 text-xs text-slateish-400">{(stakeholders[item.id] ?? []).length === 0 ? "No stakeholders assigned." : <div className="flex flex-wrap gap-2">{stakeholders[item.id].map((person) => <span key={`${person.user_id}-${person.role}`} className="rounded-full bg-ink-700 px-2 py-1"><strong className="text-signal-300">{person.role}</strong> · {person.display_name || person.email}</span>)}</div>}</div>}</div>)}</div>}
      </section>

      <section aria-label="Expected deliverables" className="mt-5 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 px-4 py-3">
          <div><h2 className="text-sm font-semibold text-slateish-200">Expected deliverables</h2><p className="mt-1 text-xs text-slateish-500">Requirement-linked expectations compared with the WBS register.</p></div>
          <StatusBadge tone={expected.some((item) => item.state === "missing") ? "warn" : "good"}>{expected.filter((item) => item.state === "missing").length} missing</StatusBadge>
        </div>
        {expected.length === 0 ? <EmptyState title="No expectations are configured or inferred yet." hint="Link a requirement document or add an expectation manually." /> : <div className="divide-y divide-ink-700/70">{expected.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"><div><p className="text-sm text-slateish-200">{item.title}</p><p className="text-xs text-slateish-500">WBS {item.wbs_code} · {item.deliverable_type} · {item.origin}</p>{item.origin === "inferred" && <span className="mt-1 inline-block rounded-[var(--radius-xs)] bg-signal-500/15 px-2 py-0.5 text-xs text-signal-300">AI suggested · review before accepting</span>}</div><StatusBadge tone={item.state === "missing" ? "warn" : "good"}>{item.state}</StatusBadge></div>)}</div>}
      </section>

      <section aria-label="Risk register" className="mt-5 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 px-4 py-3"><div><h2 className="text-sm font-semibold text-slateish-200">Risk register</h2><p className="mt-1 text-xs text-slateish-500">Schedule, review, dependency, and compliance risks linked to project records.</p></div><div className="flex flex-wrap gap-2"><select aria-label="Risk type filter" value={riskType} onChange={(e) => { const next = e.target.value as import("../types/api").RiskType; setRiskType(next); void risksApi.list(next).then((result) => { if (result.ok) setRisks(result.data.risks); else setError(result.error.message); }); }} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200"><option value="schedule">Schedule</option><option value="review">Review</option><option value="dependency">Dependency</option><option value="compliance">Compliance</option></select><input aria-label="Risk title" value={riskTitle} onChange={(e) => setRiskTitle(e.target.value)} placeholder="Add risk" className="w-40 rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><button type="button" onClick={() => void createRisk()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs text-signal-300">Create</button></div></div>
        {risks.length === 0 ? <EmptyState title={`No ${riskType} risks are recorded.`} hint="Create a risk or choose another risk type." /> : <div className="divide-y divide-ink-700/70">{risks.map((risk) => <div key={risk.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"><div><p className="text-sm text-slateish-200">{risk.title}</p><p className="text-xs text-slateish-500">{risk.description}</p>{risk.source_finding_id && <span className="mt-1 inline-block rounded-[var(--radius-xs)] bg-signal-500/15 px-2 py-0.5 text-xs text-signal-300">AI suggested · linked to review finding</span>}</div><StatusBadge tone={risk.severity === "critical" ? "danger" : "warn"}>{risk.severity} · {risk.status}</StatusBadge></div>)}</div>}
      </section>

      <section className="mt-5 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div><h2 className="text-sm font-semibold text-slateish-200">Escalation matrix</h2><p className="mt-1 text-xs text-slateish-500">Reminder and escalation policy applied to overdue deliverables. Sending is enabled by your deployment notification provider.</p></div>
          <span className="text-xs uppercase tracking-wide text-signal-400">operational policy</span>
        </div>
        <div className="mt-3 divide-y divide-ink-700/70">
          {rules.map((rule) => <div key={rule.level} className="grid gap-2 py-3 md:grid-cols-[70px_130px_180px_1fr] md:items-center"><span className="font-mono text-xs text-signal-400">Level {rule.level}</span><span className="text-xs text-slateish-400">{rule.trigger_days === 0 ? "Due date" : `${rule.trigger_days} days overdue`}</span><span className="text-sm text-slateish-200">{rule.recipient_role}</span><span className="text-xs text-slateish-400">{rule.action}</span></div>)}
          {rules.length === 0 && <EmptyState title="No escalation policy is configured." hint="Configure escalation rules before relying on automated notifications." />}
        </div>
      </section>

      {workspace && selected === workspace.node.id && <section className="mt-5 rounded-[var(--radius-md)] border border-signal-500/40 bg-ink-850 p-4"><div className="flex items-baseline justify-between"><h2 className="text-sm font-semibold text-slateish-200">WBS workspace · {workspace.node.wbs_code}</h2><button type="button" onClick={() => setWorkspace(null)} className="text-xs text-slateish-400 hover:text-slateish-200">Close</button></div><p className="mt-1 text-xs text-slateish-500">Linked context for this node and its direct children.</p><div className="mt-3 grid gap-3 md:grid-cols-3"><div><p className="text-xs uppercase tracking-wide text-slateish-500">Children</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.children.length}</p></div><div><p className="text-xs uppercase tracking-wide text-slateish-500">Linked documents</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.documents.length}</p></div><div><p className="text-xs uppercase tracking-wide text-slateish-500">Review / escalation signals</p><p className="mt-1 text-xl font-semibold text-slateish-100">{workspace.reviews.length + workspace.escalations.length}</p></div></div><div className="mt-3 flex flex-wrap gap-2 text-xs text-slateish-400">{workspace.children.map((child) => <span key={child.id} className="rounded-full bg-ink-700 px-2 py-1"><strong className="text-signal-300">{child.wbs_code}</strong> · {child.title}</span>)}</div></section>}
      {selected && <section className="mt-3 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4"><h2 className="text-sm font-semibold text-slateish-200">Assign stakeholder</h2><div className="mt-2 flex flex-wrap gap-2"><input value={stakeholderUser} onChange={(e) => setStakeholderUser(e.target.value)} placeholder="User ID" aria-label="Stakeholder user ID" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><select value={stakeholderRole} onChange={(e) => setStakeholderRole(e.target.value as StakeholderRole)} aria-label="Stakeholder role" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200"><option value="owner">Owner</option><option value="reviewer">Reviewer</option><option value="approver">Approver</option><option value="informed">Informed</option></select><button type="button" onClick={() => void assignStakeholder()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs text-signal-300">Assign</button></div></section>}
    </main>
  );
}
