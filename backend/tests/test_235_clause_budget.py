"""Order 235 item 1: the clause-check budget goes to the sentences that matter.

`ai_clause_checks_max_per_run` caps the model calls a review spends proposing
checks for clause sentences. The cap stays; the order changes: a sentence about
a field the sheet states first, then a standard the sheet cites, then a sentence
that prints a figure, then the rest in stored order. Each standard's share
(asked of its sentences) is reported. Invented sentences; a fake model.
"""

from __future__ import annotations

from app import ai_numbers, clause_check_rank
from app import ai_requirements as air
from app.db import connect
from tests import test_w5_677_scope_ledger as scope_ledger_tests
from tests.test_645_clause_checks import Fake, proposal

review_run = scope_ledger_tests.review_run  # fixtures of the scope-ledger tests
temp_storage = scope_ledger_tests.temp_storage


def _s(rid, text, standard="spec"):
    return {
        "id": rid,
        "requirement_type": "statement",
        "source_text": text,
        "standard_document_id": standard,
    }


def _order(requirements, fields=(), cited=()):
    ranked = clause_check_rank.rank(
        requirements,
        [clause_check_rank.words(f) for f in fields],
        frozenset(cited),
        air._sentence,
    )
    return [r["id"] for r in ranked]


PLAIN = _s("plain", "Valve bodies shall be cast steel.")
FIGURE = _s("figure", "The test shall last 30 minutes.")
FIELD = _s("field", "The set pressure shall be marked on the nameplate.")
CITED = _s("cited", "Gaskets shall be spiral wound.", standard="nace")


def test_a_sentence_about_a_field_the_sheet_states_comes_first():
    assert _order([PLAIN, FIGURE, FIELD], fields=["Set pressure"])[0] == "field"


def test_every_word_of_the_field_name_must_appear_in_the_sentence():
    assert _order([PLAIN, FIELD], fields=["Set pressure barg"]) == ["plain", "field"]


def test_then_a_standard_the_sheet_cites_then_a_figure_then_stored_order():
    rest = _order(
        [PLAIN, FIGURE, CITED, FIELD], fields=["Set pressure"], cited=["nace"]
    )
    assert rest == ["field", "cited", "figure", "plain"]
    assert _order([PLAIN, _s("later", "Valves shall be cast steel.")]) == [
        "plain",
        "later",
    ]


def test_the_cap_is_spent_on_the_top_sentences_and_each_standards_share_is_counted(
    review_run,
):
    run, _ids, _scope = review_run
    spec = "spec"
    with connect() as conn:
        conn.execute(
            "UPDATE review_applicable_standards SET selection_method = 'referenced'"
            " WHERE review_run_id = ? AND standard_document_id = 'nace'",
            (run,),
        )
    reqs = [
        _s("b-plain", "Seats shall be hardened.", standard=spec),
        _s("c-field", "The set pressure shall be stamped on the body.", standard=spec),
        _s("a-plain", "Valve bodies shall be cast steel.", standard="nace"),
    ]
    asked = []

    class Recording(Fake):
        def reason(self, packet):
            asked.append(packet)
            return super().reason(packet)

    out = air.propose_checks(
        reqs, review_run_id=run, limit=2, provider=Recording(proposal(), proposal())
    )
    assert out["asked"] == 2 and out["not_asked_budget"] == 1
    # the field sentence FIRST, then the cited standard's sentence; the
    # other sentence of the first standard is skipped (the asked ORDER, not
    # only the counts: a different order would still give these counts)
    assert [("stamped" in p.prompt, "cast steel" in p.prompt) for p in asked] == [
        (True, False),
        (False, True),
    ]
    assert out["by_standard"]["nace"]["asked"] == 1
    assert out["by_standard"][spec]["asked"] == 1
    assert out["by_standard"][spec]["sentences"] == 2
    assert out["by_standard"]["nace"]["label"].endswith(".pdf")


def test_the_report_line_says_what_each_standard_got():
    counts = {
        "sentences": 3,
        "asked": 2,
        "proposed": 0,
        "no_limit": 0,
        "refused": {},
        "could_not_read": 0,
        "not_asked_budget": 1,
        "by_standard": {
            "a": {"label": "A.pdf", "sentences": 2, "asked": 2},
            "b": {"label": "B.pdf", "sentences": 1, "asked": 0},
        },
    }
    line = air.report_line(counts)
    assert line.endswith(" Asked per standard: A.pdf 2 of 2; B.pdf 0 of 1.")
    assert air.report_line(
        {k: v for k, v in counts.items() if k != "by_standard"}
    ).endswith("(the per-run cap).")
    step = ai_numbers.clause_checks(counts)
    assert any("Asked per standard: A.pdf 2 of 2" in str(x) for x in step["lines"])


