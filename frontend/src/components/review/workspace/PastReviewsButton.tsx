/**
 * OWNER: builder E. "All reviews of this file (N)" on a Submittals row.
 *
 * N is every review of the file, the latest included (so the button does not
 * say "Past" while counting the latest). N is counted from the runs the landing page already loaded - no request.
 * The button is hidden when the document has no reviews; pressing it opens
 * the compact list right under the row.
 */
import { useId, useMemo, useState } from "react";

import type { PastReviewsButtonProps } from "./contract";
import { PastReviewsList } from "./PastReviewsList";
import { pastReviewsOf } from "./pastReviews";
import { Button } from "../../kit/Kit";

/** v2.2: on the review page, `currentRunId` is the review on screen; the list
 *  then offers "Compare with this one" on each earlier finished review. */
export function PastReviewsButton({ documentId, runs, onOpenRun, currentRunId = null }:
  PastReviewsButtonProps & { currentRunId?: string | null }) {
  const reviews = useMemo(() => pastReviewsOf(documentId, runs), [documentId, runs]);
  const [open, setOpen] = useState(false);
  const listId = useId();

  if (reviews.length === 0) return null;

  return (
    <div className="w-full">
      <Button variant="secondary" size="sm"
       
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
      >
        All reviews of this file ({reviews.length})
      </Button>
      {open && (
        <div id={listId} className="mt-2">
          <PastReviewsList reviews={reviews} onOpenRun={onOpenRun} currentRunId={currentRunId} />
        </div>
      )}
    </div>
  );
}
