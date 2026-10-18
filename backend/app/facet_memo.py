"""#615: ask the facet merge rule at most once per pair of facet versions.

`claims._merge_facets` restarts its scan after every merge, because a facet
that just grew may now absorb one scanned earlier. Without a memory it asked
`_can_merge` - which labels both sides and the merged rows, the expensive
part - for every pair on every restart. A facet changes only by absorbing
another, which always adds rows, so (its terms, its row count) names one
version of it exactly: an answer remembered under that key can never be
reused for a facet that has since changed.
"""
from __future__ import annotations

from collections.abc import Callable


def ask(asked: dict, can_merge: Callable[..., bool], small: list, big: list) -> bool:
    """`can_merge(small_key, small_rows, big_key, big_rows)`, remembered in `asked`."""
    pair = (small[0], len(small[1]), big[0], len(big[1]))
    if pair not in asked:
        asked[pair] = can_merge(small[0], small[1], big[0], big[1])
    return asked[pair]
