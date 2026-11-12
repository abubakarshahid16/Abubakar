"""PR #1806: a Claude 4xx names its cause in the log and the error, never the request, never a key.
`reader_transport.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_u4_chat_400.py"
_P = APP / "reader_transport.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1806-01", phase=1806, description="the API's error message is dropped from a 4xx",
             path=_P,
             anchor='    detail = ": ".join(part for part in (kind, message) if part)\n',
             replacement='    detail = kind\n',
             target=_T, keyword="a_400_names_its_type", tags=("honesty",)),
    Mutation(id="M1806-02", phase=1806, description="the error message is not cut to its limit",
             path=_P,
             anchor='" ".join(message.split())[:ERROR_MESSAGE_CHARS]',
             replacement='" ".join(message.split())',
             target=_T, keyword="cut_cleaned_and_never_carries_a_key", tags=("privacy",)),
    Mutation(id="M1806-03", phase=1806, description="a key-shaped string is left in the message",
             path=_P,
             anchor='    message = re.sub(r"sk-[A-Za-z0-9_\\-]+", "[key removed]", message)\n',
             replacement='',
             target=_T, keyword="cut_cleaned_and_never_carries_a_key", tags=("privacy", "critical")),
    Mutation(id="M1806-04", phase=1806, description="an authentication message is carried (it can echo a credential)",
             path=_P,
             anchor='    if status in (401, 403):\n        return kind, ""\n',
             replacement='',
             target=_T, keyword="cut_cleaned_and_never_carries_a_key", tags=("privacy", "critical")),
    Mutation(id="M1806-05", phase=1806, description="a streamed 4xx drops the API's message",
             path=_P,
             anchor="lambda: json.loads(response.read())",
             replacement="lambda: {}",
             target=_T, keyword="streamed_400_names_its_cause", tags=("honesty",)),
)
