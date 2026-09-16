"""Session-level guards, so a run that cannot prove anything says so.

Three things this file exists to prevent, all found by running the suite on a
clean machine for the first time.

1. WITHOUT MODELS THE SUITE FAILS 90 TIMES AND EXPLAINS NOTHING.
   The e5-small tokenizer is the prerequisite for chunking, so its absence
   cascades: 25 direct FileNotFoundError, then 65 downstream failures where a
   document could not be chunked and every assertion about its answers fell
   over. Ninety failures with one cause, and none of them said which.
   Now the session stops immediately with the command that fixes it.

2. A SKIPPED SUITE REPORTS SUCCESS.
   Nine tests guard themselves on model presence and skip when it is absent.
   That is correct behaviour for a single test and a disaster for a run: green
   ticks all the way down while the embedding and rerank paths were never
   exercised. Skips are now printed as a table with their reasons, and the
   count is stated in the summary rather than absorbed into the tick.

3. A SUITE THAT COLLECTS ALMOST NOTHING STILL PASSES.
   A broken conftest, a bad testpath or a filter typo can reduce a run to two
   tests and still exit zero. There is a floor: fewer than MINIMUM_TESTS
   actually executed is a failure, because a run that small has not tested the
   system regardless of what it reports.
"""

from __future__ import annotations

import os

import pytest

from app.config import settings

#: What the application opens at runtime. A missing file here is a setup
#: problem, not a test failure, and must be reported as one.
REQUIRED_MODEL_FILES = (
    ("e5-small tokenizer", lambda: settings.embed_model_dir / "tokenizer.json"),
    (
        "e5-small ONNX weights",
        lambda: settings.embed_model_dir / "onnx" / "model_qint8_avx512_vnni.onnx",
    ),
    ("reranker tokenizer", lambda: settings.embed_model_dir.parent / "reranker" / "tokenizer.json"),
    (
        "reranker ONNX weights",
        lambda: settings.embed_model_dir.parent / "reranker" / "onnx" / "model_quantized.onnx",
    ),
)

#: A floor on tests actually EXECUTED. Set well below the current count so it
#: does not need editing for every new test, but high enough that a collapsed
#: run cannot pass. The suite is at 409; anything under 300 means something
#: went wrong with collection rather than with the code.
MINIMUM_TESTS = 300


