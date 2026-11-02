"""How the division gate asks its model, and what changes on the Claude route.

THE LOCAL PATH IS UNCHANGED, on purpose: no local proof is planned, so its instruction,
schema, version, stored answers and two attempts stay exactly as they were. Only with
`AI_DIVISION_SCOPE_ENGINE=claude` does `for_provider` hand out these tasks:

  * THE SCOPE QUESTION HAS NO ROOM FOR A DOUBT ABOUT NOTHING. A paid proof showed
    Claude answering "unsure" on parts with no limit to read, where the local model said
    "no", holding 150 rules. Here no scope sentence means "no", and "unsure" is only for a
    sentence that leaves the limit open. The reply names the sentence, so code can check
    the claim: `scope_problems`, on the passage `division_text.scope_passage` picked.
    "No" only sends rules on to comparison; it decides nothing about them.
  * ONE CORRECTIVE RETRY after a code rejection (`TaskSpec.claude_retries`), Claude and this
    route only; a reply that does not parse is not retried. Each attempt is charged, and
    a rejected reply is not stored (`Packet.keep_if`). The owner's cost note on #1593 is
    the answer to #1288's "a repeat read must be local-only". The reasons are counted on
    the run: fixed wording, no document text.
"""

from __future__ import annotations

import dataclasses
import re

from . import ai_task_runner

#: A model that does not answer in time, or cannot be reached: no further
#: division of the run is asked (each would wait `ai_task_timeout_s`).
_MODEL_DOWN = ("the model did not answer in time", "the model could not be reached")
#: Said about a model "no" whose own quoted stated line shares a word with the
#: construction: the sheet speaks against the model's "no" (`read` marks it).
NAMES_ITSELF = "the quoted line names the construction itself"
#: Words that read as a part stating its scope. True of any document: a passage with them
#: and a reply with no sentence carrying them is rejected, and then the part is held.
_SCOPE_WORDS = re.compile(
    r"\b(?:scope|appl(?:y|ies|icable)\s+(?:only\s+|exclusively\s+)?to|only\s+appl(?:y|ies)"
    r"|limit(?:ed|s)?\s+to|restrict(?:ed|s)?\s+to|confined\s+to"
    r"|intended\s+(?:only\s+)?for|covers)\b",
    re.IGNORECASE,
)
#: A sentence that says the part is limited cannot be read as "no".
_SAYS_LIMITED = re.compile(
    r"\b(?:appl(?:y|ies|icable)\s+(?:only|exclusively)\s+to|only\s+appl(?:y|ies)"
    r"|scope\b.*\b(?:limited|restricted|confined)\s+to)\b",
    re.IGNORECASE | re.DOTALL,
)
_SENTENCE = (
    "\n- scope_sentence: the division's own scope sentence, copied exactly from the TEXT; "
    "null when the TEXT has none.\n"
    'A division whose TEXT has no scope sentence names no limit: that is "no", not '
    '"unsure". "unsure" is only for a scope sentence whose words leave the limit open.'
)


def _scope_task() -> ai_task_runner.TaskSpec:
    from . import ai_applicability as local

    def problems(data: dict, text: str) -> list[str]:
        return local._scope_problems(data, text) or scope_problems(data, text)

    schema = {
        **local.SCOPE_SCHEMA,
        "required": [*local.SCOPE_SCHEMA["required"], "scope_sentence"],
        "properties": {
            **local.SCOPE_SCHEMA["properties"],
            "scope_sentence": {"type": ["string", "null"]},
        },
    }
    return dataclasses.replace(
        local.SCOPE_TASK,
        version="claude-v1",
        instruction=local.SCOPE_INSTRUCTION + _SENTENCE,
        schema=schema,
        check=problems,
        claude_retries=1,
    )


def scope_problems(data: dict, text: str) -> list[str]:
    """Code's check of the reply's claim about the scope sentence. A rejection earns one
    corrective ask; a second holds the part (`_read_unit`, `not_read`), never a pass."""
    from . import scope_quote
    from .ai_applicability import _QUOTE_MIN, folded_in

    limited, sentence = data.get("limited"), data.get("scope_sentence")
    if not sentence:
        if limited == "unsure":
            return ["unsure needs the scope sentence that leaves the limit open"]
        if limited == "no" and _SCOPE_WORDS.search(text):
            return ["the TEXT has words of scope; quote the sentence that carries them"]
        return []
    if not folded_in(sentence, text, least=_QUOTE_MIN):
        return ["the scope sentence is not in the TEXT"]
    if not _SCOPE_WORDS.search(sentence):
        return ["the quoted sentence carries no words of scope"]
    # The one shape test of a real sentence; `construction` only satisfies its signature.
    if scope_quote.problems(
        {"limited": "yes", "quote": sentence, "construction": "named"}
    ):
        return ["the quoted scope sentence is not a whole sentence"]
    if limited == "no" and _SAYS_LIMITED.search(sentence):
        return ["the quoted sentence limits the part, so the answer cannot be no"]
    return []


def for_provider(task: ai_task_runner.TaskSpec, provider) -> ai_task_runner.TaskSpec:
    """The task as this provider asks it: the same task on anything but Claude."""
    from . import ai_applicability as local

    if getattr(provider, "name", "") != "claude":
        return task
    if task is local.SCOPE_TASK:
        return _scope_task()
    if task is local.CONSTRUCTION_TASK:
        return dataclasses.replace(task, claude_retries=1)
    return task


def read(task, text: str, provider, run: dict) -> dict | None:
    """One task, unless the model already stopped answering in this run."""
    if run.get("stopped"):
        return None
    result = ai_task_runner.run_task(
        for_provider(task, provider), text, provider=provider
    )
    for why in result.rejected:
        said = run.setdefault("rejected_by_code", {})
        said[why] = said.get(why, 0) + 1
    if result.state == ai_task_runner.STATE_OK:
        return result.data
    run["contradicted"] = NAMES_ITSELF in (result.reason or "")
    if (result.reason or "").startswith((*_MODEL_DOWN, *ai_task_runner.STOPPED_BY)):
        run["stopped"] = result.reason
    return None


def rejections(run: dict) -> dict:
    """What the run says about replies code rejected; nothing when there were none."""
    said = run.get("rejected_by_code")
    return {"replies_rejected_by_code": said} if said else {}
