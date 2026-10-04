import type { MetricWarning } from "../../types/api";
import { NavLink } from "../NavLink";

export function MetricWarningRow({ warning }: { warning: MetricWarning }) {
  const style = warning.severity === "error"
    ? "border-danger-500/50 bg-danger-500/10 text-danger-500"
    : warning.severity === "warning"
      ? "border-warn-500/50 bg-warn-500/10 text-warn-500"
      : "border-ink-600 bg-ink-850 text-slateish-400";
  return <li className={`rounded-[var(--radius-sm)] border px-3 py-2 text-sm ${style}`}>
    <span role={warning.severity === "error" ? "alert" : "status"}>
      {/* The app's own navigation, not a page load: the token is memory-only
          and a reload signed the reader out. */}
      {warning.document_id
        ? <NavLink view="documents" recordId={warning.document_id} className="text-slateish-300 underline-offset-2 hover:underline">{warning.message}</NavLink>
        : <NavLink view="deliverables" className="text-slateish-300 underline-offset-2 hover:underline">{warning.message}</NavLink>}
      <span className="ms-2 font-mono text-xs uppercase tracking-wide text-slateish-500">{warning.code}</span>
    </span>
  </li>;
}
