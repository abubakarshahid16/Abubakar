"""PR #1111 (order 95 piece 1): the CRS-first Sheet's tiers on the server, the
same table as tiers.ts. A wrong tier puts an unsure row out of the engineer's
sight. backend/tests/test_95_run_summary.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "review_tiers.py"
_T = "tests/test_95_run_summary.py"
_TAG = ("pr1111", "review_tiers")


def _m(n, desc, anchor, repl, kw):
    return Mutation(id=f"M1111-{n:02d}", phase=1111, description=desc, path=_P,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "a finding with an unknown status or none reads as met",
       "    return C, \"Needs you\", UNSETTLED\n",
       "    return A, \"Met\", None\n", "matches_the_screens_table"),
    _m(2, "a met value on an unread page is swept into Met",
       "    return page in facts.pages_not_read or page in facts.reader_timed_out_pages\n",
       "    return False\n", "matches_the_screens_table"),
    _m(3, "a removed finding stays on the screen as a row",
       "    if finding.get(\"approval_status\") == \"rejected\":\n",
       "    if False:\n", "removed"),
    _m(4, "a blank whose standard is not held becomes a comment nobody is asked about",
       "        return C, \"Needs you\", NOT_IN_LIBRARY\n    return C",
       "        return B, \"Comment\", None\n    return C", "matches_the_screens_table"),
    _m(5, "an unread page no longer says \"page not read\" as its reason",
       "    if page_not_read(finding, facts):\n        return PAGE_NOT_READ\n",
       "    if False:\n        return PAGE_NOT_READ\n", "matches_the_screens_table"),
    _m(6, "a finding citing a missing standard is not flagged",
       "                 if _fold(ident) and _fold(ident) in text), None)\n",
       "                 if False), None)\n", "missing_standard"),
    _m(7, "a pairing an AI guessed and nobody confirmed is shown as a decided row",
       "    if _pairing_unconfirmed(finding):\n",
       "    if False:\n", "matches_the_screens_table"),
    _m(8, "an unticked safety field is swept into Met",
       "    return (bool(finding.get(\"show_for_engineer_tick\"))\n",
       "    return (False\n", "matches_the_screens_table"),
    _m(9, "a rule not yet proven is shown as decided",
       "    if finding.get(\"trust_label\") == \"UNPROVEN\":\n",
       "    if False:\n", "matches_the_screens_table"),
)
