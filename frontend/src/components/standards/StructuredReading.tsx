/**
 * The phase-3B structured reading of one standard requirement.
 *
 * SECONDARY TO THE QUOTED CLAUSE, ALWAYS. The clause text above it is what the
 * standard says; this is what the extractor made of it - a limit, the
 * circumstance it holds under, and its carve-outs - and it is labelled a
 * machine reading until an engineer confirms the row.
 *
 * WHAT IT REFUSES TO SAY:
 *  - Null renders as nothing. A limit with no value is not shown as a limit
 *    of 0, and a row with no structured field renders no box at all.
 *  - A `table_value` row's `condition` is the table's ROW LABEL, not a
 *    condition (backend `conditions.py`: on those rows the column holds names
 *    like "Arsenic" and bare numbers like "100"). Calling it "applies to"
 *    would narrow the requirement in the reader's head exactly the way the
 *    condition gate refuses to in the engine.
 *  - A table cell is a VALUE, not a limit: it carries no operator and a human
 *    decides whether it is a requirement or a reference value.
 *  - The number shown is the one the document WROTE (`raw_value`), because
 *    that is what the reader can check against the quote. The normalised one
 *    is used only when nothing raw was recorded.
 */
import type {
  RequirementException, StandardRequirement,
} from "../../types/api";

/** The backend writes ASCII comparators; a reader sees the symbols. An
 *  operator this table does not know is shown verbatim, never dropped - a
 *  dropped operator turns a limit into a bare number. */
const OPERATOR_SYMBOL: Readonly<Record<string, string>> = {
  "<=": "≤", ">=": "≥", "<": "<", ">": ">", "=": "=", "==": "=",
};

const TYPE_LABEL: Readonly<Record<string, string>> = {
  numeric_limit: "Numeric limit",
  statement: "Statement (no limit read)",
  table_value: "Table value",
};

function present(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim() !== "";
}

/** "≥ 3 mm", "≤ 115 dB(A)", "100 mg/kg" - or null when no value was read. */
function formatLimit(limit: {
  operator?: string | null; value?: number | null; unit?: string | null;
  raw_value?: string | null; raw_unit?: string | null;
}): string | null {
  let quantity: string | null = null;
  if (present(limit.raw_value)) {
    quantity = present(limit.raw_unit)
      ? `${limit.raw_value} ${limit.raw_unit}` : limit.raw_value;
  } else if (typeof limit.value === "number" && Number.isFinite(limit.value)) {
    quantity = present(limit.unit) ? `${limit.value} ${limit.unit}` : String(limit.value);
  }
  // No number, no limit: an operator on its own is not a requirement.
  if (quantity === null) return null;
  if (!present(limit.operator)) return quantity;
  const symbol = OPERATOR_SYMBOL[limit.operator.trim()] ?? limit.operator.trim();
  return `${symbol} ${quantity}`;
}

/** An exception as one line, or null when the stored entry is unusable. */
function formatException(ex: RequirementException | null | undefined): string | null {
  if (!ex || typeof ex !== "object") return null;
  const subject = present(ex.applies_to) ? ex.applies_to.trim() : null;
  const limit = formatLimit(ex);
  if (subject && limit) return `${subject} (${limit})`;
  return subject ?? limit;
}

export function StructuredReading({ row }: { row: StandardRequirement }) {
  const isTable = row.requirement_type === "table_value";
  const limit = formatLimit(row);
  const condition = present(row.condition) ? row.condition.trim() : null;
  const field = present(row.field) ? row.field.trim() : null;
  const exceptions = (Array.isArray(row.exceptions) ? row.exceptions : [])
    .map(formatException)
    .filter((line): line is string => line !== null);
  const typeLabel = row.requirement_type ? TYPE_LABEL[row.requirement_type] ?? null : null;

  // Nothing structured was read: no box, no "none", no empty labels. The type
  // alone does not earn a box - every plain statement would carry one.
  if (!limit && !condition && !field && exceptions.length === 0) {
    return null;
  }

  const confirmed = present(row.confirmed_by);
  const headingId = `structured-${row.id}`;

  return (
    <section
      aria-labelledby={headingId}
      className="mt-2 rounded border border-dashed border-white/15 p-2"
    >
      <h4 id={headingId} className="text-[11px] uppercase tracking-wide opacity-70">
        {confirmed
          ? "Structured reading - confirmed by an engineer"
          : "Machine-extracted from the quoted clause - not confirmed by an engineer"}
      </h4>
      <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5">
        {typeLabel && (
          <>
            <dt className="opacity-60">Reading</dt>
            <dd>{typeLabel}</dd>
          </>
        )}
        {field && (
          <>
            <dt className="opacity-60">{isTable ? "Table column" : "Field"}</dt>
            <dd>{field}</dd>
          </>
        )}
        {limit && (
          <>
            <dt className="opacity-60">{isTable ? "Cell value" : "Limit"}</dt>
            <dd className="font-mono">{limit}</dd>
          </>
        )}
        {condition && (
          <>
            {/* A table row's label is NOT a condition - see the module doc. */}
            <dt className="opacity-60">{isTable ? "Table row" : "Applies to"}</dt>
            <dd>{condition}</dd>
          </>
        )}
        {exceptions.length > 0 && (
          <>
            <dt className="opacity-60">Except</dt>
            <dd>
              <ul className="list-disc pl-4">
                {exceptions.map((line, i) => <li key={i}>{line}</li>)}
              </ul>
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}
