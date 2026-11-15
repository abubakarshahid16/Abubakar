"""PR #1806: a Claude 4xx names its cause in the log and the error, never the request, never a key.
`reader_transport.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_u4_chat_400.py"
_P = APP / "reader_transport.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1806-01", phase=1806, description="our fixed sentence is dropped from a 4xx (type alone)",
             path=_P,
             anchor='    detail = ": ".join(part for part in (kind, message) if part)\n',
             replacement='    detail = kind\n',
             target=_T, keyword="a_400_names_its_type", tags=("honesty",)),
    Mutation(id="M1806-02", phase=1806, description="the API's own words are passed on when no safe pattern matches",
             path=_P,
             anchor='            return kind, sentence.format(*found.groups())\n    return kind, ""\n',
             replacement='            return kind, sentence.format(*found.groups())\n    return kind, message\n',
             target=_T, keyword="echoes_content_or_a_key", tags=("privacy", "critical")),
    Mutation(id="M1806-03", phase=1806, description="a safe pattern matches anywhere in the message, not the whole of it",
             path=_P,
             anchor='        found = re.fullmatch(pattern, message)\n',
             replacement='        found = re.search(pattern, message)\n',
             target=_T, keyword="echoes_content_or_a_key", tags=("privacy", "critical")),
    Mutation(id="M1806-04", phase=1806, description="the screen reason shows a sentence that is not one of ours",
             path=APP / "reasoning_provider.py",
             anchor='    if sentence and reader_transport.is_fixed_sentence(sentence):\n',
             replacement='    if sentence:\n',
             target=_T, keyword="never_shows_the_text_of_an_arbitrary_exception", tags=("privacy", "critical")),
    Mutation(id="M1806-05", phase=1806, description="a streamed 4xx drops the API's cause",
             path=_P,
             anchor="lambda: json.loads(response.read())",
             replacement="lambda: {}",
             target=_T, keyword="streamed_400_names_its_cause", tags=("honesty",)),
    Mutation(id="M1806-06", phase=1806, description="an authentication error is given a sentence",
             path=_P,
             anchor='    if status in (401, 403) or not kind:\n        return kind, ""\n',
             replacement='    if not kind:\n        return kind, ""\n    if status in (401, 403):\n        return kind, "x-api-key: " + message[:40]\n',
             target=_T, keyword="authentication_and_permission_errors_give_the_type_alone", tags=("privacy", "critical")),
)
