"""#450 / #451 "absence is unknown, never positive": each entry deletes one part;
backend/tests/test_w3_450_absence_is_unknown.py (or the named test) must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w3_450_absence_is_unknown.py"
_TAG = ("w3_450", "honesty")


def _m(i, desc, path, anchor, repl, kw=None, target=_T):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=target, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(3301, "a stopped side reads as an empty search again",
       "absence.py", "        return COULD_NOT_BE_CHECKED, STOPPED_REASON\n",
       "        return NOT_FOUND, None\n", "stopped_side"),
    _m(3302, "a side whose model was unavailable reads as an empty search again",
       "absence.py", '        return COULD_NOT_BE_CHECKED, reason or "the answer model was not available"\n',
       "        return NOT_FOUND, None\n", "raised or no_text"),
    _m(3303, "a refusal that is not an absence is worded as one again",
       "absence.py", "        return COULD_NOT_BE_CHECKED, reason\n    if kind in _FINISHED_TYPES:",
       "        return NOT_FOUND, reason\n    if kind in _FINISHED_TYPES:", "refusal_that_is_not"),
    _m(3304, "one side that raises aborts the whole comparison again",
       "chat_comparison.py", "            except Exception as exc:  # noqa: BLE001 - one side failing is a state\n",
       "            except ZeroDivisionError as exc:  # noqa: BLE001\n", "raised"),
    _m(3305, "the sides after a Stop are still searched",
       "chat_comparison.py", "        if stopped:\n            # The reader pressed Stop",
       "        if False:\n            # The reader pressed Stop", "stopped_side"),
    _m(3306, "a comparison with a side that could not be checked is not marked incomplete",
       "chat_comparison.py", '        comparison["incomplete"] = True\n',
       '        comparison["incomplete"] = False\n', "raised"),
    _m(3307, "an unrecognised finding status can reach Approved again",
       "comparison.py", "    unrecognised = [s for s in statuses if s not in RECOGNISED_STATUSES]\n",
       "    unrecognised = []\n", "policy_does_not_know"),
    _m(3308, "a run whose only findings are blanks is better than a run with no findings",
       "comparison.py", "    if missing and COMPLIANT not in statuses:\n", "    if False:\n",
       "never_improves"),
    _m(3309, "the contractor's blanks outrank requirements nobody could check again",
       "comparison.py", "    if out_of_scope:\n        return {\n            # NOT AN APPROVAL.",
       "    if False and out_of_scope:\n        return {\n            # NOT AN APPROVAL.",
       "outrank or never_improves"),
    _m(3310, "a standard in scope with nothing to check is approved over again",
       "comparison.py", "    if unchecked:\n        # #450: A STANDARD IN SCOPE",
       "    if False:\n        # #450: A STANDARD IN SCOPE", "nothing_to_check"),
    _m(3311, "a rule that refused the only candidate field reads as a missing value again",
       "absence.py", '    if match_reason == "refused_by_rule":\n', "    if False:\n",
       "pairing_step"),
    _m(3312, "a failed pairing model reads as a missing value again",
       "absence.py", "    if model_reason in _MODEL_FAILURES:\n", "    if False:\n", "pairing_step"),
    _m(3313, "the review stops using the pairing check (a failed model is a missing value)",
       "comparison.py", "                if not_checked:\n                    verdict = {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
       "                if False:\n                    verdict = {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
       "unavailable_model", target="tests/test_model_matching.py"),
    _m(3314, "two profiles that share no field are 'not applicable' again",
       "applicability.py", "        if not mismatches:\n            # #450: NOTHING TO COMPARE", 
       "        if False:\n            # #450: NOTHING TO COMPARE", "share_no_filled_field"),
    _m(3315, "a failed scope reasoning is dropped without a record again",
       "applicability.py", '            out[entry["id"]] = {\n                "decision": applicability_v2.UNKNOWN, "quote": None, "page": None,',
       '            _dropped = {\n                "decision": applicability_v2.UNKNOWN, "quote": None, "page": None,',
       "scope_reasoning_that_failed"),
    _m(3316, "a drafted comment on a missing or unresolved row may say it conforms",
       "claude_crs_comments.py", "    if status in (comparison.MISSING_INFORMATION, comparison.NEEDS_ENGINEER_REVIEW):\n",
       "    if False:\n", "drafted_comment"),
    _m(3317, "a run with no recommendation can be approved without a reason",
       "comparison.py", '    if not recommended and code == codes[0] and not (override_reason or "").strip():\n',
       "    if False:\n", "no_recommendation"),
    Mutation(id="M3318", phase=3318, runner="vitest",
             description="a side that could not be checked is rendered as 'not found' again",
             path=FRONTEND_SRC / "components" / "chat" / "AnswerComparison.tsx",
             anchor='const couldNotCheck = !notInLibrary && side.answer_type === "could_not_be_checked";',
             replacement="const couldNotCheck = false;",
             target="src/components/chat/AnswerComparison.test.tsx",
             keyword="could not be checked", tags=_TAG),
)