def test_a_long_list_of_standards_is_cut_with_a_count():
    shares = {
        str(i): {"label": f"S{i}.pdf", "sentences": 10 - i, "asked": 0}
        for i in range(9)
    }
    line = clause_check_rank.share_line(shares)
    assert line.count("of") == clause_check_rank.LINE_STANDARDS
    assert line.endswith("; and 3 more standard(s).")
    assert clause_check_rank.share_line(None) == "" == clause_check_rank.share_line({})


def test_nothing_changes_when_the_budget_covers_every_sentence(review_run):
    run, _ids, _scope = review_run
    reqs = [
        _s("one", "Seats shall be hardened.", standard="spec"),
        _s("two", "The set pressure shall be stamped on the body.", standard="spec"),
        _s("three", "Valve bodies shall be cast steel.", standard="nace"),
    ]
    out = air.propose_checks(
        reqs, review_run_id=run, limit=20, provider=Fake(*[proposal()] * 3)
    )
    assert (out["asked"], out["not_asked_budget"]) == (3, 0)
    assert {k: (v["sentences"], v["asked"]) for k, v in out["by_standard"].items()} == {
        "spec": (2, 2),
        "nace": (1, 1),
    }


def test_a_sentence_with_no_standard_is_counted_so_the_shares_add_up():
    reqs = [
        _s("a", "Seats shall be hardened.", standard="spec"),
        {
            "id": "b",
            "requirement_type": "statement",
            "source_text": "Bolts shall be zinc.",
        },
        {
            "id": "c",
            "requirement_type": "statement",
            "source_text": "Nuts shall be zinc.",
        },
    ]
    shares = clause_check_rank.by_standard(reqs, 2)
    assert shares[clause_check_rank.UNKNOWN]["sentences"] == 2
    assert sum(e["sentences"] for e in shares.values()) == len(reqs)
    assert sum(e["asked"] for e in shares.values()) == 2


def test_a_generic_or_short_one_word_field_does_not_tie_a_sentence_to_it(review_run):
    from app import datasheets

    run, _ids, _scope = review_run
    sub = (
        connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id = ?", (run,))
        .fetchone()["submittal_document_id"]
    )
    for label in ("Type", "Size", "Capacity", "Rated flow"):
        datasheets.create_fact(
            submittal_document_id=sub,
            chunk_id="fc",
            field_label=label,
            raw_value="1",
            page=1,
        )
    fields, _cited = clause_check_rank.sheet_context(run)
    assert frozenset({"type"}) not in fields and frozenset({"size"}) not in fields
    assert frozenset({"capacity"}) in fields
    assert frozenset({"rated", "flow"}) in fields
    # field_label is read as well as field_name: "Set pressure" is both
    assert frozenset({"set", "pressure"}) in fields


# ------------------------------------------------ order 243.6: the safety tier

SAFETY = _s("safety", "Relief valves shall not be isolated.", standard="other")


def test_a_safety_sentence_under_an_uncited_standard_beats_cited_and_figure_sentences():
    """The planner's exact case: 25 cited sentences that print a figure, one
    safety sentence of an uncited standard, and a budget of 20."""
    crowd = [
        _s(f"c{i}", f"Gasket {i} shall be rated for {i + 10} bar.", standard="nace")
        for i in range(25)
    ]
    ranked = _order([*crowd, SAFETY], cited=["nace"])
    assert ranked.index("safety") < 20
    assert ranked[0] == "safety"


def test_a_field_the_sheet_states_still_comes_before_a_safety_sentence():
    ranked = _order([SAFETY, FIELD, CITED], fields=["Set pressure"], cited=["nace"])
    assert ranked == ["field", "safety", "cited"]


def test_a_bare_shall_not_and_a_limit_phrase_are_not_safety():
    assert clause_check_rank.is_safety("Relief valves shall not be isolated.")
    assert clause_check_rank.is_safety("The area is hazardous (Zone 1).")
    assert clause_check_rank.is_safety("SIL 2 applies to the shutdown loop.")
    assert not clause_check_rank.is_safety(
        "The test pressure shall not exceed 12 barg."
    )
    assert not clause_check_rank.is_safety("Bolts shall not be reused.")
    assert not clause_check_rank.is_safety(
        "A silicone gasket is used."
    )  # whole words only
    assert not clause_check_rank.is_safety("")
