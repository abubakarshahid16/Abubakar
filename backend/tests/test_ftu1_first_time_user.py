# ruff: noqa: RUF059
"""First-time-user findings, round 1 (order 14): what a new engineer saw on the live code and was not true. Invented data only.

1. A "not met" on SILENCE (the line's own reason code says the paper does not state the value) said "a value is stated on the paper"
   and showed a quote code found on the page as if it were the value: the quote of another field's label. Now the reason follows the
   line's own reason code, and the quote is shown only as where the reader looked, never as evidence.
2. A cell of the column Note was cut mid-word with no mark: every shortened cell ends with the mark and keeps its whole text in Full text,
   and the completeness check covers the Note column.
3. A paper never reviewed got a CRS file: it is refused with a plain sentence.
4. The documents API said "not_reviewed" for a reviewed paper: it says the latest run's status.
5. The one-CRS download is named after the paper.
6. The older per-review file's route offered copy words it then refused.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app import agent_review_wording as W
from app import (
    crs_ai_actions,
    crs_ai_words,
    crs_completeness,
    crs_copy_words,
    crs_one,
    db,
    review_points,
)
from app import crs_ai_workbook as wb
from app.config import settings
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, world_with_both
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)
from tests.test_k4_one_crs import rows_after, scope_all, sheet


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


CTX = {
    "run_id": "r",
    "paper_document_id": "d",
    "book_of": {"R-5": ("doc_std", "STD-1")},
    "readable": frozenset({"doc_std"}),
}
#: an invented label of ANOTHER field, found on the page by code: where the AI looked, not a value of the field it judged
OTHER_LABEL = "Body material"


def silent_line(
    code: str = "absent", *, opinion: bool = True, paper_quote: str = OTHER_LABEL, **kw
) -> dict:
    """An AI line whose OWN reason code says the paper does not state the value, carrying a quote code found on the page."""
    line = mk(
        "R-5",
        "Query",
        "Fail",
        reason_code=code,
        paper_quote=paper_quote,
        why="the paper is silent",
        **kw,
    )
    if opinion:  # "Not met · one reader"
        line = {
            **line,
            "verdict_class": W.CLASS_OPINION,
            "verdict_label": W.THINKS_NOT_MET,
        }
    return line


# ------------------------------------------------------------------------------------------------ 1. reason and quote agree with the code


@pytest.mark.parametrize("code", ["absent", "sheet_silent", "absent_pages_not_named"])
@pytest.mark.parametrize("opinion", [True, False])
def test_a_not_met_on_silence_says_the_paper_does_not_state_it_and_never_shows_the_quote_as_evidence(
    code, opinion
):
    point = review_points.ai_point(silent_line(code, opinion=opinion), CTX)
    assert point["rank"] == (3 if opinion else 4)
    reason = crs_one.reason_of(point)
    assert "a value is stated" not in reason and "does not state" in reason
    shows = crs_one.paper_shows(point)
    assert (
        "found on the page" in shows
        and "looked" in shows
        and "not evidence" in shows.lower()
    )
    assert shows != f'"{OTHER_LABEL}" ({review_points.PAPER_CHECK})'
    # the quote is never the point's evidence: not as a verified quote, not as a stored value, not to the contractor
    assert (
        point["paper_quote"] is None
        and point["paper_value"] is None
        and point["paper_looked"] == OTHER_LABEL
    )
    # the page shows the same words (its note), and a silent query asks the contractor to STATE the value, never to confirm it
    assert point["paper_quote_note"] == shows
    if not opinion:
        assert (
            "confirm or justify" not in (point["action"] or "")
            and "to state" in point["action"]
        )


def test_the_older_ai_sheet_says_the_same_for_a_not_met_on_silence():
    line = silent_line("absent")
    cell = wb.layout_comment(
        line, crs_ai_words.STATUS_AI, crs_ai_words.ORDER_AI_NOT_MET
    )
    assert (
        f'The paper states "{OTHER_LABEL}"' not in cell
        and "a value is stated" not in cell
    )
    assert "did not find" in cell and "looked" in cell
    assert (
        crs_ai_actions.action_case(silent_line("sheet_silent", opinion=False))
        == "blank"
    )


def test_a_stated_value_without_a_silence_code_is_still_evidence_and_a_deferral_still_reads_as_deferred():
    stated = mk("R-5", "Query", "Fail", paper_quote="Body: steel")
    point = review_points.ai_point(stated, CTX)
    assert point["paper_quote"] == "Body: steel" and not point.get("paper_looked")
    assert crs_ai_actions.action_case(stated) == "stated"
    deferred = silent_line(
        "sheet_silent", opinion=False, paper_quote="Body material: by vendor"
    )
    assert crs_ai_actions.action_case(
        deferred
    ) == "deferred" and not crs_ai_actions.looked_only(deferred)
    silent_no_quote = silent_line(
        "absent", quotes_checked={"paper": False, "clause": True}
    )
    assert not crs_ai_actions.looked_only(silent_no_quote)


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("missing_information", "MISSING_INFORMATION"),
        ("datasheet_check", "MISSING_INFORMATION"),
    ],
)
def test_a_rule_check_point_with_no_value_shows_its_passage_only_as_where_it_looked(
    kind, status
):
    ctx = {"run_id": "r", "paper_document_id": "d", "readable": frozenset({"doc_std"})}
    row = {
        "row_kind": kind,
        "finding_id": "f-1",
        "comment": "Contractor to state the design pressure.",
        "page_section": "Page 4",
    }
    finding = {
        "compliance_status": status,
        "contractor_evidence_text": "Design data",
        "standard_document_id": "doc_std",
    }
    sides = {"submittal": {"verified": True, "page": 4}, "standard": {}}
    point = review_points.rule_point(row, ctx, finding, sides)
    assert point["paper_quote"] is None and point["paper_looked"] == "Design data"
    shows = crs_one.paper_shows(point)
    assert "not evidence" in shows.lower() and "Design data" in shows
    # a value the rule check found is still its evidence
    found = review_points.rule_point(
        row, ctx, {**finding, "compliance_status": "NON_COMPLIANT"}, sides
    )
    if kind != "missing_information":
        assert found["paper_quote"] == "Design data" and not found.get("paper_looked")


def test_a_looked_here_quote_never_joins_two_fields_into_one_comment():
    from app import crs_comments

    a = {**review_points.ai_point(silent_line("absent"), CTX), "id": "a", "page": 2}
    b = {
        **a,
        "id": "b",
        "name": "Another field",
        "_line": {**a["_line"], "field": "Another field"},
    }

    def paper(p):
        return {e for e in crs_comments._evidence([p]) if e[0] == "paper"}

    assert not paper(a) and not paper(
        b
    )  # the same found quote on the same page: not evidence, so not shared
    stated = {
        **a,
        "paper_quote": OTHER_LABEL,
        "paper_looked": None,
        "_line": {**a["_line"], "reason_code": None, "silence_query": None},
    }
    assert paper(stated)  # a quote that is evidence still counts


# ------------------------------------------------------------------------------------------------ 2. every cut is marked


def test_the_absence_sentence_keeps_the_whole_clause_quote():
    quote = (
        "The nameplate shall carry the maker, the serial number and the rated set pressure "
        * 6
        + "endword"
    )
    cell = crs_ai_words.absence_cell({"clause_quote": quote}, "set pressure")
    assert quote.strip() in cell and "endword" in cell


def test_a_point_name_taken_from_its_comment_is_never_cut_without_a_mark():
    from app import review_points_content as content

    ctx = {"run_id": "r", "paper_document_id": "d", "readable": frozenset()}
    row = {
        "row_kind": "needs_engineer_review",
        "finding_id": "f-2",
        "comment": f"{content.PLACEHOLDER} on the design pressure of the drum",
    }
    name = review_points.rule_point(row, ctx, None, {})["name"]
    assert name.endswith("...") and len(name.split()) == 8


def test_a_long_note_ends_with_the_mark_and_its_whole_text_is_in_full_text(monkeypatch):
    doc, rc, ai, client = world_with_both()
    long_note = (
        "Also: Not met, Field Z: Contractor to state the value of the item " * 20
        + "lastword"
    )
    monkeypatch.setattr(crs_one, "comment_note", lambda c, ms: long_note)
    data = crs_completeness.file_or_refuse(doc, scope_all(), "team")
    head, rows = rows_after(sheet(data), "Comment")
    note = rows[0][head.index("Note")]
    assert note.endswith(crs_one.CUT_MARK) and len(note) <= crs_one.CELL_LIMIT
    assert f"note: {long_note}" in rows[0][head.index("Full text")]
    report = crs_completeness.checked_files(doc, scope_all())["team"][1]
    assert report["ok"] and report["cut_cells_marked"] >= 1


def test_a_note_cut_without_the_mark_refuses_the_file(monkeypatch):
    doc, rc, ai, client = world_with_both()
    monkeypatch.setattr(crs_one, "comment_note", lambda c, ms: "word " * 200)
    monkeypatch.setattr(crs_one, "CUT_MARK", "")
    with pytest.raises(crs_completeness.Incomplete) as got:
        crs_completeness.file_or_refuse(doc, scope_all(), "team")
    assert any("note is cut without the mark" in m for m in got.value.report["missing"])


# ------------------------------------------------------------------------------------------------ 3. no CRS for a paper never reviewed


@pytest.mark.parametrize("copy", ["team", "contractor"])
def test_a_paper_never_reviewed_gets_no_crs_file_but_a_plain_sentence(copy):
    doc = _submittal()
    got = _client(doc).get(f"/api/reviews/papers/{doc}/crs", params={"copy": copy})
    assert got.status_code == 409, got.text
    assert got.json()["detail"]["message"] == crs_completeness.NOT_REVIEWED
    assert "spreadsheet" not in got.headers.get("content-type", "")
    with pytest.raises(crs_completeness.Incomplete):
        crs_completeness.file_or_refuse(doc, scope_all(), copy)


def test_a_paper_with_only_a_running_review_is_not_reviewed_yet():
    doc = _submittal()
    ai_run(doc, [mk("R-1", "Fail", "Fail")], status="running")
    assert _client(doc).get(f"/api/reviews/papers/{doc}/crs").status_code == 409


# ------------------------------------------------------------------------------------------------ 4. the review status is true


def test_the_documents_api_says_a_reviewed_paper_is_reviewed_on_the_list_and_on_its_own_route():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    _run(doc)
    client = _client(doc, other)
    one = client.get(f"/api/documents/{doc}")
    assert one.status_code == 200 and one.json()["review_status"] == "completed"
    assert (
        client.get(f"/api/documents/{other}").json()["review_status"] == "not_reviewed"
    )
    listed = {d["id"]: d["review_status"] for d in client.get("/api/documents").json()}
    assert listed == {doc: "completed", other: "not_reviewed"}


# ------------------------------------------------------------------------------------------------ 5. the file is named after the paper


def _set_number(doc: str, number: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, document_number) VALUES (?,'upload',?)"
            " ON CONFLICT(document_id) DO UPDATE SET document_number = excluded.document_number",
            (doc, number),
        )


def _name_of(response) -> str:
    return response.headers["content-disposition"].split('filename="', 1)[1].rstrip('"')


def test_the_one_crs_file_is_named_after_the_papers_number_else_its_file_stem():
    doc, rc, ai, client = world_with_both()  # an invented paper "drum.pdf"
    assert (
        _name_of(client.get(f"/api/reviews/papers/{doc}/crs?copy=team"))
        == "crs-team-drum.xlsx"
    )
    assert (
        _name_of(client.get(f"/api/reviews/papers/{doc}/crs?copy=contractor"))
        == "crs-contractor-drum.xlsx"
    )
    _set_number(doc, "XX/0000 Rev:A ü")
    assert (
        _name_of(client.get(f"/api/reviews/papers/{doc}/crs?copy=team"))
        == "crs-team-XX-0000-Rev-A.xlsx"
    )


def test_a_file_name_keeps_only_safe_characters_at_most_sixty():
    assert crs_one.paper_file_stem("a" * 80 + ".pdf") == "a" * 60
    assert crs_one.paper_file_stem("  ../..//  ") == ""
    assert crs_one.file_name("team", "") == "crs-team.xlsx"
    assert crs_one.file_name("contractor", "Q-1") == "crs-contractor-Q-1.xlsx"


# ------------------------------------------------------------------------------------------------ 6. the older route's plain words


def test_with_the_older_file_off_the_ai_route_says_the_one_sentence_with_or_without_a_copy_word(
    monkeypatch,
):
    monkeypatch.setattr(settings, "old_crs_download_enabled", False)
    doc, rc, ai, client = world_with_both()
    for params in ({}, {"copy": "internal"}, {"copy": "nope"}):
        got = client.get(f"/api/reviews/runs/{ai}/agent/crs", params=params)
        assert got.status_code == 404, (params, got.text)
        assert got.json()["detail"]["message"] == crs_copy_words.OLD_FILE_OFF
    for params in (
        {"copy": "internal"},
        {"copy": "nope"},
    ):  # the rule check's older file: the same sentence first
        got = client.get(f"/api/reviews/runs/{rc}/crs", params=params)
        assert (
            got.status_code == 404
            and got.json()["detail"]["message"] == crs_copy_words.OLD_FILE_OFF
        )


def test_with_the_older_file_on_a_missing_or_wrong_copy_word_lists_the_words_the_route_serves(
    monkeypatch,
):
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    doc, rc, ai, client = world_with_both()
    for params in ({}, {"copy": "nope"}):
        got = client.get(f"/api/reviews/runs/{ai}/agent/crs", params=params)
        assert got.status_code == 422 and "copy must be one of" in got.text
    assert (
        client.get(
            f"/api/reviews/runs/{ai}/agent/crs", params={"copy": "internal"}
        ).status_code
        == 200
    )
    assert load_workbook(
        io.BytesIO(
            client.get(
                f"/api/reviews/runs/{ai}/agent/crs", params={"copy": "contractor"}
            ).content
        )
    )
