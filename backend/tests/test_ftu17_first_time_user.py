"""First-time-user test of live update 17 (17 Nov 2026): the engine that read a line, a quote about another field, a quote code did not
find, "does not apply" with one count and its proof, and the words of a paper never reviewed or whose review was cancelled. Every check
reads the file AS BUILT (or the route as served). Invented values only."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import crs_ai_actions, crs_completeness, crs_one, db
from app.config import settings
from tests.agent_review_support import NA_PROOF
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, points_of
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _client,
    _run,
    _submittal,
    temp_db,
)
from tests.test_ftu1_first_time_user import silent_line
from tests.test_ftu16_first_time_user import _rows
from tests.test_k4_one_crs import rows_after, scope_all


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def _book(data: bytes):
    return load_workbook(io.BytesIO(data))


def _texts(ws) -> list[str]:
    return [str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None]


def _team(doc: str) -> bytes:
    return crs_completeness.file_or_refuse(doc, scope_all(), "team")


def _paper(
    lines: list[dict], models: list[str] | None = None
) -> tuple[str, str, object]:
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run = ai_run(doc, lines)
    if models is not None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE agent_review_run SET models_json = ? WHERE run_id = ?",
                (json.dumps(models), run),
            )
    return doc, run, _client(doc, "doc_std")


# ------------------------------------------------------------------------------------------------ 1. the engine that read a line


@pytest.mark.parametrize(
    ("models", "model", "point_words", "header"),
    [
        (
            ["local-lead-x", "local-second-y"],
            "local-lead-x",
            "AI reviewer on the local model",
            "AI review: Local",
        ),
        (
            ["claude-invented-a", "claude-invented-b"],
            "claude-invented-a",
            "AI reviewer on Claude",
            "AI review: Claude",
        ),
    ],
)
def test_the_page_the_points_route_and_the_crs_name_the_engine_the_run_stored(
    models, model, point_words, header
):
    doc, _run_id, client = _paper(
        [
            mk("R-1", "Fail", "Fail", model=model),
            mk("R-3", "Query", "Fail", model=model),
        ],
        models,
    )
    ai = [p for p in points_of(client, doc)["points"] if p["source"] == "ai_review"]
    assert ai and {p["engine"] for p in ai} == {point_words}
    engine_row = next(t for t in _texts(_book(_team(doc))["CRS"]) if "AI review:" in t)
    assert header in engine_row


def test_a_line_with_no_model_of_its_own_takes_the_runs_engine():
    doc, _run_id, client = _paper(
        [mk("R-1", "Fail", "Fail", model="")], ["claude-invented-a"]
    )
    ai = [p for p in points_of(client, doc)["points"] if p["source"] == "ai_review"]
    assert {p["engine"] for p in ai} == {"AI reviewer on Claude"}


# ------------------------------------------------------------------------------------------------ 3. a quote about another field


def _silent(quote: str, **kw) -> dict:
    return silent_line(
        "absent",
        opinion=False,
        paper_quote=quote,
        field="Body material",
        field_roles=["body_material"],
        **kw,
    )


def test_a_verified_quote_about_another_field_says_so_and_the_engineer_checks():
    doc, _run_id, _c = _paper([_silent("Rated flow: 30 m3/h")])
    rows = [r for r in _rows(_team(doc)) if "found on the page by code" in str(r)]
    assert len(rows) == 2, "the row on the sheet CRS and on the sheet Evidence"
    for r in rows:
        assert (
            r["What the contractor must do"]
            == "Engineer to check Body material: the quoted words are about another field."
        )
        assert r["Reason"] == crs_ai_actions.OTHER_FIELD_REASON
        assert not [v for v in r.values() if "may state it" in v]


@pytest.mark.parametrize(
    "quote",
    [
        "Body: forged steel",
        "Rated flow 30 m3/h; body material: steel",
        "30 m3/h",
        "Water/Gas (dual service)",
    ],
)  # the last: a word inside a value ("gas") is never read as another field's label
def test_a_quote_with_this_fields_words_or_no_other_label_is_never_about_another_field(
    quote,
):
    doc, _run_id, _c = _paper([_silent(quote)])
    rows = [r for r in _rows(_team(doc)) if "found on the page by code" in str(r)]
    assert rows and not [
        v for r in rows for v in r.values() if "about another field" in v
    ]


def test_a_row_named_by_no_field_of_the_list_is_never_about_another_field():
    assert not crs_ai_actions.about_another_field(
        "Rated flow: 30 m3/h", ["Design data"]
    )
    assert crs_ai_actions.about_another_field("Rated flow: 30 m3/h", ["Body material"])


# ------------------------------------------------------------------------------------------------ 4. a quote code did not find


def test_a_quote_code_did_not_find_never_decides_the_action():
    line = _silent(
        "Rated flow: 30 m3/h", quotes_checked={"paper": False, "clause": True}
    )
    doc, _run_id, client = _paper([line])
    point = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "ai_review"
    )
    assert (
        point["action"]
        == "Engineer to check Body material: the words quoted were not found on the page by code."
    )
    rows = [r for r in _rows(_team(doc)) if "Body material" in str(r)]
    assert rows
    for r in rows:
        assert not [v for v in r.values() if "Contractor to" in v], r
        assert r["What the contractor must do"].startswith("Engineer to check")
    # the same row with NO quote asks the contractor, as before
    bare = _silent("", quotes_checked={"paper": False, "clause": True})
    assert crs_ai_actions.query_action(bare, "Body material", "").startswith(
        "Contractor to state"
    )


# ------------------------------------------------------------------------------------------------ 5. does not apply: proof and one count


def _na(iid: str, field: str, proof: bool) -> dict:
    return mk(
        iid,
        "Query",
        None,
        reason_code="not_applicable",
        field=field,
        **(NA_PROOF if proof else {}),
    )


def test_a_does_not_apply_without_its_proof_is_its_own_section_never_a_main_question():
    doc, _run_id, client = _paper([_na("R-21", "Design pressure", proof=False)])
    listing = points_of(client, doc)
    point = next(p for p in listing["points"] if p["source"] == "ai_review")
    assert point["rank"] == 9 and point["tile"] == "na_to_confirm"  # owner on PR #1872: not a main question
    assert point["action"].startswith("Engineer to check whether the rule applies")
    assert listing["counts"]["tiles"]["does_not_apply"]["total"] == 0
    assert listing["counts"]["tiles"]["questions"]["total"] == 0
    wb = _book(_team(doc))
    assert rows_after(wb[crs_one.DNA_SHEET], "No on the sheet Evidence")[1] == []


def test_a_does_not_apply_with_its_proof_carries_it_and_every_sheet_uses_one_count():
    lines = [
        _na("R-21", "Field A", proof=True),  # alone on its field: not a comment
        _na(
            "R-22", "Field B", proof=True
        ),  # on a field that also has a finding: inside that comment
        mk("R-23", "Query", "Fail", field="Field B"),
    ]
    doc, _run_id, client = _paper(lines)
    tile = points_of(client, doc)["counts"]["tiles"]["does_not_apply"]["total"]
    wb = _book(_team(doc))
    head, dna = rows_after(wb[crs_one.DNA_SHEET], "No on the sheet Evidence")
    assert tile == len(dna) == 2
    proof_col = head.index("Why, with its proof (found by code)")
    assert all(
        "found in the rule book by code" in r[proof_col]
        and "found on the page by code" in r[proof_col]
        for r in dna
    )
    said = "Does not apply: 2 (1 not a comment"
    assert any(said in t for t in _texts(wb[crs_one.TEAM_SHEET]))
    assert any(said in t for t in _texts(wb[crs_one.NOT_A_COMMENT_SHEET]))
    assert any(said in t for t in _texts(wb[crs_one.DNA_SHEET]))
    _h, rows = rows_after(wb[crs_one.NOT_CHECKED_SHEET], "What")
    assert ["Does not apply", 2] in [r[:2] for r in rows]


# ------------------------------------------------------------------------------------------------ 8. not reviewed, review cancelled


def test_the_check_of_a_paper_never_reviewed_says_not_reviewed_never_complete():
    doc = _submittal()
    client = _client(doc)
    got = client.get(f"/api/reviews/papers/{doc}/crs/check").json()
    for copy in ("team", "contractor"):
        assert got[copy]["not_reviewed"] is True and got[copy]["ok"] is False
        assert got[copy]["sentence"] == crs_completeness.NOT_REVIEWED
        assert "Complete" not in got[copy]["sentence"]


def _cancelled(doc: str, at: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (f"cancelled-{at}", doc, "cancelled", at, at, at),
        )


def test_a_paper_whose_only_review_was_cancelled_is_said_so():
    doc = _submittal()
    client = _client(doc)
    _cancelled(doc, "2099-01-01T00:00:00Z")
    got = client.get(f"/api/reviews/papers/{doc}/crs/check").json()
    assert got["team"]["sentence"] == crs_completeness.CANCELLED_NOT_REVIEWED


def test_a_file_whose_papers_latest_review_was_cancelled_says_so_on_its_first_sheet():
    doc, _run_id, _c = _paper([mk("R-1", "Fail", "Fail")])
    for copy in ("team", "contractor"):
        assert not [
            t
            for t in _texts(
                _book(crs_completeness.file_or_refuse(doc, scope_all(), copy))["CRS"]
            )
            if "cancelled" in t
        ]
    _cancelled(
        doc, "2099-01-01T00:00:00Z"
    )  # newer than the finished review the file holds
    for copy in ("team", "contractor"):
        texts = _texts(
            _book(crs_completeness.file_or_refuse(doc, scope_all(), copy))["CRS"]
        )
        assert [
            t
            for t in texts
            if t.startswith(
                "Review cancelled: the latest review of this paper (started 2099-01-01)"
            )
        ]
    _cancelled(doc, "2000-01-01T00:00:00Z")  # an OLDER cancelled run changes nothing
    assert crs_completeness.latest_cancelled(doc, ()) == "2099-01-01"


def test_an_older_runs_stored_does_not_apply_without_proof_is_read_as_the_question():
    doc, run_id, client = _paper([_na("R-21", "Design pressure", proof=False)])
    with db.connect() as conn:  # as an earlier run stored it, before FTU-17
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Not applicable', word = 'Not applicable' WHERE run_id = ?",
            (run_id,),
        )
    point = next(
        p for p in points_of(client, doc)["points"] if p["source"] == "ai_review"
    )
    assert point["rank"] == 9 and point["action"].startswith(
        "Engineer to check whether the rule applies"
    )
