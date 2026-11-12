/**
 * A rule book the review found only while it ran is not sent: it was not on the list the user saw. The result says how many, and
 * that a second review lists them (the plan lists the books the last completed review applied by scope). Props only; the count is
 * the result's `claude_unshown_specifications.found_during_review`.
 */
export function FoundDuringReview({ count }: { count: number }) {
  if (!Number.isFinite(count) || count <= 0) return null;
  return (
    <p role="note" className="text-xs text-slateish-300" data-testid="found-during-review">
      {count} more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again
      to include them.
    </p>
  );
}
