"""The evidence has to fit the context window, and say so when it does not.

The defect these tests were written against: `generated_context_chars` is a
CHARACTER budget standing in for a TOKEN budget, and the exchange rate is not
stable. Measured with the deployed qwen3.5:4b tokenizer on this corpus, prose
runs at 4.4-5.8 characters per token and a numeric table at **1.01**, because
Qwen splits digits one at a time - `30.0000` is eight tokens for seven
characters.

Three 1,200-character table passages therefore build a **3,645-token prompt
against a 1,536-token window**. llama.cpp discarded the overflow silently and
reported `prompt_eval_count` of 1,026 - five hundred tokens BELOW the ceiling,
so no caller could detect it. The answer was generated from roughly a quarter
of its evidence, citing sources it had never been shown.

The ground truth below was measured against the deployed model on 2026-09-05
and is recorded here so the estimator can be checked without one.
"""

import pytest

from app import answer
from app import context_budget as cb
from app.config import settings


#: The window these tests pin themselves to.
#:
#: THE OVERFLOW PATH IS THE SUBJECT HERE, and it only exists when the evidence
#: is too big for the window. Inheriting the deployed `num_ctx` made that a
#: property of configuration rather than of the code: raising it from 1536 to
#: 4096 (a deliberate change, see config.py and #82) made three 1,200-character
#: table passages FIT, so nothing was trimmed, so every assertion about
#: trimming failed - while the behaviour under test was perfectly intact.
#:
#: `test_three_numeric_table_passages_are_budgeted_before_the_call_and_reported`
#: caught this itself, with the guard "the fixture is not expensive enough to
#: overflow; this test would be vacuous". That guard is the reason this pin
#: exists rather than a widened fixture: the honest fix is to state the window
#: the test needs, not to inflate the data until the default happens to break.
#:
#: Same shape as conftest pinning AUTH_MODE. A suite whose result depends on a
#: deployment setting is not testing the code.
OVERFLOW_WINDOW = 1536


@pytest.fixture(autouse=True)
def _pin_the_window(monkeypatch):
    monkeypatch.setattr(settings, "num_ctx", OVERFLOW_WINDOW)

TABLE_ROW = " ".join(["30.0000"] * 10)
#: ~1,200 characters of numeric table, the shape `book2` is full of.
TABLE_TEXT = "\n".join([TABLE_ROW] * 15)[:1200]
PROSE_TEXT = (
    "The organisation shall develop and document an incident response plan "
    "that provides the organisation with a roadmap for implementing its "
    "incident response capability, describes the structure and organisation "
    "of the incident response capability, and provides a high level approach "
    "for how the incident response capability fits into the overall "
    "organisation. " * 4
)[:1200]


#: (label, text, tokens the DEPLOYED tokenizer charged). Every number here was
#: measured against qwen3.5:4b on 2026-09-05, not derived from a ratio.
GROUND_TRUTH = [
    ("one numeric value", "30.0000", 8),
    ("1,199 characters of numeric table", TABLE_TEXT, 1200),
    ("1,200 characters of prose", PROSE_TEXT, 179),
]


def passage(text, index=1):
    return {"filename": f"doc{index}.pdf", "page_start": index, "page_end": index,
            "text": text}


# ------------------------------------------------------- the estimate is safe


@pytest.mark.parametrize("label,text,measured", GROUND_TRUTH)
def test_the_estimate_never_falls_below_the_deployed_tokenizer(label, text, measured):
    """Over-estimating wastes window. Under-estimating loses evidence silently.

    Only one of those is a defect, so the estimate is only ever allowed to err
    upward.
    """
    assert cb.estimate_tokens(text) >= measured, label


def test_a_numeric_table_is_costed_near_one_token_per_character():
    """The whole point. A character budget cannot see this."""
    per_char = cb.estimate_tokens(TABLE_TEXT) / len(TABLE_TEXT)
    assert per_char > 0.9, f"tables costed at {per_char:.2f} tokens/char"


def test_prose_is_not_costed_like_a_table():
    """If it were, the estimator would drop prose sources that fit today."""
    per_char = cb.estimate_tokens(PROSE_TEXT) / len(PROSE_TEXT)
    assert per_char < 0.4, f"prose costed at {per_char:.2f} tokens/char"


