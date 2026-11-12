"""A Pass of a rule without numbers needs the rule's own field and, for a conditional rule, the condition quoted; and a Pass the code
did not compare is never "Proven by code" (owner, 12 Nov 2026). Invented paper, rule book and model.

Guards only take confidence away: never a Fail, never a number rule. They run on EVERY Pass answer, whatever the gate decided, and on
the second reader's own quotes."""

# ruff: noqa: F811
from __future__ import annotations

import itertools
import json

import pytest

from app import agent_review_absence as absence
from app import agent_review_pass_guards as G
from app import agent_review_request as request_mod
from app import agent_review_two_reader as two
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app import crs_ai_words as words
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import TwoLane

#: the label and its value on neighbouring lines, the other fields further away
SPACED = "DATA SHEET\nCoating layers two\nfiller line one\nfiller line two\nMarking blue\nfiller line three\nfiller line four\nSerial invented"
#: a stacked layout: the label line above its value line
STACKED = "DATA SHEET\nCoating layers\nTwo layers carbon steel\nfiller line one\nfiller line two\nMarking\nBlue paint"
VERDICT_MET = ("AI verdict, two readers agree", "AI verdict: met")
THINKS_MET = ("AI opinion, engineer to confirm", "AI thinks: met")


def stored(run_id, iid):
    return json.loads(lines_of(run_id)[iid]["line_json"])


def setup(w, page=SPACED, iid="R-coat", **answer):
    from app import db

    with db.connect() as conn:
        conn.execute("UPDATE pages SET text = ? WHERE document_id = ?", (page, s.PAPER))
    w["fake"].answers = {iid: {**s.ANSWERS[iid], **answer}}


def cls(run_id, iid="R-coat"):
    row = lines_of(run_id)[iid]
    return row["verdict_class"], row["word"]


# ---------------------------------------------------------------- owner: a Pass the code did not compare is never "Proven by code"


def test_a_textual_pass_with_both_quotes_and_a_second_reader_is_ai_verdict_met_not_proven(
    w,
):
    setup(w)
    run_id = run_review()
    assert cls(run_id) == VERDICT_MET and stored(run_id, "R-coat")["pass_guard"] == {
        "ok": True
    }


def test_only_a_pass_the_code_compared_is_proven_by_code(w):
    from app import db

    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ?", (s.PAPER_PAGE, s.PAPER)
        )
    w["fake"].answers = {"R-frame": s.ANSWERS["R-frame"]}
    run_id = run_review()
    assert (
        cls(run_id, "R-frame") == ("Proven by code", "Pass")
        and stored(run_id, "R-frame")["compare"]["decided"] is True
    )


def test_no_line_shape_is_proven_by_code_pass_without_a_passed_code_comparison():
    decided = ["decided by code", "AI verdict", "engineer", None]
    compares = [
        None,
        {},
        {"decided": False, "verdict": "meets"},
        {"decided": True, "verdict": "does_not_meet"},
        {"decided": True, "verdict": "meets"},
    ]
    for by, cmp_, guard, second, tier in itertools.product(
        decided,
        compares,
        [None, {"ok": True}, {"ok": False}],
        [None, {"agree": True, "model": "m2"}, {"agree": False}],
        ["AI approved", None],
    ):
        line = {
            "item_id": "R-1", "verdict": "Pass", "ai_verdict": "Pass", "reason_code": "met", "decided_by": by, "compare": cmp_, "model": "m1",
            "pass_guard": guard, "second_opinion": second, "tier": tier, "checklist": tier is None, "source": "rule",
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "paper_quote": "Body material: steel",
        }  # fmt: skip
        got = W.classify(line)
        compared = by == "decided by code" and cmp_ == {
            "decided": True,
            "verdict": "meets",
        }
        assert (got["verdict_class"] == "Proven by code") is compared, (
            by,
            cmp_,
            guard,
            second,
            tier,
        )
        if (
            got["verdict_class"] == two.CLASS_TWO_READERS
        ):  # the class needs: a guard result ok, a second reader who agreed
            assert (
                guard == {"ok": True}
                and second
                and second.get("agree") is True
                and got["verdict_label"] == two.WORD_MET
            )
        assert got["verdict_label"] not in ("Pass", "Fail") or compared


