"""#648: a drafted CRS comment may not name a standard the model was not given.
Ids M4971-M4976."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_claude_crs_comments.py"
_P = APP / "claude_crs_comments.py"
_TAG = ("w4b", "honesty")


def _m(i, desc, anchor, repl, kw):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_P, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4971, "an invented standard passes the gate",
       "    if _unknown_standards(prose, inputs):\n        return refuse(Reason.STANDARD_NOT_IN_INPUTS)\n",
       "", "never_given_is_rejected"),
    _m(4972, "only the finding's own standard is allowed, not one the requirement cites",
       "             *standard_ids.cited_standards(\" \".join(v for v in inputs.values() if v))]",
       "             ]", "requirement_itself_cites"),
    _m(4973, "a standard is compared by its spelling, not its identity",
       "standard_ids.same_standard(raw, known_one)", "raw == known_one",
       "another_spelling"),
    _m(4974, "the action is not checked for standards",
       "    if _unknown_standards(prose, inputs):", "    if _unknown_standards(comment, inputs):",
       "in_the_action_is_checked"),
    _m(4975, "any standard of the same family counts as given",
       "standard_ids.same_standard(raw, known_one)",
       "raw.split()[0] == known_one.split()[0]", "same_family"),
    _m(4976, "the prompt no longer tells the model to name no other standard",
       "3. Name NO standard that is not in the inputs below. Use NO number",
       "3. Use NO number", "name_no_other_standard"),
)
