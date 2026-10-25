"""Answer prompt variants for the local engine (order 189, part B).

OFF BY DEFAULT: `settings.answer_prompt_variant` is "default", which returns the
prompt `answer.py` always used, byte for byte. A variant is a measurement tool
first: `eval/answer_quality/` scores it on invented sheets, and the rule
`quality_scoring.keep_variant` says it may become the default only if it is the
same or better on EVERY measure and costs no citation quality and no false Meets.

Local lane only. The Claude lane keeps its own quoting prompt whatever this
says, so no variant changes what leaves the machine. A variant only changes the
wording of the instructions; the sources, the question and every check on the
answer (`verify_claims`, `ground_numbers`, the citation validator) are
untouched, so a variant can make an answer worse but never skip a check.
Generic: no document type is named.
"""

from __future__ import annotations

from .config import settings

DEFAULT = "default"

#: name -> the rule lines appended to the base prompt, or None for "swap in the
#: quoting prompt" (`quote_first`).
_EXTRA_RULES: dict[str, str] = {
    "cite_every_sentence": (
        "\n- End every sentence that states a fact with its citation. A sentence you cannot "
        "cite, leave out. Do not repeat the question."
    ),
    "check_figures": (
        "\n- Before you write a number, find it in the source you cite. If it is not "
        "there, leave it out. Copy numbers and units exactly as the source writes them."
    ),
}
VARIANTS: tuple[str, ...] = (DEFAULT, "quote_first", *_EXTRA_RULES)


def pick(claude: bool, base: str, quoting: str) -> str:
    """The system prompt. `base` is the plain prompt, `quoting` the one that
    asks for an exact quote per claim. The Claude lane and an unknown variant
    name get what they always got."""
    variant = settings.answer_prompt_variant
    if claude:
        return quoting
    if variant == "quote_first":
        return quoting
    return base + _EXTRA_RULES.get(variant, "")
