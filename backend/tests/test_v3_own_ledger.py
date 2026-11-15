"""V3 (review R72): every test has its own Claude spend ledger. The first test leaves a row; the second, which runs after it
in the same process, must not see it (it did, through the one-file-per-worker ledger: some full runs failed on it)."""

from app import claude_spend
from app.config import settings


def test_a_leaves_a_row_in_its_own_ledger():
    settings.claude_spend_log.parent.mkdir(parents=True, exist_ok=True)
    settings.claude_spend_log.write_text(
        '{"at":"2026-11-15T00:00:00+00:00","step":"chat_claude","model":"claude-x","input_tokens":1,"output_tokens":1,"usd":0.01}\n')
    assert claude_spend.entries()


def test_b_runs_after_it_and_sees_an_empty_ledger():
    assert claude_spend.entries() == []
