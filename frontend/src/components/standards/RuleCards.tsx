/**
 * Order 302.4 (d): the rule-approval screen. A rule card is a checklist item the real code has tested. The
 * engineer reads it here and approves, edits or rejects it.
 *
 * WHAT IT REFUSES TO DO:
 *  - Call a card approved because it is tested. "Tested" and "approved" are two words, two states.
 *  - Hide what "tested" rests on. A card tested by generated cases only (they check the code path, not that the
 *    box the card names is the right one) says so beside the Approve button.
 *  - Let a stale screen decide. Every decision carries the version and the hash the engineer saw; a card that
 *    changed meanwhile answers 409 and nothing is written.
 *  - Edit a thing the rule's kind does not allow: the form shows only the fields the server accepts.
 * Super user only: the routes answer the admin 404 to anyone else, so the screen is mounted for an administrator.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import { ErrorState, Spinner } from "../states";
import type { ApiError, RuleCard, RuleCardListing, RuleCardState } from "../../types/api";

const STATE_WORDS: Record<RuleCardState, string> = {
  draft: "Draft",
  tested: "Tested, not yet approved",
  approved: "Approved",
  rejected: "Rejected",
};
const STATES: RuleCardState[] = ["draft", "tested", "approved", "rejected"];
const OPS: Record<string, string> = { ">=": "at least", ">": "above", "<=": "at most", "<": "below" };

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "ready"; listing: RuleCardListing };

/** The rule in plain words, from the card's own fields. */
export function describeRule(rule: RuleCard["item"]["rule"]): string {
  const name = (key: string) => String(rule[key] ?? "").replace(/_/g, " ");
  const op = OPS[String(rule.op)] ?? String(rule.op ?? "");
  switch (rule.kind) {
    case "required":
      return `The ${name("field")} is stated.`;
    case "allowed":
      return `The ${name("field")} is one of: ${(rule.values as string[]).join(", ")}.`;
    case "compare":
      return `The ${name("left")} is ${op} the ${name("right")}.`;
    case "constant":
      return `The ${name("field")} is ${op} ${rule.value}${rule.unit ? ` ${rule.unit}` : ""}.`;
    case "percent_of":
      return `The ${name("left")} is ${op} ${rule.percent}% of the ${name("right")}.`;
    case "above_by":
      return `The ${name("left")} is above the ${name("right")} by at least the greater of ${rule.percent}% or ${rule.at_least} ${rule.unit}.`;
    case "calc":
      return `The ${name("field")} is calculated: ${name("formula")}.`;
    default:
      return String(rule.kind ?? "");
  }
}

