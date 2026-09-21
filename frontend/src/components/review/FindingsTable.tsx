/**
 * The findings of one review run.
 *
 * WHAT A REVIEWER'S ATTENTION IS FOR. On the drum sheet this table holds
 * 1,580 rows, of which 1,578 say the submittal stated no value for a
 * requirement. Leading with those buries the two that need a person, so the
 * order is NON_COMPLIANT, NEEDS_ENGINEER_REVIEW, CONDITIONAL, COMPLIANT,
 * NOT_APPLICABLE, and MISSING_INFORMATION is collapsed behind its own count.
 *
 * COLLAPSED, NOT HIDDEN. The count is on screen with its denominator and one
 * click opens it. A screen that dropped them would be answering "how much of
 * this submittal was examined" by not mentioning most of it.
 */
import { useMemo, useState } from "react";

import type { ReviewFinding } from "../../types/api";
import {
  confidenceLabel, matchMethodLabel, matchMethodTone, orNothing,
  statusLabel, statusRank, statusTone, withDenominator,
} from "./reviewFormat";

export interface FindingsTableProps {
  findings: ReviewFinding[];
  selectedId: string | null;
  /** Standard document id -> filename. An id is not a name. */
  standardNames?: Map<string, string>;
  onSelect: (finding: ReviewFinding) => void;
}

const MISSING = "MISSING_INFORMATION";

