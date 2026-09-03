import pytest

from app.rates import MIN_ELAPSED_S, Timer, rate


def test_rate_is_none_when_nothing_was_processed():
    """A no-op resume must report null, not a finite rate."""
    assert rate(0, 1.0) is None
    assert rate(0, 0.0) is None


def test_rate_is_none_below_the_measurable_floor():
    """Never publish a rate computed from a near-zero denominator."""
    assert rate(613, 0.0) is None
    assert rate(613, 0.0000006) is None      # the bug: 613/6e-7 = 1.02e9
    assert rate(613, MIN_ELAPSED_S / 2) is None


def test_rate_is_computed_when_meaningful():
    assert rate(600, 2.0) == 300.0
    assert rate(1, MIN_ELAPSED_S) == pytest.approx(1 / MIN_ELAPSED_S, rel=1e-6)


def test_timer_reports_millisecond_precision_not_integers():
    t = Timer()
    s = t.seconds()
    assert isinstance(s, float)
    # 3 decimal places, so a sub-second run is never reported as 0 seconds
    assert round(s, 3) == s
