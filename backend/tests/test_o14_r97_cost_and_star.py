"""Order 14, lane A, review R97: (S1) a second opinion cut off by its token limit reports what it cost, the same figure the meter
charged, so the run's own cost and the gate's settled total match the ledger; (S3) each star guard of `blank_markers.defers_value`
on its own: a star that opens a note line and a star that points to a note are never a value deferred to the vendor. Invented."""

from __future__ import annotations

from app import agent_claude as ac
from app import blank_markers
from tests.test_agent_claude import (  # noqa: F401 - the module's two fixtures: declared document, temp ledger
    ENV,
    EV,
    F,
    Sender,
    _declared,
    _ledger,
)


def test_a_cut_second_opinion_reports_what_it_cost():
    meter = ac.SpendMeter()
    cut = Sender([{"type": "text", "text": '{"agree": tr'}], stop="max_tokens")
    out = ac._second_opinion(F, EV, meter=meter, send=cut, env=ENV)
    assert out["agree"] is None and out["reason"] == "stop_max_tokens"
    assert (
        out["usd"] > 0 and abs(out["usd"] - meter.spent) < 1e-12
    )  # the run's figure is the meter's figure


def test_a_refused_second_opinion_reports_what_it_cost_too():
    meter = ac.SpendMeter()
    out = ac._second_opinion(
        F, EV, meter=meter, send=Sender([], stop="refusal"), env=ENV
    )
    assert (
        out["agree"] is None
        and out["usd"] > 0
        and abs(out["usd"] - meter.spent) < 1e-12
    )


def test_a_star_that_opens_a_note_line_is_no_deferral():
    assert (
        blank_markers.defers_value("* psig values are gauge pressure") is False
    )  # the note guard alone stops it (a star, then words: a note line)
    assert (
        blank_markers.defers_value("* psig") is True
    )  # lane D's rule (review R102): a lone star whose unit ENDS the cell is a value to fill


def test_a_star_that_points_to_a_note_is_no_deferral():
    assert (
        blank_markers.defers_value("Rated flow * m3/h * see note 3") is False
    )  # the pointer guard alone stops it
    assert (
        blank_markers.defers_value("Rated flow * m3/h") is True
    )  # the same star with no pointer: a value to fill
