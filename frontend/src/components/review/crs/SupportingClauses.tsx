/**
 * Order 139 part 2 (spec c): under a field row's required action, the clauses
 * behind it - the file's cap and count ("Supporting clauses (n)", at most 10,
 * then "and k more of these n"). Nothing on a row with no action line.
 */
import { type CrsRow, supportingClauseLines } from "./crsRows";

export function SupportingClauses({ row }: { row: CrsRow }) {
  const [head, ...lines] = supportingClauseLines(row);
  if (!head) return null;
  return (
    <div className="mt-1 text-xs text-slateish-400" data-testid="supporting-clauses">
      <span className="block">{head}</span>
      <ul className="list-disc pl-4">
        {lines.map((line, i) => <li key={`${i}:${line}`}>{line}</li>)}
      </ul>
    </div>
  );
}
