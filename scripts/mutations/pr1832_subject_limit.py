"""PR #1832 (owner, 16 Nov 2026: the corrosion allowance of a vessel is a code-proven Pass): "The maximum/minimum <subject> shall be <value> <unit>" is a number rule
and its proof is asked of the clause quote as the limit is PRINTED. Each entry deletes one control; `tests/test_ca_subject_limit.py` must notice.
Ids M1832-01 onwards (CLAUDE.md rule 12); the PR number is provisional until the PR is opened."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ca_subject_limit.py"
_TAGS = ("honesty", "critical", "numbers")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1832-01",
        phase=1832,
        description="the extractor does not read the shape: the clause stays a statement and nothing is compared",
        path=APP / "requirements_3b.py",
        anchor="        return own_value_limit.parse(sentence) or own_value_limit.subject_be(sentence) or own_value_limit.trailing(sentence)\n",
        replacement="        return own_value_limit.parse(sentence) or own_value_limit.trailing(sentence)\n",
        target=_T,
        keyword="shape_is_read_as_a_limit",
        tags=_TAGS,
    ),
    Mutation(
        id="M1832-02",
        phase=1832,
        description="a registered field NAME that starts with a comparator word is read as a limit on something",
        path=APP / "own_value_limit.py",
        anchor='        return None  # "maximum allowable working pressure" is a field, not a limit on one\n',
        replacement="        pass\n",
        target=_T,
        keyword="stays_a_statement",
        tags=_TAGS,
    ),
    Mutation(
        id="M1832-03",
        phase=1832,
        description="the proof asks the clause quote for the normalised limit (3200 um), not the limit as printed (3.2 mm)",
        path=APP / "agent_review_calculator.py",
        anchor='        "raw_value": proof.stored_text(item.get("raw_value") if item.get("raw_value") not in (None, "") and item.get("raw_unit") else value) or None,\n',
        replacement='        "raw_value": proof.stored_text(value) or None,\n',
        target=_T,
        keyword="limit_as_printed",
        tags=_TAGS,
    ),
    Mutation(
        id="M1832-04",
        phase=1832,
        description="the direction of the shape is not read from the clause's own comparator word: no direction is shown",
        path=APP / "agent_review_code_proof.py",
        anchor='        got = _subject_be_sense(str(quote or ""), numbers[0])\n',
        replacement="        got = None\n",
        target=_T,
        keyword="direction_and_the_subject",
        tags=_TAGS,
    ),
    Mutation(
        id="M1832-05",
        phase=1832,
        description="a dotted abbreviation ends the sentence that names the subject",
        path=APP / "agent_review_code_proof.py",
        anchor='_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])(?<!\\b[A-Za-z]\\.[A-Za-z]\\.)\\s+|\\n+")\n',
        replacement='_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\\s+|\\n+")\n',
        target=_T,
        keyword="dotted_abbreviation",
        tags=_TAGS,
    ),
    Mutation(
        id="M1832-06",
        phase=1832,
        description="a field spelling written without full stops does not match the text written with them (C.A.)",
        path=APP / "agent_review_pass_guards.py",
        anchor='            or re.search(rf"(?<!\\w){re.escape(sp)}(?!\\w)", undotted)\n',
        replacement="            or False\n",
        target=_T,
        keyword="direction_and_the_subject",
        tags=_TAGS,
    ),
)
