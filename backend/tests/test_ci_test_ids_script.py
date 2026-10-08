"""scripts/ci_test_ids.py: the audit that proves a sharded run executed every
collected test exactly once (#589). A shard that dropped a test, two shards
that ran the same test, or a test that ran without being collected must fail
it; so must an empty collection list.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_test_ids.py"
FULL = ["tests/test_a.py::test_one", "tests/test_a.py::test_two[x]", "tests/test_b.py::test_three"]


@pytest.fixture(scope="module")
def ids():
    spec = importlib.util.spec_from_file_location("ci_test_ids", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_test_once_across_shards_passes(ids):
    ok, lines = ids.compare(FULL, {"s1": FULL[:1], "s2": FULL[1:2], "s3": FULL[2:]})
    assert ok, lines


def test_a_test_no_shard_ran_fails(ids):
    ok, lines = ids.compare(FULL, {"s1": FULL[:1], "s2": FULL[1:2], "s3": []})
    assert not ok
    assert any(line.startswith("MISSING") for line in lines)


def test_a_test_two_shards_ran_fails(ids):
    ok, lines = ids.compare(FULL, {"s1": FULL[:2], "s2": FULL[1:], "s3": []})
    assert not ok
    assert any(line.startswith("RAN MORE THAN ONCE") for line in lines)


def test_a_test_that_ran_without_being_collected_fails(ids):
    ok, lines = ids.compare(FULL, {"s1": FULL + ["tests/test_c.py::test_stray"]})
    assert not ok
    assert any(line.startswith("RAN BUT NOT COLLECTED") for line in lines)


def test_an_empty_collection_is_not_a_pass(ids):
    ok, _ = ids.compare([], {"s1": []})
    assert not ok


@pytest.mark.parametrize(("when", "outcome", "counted"), [
    ("setup", "passed", False),   # a call phase follows; count that instead
    ("call", "passed", True),
    ("call", "failed", True),
    ("call", "skipped", True),    # xfail and in-test skips report here
    ("setup", "skipped", True),   # skipif: no call phase follows
    ("setup", "failed", True),    # fixture error: no call phase follows
    ("teardown", "passed", False),
    ("teardown", "failed", False),
])
def test_each_test_is_counted_exactly_once(ids, when, outcome, counted):
    assert ids.ran_once(when, outcome) is counted
