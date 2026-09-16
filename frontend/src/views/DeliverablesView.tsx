import { useCallback, useEffect, useState } from "react";

import { deliverables as deliverablesApi, management } from "../api/client";
import type { Deliverable, DeliverableCreate, DeliverableStatus } from "../types/api";
import type { EscalationRule } from "../types/api";

const statuses: DeliverableStatus[] = ["planned", "in_progress", "submitted", "under_review", "approved", "rejected", "superseded"];

export function DeliverablesView() {
  const [items, setItems] = useState<Deliverable[]>([]);
  const [alerts, setAlerts] = useState<{ title: string; days_overdue: number; escalation_level: number; severity: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rules, setRules] = useState<EscalationRule[]>([]);
  const [form, setForm] = useState<DeliverableCreate>({ wbs_code: "1.0", title: "", deliverable_type: "Engineering submittal", due_date: "" });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    const [list, alertResult, ruleResult] = await Promise.all([deliverablesApi.list(), deliverablesApi.alerts(), management.escalationRules()]);
    if (!list.ok) { setError(list.error.message); setLoading(false); return; }
    setItems(list.data.deliverables);
    if (alertResult.ok) setAlerts(alertResult.data.alerts);
    if (ruleResult.ok) setRules(ruleResult.data.rules);
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

  return (
    <main id="deliverables" className="mx-auto w-full max-w-6xl px-4 py-6">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-signal-400">EPC delivery control</p>
        <h1 className="mt-1 text-2xl font-semibold text-slateish-100">Deliverables &amp; timeline</h1>
        <p className="mt-1 max-w-2xl text-sm text-slateish-400">Track the WBS, revision, review status, and due-date risk for every engineering submittal.</p>
      </header>

      {error !== null && <p role="alert" className="mt-4 rounded border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">{error}</p>}
      {alerts.length > 0 && <section className="mt-5 rounded-lg border border-warn-500/40 bg-warn-500/10 p-4"><h2 className="text-sm font-semibold text-warn-500">Escalation alerts</h2><ul className="mt-2 space-y-1 text-sm text-warn-500">{alerts.map((alert) => <li key={`${alert.title}-${alert.escalation_level}`}>{alert.title} is {alert.days_overdue} day{alert.days_overdue === 1 ? "" : "s"} overdue · level {alert.escalation_level} · {alert.severity}</li>)}</ul></section>}

      <section className="mt-5 rounded-lg border border-ink-600 bg-ink-850 p-4">
        <h2 className="text-sm font-semibold text-slateish-200">Add deliverable</h2>
        <div className="mt-3 grid gap-2 md:grid-cols-[130px_1fr_180px_150px_auto]">
          <input value={form.wbs_code} onChange={(e) => setForm({ ...form, wbs_code: e.target.value })} aria-label="WBS code" placeholder="WBS 1.1" className="rounded border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} aria-label="Deliverable title" placeholder="Deliverable title" className="rounded border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input value={form.deliverable_type} onChange={(e) => setForm({ ...form, deliverable_type: e.target.value })} aria-label="Deliverable type" className="rounded border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <input type="date" value={form.due_date ?? ""} onChange={(e) => setForm({ ...form, due_date: e.target.value || null })} aria-label="Due date" className="rounded border border-ink-600 bg-ink-900 px-2 py-2 text-sm text-slateish-200" />
          <button type="button" onClick={() => void create()} className="rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30">Add</button>
        </div>
      </section>

      <section className="mt-5 overflow-hidden rounded-lg border border-ink-600 bg-ink-850">
        <div className="border-b border-ink-700 px-4 py-3"><h2 className="text-sm font-semibold text-slateish-200">WBS register</h2></div>
        {loading ? <p className="p-4 text-sm text-slateish-500">Loading deliverables…</p> : items.length === 0 ? <p className="p-4 text-sm text-slateish-500">No deliverables have been registered yet.</p> : <div className="divide-y divide-ink-700/70">{items.map((item) => <div key={item.id} className="grid gap-2 px-4 py-3 md:grid-cols-[100px_1fr_150px_130px_150px] md:items-center"><span className="font-mono text-xs text-signal-400">{item.wbs_code}</span><div><p className="text-sm text-slateish-200">{item.title}</p><p className="text-xs text-slateish-500">{item.deliverable_type} · revision {item.revision}</p></div><span className="text-xs text-slateish-400">Due {item.due_date || "not set"}</span><span className="text-xs text-slateish-400">{item.status.replaceAll("_", " ")}</span><select value={item.status} onChange={(e) => void changeStatus(item, e.target.value as DeliverableStatus)} aria-label={`Status for ${item.title}`} className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200">{statuses.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></div>)}</div>}
      </section>

      <section className="mt-5 rounded-lg border border-ink-600 bg-ink-850 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div><h2 className="text-sm font-semibold text-slateish-200">Escalation matrix</h2><p className="mt-1 text-xs text-slateish-500">Reminder and escalation policy applied to overdue deliverables. Sending is enabled by your deployment notification provider.</p></div>
          <span className="text-[11px] uppercase tracking-wide text-signal-400">operational policy</span>
        </div>
        <div className="mt-3 divide-y divide-ink-700/70">
          {rules.map((rule) => <div key={rule.level} className="grid gap-2 py-3 md:grid-cols-[70px_130px_180px_1fr] md:items-center"><span className="font-mono text-xs text-signal-400">Level {rule.level}</span><span className="text-xs text-slateish-400">{rule.trigger_days === 0 ? "Due date" : `${rule.trigger_days} days overdue`}</span><span className="text-sm text-slateish-200">{rule.recipient_role}</span><span className="text-xs text-slateish-400">{rule.action}</span></div>)}
          {rules.length === 0 && <p className="py-3 text-sm text-slateish-500">No escalation policy is configured.</p>}
        </div>
      </section>
    </main>
  );
}