export function FindingsTable(
  { findings, selectedId, standardNames, onSelect }: FindingsTableProps,
) {
  const [status, setStatus] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [standard, setStandard] = useState<string>("");
  const [showMissing, setShowMissing] = useState(false);

  const tags = useMemo(
    () => Array.from(new Set(findings.map((f) => f.equipment_tag).filter(Boolean))) as string[],
    [findings],
  );
  const standards = useMemo(
    () => Array.from(new Set(findings.map((f) => f.standard_document_id).filter(Boolean))) as string[],
    [findings],
  );

  const filtered = useMemo(() => {
    const rows = findings.filter((finding) => {
      if (status && finding.compliance_status !== status) return false;
      if (tag && finding.equipment_tag !== tag) return false;
      if (standard && finding.standard_document_id !== standard) return false;
      return true;
    });
    return [...rows].sort((a, b) => {
      const byStatus = statusRank(a.compliance_status) - statusRank(b.compliance_status);
      if (byStatus !== 0) return byStatus;
      return (a.standard_clause ?? "").localeCompare(b.standard_clause ?? "");
    });
  }, [findings, status, tag, standard]);

  const actionable = filtered.filter((f) => f.compliance_status !== MISSING);
  const missing = filtered.filter((f) => f.compliance_status === MISSING);
  const visible = showMissing ? [...actionable, ...missing] : actionable;

  return (
    <section aria-labelledby="findings-title" className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <h3 id="findings-title" className="text-lg font-semibold text-slateish-100">
          Findings
        </h3>
        <p className="text-sm text-slateish-400">
          {withDenominator(filtered.length, findings.length)} shown
        </p>
        <div className="ml-auto flex flex-wrap gap-2">
          <label className="text-xs text-slateish-400">
            Status
            <select
              aria-label="Filter by status" value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="ml-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-2 py-1 text-sm text-slateish-100"
            >
              <option value="">All</option>
              {Array.from(new Set(findings.map((f) => f.compliance_status).filter(Boolean))).map((value) => (
                <option key={value as string} value={value as string}>{statusLabel(value)}</option>
              ))}
            </select>
          </label>
          {tags.length > 0 && (
            <label className="text-xs text-slateish-400">
              Equipment
              <select
                aria-label="Filter by equipment tag" value={tag}
                onChange={(event) => setTag(event.target.value)}
                className="ml-2 max-w-[16rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-2 py-1 text-sm text-slateish-100"
              >
                <option value="">All</option>
                {tags.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
          {standards.length > 0 && (
            <label className="text-xs text-slateish-400">
              Standard
              <select
                aria-label="Filter by standard" value={standard}
                onChange={(event) => setStandard(event.target.value)}
                className="ml-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-2 py-1 text-sm text-slateish-100"
              >
                <option value="">All</option>
                {standards.map((value) => (
                  <option key={value} value={value}>
                    {standardNames?.get(value) ?? value}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-700">
        <table className="w-full text-left text-sm">
          <thead className="bg-ink-900 text-xs uppercase tracking-wide text-slateish-400">
            <tr>
              <th scope="col" className="px-3 py-2">Standard / clause</th>
              <th scope="col" className="px-3 py-2">Requirement</th>
              <th scope="col" className="px-3 py-2">Submitted value</th>
              <th scope="col" className="px-3 py-2">Outcome</th>
              <th scope="col" className="px-3 py-2">Pairing</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((finding) => (
              <FindingRow
                key={finding.id} finding={finding}
                name={standardNames?.get(finding.standard_document_id ?? "")}
                selected={finding.id === selectedId}
                onSelect={() => onSelect(finding)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {missing.length > 0 && !showMissing && (
        <button
          type="button" onClick={() => setShowMissing(true)}
          className="w-full rounded-[var(--radius-md)] border border-dashed border-ink-600 bg-ink-900 px-4 py-3 text-left text-sm text-slateish-300 hover:border-ink-500"
        >
          <span className="font-semibold text-slateish-200">
            {missing.length.toLocaleString()} requirements had no evidence on this submittal
          </span>
          <span className="ml-2 text-slateish-400">
            ({withDenominator(missing.length, findings.length)}) — show
          </span>
          <span className="mt-1 block text-xs text-slateish-500">
            No value was submitted against these. That is a question for the
            contractor, not a breach.
          </span>
        </button>
      )}
      {missing.length > 0 && showMissing && (
        <button
          type="button" onClick={() => setShowMissing(false)}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-300"
        >
          Hide the {missing.length.toLocaleString()} with no evidence
        </button>
      )}
      {visible.length === 0 && (
        <p className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-4 py-6 text-center text-sm text-slateish-400">
          No findings match these filters.
        </p>
      )}
    </section>
  );
}

function FindingRow({ finding, name, selected, onSelect }: {
  finding: ReviewFinding; name?: string; selected: boolean; onSelect: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const requirement = finding.requirement ?? "";
  const long = requirement.length > 140;
  const shown = expanded || !long ? requirement : `${requirement.slice(0, 140)}…`;
  const value = [
    orNothing(finding.contractor_evidence_text),
  ].filter(Boolean).join(" ");

  return (
    <tr
      className={`border-t border-ink-800 align-top ${selected ? "bg-signal-500/10" : "hover:bg-ink-850"}`}
      aria-selected={selected}
    >
      <td className="px-3 py-2">
        <button type="button" onClick={onSelect} className="text-left text-signal-300 hover:underline">
          {name ?? orNothing(finding.standard_document_id)}
        </button>
        <span className="mt-0.5 block text-xs text-slateish-400">
          {finding.standard_clause ? `clause ${finding.standard_clause}` : ""}
          {finding.standard_page ? ` · p${finding.standard_page}` : ""}
        </span>
      </td>
      <td className="max-w-md px-3 py-2 text-slateish-300">
        {shown}
        {long && (
          <button
            type="button" onClick={() => setExpanded((value) => !value)}
            className="ml-1 text-xs text-signal-300 hover:underline"
          >
            {expanded ? "less" : "more"}
          </button>
        )}
      </td>
      <td className="px-3 py-2">
        <span className="block text-slateish-100">{value}</span>
        {finding.matched_phrase && (
          <span className="block text-xs text-slateish-400">{finding.matched_phrase}</span>
        )}
        {finding.equipment_tag && (
          <span className="mt-0.5 block text-xs text-slateish-500">{finding.equipment_tag}</span>
        )}
      </td>
      <td className="px-3 py-2">
        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${statusTone(finding.compliance_status)}`}>
          {statusLabel(finding.compliance_status)}
        </span>
        {finding.confirmed_by && (
          <span className="mt-1 block text-xs text-emerald-300">
            confirmed by {finding.confirmed_by}
          </span>
        )}
      </td>
      <td className="px-3 py-2">
        {finding.match_method && (
          <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${matchMethodTone(finding.match_method)}`}>
            {matchMethodLabel(finding.match_method)}
          </span>
        )}
        {finding.confidence && (
          <span className="mt-1 block text-xs text-slateish-400">
            confidence {confidenceLabel(finding.confidence)}
          </span>
        )}
      </td>
    </tr>
  );
}
