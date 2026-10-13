"""The call cap and the running total."""

from __future__ import annotations

import pytest

from app import access, claude_api, claude_budget, db
from app.config import settings


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "budget.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def test_the_cap_stops_the_next_call_not_the_ones_before(monkeypatch):
    sent = []
    budget = claude_budget.Budget(lambda p: sent.append(p) or "{}", max_calls=3)
    for i in range(3):
        budget(f"p{i}")
    with pytest.raises(claude_budget.BudgetExhausted):
        budget("p3")
    assert sent == ["p0", "p1", "p2"]
    assert budget.calls == 3 and budget.remaining == 0


def test_the_cap_reads_the_environment(monkeypatch):
    monkeypatch.setenv(claude_budget.ENV_MAX_CALLS, "7")
    assert claude_budget.Budget(lambda p: "").max_calls == 7
    monkeypatch.setenv(claude_budget.ENV_MAX_CALLS, "nonsense")
    assert claude_budget.Budget(lambda p: "").max_calls == claude_budget.DEFAULT_MAX_CALLS
    monkeypatch.delenv(claude_budget.ENV_MAX_CALLS)
    assert claude_budget.Budget(lambda p: "").max_calls == claude_budget.DEFAULT_MAX_CALLS


def test_a_zero_cap_lets_nothing_out():
    budget = claude_budget.Budget(lambda p: pytest.fail("a call went out"), max_calls=0)
    with pytest.raises(claude_budget.BudgetExhausted):
        budget("anything")


def test_the_total_accumulates_across_records_and_survives_reconnect():
    claude_budget.record({"calls": 2, "input_tokens": 1000, "output_tokens": 100})
    db.reset_connection()
    total = claude_budget.record({"calls": 1, "input_tokens": 500, "output_tokens": 50})
    assert total["calls"] == 3
    assert total["input_tokens"] == 1500
    assert total["output_tokens"] == 150
    # A8/#922: one price table (claude_spend.PRICES, not a second copy here);
    # the no-model default resolves to claude-sonnet-5's rate.
    assert total["estimated_usd"] == round((1500 * 2.0 + 150 * 10.0) / 1e6, 2)
    assert claude_budget.total()["calls"] == 3


def test_the_estimate_follows_the_model_family():
    assert claude_budget.estimate_usd(1_000_000, 0, "claude-haiku-4-5") == 1.0
    assert claude_budget.estimate_usd(1_000_000, 0, "claude-sonnet-4-5") == 3.0
    assert claude_budget.estimate_usd(1_000_000, 0, None) == 2.0


def test_the_estimate_uses_one_price_table_not_a_second_copy():
    """A8/#922: this module used to keep its own PRICE_PER_MILLION, stale
    against claude_spend.PRICES (claude-sonnet priced at 3.0 here, 2.0 for
    claude-sonnet-5 there). Proves the two can no longer disagree, because
    there is only one table left to read."""
    from app import claude_spend
    assert not hasattr(claude_budget, "PRICE_PER_MILLION")
    for model in ("claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"):
        per_in, per_out, _w, _r = claude_spend.price_for(model)
        assert claude_budget.estimate_usd(1_000_000, 1_000_000, model) == round(per_in + per_out, 2)


def test_a_route_reports_the_cap_and_the_total_when_exhausted():
    class T:
        usage = {"calls": 1, "input_tokens": 10, "output_tokens": 2}

    def explode(call):
        call("one")
        call("two")  # over the cap
        pytest.fail("the second call should have been refused")

    budget = claude_budget.Budget(lambda p: "{}", max_calls=1)
    result, exhausted = claude_api._capped(budget, explode)
    assert exhausted and result == {}
    settled = claude_api._settle(T(), {"counts": {"x": 1}}, exhausted, budget)
    assert settled["complete"] is False
    assert settled["counts"] == {"x": 1, claude_budget.BUDGET_EXHAUSTED: 1}
    assert settled["calls_this_run"] == 1 and settled["call_cap"] == 1
    assert settled["spend_total"]["calls"] == 1


def test_a_complete_route_says_so():
    class T:
        usage = {"calls": 4, "input_tokens": 40, "output_tokens": 4}
    budget = claude_budget.Budget(lambda p: "{}", max_calls=10)
    result, exhausted = claude_api._capped(budget, lambda call: {"counts": {}})
    settled = claude_api._settle(T(), result, exhausted, budget)
    assert settled["complete"] is True
    assert claude_budget.BUDGET_EXHAUSTED not in settled["counts"]