# ---------------------------------------------------------------- guard A: the field


def test_a_pass_on_the_rules_own_field_line_is_ai_verdict_met(w):
    setup(w)
    assert cls(run_review()) == VERDICT_MET


def test_a_label_line_directly_above_the_value_line_counts(w):
    setup(w, page=STACKED, paper_quote="Two layers carbon steel")
    assert cls(run_review()) == VERDICT_MET


def test_a_label_line_below_the_value_line_never_counts(w):
    setup(
        w,
        page="DATA SHEET\nTwo layers carbon steel\nCoating layers\nfiller",
        paper_quote="Two layers carbon steel",
    )
    run_id = run_review()
    assert (
        cls(run_id) == THINKS_MET
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_FIELD_NOT_QUOTED
    )


def test_a_pass_quoted_on_another_fields_row_is_ai_thinks_met_with_a_plain_reason(w):
    setup(w, paper_quote="Marking blue")
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == THINKS_MET
    assert (
        row["reason"] == G.FIELD_LINE_WHY
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_FIELD_NOT_QUOTED
    )


def test_a_rule_whose_field_is_not_known_is_never_proven_or_ai_verdict_met(w):
    for it in w["doc"]["items"]:
        if it["item_id"] == "R-coat":
            it["rule_label"] = {**it["rule_label"], "field": None}
    setup(w)
    run_id = run_review()
    assert (
        cls(run_id) == THINKS_MET
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_FIELD_UNKNOWN
    )


def test_the_ais_own_field_label_is_never_evidence(w):
    setup(w, paper_quote="Marking blue", field_label="Coating layers")
    assert cls(run_review()) == THINKS_MET


def test_a_single_generic_word_is_the_field_only_as_the_whole_label_line():
    item = {"rule_label": {"field": "valve_type"}}
    assert (
        G.belongs(item, "Safety valve 12", "x\nValve type\nSafety valve 12")[0] is True
    )  # a label line above
    assert (
        G.belongs(item, "Valve material carbon 12", "x\nValve material carbon 12")[0]
        is False
    )  # "valve" is not the field's label
    assert (
        G.belongs(
            {"rule_label": {"field": "design_code"}},
            "Code of practice 12 here",
            "a\nCode of practice 12 here",
        )[0]
        is False
    )
    assert (
        G.belongs(
            {"rule_label": {"field": "design_code"}},
            "ASME VIII 12",
            "a\nDesign code\nASME VIII 12",
        )[0]
        is True
    )


def test_the_quotes_own_line_carrying_another_known_fields_words_refuses_the_label_above():
    item = {"rule_label": {"field": "spring_material"}}
    page = "filler\nSpring material\nBody material carbon steel 12"
    assert (
        G.belongs(item, "Body material carbon steel 12", page)[0] is False
    )  # another field's row, whatever stands above it
    assert (
        G.belongs(
            item, "Inconel X750 grade", "filler\nSpring material\nInconel X750 grade"
        )[0]
        is True
    )


def test_a_digit_or_a_long_line_above_is_not_a_label_line():
    item = {"rule_label": {"field": "spring_material"}}
    assert (
        G.belongs(item, "Inconel X750", "Spring material 2 off\nInconel X750")[0]
        is False
    )
    assert (
        G.belongs(
            item,
            "Inconel X750",
            "The spring material is stated below for the sour service case\nInconel X750",
        )[0]
        is False
    )


def _own_line_of(role):
    fw = absence.field_words([(role, "x")])
    return (
        fw.spellings[0] if fw and fw.spellings else role.replace("_", " ")
    ) + " 12 value"


