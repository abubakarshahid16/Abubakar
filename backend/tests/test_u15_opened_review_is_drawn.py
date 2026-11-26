"""The review a row names is the review its Open draws (lead-4, 26 Nov 2026: the valve row named the signed Claude review, Open went to
its id, and the page drew the paper's newer local rough draft, because `GET /api/reviews/runs/{id}` did not say the run was a general
one). One general run's own fields, as its list row carries them. Invented runs only."""

from __future__ import annotations

from app import aim_review_face, aim_review_runs, db
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_u12_rough_draft_guard import LOCAL_RUN, _entries, _make_local, _world


def _fields(run_id: str, allowed=frozenset({PAPER, BOOK})):
    with db.connect() as conn:
        return aim_review_runs.face_fields(conn, allowed, run_id)


def test_one_run_carries_the_same_face_fields_as_its_row_in_the_list(temp_db):
    _world()
    make_run(RUN)  # Claude, older
    _make_local()  # local rough draft, newer
    rows = {e["review_run_id"]: e for e in _entries()}
    for run_id in (RUN, LOCAL_RUN):
        got = _fields(run_id)
        assert got["method"] == aim_review_runs.GENERAL
        for key in ("engine", "engine_words", "general_signoff", "face", "newer_note"):
            assert got[key] == rows[run_id][key], key
    assert _fields(RUN)["face"] is True and _fields(RUN)["newer_note"].startswith(aim_review_face.NEWER_UNSIGNED)
    assert _fields(LOCAL_RUN)["face"] is False and _fields(LOCAL_RUN)["engine"] == aim_review_face.LOCAL


def test_a_run_outside_the_reader_s_papers_or_not_general_answers_nothing(temp_db):
    _world()
    make_run(RUN)
    assert _fields(RUN, allowed=frozenset({BOOK})) is None  # rule 5: never answered for a paper the caller may not read
    assert _fields("run-invented-not-general") is None
