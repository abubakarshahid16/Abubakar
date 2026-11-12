"""PR #873 (#872): a failed Claude call says why - HTTP status, the API's
error class, and "no credit" - and never the API's free-text message.
`claude_spend.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_872_failed_call_says_why.py"
_S = APP / "claude_spend.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M873-01", phase=873,
             description="any string the API calls its error type is copied into the ledger (free text, a URL)",
             path=_S,
             anchor='            kind = stated if _ERROR_TYPE.fullmatch(stated) else ""\n',
             replacement="            kind = stated\n",
             target=_T, keyword="not_the_apis_enum", tags=("privacy", "critical")),
    Mutation(id="M873-02", phase=873,
             description="an empty credit balance is not told apart from any other 400",
             path=_S,
             anchor='    if no_credit:\n        return f"{name}:http_{status}:{NO_CREDIT}"\n',
             replacement="",
             target=_T, keyword="closed_description or plain_words or names_no_credit or unbilled_failure",
             tags=("honesty",)),
    Mutation(id="M873-03", phase=873,
             description="a 5xx whose message mentions credit is called 'no credit' (only the API's 400 means it)",
             path=_S,
             anchor='            no_credit = status == 400 and "credit balance" in str(err.get("message") or "").lower()\n',
             replacement='            no_credit = "credit balance" in str(err.get("message") or "").lower()\n',
             target=_T, keyword="not_called_no_credit", tags=("honesty",)),
    Mutation(id="M873-04", phase=873,
             description="the ledger line of a failed call names only the exception type again",
             path=_S,
             anchor='        release(reservation, f"unbilled:{failure_word(exc)}")\n',
             replacement='        release(reservation, f"unbilled:{type(exc).__name__}")\n',
             target=_T, keyword="unbilled_failure", tags=("honesty",)),
)
