"""#615 item 3: facet merging asks the merge rule once per pair of facet
versions, not once per pair on every restart, and gives exactly the old
result.

The old loop restarted the whole pairwise scan after every merge and called
`_can_merge` (which labels both sides and the merged rows) for every pair each
time. It is kept below as the oracle. Invented engineering text only (the #606
fixture).
"""
from __future__ import annotations

import pytest

from app import acronyms, claims
from tests.test_w7_gaps_freeze import _evidence, corpus  # noqa: F401 - fixture


def _old_merge(groups):
    """The loop as it was before #615, verbatim apart from its name."""
    items = [[key, list(rows)] for key, rows in groups.items()]
    items.sort(key=lambda it: (len(claims.subject_terms(it[0])), sorted(it[0])))
    changed = True
    while changed:
        changed = False
        for i, small in enumerate(items):
            target = None
            for j, big in enumerate(items):
                if i == j or j < i:
                    continue
                if claims._can_merge(small[0], small[1], big[0], big[1]):
                    target = j
                    break
            if target is not None:
                items[target][0] = items[target][0] | small[0]
                items[target][1] = items[target][1] + small[1]
                items.pop(i)
                changed = True
                break
    return [(key, rows) for key, rows in items]


def _groups(ids, n=12, chars=2500, question="design pressure test pressure wall thickness coating"):
    acronyms.warm_all()
    rows = claims.extract_claims(_evidence(ids, n=n, chars=chars),
                                 allowed_document_ids=frozenset(ids))
    terms = claims.question_terms(question, allowed_document_ids=frozenset(ids))
    groups: dict = {}
    for c in rows:
        key = claims.facet_key(c, terms)
        if key is not None:
            groups.setdefault(key, []).append(c)
    return groups


def _shape(result):
    return [(sorted(key), [id(r) for r in rows]) for key, rows in result]


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = claims._can_merge
    monkeypatch.setattr(claims, "_can_merge",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


def test_the_result_is_exactly_the_old_loops(corpus, counted):  # noqa: F811
    groups = _groups(corpus)
    assert len(groups) >= 10, "the fixture must produce many facets"
    assert _shape(claims._merge_facets(groups)) == _shape(_old_merge(groups))


def test_the_rule_is_asked_far_fewer_times_once_facets_merge(corpus, counted):  # noqa: F811
    groups = _groups(corpus)
    old_result = _old_merge(groups)
    old_calls = len(counted)
    merges = len(groups) - len(old_result)
    assert merges >= 2, "the fixture must merge some facets, or there is nothing to save"
    counted.clear()

    claims._merge_facets(groups)

    n = len(groups)
    assert len(counted) < old_calls
    # Bounded by size: every pair once, plus one row of pairs per merge.
    assert len(counted) <= n * (n - 1) // 2 + merges * n


def test_with_nothing_to_merge_each_pair_is_asked_once(counted):
    """Facets that never merge (empty rows name no shared subject): one scan,
    each ordered pair asked at most once - the size bound with zero merges."""
    groups = {frozenset({f"term{i}"}): [] for i in range(30)}
    claims._merge_facets(groups)
    assert len(counted) <= 30 * 29 // 2

