"""A Pass on a contractor-deferred value ('By Contractor', TBA): owner decision D2
makes it a Query. One home for the test, so the bench (#1471) and the per-review
audit (#1525) can never count it differently."""

from __future__ import annotations

import re

DEFERRED = re.compile(r"\bby contractor\b|\btba\b|\bto be advised\b", re.I)


def is_deferred_pass(finding: dict) -> bool:
    return finding.get("compliance_status") == "COMPLIANT" and bool(
        DEFERRED.search(finding.get("finding") or "")
    )
