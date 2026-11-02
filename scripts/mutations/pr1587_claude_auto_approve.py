"""PR #1587 (#1584): every send names what it carried on its ledger line. Entries
for `claude_spend.py` (danger zone: the budget and the network); the list and the
gate in `claude_approved.py` were reverted by hand in the PR."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1584_claude_auto_approve.py"
_S = APP / "claude_spend.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1587-01",
        phase=1587,
        description="a send goes without its record on the ledger line",
        path=_S,
        anchor='                line["sent_documents"] = sent_documents\n',
        replacement="                pass\n",
        target=_T,
        keyword="every_send or every_request or chat_consent_send",
        tags=("egress", "critical"),
    ),
    Mutation(
        id="M1587-02",
        phase=1587,
        description="the reservation never asks what the call carries",
        path=_S,
        anchor="    sent_documents = claude_approved.sent_documents()\n",
        replacement="    sent_documents = []\n",
        target=_T,
        keyword="every_send or every_request or chat_consent_send",
        tags=("egress", "critical"),
    ),
    Mutation(
        id="M1587-03",
        phase=1587,
        description="a prompt with no document content still gets the field (switch off: not byte-identical)",
        path=_S,
        anchor="            if sent_documents:\n",
        replacement="            if True:\n",
        target=_T,
        keyword="no_document_content or switch_off_nothing",
        tags=("honesty",),
    ),
    Mutation(
        id="M1587-04",
        phase=1587,
        description="a comparison rewrites the outcome and loses the could-not-check count",
        path=_C,
        anchor="@notes_after  # #1584\n",
        replacement="",
        target="tests/test_1584_review_run_note.py",
        keyword="re_comparison or review_job_records",
        tags=("honesty",),
    ),
)
