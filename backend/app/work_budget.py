"""A hard work budget for a request that can grow with the library (#606).

A budget is a deadline plus caps. Loops that can run long ask `exceeded()`;
when it says yes they STOP and the caller returns what it has with
`truncated: true` and the reasons. Nothing is dropped silently: every stop
adds a reason, and `to_api()` is what the response carries.
"""
from __future__ import annotations

import time


class WorkBudget:
    def __init__(self, seconds: float | None, *, max_claims: int | None = None,
                 max_evidence: int | None = None, clock=time.monotonic) -> None:
        self._clock = clock
        self.seconds = seconds
        self.max_claims = max_claims
        self.max_evidence = max_evidence
        self._deadline = None if not seconds else clock() + float(seconds)
        self.reasons: list[str] = []

    def note(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)

    def exceeded(self) -> bool:
        """True once the deadline has passed (and says so, once)."""
        if self._deadline is not None and self._clock() >= self._deadline:
            self.note(f"time budget of {self.seconds:g} s reached")
            return True
        return False

    @property
    def truncated(self) -> bool:
        return bool(self.reasons)

    def to_api(self) -> dict:
        return {"truncated": self.truncated,
                "truncation_reason": "; ".join(self.reasons) or None}