function EditForm({ card, busy, onSave }: {
  card: RuleCard; busy: boolean; onSave: (changes: Record<string, unknown>) => void;
}) {
  const rule = card.item.rule;
  const [text, setText] = useState(card.item.text);
  const [severity, setSeverity] = useState(card.item.severity);
  const [clause, setClause] = useState(card.item.source.clause);
  const [op, setOp] = useState(String(rule.op ?? ""));
  const [numbers, setNumbers] = useState<Record<string, string>>(
    Object.fromEntries(["percent", "at_least", "value", "tolerance_percent"]
      .filter((k) => rule[k] !== undefined).map((k) => [k, String(rule[k])])));
  const [values, setValues] = useState(Array.isArray(rule.values) ? (rule.values as string[]).join(", ") : "");

  const save = () => {
    const changes: Record<string, unknown> = {};
    if (text !== card.item.text) changes.text = text;
    if (severity !== card.item.severity) changes.severity = severity;
    if (clause !== card.item.source.clause) changes.clause = clause;
    if (rule.op !== undefined && op !== String(rule.op)) changes.op = op;
    for (const [key, raw] of Object.entries(numbers)) {
      if (raw !== String(rule[key]) && raw.trim() !== "" && !Number.isNaN(Number(raw))) changes[key] = Number(raw);
    }
    if (Array.isArray(rule.values) && values !== (rule.values as string[]).join(", ")) {
      changes.values = values.split(",").map((v) => v.trim()).filter(Boolean);
    }
    onSave(changes);
  };

  return (
    <form className="mt-2 flex flex-col gap-2 text-xs" onSubmit={(e) => { e.preventDefault(); save(); }}
          aria-label="Edit the rule card">
      <label className="flex flex-col gap-1">Words
        <input value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">Clause number
        <input value={clause} onChange={(e) => setClause(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">Severity
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {["critical", "major", "minor"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      {rule.op !== undefined && (
        <label className="flex flex-col gap-1">Comparison
          <select value={op} onChange={(e) => setOp(e.target.value)}>
            {Object.entries(OPS).map(([k, w]) => <option key={k} value={k}>{w}</option>)}
          </select>
        </label>
      )}
      {Object.keys(numbers).map((key) => (
        <label key={key} className="flex flex-col gap-1">{key.replace(/_/g, " ")}
          <input inputMode="decimal" value={numbers[key]}
                 onChange={(e) => setNumbers({ ...numbers, [key]: e.target.value })} />
        </label>
      ))}
      {Array.isArray(rule.values) && (
        <label className="flex flex-col gap-1">Allowed values, separated by commas
          <input value={values} onChange={(e) => setValues(e.target.value)} />
        </label>
      )}
      <p className="opacity-70">
        Saving makes a new version. It is tested again at once and has no decision until you approve it.
      </p>
      <button type="submit" disabled={busy}>Save as a new version</button>
    </form>
  );
}

function CardDetail({ card, onDone }: { card: RuleCard; onDone: (card: RuleCard) => void }) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const run = async (call: Promise<{ ok: true; data: RuleCard } | { ok: false; error: ApiError }>) => {
    setBusy(true);
    setFailure(null);
    const result = await call;
    setBusy(false);
    if (!result.ok) {
      setFailure(result.error.message || "Could not record it.");
      return;
    }
    setEditing(false);
    onDone(result.data);
  };

  const generatedOnly = card.written_cases === 0;
  return (
    <section aria-label={`Rule card ${card.card_id}`} data-testid="rule-card-detail"
             className="rounded border border-ink-700 p-3 text-xs">
      <h4 className="text-sm font-medium">{card.card_id}: {STATE_WORDS[card.state]}</h4>
      <p>{describeRule(card.item.rule)}</p>
      <p className="opacity-70">
        Words: {card.item.text} Source: {card.item.source.standard} clause {card.item.source.clause}.
        Version {card.version}{card.versions > 1 ? ` of ${card.versions}` : ""}.
      </p>
      {card.why && card.state !== "tested" && <p>{card.why}</p>}
      {card.weak_source && <p role="note" className="text-warn-500">Weak source: the clause only partly supports this rule.</p>}
      {card.baseline_changed && (
        <p role="note">The committed card changed after the last decision; the decision no longer applies.</p>
      )}
      <p className="mt-1">What &ldquo;tested&rdquo; rests on: {card.basis}.</p>
      {generatedOnly && (
        <p role="note" className="text-warn-500">
          Read the box this card names before you approve it: generated cases cannot tell a right box from a wrong one.
        </p>
      )}
      <table className="mt-1 w-full text-left" aria-label="Test cases">
        <thead><tr><th>Case</th><th>Kind</th><th>Expected</th><th>Got</th><th>Result</th></tr></thead>
        <tbody>
          {card.cases.map((c, i) => (
            <tr key={`${c.case}-${i}`}>
              <td>{c.case}</td><td>{c.kind}</td><td>{c.expected}</td><td>{c.got ?? ""}</td>
              <td>{c.passed ? "passed" : "failed"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {card.decided_by && (
        <p className="mt-1">
          {card.state === "approved" ? "Approved" : "Decided"} by {card.decided_by}
          {card.decided_at ? ` on ${card.decided_at}` : ""}.
        </p>
      )}
      {failure && <p role="alert" className="text-red-400">{failure}</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" disabled={busy || card.state !== "tested"}
                onClick={() => void run(api.decideRuleCard(card.card_id, card.version, card.content_hash, "approved"))}>
          Approve this version
        </button>
        <button type="button" disabled={busy || card.state === "rejected" || card.state === "approved"}
                onClick={() => void run(api.decideRuleCard(card.card_id, card.version, card.content_hash, "rejected"))}>
          Reject
        </button>
        <button type="button" disabled={busy} onClick={() => setEditing(!editing)}>
          {editing ? "Cancel the edit" : "Edit"}
        </button>
      </div>
      {card.state !== "tested" && card.state !== "approved" && (
        <p className="mt-1 opacity-70">Only a tested card can be approved.</p>
      )}
      {editing && (
        <EditForm card={card} busy={busy}
                  onSave={(changes) => void run(api.editRuleCard(card.card_id, card.version, card.content_hash, changes))} />
      )}
    </section>
  );
}

export function RuleCards() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [filter, setFilter] = useState<RuleCardState | "all">("all");
  const [open, setOpen] = useState<RuleCard | null>(null);

  const refresh = useCallback(async () => {
    const result = await api.ruleCards();
    if (result.ok) setLoad({ state: "ready", listing: result.data });
    else setLoad({ state: "error", error: result.error });
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const openCard = async (id: string) => {
    const result = await api.ruleCard(id);
    if (result.ok) setOpen(result.data);
  };

  if (load.state === "loading") return <Spinner />;
  if (load.state === "error") return <ErrorState error={load.error} onRetry={() => void refresh()} />;

  return (
    <section aria-labelledby="rule-cards" className="flex flex-col gap-2">
      <h3 id="rule-cards" className="text-sm font-medium">Rule cards: tested by the real code, approved by an engineer</h3>
      <p className="text-xs opacity-70">
        A card is a checklist rule. &ldquo;Tested&rdquo; means the real checking code passed its cases;
        &ldquo;approved&rdquo; means an engineer read this exact version and approved it. An edit is a new version
        that is tested again and has no decision.
      </p>
      <label className="text-xs">Show
        <select value={filter} onChange={(e) => setFilter(e.target.value as RuleCardState | "all")}>
          <option value="all">all cards</option>
          {STATES.map((s) => <option key={s} value={s}>{STATE_WORDS[s].toLowerCase()}</option>)}
        </select>
      </label>
      {Object.entries(load.listing).map(([type, group]) => (
        <div key={type} data-testid={`rule-card-group-${type}`}>
          <h4 className="text-sm">{type}</h4>
          <p className="text-xs opacity-70">
            {group.total} cards of this equipment type:{" "}
            {STATES.map((s) => `${group.counts[s]} ${STATE_WORDS[s].toLowerCase()}`).join(", ")}.
          </p>
          <ul className="flex flex-col gap-1">
            {group.cards.filter((c) => filter === "all" || c.state === filter).map((c) => (
              <li key={c.card_id} className="text-xs">
                <button type="button" onClick={() => void openCard(c.card_id)}>
                  {c.card_id}: {c.text}
                </button>{" "}
                <span>({STATE_WORDS[c.state]}{c.weak_source ? ", weak source" : ""})</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {open && (
        <CardDetail key={`${open.card_id}-${open.version}-${open.state}`} card={open}
                    onDone={(card) => { setOpen(card); void refresh(); }} />
      )}
    </section>
  );
}
