"""#648: a drafted CRS comment may not name a standard the model was not given.
Ids M4971-M4976 (standard names) and M4991-M4998 (unsupported claims)."""
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
       "Name NO standard that is not in the inputs below. Use NO number",
       "Use NO number", "name_no_other_standard"),
)

# ---- #648 second half: a sentence the evidence does not support. M4991-M4998.
MUTATIONS = MUTATIONS + (
    _m(4991, "an unsupported claim passes the gate",
       "    if unsupported_sentences(prose, inputs):\n        return refuse(Reason.CLAIM_NOT_IN_QUOTES)\n", "",
       "says_something_the_evidence_does_not"),
    _m(4992, "the finding's own quotes are not used as the evidence",
       "    known = set(_WORD.findall(_fold(\" \".join(v for v in inputs.values() if v))))",
       "    known = set()", "words_from_the_requirement"),
    _m(4993, "the reviewer vocabulary is ignored",
       "if not _known(word, known) and not _known(word, vocabulary) and word not in words:",
       "if not _known(word, known) and word not in words:", "words_from_the_requirement"),
    _m(4994, "a single stray word is rejected",
       "MAX_UNSUPPORTED_WORDS_PER_SENTENCE = 1", "MAX_UNSUPPORTED_WORDS_PER_SENTENCE = 0", "one_stray_word"),
    _m(4995, "five stray words are tolerated",
       "MAX_UNSUPPORTED_WORDS_PER_SENTENCE = 1", "MAX_UNSUPPORTED_WORDS_PER_SENTENCE = 5",
       "says_something_the_evidence_does_not or one_stray_word"),
    _m(4996, "a plural is a different word",
       "    out = {word}\n    for suffix in (\"es\", \"s\", \"ed\", \"ing\", \"d\"):",
       "    out = {word}\n    for suffix in ():", "plural_of_a_word"),
    _m(4997, "the action is not checked for unsupported claims",
       "    if unsupported_sentences(prose, inputs):", "    if unsupported_sentences(comment, inputs):",
       "claim_in_the_action or in_the_action_is_rejected"),
    _m(4998, "the prompt no longer tells the model to say nothing the inputs do not say",
       "3. Say nothing the inputs below do not say: no causes, faults, materials or opinions of your own. Name NO standard",
       "3. Name NO standard", "say_nothing_the_inputs"),
)
