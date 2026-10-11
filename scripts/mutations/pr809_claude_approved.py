"""PR #809 (#806 S3): the Claude lane refuses a prompt that carries an
unapproved document, or whose caller declared nothing. Entries for
`claude_spend.py` (danger zone: the budget and the network); the list module
itself was hand-checked in the PR."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_806_claude_approved.py"
_S = APP / "claude_spend.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M809-01", phase=809, description="the approved-document check is skipped at the reservation",
             path=_S, anchor="    refused = claude_approved.refusal()\n",
             replacement="    refused = None\n",
             target=_T, keyword="declared_nothing or unapproved or metered_lane", tags=("egress", "critical")),
    Mutation(id="M809-02", phase=809, description="a refused call is still reserved and sent",
             path=_S, anchor="        raise DocumentNotApproved(code, reason)\n",
             replacement="        pass\n",
             target=_T, keyword="metered_lane or declared_nothing", tags=("egress", "critical")),
    Mutation(id="M809-03", phase=809, description="a refusal leaves no line in the ledger",
             path=_S, anchor='                line["refused"] = code\n',
             replacement='                continue\n',
             target=_T, keyword="written_to_the_ledger", tags=("honesty",)),
    Mutation(id="M809-04", phase=809, description="the refusal is not a cap-style stop (callers no longer stop cleanly)",
             path=_S, anchor="class DocumentNotApproved(BudgetExceeded):\n",
             replacement="class DocumentNotApproved(RuntimeError):\n",
             target=_T, keyword="cap_style_stop", tags=("honesty",)),
    Mutation(id="M809-05", phase=809, description="the reader is told it was the spending cap",
             path=_S, anchor="    words = NOT_APPROVED_WORDS if isinstance(exc, DocumentNotApproved) else cap_words\n",
             replacement="    words = cap_words\n",
             target=_T, keyword="reader_is_told", tags=("honesty",)),
)
