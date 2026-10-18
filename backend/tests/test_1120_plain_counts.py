"""Order 112: the review's reason sentence writes its counts with thousands
separators, the way the sheet's headline writes its own ("6,584"), so one
screen never mixes "6577" with "6,584".

Invented counts only.
"""

from __future__ import annotations

from app import comparison


def test_the_completeness_reason_writes_large_counts_with_thousands_separators():
    reason = comparison._insufficient_reason(
        {
            "basis": comparison.BASIS_REQUIRED_FIELDS,
            "fields_required": 6577,
            "fields_answered": 41,
        }
    )
    assert "41 of the 6,577 datasheet values" in reason
    assert "6577" not in reason