def test_no_registry_field_accepts_another_fields_own_line_except_the_registrys_own_synonyms():
    """The reviewer found 298 of 5,402 (rule field, other field's own line) pairs accepted; each one left must be explained."""
    roles = sorted(absence.registry()["roles"])
    accepted = []
    for rule, other in itertools.permutations(roles, 2):
        line = _own_line_of(other)
        if G.belongs({"rule_label": {"field": rule}}, line, f"filler\n{line}\nfiller")[
            0
        ]:
            accepted.append((rule, other))
    assert len(roles) * (len(roles) - 1) == 5402
    # the two left are one quantity under two names in the registry's own synonym table (rated capacity = rated flow)
    assert sorted(accepted) == [
        ("rated_capacity", "rated_flow"),
        ("rated_flow", "rated_capacity"),
    ]


# ---------------------------------------------------------------- guard B: the condition


@pytest.fixture
def conditional(monkeypatch):
    quote = "The coating shall be applied in two layers for sour service."
    monkeypatch.setitem(s.RULES, "R-coat", (quote, "4.4", None, None, None, None))
    return quote


COND_PAGE = SPACED + "\nService: sour crude\nService: crude"


def test_a_conditional_rule_needs_a_quote_of_the_condition(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    setup(w, page=COND_PAGE, clause_quote=conditional)
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == THINKS_MET
    assert (
        row["reason"] == G.CONDITION_NOT_QUOTED_WHY
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_CONDITION_NOT_QUOTED
    )


def test_the_value_quote_repeated_is_not_a_condition_quote(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    setup(
        w,
        page=COND_PAGE,
        clause_quote=conditional,
        condition_quote="Coating layers two",
        condition_page=1,
    )
    assert cls(run_review()) == THINKS_MET


def test_an_unrelated_line_is_not_a_condition_quote(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    setup(
        w,
        page=COND_PAGE,
        clause_quote=conditional,
        condition_quote="Service: crude",
        condition_page=1,
    )  # "service" is the head, not the condition
    assert cls(run_review()) == THINKS_MET


def test_a_verified_quote_holding_a_word_of_the_condition_lets_the_pass_become_ai_verdict_met(
    w, conditional
):
    w["doc"], w["cache"] = s.item_doc()
    setup(
        w,
        page=COND_PAGE,
        clause_quote=conditional,
        condition_quote="Service: sour crude",
        condition_page=1,
    )
    assert cls(run_review()) == VERDICT_MET


@pytest.mark.parametrize(
    "text,conditional_,why",
    [
        ("Springs for sour service shall be protected.", True, "for ... service"),
        ("A valve in hydrogen service shall have a bonnet.", True, "in ... service"),
        ("Each valve in sour service shall be marked.", True, "in ... service"),
        ("The rule is applicable to oil service.", True, "to ... service"),
        (
            "The coating shall be tested when specified.",
            True,
            "the word 'when': a generic condition, safe direction (needs a quote)",
        ),
        ("The gauge is fitted where applicable.", True, "the word 'where'"),
        ("It shall be fitted if required by the purchaser.", True, "the word 'if'"),
        (
            "The finish is standard unless otherwise specified.",
            True,
            "the word 'unless' (and 'otherwise')",
        ),
        (
            "The valve is sized for the duty point.",
            False,
            "'duty point' is a quantity, not a condition",
        ),
        ("The service life shall be 25 years.", False, "'service life' is a quantity"),
        (
            "A service factor of 1.15 is applied.",
            False,
            "'service factor' is a quantity",
        ),
        (
            "The service manual shall be supplied.",
            False,
            "'service manual' is a document",
        ),
        ("The coating shall be applied in two layers.", False, "no condition word"),
    ],
)
def test_is_conditional_near_miss_table(text, conditional_, why):
    assert V.is_conditional(text) is conditional_, why


def test_the_condition_terms_are_the_words_of_the_condition_not_the_head():
    assert G.condition_terms("Springs for sour service shall be protected.") == {"sour"}
    assert G.condition_terms("protected when installed offshore, and tested") == {
        "installed",
        "offshore",
    }
    assert G.condition_terms("It shall be fitted if required by the purchaser.") >= {
        "purchaser"
    }


def _answer(**kw):
    return {
        "paper_page": 1,
        "paper_quote": "Coating layers two",
        "clause_quote": "Springs for sour service shall be protected.",
        **kw,
    }


PAGES = {1: SPACED + "\nService: sour crude\nService: crude\nCoating layers two sour"}


def test_condition_ok_cases():
    base = _answer(condition_page=1)

    def ok(quote, **kw):
        return G.condition_ok({**base, "condition_quote": quote, **kw}, PAGES, {"sour"})

    assert ok("Service: sour crude") is True
    assert ok("Service: crude") is False  # no word of the condition
    assert ok("Coating layers two") is False  # the value quote
    assert ok("Coating layers two sour") is False  # holds the value quote
    assert ok("Sour not on the page at all") is False  # not verified
    assert ok("Service: sour crude", condition_page=2) is False  # not on that page


# ---------------------------------------------------------------- finding 1: every path, every switch


@pytest.fixture
def switches(monkeypatch):
    from app.config import settings

    for name in (
        "agent_review_two_reader_verdict_enabled",
        "agent_review_two_reader_absence_enabled",
        "agent_review_two_reader_other_paper_enabled",
    ):
        monkeypatch.setattr(settings, name, True)


@pytest.mark.parametrize("old_second", [None, True])
def test_a_wrong_field_pass_never_becomes_ai_verdict_met_by_any_path(
    w, switches, old_second
):
    """The bypass: a first-reader Pass the old second opinion left a Query, then an independent second reader quoting the same wrong row."""
    fake = w["fake"] = TwoLane(agree=old_second)
    setup(w, paper_quote="Marking blue")
    fake.second = {"R-coat": {**s.ANSWERS["R-coat"], "paper_quote": "Marking blue"}}
    run_id = run_review()
    assert cls(run_id) == THINKS_MET
    line = stored(run_id, "R-coat")
    assert (
        line["pass_guard"]["ok"] is False
        and line["reason_code"] == G.CODE_FIELD_NOT_QUOTED
        and "two_reader" not in line
    )


def test_the_second_readers_own_wrong_field_quote_never_earns_the_class(w, switches):
    fake = w["fake"] = TwoLane(agree=None)
    setup(w)
    fake.second = {
        "R-coat": {**s.ANSWERS["R-coat"], "paper_quote": "Marking blue"}
    }  # the first reader is right, the second quotes another row
    run_id = run_review()
    assert cls(run_id) == THINKS_MET
    assert stored(run_id, "R-coat")["two_reader"]["pass_guard"]["ok"] is False


def test_a_right_field_pass_the_old_second_opinion_left_open_is_ai_thinks_then_the_independent_reader_may_agree(
    w, switches
):
    fake = w["fake"] = TwoLane(agree=None)
    setup(w)
    fake.second = {"R-coat": s.ANSWERS["R-coat"]}
    assert cls(run_review()) == VERDICT_MET


def test_every_line_shape_with_a_guard_objection_ends_as_neither_proof_nor_ai_verdict_met():
    """Brute force over stored-line shapes: a Pass answer the guards object to is never 'Proven by code' and never 'AI verdict: met'."""
    for verdict_, by, agree, guard, rec_guard, rec_verdict in itertools.product(
        ["Pass", "Query"], ["decided by code", "AI verdict", "engineer"], [None, True, False], [None, {"ok": True}, {"ok": False, "code": G.CODE_FIELD_NOT_QUOTED}],
        [None, {"ok": True}, {"ok": False}], ["met", "not met"],
    ):  # fmt: skip
        line = {
            "item_id": "R-1", "source": "rule", "standard": "S", "clause": "1", "verdict": verdict_, "decided_by": by, "ai_verdict": "Pass",
            "reason_code": "met", "model": "m1", "tier": "AI approved", "pass_guard": guard, "paper_page": 1, "paper_quote": "Value line 12",
            "second_opinion": {"agree": agree, "model": "m2"} if agree is not None else None, "textual_pass": verdict_ == "Pass",
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "field_label_ai": "Other",
            "two_reader": {"verdict": rec_verdict, "model": "m3", "reason_code": "met", "paper_page": 1, "paper_quote": "Value line 12", "pass_guard": rec_guard,
                           "spans": {"first": [0, 5], "second": [0, 5]}, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}},
        }  # fmt: skip
        got = W.classify(W.demote_uncompared_pass(line))
        if guard != {"ok": True}:
            assert got["verdict_class"] not in (
                "Proven by code",
                two.CLASS_TWO_READERS,
            ), (verdict_, by, agree, guard, rec_guard)
        elif (
            rec_guard != {"ok": True} and got["verdict_class"] == two.CLASS_TWO_READERS
        ):
            assert (
                agree is True
            )  # only the old agreement route, whose own quotes passed the guards upstream


# ---------------------------------------------------------------- a Fail and a number rule are never touched


def test_a_fail_is_never_changed_by_these_guards(w):
    setup(
        w, iid="R-mark", paper_quote="Coating layers two"
    )  # another field's row: a Pass would be refused, a Fail must not be
    assert cls(run_review(), "R-mark") == (
        "AI verdict, two readers agree",
        "AI verdict: not met",
    )  # the Pass guards never touch a Fail


def test_a_number_rule_with_a_code_comparison_is_untouched(w):
    from app import db

    for it in w["doc"]["items"]:
        if it["item_id"] == "R-frame":
            it["rule_label"] = {**it["rule_label"], "field": "something_else"}
    w["fake"].answers = {"R-frame": s.ANSWERS["R-frame"]}
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ?", (s.PAPER_PAGE, s.PAPER)
        )
    assert cls(run_review(), "R-frame") == ("Proven by code", "Pass")


def test_the_answer_shape_has_the_condition_slot_and_the_prompt_asks_for_it():
    assert (
        "condition_quote" in request_mod.ANSWER_SHAPE
        and "condition_page" in request_mod.ANSWER_SHAPE
    )
    assert "condition_quote" in request_mod.SYSTEM


# ---------------------------------------------------------------- the words state only what the code saw


def test_every_reason_and_every_plain_phrase_of_the_guards_states_only_what_the_code_saw():
    banned = (
        "does not state",
        "not mentioned",
        "absent",
        "missing",
        "wrong",
        "incorrect",
        "is not the",
        "not the field",
        "different field",
    )
    reasons = [
        G.FIELD_UNKNOWN_WHY,
        G.FIELD_LINE_WHY,
        G.CONDITION_NOT_QUOTED_WHY,
        G.CONDITION_WORD_WHY,
    ]
    phrases = [words.CODE_PHRASES[c] for c in G.CODES] + [
        words.why_phrase(r) for r in reasons
    ]
    for text in reasons + phrases:
        assert not any(b in text.lower() for b in banned), text
        assert text and text != words.UNKNOWN_WHY, text
    assert "line above it" in G.FIELD_LINE_WHY  # exactly what the code looked at


# ---------------------------------------------------------------- R39b A: the line above must be ONLY the label


def test_a_row_holding_a_text_value_is_not_a_label_line_above():
    """The reviewer's page: a material row (label and text value) above a bonnet-type row: the next row must not pass for the material."""
    item = {"rule_label": {"field": "body_material"}}
    page = "filler\nBody material: carbon steel\nBonnet type: bolted\nfiller"
    assert G.belongs(item, "Bonnet type: bolted", page)[0] is False
    stacked = "filler\nBody material\nA216 WCB\nfiller"
    assert (
        G.belongs(item, "A216 WCB", stacked)[0] is True
    )  # a label-only line above the value
    assert (
        G.belongs(item, "A216 WCB", "filler\nBody material (unit)\nA216 WCB")[0] is True
    )  # a parenthesised unit header is allowed
    assert (
        G.belongs(item, "A216 WCB", "filler\nBody material units\nA216 WCB")[0] is True
    )
    assert (
        G.belongs(
            item, "A216 WCB", "filler\nBody material and bonnet bolting\nA216 WCB"
        )[0]
        is False
    )  # more than the label


def test_the_label_only_rule_also_holds_for_a_field_the_registry_does_not_know(w):
    setup(
        w,
        page="DATA SHEET\nCoating layers: two layers\nTwo layers carbon steel\nfiller\nfiller",
        paper_quote="Two layers carbon steel",
    )
    assert (
        cls(run_review()) == THINKS_MET
    )  # "Coating layers: two layers" is a row with a value, not a label line


# ---------------------------------------------------------------- R39b: the condition quote saying the condition does NOT hold


@pytest.mark.parametrize(
    "quote,ok",
    [
        ("Service: sour crude", True),
        ("Service: not sour", False),
        ("Not a sour service", False),
        ("Service: non-sour crude", False),
        ("Sour service without hydrogen", False),
        ("Service: not expected to be sour", False),
        ("Service: nil sour content", False),
    ],
)
def test_a_condition_quote_with_a_negation_next_to_the_condition_word_is_refused(
    quote, ok
):
    page = {1: SPACED + f"\n{quote}"}
    answer = _answer(condition_quote=quote, condition_page=1)
    assert G.condition_ok(answer, page, {"sour"}) is ok


# ---------------------------------------------------------------- R39b B: each sentence is true of its route


def _verdict_line(**kw):
    from tests.test_agent_review_crs import OK, SK

    base = {
        "item_id": "R-1", "source": "rule", "standard": "S", "clause": "1", "verdict": "Pass", "decided_by": "AI verdict", "ai_verdict": "Pass",
        "reason_code": "met", "model": "m1", "paper_page": 1, "paper_quote": "Coating layers two", "clause_quote": "x",
        "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "second_opinion": {"agree": True, "model": "m2"},
        "pass_guard": {"ok": True}, "field": "Coating layers", "field_roles": [], "reasoning": "r",
    }  # fmt: skip
    return W.final_cap({**base, **kw}, OK, skill_ids=SK, paper_kind="datasheet")


def _comment(line):
    from app import crs_ai_workbook as WB

    return WB.layout_comment(line, *WB.status_of(line))


def test_the_always_on_route_says_the_second_reader_saw_the_first_answer_never_independently():
    line = _verdict_line()
    assert (line["verdict_class"], line["verdict_label"]) == (
        two.CLASS_TWO_READERS,
        two.WORD_MET,
    ) and not two.is_independent(line)
    text = _comment(line)
    assert "saw the first answer" in text and "independent" not in text.lower()
    assert text.count(words.VERDICT_PREFIX_CHECKED) == 1


def test_the_independent_step_says_independently():
    line = _verdict_line(
        verdict="Query", decided_by="engineer", second_opinion=None,
        two_reader={"verdict": "met", "model": "m3", "reason_code": "met", "paper_page": 1, "paper_quote": "Coating layers two", "pass_guard": {"ok": True},
                    "spans": {"first": [0, 5], "second": [0, 5]}, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}},
    )  # fmt: skip
    assert two.agrees(line) and two.is_independent(line)
    text = _comment(line)
    assert (
        "reached independently by two AI readers" in text
        and "saw the first answer" not in text
    )


