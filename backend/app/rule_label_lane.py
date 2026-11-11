"""The label job's money lane (owner decision 1, 11 Nov 2026): one call through the app's one Claude lane, booked on an
INJECTED order ledger.

`Lane.call` reserves the call's worst case on the ledger BEFORE anything is sent (the ledger raises when the order's stop
would be passed), sends through `agent_claude._call` (`reader_transport` + `claude_spend.metered`: the app's own caps),
and settles with the real usage afterwards. A transport failure is retried and charged at its worst case (the safe
side); a reply that came back, also a bad one the app paid for, is booked at its real usage. `CapLedger` is an
in-process ledger with a hard stop; a shared, file-backed ledger is injected instead when one exists.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Protocol

from . import agent_claude, claude_spend

MAX_RETRIES = 2
RETRY_BASE_SECONDS = 4.0


class Ledger(Protocol):
    """What the job needs of an order ledger: `reserve(worst)` raises before anything is sent when the order's stop
    would be passed and returns a reservation id; `settle(...)` closes it with the real cost; `run_usd` is what this
    object has settled."""

    run_usd: float

    def reserve(self, worst: float) -> str: ...

    def settle(
        self,
        worst: float,
        *,
        usd: float,
        model: str,
        kind: str,
        ok: bool,
        ids: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        rid: str | None = None,
    ) -> None: ...


class OrderStopReached(RuntimeError):
    """The order's USD stop would be passed: the call is not sent."""

    code = "order_stop_usd"


class CapLedger:
    """An in-process ledger with a hard stop: settled USD plus every open reservation at its worst case plus this
    call's worst case must stay at or under `stop_usd`. For a shared, file-backed ledger inject another object."""

    def __init__(self, stop_usd: float) -> None:
        if stop_usd <= 0:
            raise ValueError("the stop must be above zero")
        self.stop, self.run_usd = float(stop_usd), 0.0
        self._open: dict[str, float] = {}
        self._lock = threading.Lock()
        self._n = 0
        #: one entry per settled call: model, kind, ok, rules asked, tokens and USD (no text), for the run's report
        self.log: list[dict] = []

    def reserve(self, worst: float) -> str:
        with self._lock:
            if self.run_usd + sum(self._open.values()) + float(worst) > self.stop:
                raise OrderStopReached(f"order stop USD {self.stop:.2f}")
            self._n += 1
            rid = f"r{self._n}"
            self._open[rid] = float(worst)
            return rid

    def settle(
        self,
        worst: float,
        *,
        usd: float,
        model: str,
        kind: str,
        ok: bool,
        ids: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        rid: str | None = None,
    ) -> None:
        with self._lock:
            key = (
                rid
                if rid in self._open
                else next((k for k, v in self._open.items() if v == float(worst)), None)
            )
            if key:
                del self._open[key]
            self.run_usd += float(usd)
            self.log.append(
                {
                    "model": model,
                    "kind": kind,
                    "ok": bool(ok),
                    "rules": ids,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "usd": float(usd),
                }
            )


class Lane:
    """One call through the app's one lane (`agent_claude._call`: reader_transport + claude_spend.metered), reserved on
    the injected ledger first. A transport failure is retried and charged at its worst case (the safe side); a reply
    that came back (also a bad one the app paid for) is booked at its real usage."""

    def __init__(
        self,
        ledger: Ledger,
        send: Callable | None = None,
        env: dict | None = None,
        retry_base: float = RETRY_BASE_SECONDS,
    ) -> None:
        self.ledger, self.send, self.env, self.retry_base = (
            ledger,
            send,
            env,
            retry_base,
        )
        self._tl = threading.local()

    def _recording(self) -> Callable:
        raw = agent_claude._transport(self.send)

        def send(url, *, headers, body, timeout):
            self._tl.last = None
            resp = raw(url, headers=headers, body=body, timeout=timeout)
            self._tl.last = resp
            return resp

        return send

    def _settle_bad_reply(self, model: str, worst: float, n: int, rid: str) -> None:
        resp = getattr(self._tl, "last", None)
        usage = (
            resp.get("usage")
            if isinstance(resp, dict) and isinstance(resp.get("usage"), dict)
            else None
        )
        if usage:
            tin = sum(
                int(usage.get(k) or 0)
                for k in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
            self.ledger.settle(
                worst,
                usd=float(claude_spend.cost_usd(model, usage)),
                model=agent_claude._answered_model(resp),
                kind="label",
                ok=False,
                ids=n,
                input_tokens=tin,
                output_tokens=int(usage.get("output_tokens") or 0),
                rid=rid,
            )
        else:
            self.ledger.settle(
                worst,
                usd=worst,
                model="no answer",
                kind="label",
                ok=False,
                ids=n,
                rid=rid,
            )

    def call(
        self, model: str, parts: dict, max_tokens: int, n_rules: int
    ) -> tuple[dict, float]:
        chars = sum(
            len(json.dumps(parts.get(k), ensure_ascii=False, default=str))
            for k in ("messages", "system")
        )
        worst = claude_spend.worst_case_usd(model, chars, int(max_tokens))
        for attempt in range(MAX_RETRIES + 1):
            rid = self.ledger.reserve(
                worst
            )  # raises OrderStopReached BEFORE anything is sent
            self._tl.last = None
            try:
                answer, usd = agent_claude._call(
                    model, parts, max_tokens, self._recording(), self.env, None
                )
            except agent_claude.AgentBudgetStop:
                self.ledger.settle(
                    worst,
                    usd=0.0,
                    model="no answer",
                    kind="label",
                    ok=False,
                    ids=n_rules,
                    rid=rid,
                )
                raise
            except agent_claude.AgentTransportError:
                self.ledger.settle(
                    worst,
                    usd=worst,
                    model="no answer",
                    kind="label",
                    ok=False,
                    ids=n_rules,
                    rid=rid,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(self.retry_base * (2**attempt))
                    continue
                raise
            except agent_claude.AgentBadReply:
                self._settle_bad_reply(model, worst, n_rules, rid)
                raise
            except (
                Exception
            ):  # after a send the call may have been billed: booked at its worst case
                self.ledger.settle(
                    worst,
                    usd=worst,
                    model="no answer",
                    kind="label",
                    ok=False,
                    ids=n_rules,
                    rid=rid,
                )
                raise
            use = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
            tin = sum(
                int(use.get(k) or 0)
                for k in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
            self.ledger.settle(
                worst,
                usd=usd,
                model=agent_claude._answered_model(answer),
                kind="label",
                ok=True,
                ids=n_rules,
                input_tokens=tin,
                output_tokens=int(use.get("output_tokens") or 0),
                rid=rid,
            )
            return answer, usd
        raise agent_claude.AgentTransportError("retries_exhausted")
