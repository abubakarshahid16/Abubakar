"""The checklist retry on the local model: a cut answer is never used (lead-4, 26 Nov 2026). Its own home so the checklist
module stays under its size limit."""

from __future__ import annotations

from . import prompts as P
from .budget import is_local
from .engine import StepFailed


def retried(model, bad: list[dict], batch, carries, lead, depth: int = 0) -> list[dict]:
    """The retry's items for `bad` (one call). On the local model a cut answer is never used: the items are asked again in two
    halves, and one item whose answer is still cut is dropped (its quote stays not found); on Claude a cut is raised, as before."""
    from .checklist import SPLIT_DEPTH, _dumps, _items_of, _material_line

    prompt = P.S3_RETRY % {
        "items": _dumps(bad),
        "material": "\n".join(_material_line(r) for r in batch),
    }
    try:
        fix = model.ask(step="aim_checklist_retry", model=lead, system="", cached=None, prompt=prompt, carries=carries,
                        max_tokens=8000)  # fmt: skip
    except StepFailed as exc:
        if not is_local() or "max_tokens" not in str(exc) or depth >= SPLIT_DEPTH:
            raise
        if len(bad) < 2:
            return []
        h = len(bad) // 2
        return retried(model, bad[:h], batch, carries, lead, depth + 1) + retried(
            model, bad[h:], batch, carries, lead, depth + 1
        )
    return _items_of(fix)