# ---------------------------------------------------------------- R39b C: the same limit for Fail


def test_no_line_shape_is_proven_by_code_fail_without_a_failed_comparison_or_the_absence_proof():
    absence_by = V.BY_ABSENCE
    for by, cmp_, second, hold in itertools.product(
        ["decided by code", "AI verdict", absence_by, V.BY_FINAL_CHECK, "engineer"],
        [None, {}, {"decided": True, "verdict": "meets"}, {"decided": True, "verdict": "does_not_meet"}, {"decided": False, "verdict": "does_not_meet"}],
        [None, {"agree": True, "model": "m2"}, {"agree": False}], [False, True],
    ):  # fmt: skip
        line = {
            "item_id": "R-1", "verdict": "Fail", "ai_verdict": "Fail", "reason_code": "not_met", "decided_by": by, "compare": cmp_, "model": "m1",
            "second_opinion": second, "conditional_hold": hold, "tier": "AI approved", "source": "rule",
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "paper_quote": "Body material: steel",
        }  # fmt: skip
        got = W.classify(line)
        proved = (
            by == "decided by code"
            and cmp_ == {"decided": True, "verdict": "does_not_meet"}
        ) or by == absence_by
        assert (got["verdict_class"] == "Proven by code") is proved, (
            by,
            cmp_,
            second,
            hold,
        )
        if got["verdict_class"] == two.CLASS_TWO_READERS:
            assert (
                got["verdict_label"] == two.WORD_NOT_MET
                and second
                and second.get("agree") is True
                and not hold
            )


