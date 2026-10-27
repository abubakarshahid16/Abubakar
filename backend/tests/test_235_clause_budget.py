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
from tests.test_645_clause_checks import Fake, proposal
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixtures
    review_run,
    temp_storage,
)


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
    review_run, monkeypatch
):
    run, _ids, scope = review_run
    spec = next(i for i in scope if i == "spec")
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
    # the field sentence first, then the cited standard's sentence; the other standard's is skipped
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