# ------------------------------------------------------------- the two the brief asks for


def test_three_numeric_table_passages_fit_inside_the_context_window():
    """FAILS before the fix: the prompt was 3,645 tokens against num_ctx 1,536."""
    passages = [passage(TABLE_TEXT, i) for i in (1, 2, 3)]
    question = "what is the amplitude at t = 30 seconds"
    overhead = answer.SYSTEM_PROMPT + answer._build_prompt(
        question, [{**p, "text": ""} for p in passages]
    )

    kept, removed = cb.fit_passages(passages, overhead)
    built = answer.SYSTEM_PROMPT + answer._build_prompt(question, kept)

    assert cb.estimate_tokens(built) <= cb.evidence_budget()
    assert cb.estimate_tokens(built) + settings.max_output_tokens <= settings.num_ctx, (
        "the prompt plus the answer's own budget must fit the window"
    )
    assert removed, "three table passages cannot fit; something had to give"


def test_a_prompt_that_cannot_fit_reports_the_drop_rather_than_proceeding():
    """FAILS before the fix: the sources were handed over and silently discarded."""
    passages = [passage(TABLE_TEXT, i) for i in (1, 2, 3)]
    kept, removed = cb.fit_passages(passages, "Question: x")

    assert len(kept) < 3
    assert [r["action"] for r in removed], "nothing was reported"
    assert len(kept) + len([r for r in removed if r["action"] == "dropped"]) == 3, (
        "every source is either used or reported as removed; none may vanish"
    )

    dropped = [r for r in removed if r["action"] == "dropped"]
    assert dropped, "sources were removed with no 'dropped' record"
    assert all(r["characters_dropped"] > 0 for r in removed)
    assert all(r["filename"] for r in removed), "a report must name the source"


# ------------------------------------------------------------------ behaviour


def test_prose_is_left_completely_alone():
    """A guard, not an allocator.

    Three prose passages cost 720 tokens against a 1,286-token budget. If the
    estimator's looseness ever pushed this over the line it would be dropping
    evidence that fits, which is a regression dressed as a fix.
    """
    passages = [passage(PROSE_TEXT, i) for i in (1, 2, 3)]
    question = "what does the incident response plan have to describe"
    overhead = answer.SYSTEM_PROMPT + answer._build_prompt(
        question, [{**p, "text": ""} for p in passages]
    )

    kept, removed = cb.fit_passages(passages, overhead)
    assert removed == [], "a prose answer lost evidence it had room for"
    assert kept == passages, "prose passages were altered"


def test_sources_after_a_removed_one_are_removed_too():
    """Citation markers are positional.

    [S1], [S2], [S3] index into the list handed to the model. Keeping source 3
    after dropping source 2 renumbers them, and every citation in the answer
    then points one place to the left - a wrong page, confidently cited.
    """
    passages = [passage(TABLE_TEXT, 1), passage(TABLE_TEXT, 2), passage(PROSE_TEXT, 3)]
    kept, _ = cb.fit_passages(passages, "Question: x")

    kept_indices = [p["page_start"] for p in kept]
    assert kept_indices == sorted(kept_indices)
    assert 3 not in kept_indices, (
        "a later source was kept after an earlier one was removed, which "
        "renumbers every citation marker"
    )


def test_a_fragment_too_small_to_be_evidence_is_dropped_not_trimmed():
    passages = [passage(TABLE_TEXT, 1), passage(TABLE_TEXT, 2)]
    # room for the first and a sliver of the second
    _, removed = cb.fit_passages(passages, "", budget=1250)
    for record in removed:
        if record["action"] == "trimmed":
            assert record["characters_kept"] >= cb.MIN_USEFUL_CHARS


def test_the_overhead_is_measured_not_assumed():
    """A long question eats the evidence budget, and must be charged for it."""
    passages = [passage(PROSE_TEXT, 1)]
    short = cb.fit_passages(passages, "Question: x")
    long_ = cb.fit_passages(passages, "Question: " + TABLE_TEXT * 2)
    assert short[1] == []
    assert long_[1], "a huge question did not reduce the room for evidence"


def test_the_budget_reserves_room_for_the_answer():
    assert cb.evidence_budget() == settings.num_ctx - settings.max_output_tokens
    assert cb.evidence_budget() < settings.num_ctx
