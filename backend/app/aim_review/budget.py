"""THE SIZE PROFILE of a general review run: how much text one call may carry and how many items one call judges.

A run on Claude uses the method's own sizes (the constants of `material`, `paper`, `steps`, `editor`, `second_read`, `answered`,
`references`), exactly as before: no profile is active and `cap` returns the constant unchanged. A run on the LOCAL model (planner
25 Nov 2026 22:35: "smaller batches and a smaller material budget to fit its context") runs inside `using(LOCAL)`: every size is
the SMALLER of the constant and the profile's own, so the local model's context window holds the whole prompt and its answer.
Same steps, same code checks, same labels: only the sizes change, and every cut is still counted where it happens.

The profile is a context variable: the judge's side-by-side threads run with a COPY of the run's context (`parallel`), so they
see the same profile; a chat or another run on another thread never does. Sizes only; no text is read or kept here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    name: str
    #: the context window the model is asked to run at (tokens)
    num_ctx: int
    #: the longest answer one call may write (tokens)
    max_tokens: int
    #: the clause material of the checklist build (characters): all books, one book's rules, one book's pages, one batch
    material: int
    book: int
    text_book: int
    batch_chars: int
    #: one page window of the paper the judge reads (tokens, as `kind_review_table` counts them)
    window_tokens: int
    #: one window of a contract's reference paper (characters)
    window_chars: int
    #: items per judge call, judge calls side by side
    judge_batch: int
    judge_parallel: int
    #: lines per call of the second reader, the whole-paper check and the editor
    line_chunk: int


#: The local model's base sizes. The window and the paper's share of it are set PER PAPER by `for_paper` (owner's standing lesson,
#: 25 Nov 2026: NO BLIND CHUNKING; the judge sees the whole paper whenever it can fit, and the context is raised to make it fit).
LOCAL = Budget(
    name="local",
    num_ctx=32_768,
    max_tokens=8_192,
    material=40_000,
    book=12_000,
    text_book=8_000,
    batch_chars=9_000,
    window_tokens=16_768,
    window_chars=50_000,
    judge_batch=3,
    judge_parallel=1,
    line_chunk=20,
)
#: Room in the window besides the paper (tokens): the step's instructions, the items with their clause text, and the answer.
RESERVE_TOKENS = 16_000
#: The smallest and largest window a local run asks for (tokens). Above the largest, a paper is judged in page windows and the
#: run record says so on every judge call ("not the whole paper").
MIN_CTX, MAX_CTX = 16_384, 65_536
STEP_CTX = 4_096
#: The app's token estimate is tuned on one tokenizer; another counts up to half more (the 14B counted 8,087 where the estimate
#: allowed less): the window keeps that much room, so the whole paper still fits.
TOKENIZER_SLACK = 1.5


def for_paper(paper_tokens: int, base: Budget = LOCAL) -> Budget:
    """The local sizes for a paper of `paper_tokens` (an upper bound, `context_budget.estimate_tokens`): the window is raised until
    the whole paper and `RESERVE_TOKENS` fit (never cut to fit a smaller window), up to `MAX_CTX`."""
    from dataclasses import replace

    want = int(int(paper_tokens) * TOKENIZER_SLACK) + RESERVE_TOKENS
    num_ctx = min(MAX_CTX, max(MIN_CTX, -(-want // STEP_CTX) * STEP_CTX))
    room = num_ctx - RESERVE_TOKENS
    return replace(base, num_ctx=num_ctx, window_tokens=room, window_chars=room * 3)


_ACTIVE: ContextVar[Budget | None] = ContextVar("aim_review_budget", default=None)


def active() -> Budget | None:
    """The profile of the run on this context, or None (a Claude run: the method's own sizes)."""
    return _ACTIVE.get()


def is_local() -> bool:
    b = _ACTIVE.get()
    return b is not None and b.name == LOCAL.name


def cap(value: int, size: str) -> int:
    """`value` (the method's constant), or the active profile's `size` when that is smaller. No profile: `value` unchanged."""
    b = _ACTIVE.get()
    if b is None:
        return value
    return min(int(value), int(getattr(b, size)))


@contextmanager
def using(profile: Budget) -> Iterator[None]:
    token = _ACTIVE.set(profile)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def of(model):
    """The sizes of a run on `model`: its own profile for the local model (`engine` "local"), else the method's own (no profile)."""
    if getattr(model, "engine", "") == LOCAL.name:
        return using(getattr(model, "budget", LOCAL))
    return nullcontext()