def _minimum() -> int:
    """Overridable, so the guard can be PROVEN to fire.

    A check nobody has watched fail is not a check - that is the lesson of the
    whole honesty audit. Setting RAGINTEL_MIN_TESTS absurdly high plants the
    defect this guard exists to catch, without editing code.
    """
    #: The pre-rename name is still accepted. If a shell profile or CI job
    #: still exports NABAA_MIN_TESTS, dropping it would not error - the
    #: override would just stop applying and the guard would run at its
    #: default, which is the failure this variable exists to make visible.
    return int(
        os.environ.get(
            "RAGINTEL_MIN_TESTS", os.environ.get("NABAA_MIN_TESTS", MINIMUM_TESTS)
        )
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Stop before the cascade, with the fix."""
    missing = [name for name, path in REQUIRED_MODEL_FILES if not path().exists()]
    if not missing:
        return

    raise pytest.UsageError(
        "\n\nThe local models are not staged, so this suite cannot prove anything.\n"
        "Missing:\n  - "
        + "\n  - ".join(missing)
        + "\n\nFix it with:\n    python scripts/fetch_models.py\n\n"
        "Stopping here on purpose. Without these the run produces about ninety\n"
        "failures with one cause, and nine silent skips that let the embedding\n"
        "and rerank paths go untested behind a green tick.\n"
    )


@pytest.fixture(autouse=True, scope="session")
def _the_suite_does_not_read_the_developers_env(tmp_path_factory):
    """Pin the authentication mode so the suite answers the same everywhere.

    5. A TEST SUITE WHOSE RESULT DEPENDS ON AN UNTRACKED FILE.
       `env_file` was a relative path, so `backend/.env` was read when pytest
       ran from `backend/` - which is what the README and the PR template both
       prescribe - and ignored when it ran from the repository root. With
       AUTH_MODE=demo_required in that file, an unauthenticated TestClient
       resolves to an EMPTY SCOPE, and the same commit on the same machine in
       the same second reported:

           from backend/   :  32 failed, 848 passed
           from repo root  :   0 failed, 880 passed

       Neither number was wrong, which is worse than one of them being wrong:
       no test report from this project could be read without also knowing the
       reporter's working directory and the contents of a file that is not in
       the repository. Anchoring `env_file` (config.py) fixes the application;
       it makes the suite read a developer's local `.env` on EVERY run, which
       is the opposite of what a suite should do.

       So the mode is pinned here. The suite tests `disabled` by default, and
       `demo_required` is tested DELIBERATELY, by fixtures that set it - see
       test_access_routes.py and test_auth_required_mode.py - rather than by
       whichever file happens to sit on the machine.

       This pin makes the assertion at test_access_routes.py's
       `test_auth_disabled_is_the_default_and_changes_nothing` vacuous, since
       it would then be asserting the value this fixture just set. That test
       was rewritten to construct a fresh Settings() with no environment, which
       is the claim it was always trying to make.
    """
    settings.auth_mode = "disabled"
    yield


@pytest.fixture(autouse=True, scope="session")
def _never_the_developers_database(tmp_path_factory):
    """Point the DEFAULT database at a temp file for the whole session.

    4. A TEST THAT PASSES ONLY BECAUSE A DATABASE HAPPENS TO EXIST.
       `backend/data/rag_intelligence.sqlite` is 62 MB on a development machine and absent
       in CI. Two test files had no storage fixture of their own, so here they
       opened the real corpus and passed, and in CI they opened an empty file
       and raised `no such table: chunks` twenty times. The suite reported 756
       passing locally and 736 in CI, and the LOCAL number was the wrong one.

       Same shape as the three above: a check that appears to pass because of
       state nobody declared. Redirecting the default makes a forgotten fixture
       fail HERE, exactly as it fails in CI, instead of waiting for a pull
       request to find it.

       Nothing is created. A file that forgets `init_db()` gets an empty
       database and fails loudly, which is the point. Tests with their own
       `temp_storage` override this per test and are unaffected.
    """
    from app import db
    from app import access

    session_dir = tmp_path_factory.mktemp("ragintel-session")
    settings.data_dir = session_dir
    settings.upload_dir = session_dir / "uploads"
    settings.db_path = session_dir / "session.sqlite"
    db.reset_connection()
    yield
    db.reset_connection()


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Print every skip with its reason, and state the count plainly.

    A skip is not a pass. Absorbed into the tick it is indistinguishable from
    one, which is how a run with the whole embedding path skipped looked
    healthy.
    """
    skipped = terminalreporter.stats.get("skipped", [])
    if not skipped:
        terminalreporter.write_line("")
        terminalreporter.write_line("no tests were skipped - the whole suite ran", green=True)
        return

    terminalreporter.write_line("")
    terminalreporter.write_sep("=", f"{len(skipped)} SKIPPED - these proved nothing")
    for report in skipped:
        reason = ""
        if isinstance(getattr(report, "longrepr", None), tuple) and len(report.longrepr) == 3:
            reason = str(report.longrepr[2]).replace("Skipped: ", "")
        terminalreporter.write_line(f"  {report.nodeid}")
        terminalreporter.write_line(f"      reason: {reason or 'not stated'}")


def _is_full_run(config: pytest.Config) -> bool:
    """Was this a whole-suite run, or a deliberate subset?

    The floor must not fire on `-k something` or a single file - that is how a
    developer works, and a guard that punishes normal use gets disabled. It
    applies only when the whole suite was asked for, which is the case CI runs
    and the case where a collapsed collection would otherwise pass.
    """
    if config.getoption("keyword") or config.getoption("markexpr"):
        return False
    # `args` holds the paths given on the command line; empty means testpaths
    # from pytest.ini, i.e. everything.
    given = [a for a in config.args if not a.startswith("-")]
    return not given or given == list(config.getini("testpaths"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """A run too small to have tested anything is a failure, not a pass."""
    if exitstatus != 0:
        return  # already failing; do not mask the real reason
    if not _is_full_run(session.config):
        return
    if session.testscollected < _minimum():
        session.exitstatus = 1
        print(
            f"\n\nFLOOR NOT MET: only {session.testscollected} tests were "
            f"collected on a FULL run, expected at least {_minimum()}.\n"
            "A run this small has not tested the system, whatever it reports. "
            "Check collection, testpaths and conftest import errors.\n"
        )
