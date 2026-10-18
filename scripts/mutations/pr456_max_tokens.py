"""#456 (C-H5, Stage D): per-route max_tokens; a length-cut reply is the named
state `truncated`, never parsed as a complete answer, no verdict stored.
Entries for `ai/output_limits.py` (the one table and the one check: a wrong
answer here reaches the engineer as a half-answer read whole) and the two
callers that store from it. Ids carry the issue number because the PR number
is not known at authoring time (rule 12: never renumbered afterwards)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_456_max_tokens.py"
_O = APP / "ai" / "output_limits.py"
_TAG = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M456-01", phase=456, description="a length stop is read as a complete reply",
             path=_O, anchor="    if reason in LENGTH_STOPS:\n        return TRUNCATED\n",
             replacement="    if False:\n        return TRUNCATED\n",
             target=_T, keyword="truncated or cut_off or not_complete", tags=_TAG),
    Mutation(id="M456-02", phase=456, description="a cut-off reply's text is handed to the parser",
             path=_O, anchor="        if state == TRUNCATED:\n            raise Truncated(route, tokens_out)\n",
             replacement="        if state == TRUNCATED:\n            return reader_api.response_text(payload)\n",
             target=_T, keyword="raises_truncated or matcher_names", tags=_TAG),
    Mutation(id="M456-03", phase=456, description="a reply with no text is handed to the parser as empty",
             path=_O, anchor="        raise Unreadable(route, str(answer.get(\"stop_reason\") or \"\"))\n",
             replacement="        return \"\"\n",
             target=_T, keyword="raises_unreadable", tags=_TAG),
    Mutation(id="M456-04", phase=456, description="every route gets the one global cap again",
             path=_O, anchor="    value = ROUTE_MAX_TOKENS.get(str(route or \"\"), DEFAULT_MAX_TOKENS)\n",
             replacement="    value = DEFAULT_MAX_TOKENS\n",
             target=_T, keyword="own_max_tokens or differ_from or from_the_table or follows_the_setting",
             tags=("robustness",)),
    Mutation(id="M456-05", phase=456, description="a cut-off reply with text is 'complete' in the Packet lane",
             path=_O, anchor="    if state == TRUNCATED:\n        _log(route, TRUNCATED, getattr(response, \"tokens_out\", None))\n        raise Truncated(route, getattr(response, \"tokens_out\", None))\n",
             replacement="    if False:\n        raise Truncated(route, None)\n",
             target=_T, keyword="complete_text_refuses", tags=_TAG),
    Mutation(id="M456-06", phase=456, description="the recheck parses a truncated reply instead of naming it",
             path=APP / "claude_recheck.py",
             anchor="    except (output_limits.Truncated, output_limits.Unreadable) as exc:\n        return None, exc.state\n",
             replacement="    except (output_limits.Truncated, output_limits.Unreadable):\n        return parse_response(\"\")\n",
             target=_T, keyword="stores_no_verdict or second_answer or raises_unreadable", tags=_TAG),
    Mutation(id="M456-07", phase=456, description="CRS wording parses a truncated reply as a comment",
             path=APP / "crs_wording.py",
             anchor="    if state != output_limits.COMPLETE:\n",
             replacement="    if False:\n",
             target=_T, keyword="crs_wording", tags=_TAG),
)