def test_nothing_but_a_proven_fail_reaches_the_contractor_copy(tmp_path):
    from app import crs_ai_workbook as WB
    from tests.test_agent_review_crs import META, rows_of

    proven = _verdict_line(
        verdict="Fail",
        ai_verdict="Fail",
        reason_code="not_met",
        decided_by="decided by code",
        compare={"decided": True, "verdict": "does_not_meet"},
        item_id="R-1",
    )
    textual = _verdict_line(
        verdict="Fail",
        ai_verdict="Fail",
        reason_code="not_met",
        item_id="R-2",
        field="Other field",
    )
    assert (
        textual["verdict_label"] == two.WORD_NOT_MET and textual["verdict"] == "Query"
    )
    path = WB.write([proven, textual], tmp_path / "c.xlsx", META, "contractor")
    assert [r["Item No"] for r in rows_of(path)] == [1] and len(rows_of(path)) == 1


# ---------------------------------------------------------------- R39b D: earlier lines are re-labelled once, audited, content kept


def _old_db(tmp_path, monkeypatch):
    import sqlite3

    from app import agent_review_schema as schema
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    conn = sqlite3.connect(tmp_path / "old.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE audit_events (id INTEGER PRIMARY KEY, at TEXT, actor_user_id, actor_username TEXT, action TEXT, resource_type TEXT, resource_id TEXT, outcome TEXT, detail TEXT)"
    )
    for stmt in schema._STATEMENTS:
        conn.execute(stmt)
    lines = {
        "i-textual-pass": {"verdict": "Pass", "decided_by": "AI verdict", "ai_verdict": "Pass", "reason_code": "met", "tier": "AI approved", "model": "m1", "second_opinion": {"agree": True, "model": "m2"}, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "keep": "a"},
        "i-number-pass": {"verdict": "Pass", "decided_by": "decided by code", "ai_verdict": "Pass", "compare": {"decided": True, "verdict": "meets"}, "tier": "AI approved", "keep": "b"},
        "i-textual-fail": {"verdict": "Fail", "decided_by": "AI verdict", "ai_verdict": "Fail", "reason_code": "not_met", "tier": "AI approved", "model": "m1", "second_opinion": {"agree": True, "model": "m2"}, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "keep": "c"},
        "i-absence-fail": {"verdict": "Fail", "decided_by": V.BY_ABSENCE, "ai_verdict": "Fail", "tier": "AI approved", "keep": "d"},
    }  # fmt: skip
    for iid, line in lines.items():
        word, cls = line["verdict"], "Proven by code"
        conn.execute(
            "INSERT INTO agent_review_line (run_id,item_id,verdict_class,word,page,clause,rule_book,reason,rule_tier,line_json,trace_json,decided_at) VALUES ('r',?,?,?,3,'4.1','Book','why','Owner',?, 'trace','t')",
            (iid, cls, word, json.dumps({"item_id": iid, **line})),
        )
    conn.commit()
    return conn, schema, lines


