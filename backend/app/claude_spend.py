"""What the Claude API has cost, and the refusal before it costs more.

OWNER RULE 2026-09-25: USD 5 per step, USD 20 in total; stop BEFORE exceeding
either. So the check is made before a call leaves, on the WORST CASE of that
call (every prompt token uncached, every allowed output token spent), against
what the ledger says was already spent. A call that could cross a cap is
refused - it never goes out and then gets reported as over budget.

THE LEDGER is a local JSONL file (`settings.claude_spend_log`), one line per
call: time, step, model, token counts, cost, and a digest of the prompt. It is
not in the database on purpose - measured runs use disposable database copies,
and a total kept in a copy would forget every run made against another copy.
It never holds prompt text, document text or the key.

PRICES are list prices per million tokens from Anthropic's pricing page
(platform.claude.com/docs/en/about-claude/pricing, read 2026-09-25). They are
an ESTIMATE; the invoice is the truth. An unknown model is priced at the most
expensive family listed, so an estimate errs toward refusing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

#: (input, output, 5-minute cache write, cache read) USD per million tokens.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-sonnet-4-5": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
}
#: The price used for a model id not in the table: the dearest listed.
_UNKNOWN = max(PRICES.values())
#: Message Batches API: every token at half the list price (same pricing
#: page, "Batch processing"). Applied to all four rates; the caps and the
#: ledger are the same as for a single call.
BATCH_DISCOUNT = 0.5


class BudgetExceeded(RuntimeError):
    """The next call could cross a USD cap, so it was not made."""


def price_for(model: str | None) -> tuple[float, float, float, float]:
    """List prices for `model`; a dated id ('...-20251001') finds its family."""
    name = (model or "").lower()
    for key in sorted(PRICES, key=len, reverse=True):
        if name == key or name.startswith(key + "-") or re.fullmatch(rf"{re.escape(key)}-\d{{8}}", name):
            return PRICES[key]
    return _UNKNOWN


def cost_usd(model: str | None, usage: dict | None, *, batch: bool = False) -> float:
    """USD for one call from the API's `usage` block; a Message Batches
    result (`batch=True`) at half price."""
    usage = usage or {}
    p_in, p_out, p_write, p_read = price_for(model)
    full = (int(usage.get("input_tokens") or 0) * p_in
            + int(usage.get("output_tokens") or 0) * p_out
            + int(usage.get("cache_creation_input_tokens") or 0) * p_write
            + int(usage.get("cache_read_input_tokens") or 0) * p_read) / 1_000_000
    return full * BATCH_DISCOUNT if batch else full


def worst_case_usd(model: str | None, prompt_chars: int, max_tokens: int, *, batch: bool = False) -> float:
    """The most one call can cost: prompt at ~3 chars per token (generous -
    English runs nearer 4), priced as an uncached cache WRITE (the dearest
    input rate), plus every allowed output token. Half for a batch request."""
    p_in, p_out, p_write, _ = price_for(model)
    tokens_in = prompt_chars // 3 + 1
    full = (tokens_in * max(p_in, p_write) + max_tokens * p_out) / 1_000_000
    return full * BATCH_DISCOUNT if batch else full


def _ledger_path() -> Path:
    return Path(settings.claude_spend_log)


def entries() -> list[dict]:
    path = _ledger_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def spent(step: str | None = None) -> float:
    """USD spent in total, or on one step."""
    return round(sum(float(e.get("cost_usd") or 0) for e in entries()
                     if step is None or e.get("step") == step), 6)


@dataclass(frozen=True)
class Caps:
    per_step: float
    total: float

    @classmethod
    def from_settings(cls) -> Caps:
        return cls(float(settings.claude_budget_usd_per_step), float(settings.claude_budget_usd_total))


def ensure_affordable(step: str, worst_case: float, caps: Caps | None = None) -> None:
    """Refuse (raise) when `worst_case` on top of what is spent could cross
    the step cap or the total cap."""
    caps = caps or Caps.from_settings()
    step_spent, total_spent = spent(step), spent()
    if step_spent + worst_case > caps.per_step:
        raise BudgetExceeded(
            f"step {step!r}: spent ${step_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.per_step:.2f} per step")
    if total_spent + worst_case > caps.total:
        raise BudgetExceeded(
            f"total: spent ${total_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.total:.2f} in total")


def record(*, step: str, model: str, usage: dict | None, prompt_sha256: str,
           wall_time_s: float, finish_reason: str, batch: bool = False) -> dict:
    """Append one call to the ledger and return the entry. Counts and a
    digest only - never text, never the key. A batch result is priced at the
    batch rate and marked `"batch": true`."""
    usage = usage or {}
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "step": step, "model": model,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cost_usd": round(cost_usd(model, usage, batch=batch), 6),
        "prompt_sha256": prompt_sha256, "wall_time_s": round(wall_time_s, 3),
        "finish_reason": finish_reason,
    }
    if batch:
        entry["batch"] = True
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry
