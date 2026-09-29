"""The load-test script's pure parts (scripts/load_test.py).

The load test itself builds a corpus and starts a server, which is far too
slow for the suite. What IS held here is everything that turns raw timings
into the numbers the owner reads - because a wrong percentile, an error
counted as a success, or a fast 500 averaged into the latency would make the
report say the system copes when it does not:

  * percentiles by linear interpolation, None (never 0) when there is no sample;
  * error classification - SQLite's "database is locked" / "schema has
    changed" named even inside a 500, exceptions named by type, any non-2xx
    an error;
  * aggregation - latency over successes only, every error counted by class,
    throughput over the level's wall time;
  * argument parsing, the mixed workload's shares, and the server-log scan
    that finds tracebacks a generic 500 body hides.
"""
from __future__ import annotations

import argparse
import importlib.util
import random
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "load_test.py"


@pytest.fixture(scope="module")
def lt():
    spec = importlib.util.spec_from_file_location("load_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # registered first: @dataclass resolves its module through sys.modules
    sys.modules["load_test"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("load_test", None)


# ================================================================ percentile

def test_percentile_interpolates_between_ranks(lt):
    values = [float(v) for v in range(1, 11)]          # 1..10
    assert lt.percentile(values, 50) == pytest.approx(5.5)
    assert lt.percentile(values, 95) == pytest.approx(9.55)
    assert lt.percentile(values, 0) == 1.0
    assert lt.percentile(values, 100) == 10.0


def test_percentile_sorts_its_input(lt):
    assert lt.percentile([10.0, 1.0, 5.0], 50) == 5.0
    assert lt.percentile([30.0, 10.0, 20.0, 40.0], 95) == pytest.approx(38.5)


def test_percentile_of_nothing_is_none_not_zero(lt):
    assert lt.percentile([], 50) is None
    assert lt.percentile([7.0], 95) == 7.0


def test_percentile_refuses_an_out_of_range_p(lt):
    with pytest.raises(ValueError):
        lt.percentile([1.0, 2.0], 101)


# ======================================================== error classification

def test_success_statuses_are_not_errors(lt):
    assert lt.classify_error(200) is None
    assert lt.classify_error(204) is None


def test_any_non_2xx_is_an_error_named_by_status(lt):
    assert lt.classify_error(500) == "http_500"
    assert lt.classify_error(503) == "http_503"
    assert lt.classify_error(404) == "http_404"
    assert lt.classify_error(None) == "exception:NoStatus"


def test_sqlite_concurrency_messages_are_named_even_inside_a_500(lt):
    assert lt.classify_error(500, '{"detail": "database is locked"}') == "sqlite_locked"
    assert lt.classify_error(500, "sqlite3.OperationalError: Database Is Locked") == "sqlite_locked"
    assert lt.classify_error(500, "database schema has changed") == "sqlite_schema_changed"


def test_exceptions_are_named_by_type(lt):
    assert lt.classify_error(None, "", ConnectionResetError("peer reset")) == \
        "exception:ConnectionResetError"
    assert lt.classify_error(None, "", TimeoutError()) == "exception:TimeoutError"
    # the SQLite message wins over the type: it is what the test looks for
    assert lt.classify_error(None, "", RuntimeError("database is locked")) == "sqlite_locked"


# ================================================================ aggregation

def test_aggregate_counts_errors_by_class(lt):
    S = lt.Sample
    samples = [S("answer", 100.0, None), S("answer", 200.0, None),
               S("answer", 5.0, "http_500"), S("answer", 6.0, "http_500"),
               S("answer", 7.0, "sqlite_locked")]
    row = lt.aggregate(samples, wall_seconds=2.0)
    assert row["requests"] == 5
    assert row["ok"] == 2
    assert row["errors"] == 3
    assert row["errors_by_type"] == {"http_500": 2, "sqlite_locked": 1}


def test_latency_is_over_successes_only(lt):
    """A fast 500 must not make the system look quicker."""
    S = lt.Sample
    samples = [S("x", 100.0, None), S("x", 300.0, None)] + [S("x", 1.0, "http_500")] * 8
    row = lt.aggregate(samples, wall_seconds=1.0)
    assert row["p50_ms"] == 200.0
    assert row["max_ms"] == 300.0
    assert row["p95_ms"] == 290.0


def test_throughput_is_requests_over_wall_time(lt):
    S = lt.Sample
    samples = [S("x", 10.0, None)] * 6 + [S("x", 10.0, "http_503")] * 2
    row = lt.aggregate(samples, wall_seconds=4.0)
    assert row["throughput_rps"] == 2.0
    assert row["ok_throughput_rps"] == 1.5


def test_all_errors_leaves_latency_null_not_zero(lt):
    row = lt.aggregate([lt.Sample("x", 3.0, "http_500")], wall_seconds=1.0)
    assert row["p50_ms"] is None and row["p95_ms"] is None and row["max_ms"] is None
    assert "0.0" not in lt.format_table([{"workload": "x", "concurrency": 1, **row}]).splitlines()[-1]


# ============================================================ argument parsing

def test_defaults(lt):
    a = lt.parse_args([])
    assert a.docs == 20
    assert a.levels == [1, 2, 5, 10, 20]
    assert a.workloads == ["documents", "answer", "crs", "chat", "mixed"]
    assert a.out is None
    assert a.requests_per_level == 100


def test_every_option_is_read(lt, tmp_path):
    a = lt.parse_args(["--docs", "5", "--levels", "1,3", "--requests-per-level", "9",
                       "--workloads", "answer,mixed", "--out", str(tmp_path / "r.json"),
                       "--seed", "42"])
    assert (a.docs, a.levels, a.requests_per_level, a.workloads, a.seed) == \
        (5, [1, 3], 9, ["answer", "mixed"], 42)
    assert a.out == tmp_path / "r.json"


@pytest.mark.parametrize("argv", [
    ["--workloads", "answer,bogus"],
    ["--levels", "1,0"],
    ["--levels", ""],
    ["--docs", "0"],
    ["--requests-per-level", "0"],
])
def test_bad_arguments_are_refused(lt, argv):
    with pytest.raises(SystemExit):
        lt.parse_args(argv)


def test_level_and_workload_parsers_raise_argparse_errors(lt):
    with pytest.raises(argparse.ArgumentTypeError):
        lt.parse_levels("2,-1")
    with pytest.raises(argparse.ArgumentTypeError):
        lt.parse_workloads("nope")


# ================================================================ mixed shares

def test_mixed_workload_follows_its_shares(lt):
    rng = random.Random(1)
    n = 4000
    drawn = [lt.pick_mixed(rng) for _ in range(n)]
    for name, share in lt.MIX:
        assert abs(drawn.count(name) / n - share) < 0.03, name
    assert set(drawn) == {name for name, _ in lt.MIX}


# ============================================================ server-log scan

LOG = """INFO: started
Traceback (most recent call last):
  File "/x/app/chat.py", line 700, in ask
    conn.execute("INSERT INTO messages ...")
sqlite3.OperationalError: database is locked
INFO: something else
Traceback (most recent call last):
  File "/x/app/main.py", line 10, in f
    g()
KeyError: 'rows'
"""


def test_server_log_scan_finds_tracebacks_and_sqlite_messages(lt):
    got = lt.scan_server_log(LOG)
    assert got["tracebacks"] == 2
    assert got["database_is_locked"] == 1
    assert got["schema_has_changed"] == 0
    assert got["by_exception"]["sqlite3.OperationalError"]["count"] == 1
    assert got["by_exception"]["KeyError"]["count"] == 1
    excerpt = got["by_exception"]["sqlite3.OperationalError"]["excerpt"]
    assert any('line 700, in ask' in line for line in excerpt)
    assert "INFO: something else" not in "\n".join(excerpt)


def test_a_clean_log_reports_nothing(lt):
    got = lt.scan_server_log("INFO: started\nINFO: stopped\n")
    assert got == {"tracebacks": 0, "by_exception": {}, "database_is_locked": 0,
                   "schema_has_changed": 0}