def _snapshot(conn):
    return {
        r["item_id"]: dict(r) for r in conn.execute("SELECT * FROM agent_review_line")
    }


def test_earlier_proven_lines_are_relabelled_once_with_the_old_class_kept_and_every_other_field_unchanged(
    tmp_path, monkeypatch
):
    conn, schema, lines = _old_db(tmp_path, monkeypatch)
    before = _snapshot(conn)
    schema.create_tables(conn)
    after = _snapshot(conn)
    assert (
        after["i-number-pass"]["verdict_class"],
        after["i-number-pass"]["word"],
    ) == ("Proven by code", "Pass")  # compared: stays proven
    assert (
        after["i-absence-fail"]["verdict_class"],
        after["i-absence-fail"]["word"],
    ) == ("Proven by code", "Fail")
    assert (
        after["i-number-pass"] == before["i-number-pass"]
        and after["i-absence-fail"] == before["i-absence-fail"]
    )  # byte for byte
    assert (
        after["i-textual-pass"]["word"] == "AI thinks: met"
        and after["i-textual-fail"]["word"] == "AI verdict: not met"
    )
    for iid in ("i-textual-pass", "i-textual-fail"):
        old, new = (
            json.loads(before[iid]["line_json"]),
            json.loads(after[iid]["line_json"]),
        )
        assert (
            new["class_before_1778"] == "Proven by code"
            and new["word_before_1778"] == lines[iid]["verdict"]
        )
        assert new["verdict_before_1778"] == lines[iid]["verdict"]
        assert new["decided_by_before_1778"] == lines[iid]["decided_by"]
        changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
        assert changed <= {
            "verdict",
            "decided_by",
            "why",
            "textual_pass",
            "textual_fail",
            "class_before_1778",
            "word_before_1778",
            "verdict_before_1778",
            "decided_by_before_1778",
        }, changed
        for col in (
            "run_id",
            "item_id",
            "page",
            "clause",
            "rule_book",
            "rule_tier",
            "trace_json",
            "decided_at",
        ):
            assert after[iid][col] == before[iid][col], col
    audit = [
        tuple(r)
        for r in conn.execute(
            "SELECT action, resource_id, detail FROM audit_events WHERE action = ?",
            (schema.RELABEL_ACTION,),
        )
    ]
    assert audit == [
        (
            schema.RELABEL_ACTION,
            "agent_review_line",
            "lines re-labelled: 2 (Fail -> AI verdict: not met x1; Pass -> AI thinks: met x1)",
        )
    ]
    schema.create_tables(
        conn
    )  # idempotent: nothing is touched again, no second audit row
    assert _snapshot(conn) == after
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = ?",
            (schema.RELABEL_ACTION,),
        ).fetchone()[0]
        == 1
    )


def test_a_failure_while_relabelling_rolls_everything_back(tmp_path, monkeypatch):
    from app.api import agent_review_schemas as contract

    conn, schema, _lines = _old_db(tmp_path, monkeypatch)
    before = _snapshot(conn)
    monkeypatch.setattr(contract, "legal_word", lambda *_a: None)
    with pytest.raises(schema.UpgradeFailed):
        schema.create_tables(conn)
    assert _snapshot(conn) == before
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = ?",
            (schema.RELABEL_ACTION,),
        ).fetchone()[0]
        == 0
    )
