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
from tests.test_b1_review_points import ai_run, decide, points_of, world_with_both
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
#: the field's OWN label and nothing else, found on the page by code: the ONE shape code can show holds no value
OTHER_LABEL = "Set pressure"


def silent_line(
    code: str = "absent", *, opinion: bool = True, paper_quote: str = OTHER_LABEL, **kw
) -> dict:
    """An AI line whose OWN reason code says the paper does not state the value, carrying a quote code found on the page."""
    kw = {"field": "Set pressure", "field_roles": ["set_pressure"], **kw}
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
    # the action says what the reason says, on a question AND on a one-reader "not met"
    assert "confirm or" not in (point["action"] or "")
    assert point["action"].startswith("Contractor to state Set pressure")


@pytest.mark.parametrize(
    "quote", ["Set pressure: 12 barg", "Rated 12 barg", "Set pressure 316 SS"]
)
@pytest.mark.parametrize("opinion", [True, False])
def test_a_silent_line_whose_quote_may_state_the_value_is_the_engineers_to_check(
    quote, opinion
):
    line = silent_line("absent", opinion=opinion, paper_quote=quote)
    assert crs_ai_actions.silent_quote(line) == crs_ai_actions.CONTRADICTS
    point = review_points.ai_point(line, CTX)
    shows, reason = crs_one.paper_shows(point), crs_one.reason_of(point)
    assert "not evidence" not in shows.lower()
    assert quote in shows and "may state it" in shows
    assert reason == crs_ai_actions.CONTRADICT_REASON
    assert point["action"].startswith("Engineer to check Set pressure")
    assert "Contractor" not in point["action"]
    assert point["paper_quote"] is None  # never the contractor's "The paper shows"
    cell = wb.layout_comment(line, *wb.status_of(line))
    assert "may state it" in cell and "not evidence" not in cell.lower()
    assert f'The paper states "{quote}"' not in cell


def test_only_the_fields_own_label_alone_is_where_it_looked():
    for quote in ("Set pressure", "Set pressure:", "SET PRESSURE"):
        got = crs_ai_actions.silent_quote(silent_line(paper_quote=quote))
        assert got == crs_ai_actions.LOOKED, quote


def test_label_only_means_all_of_the_labels_words_and_nothing_else():
    kind = crs_ai_actions.found_quote_kind
    assert kind("Insulation required", ["Insulation required"]) == crs_ai_actions.LOOKED
    for quote in ("Required", "Insulation", "Insulation required: yes"):
        assert kind(quote, ["Insulation required"]) == crs_ai_actions.CONTRADICTS, quote


@pytest.mark.parametrize("passage", ["Body material: carbon steel", "Carbon steel"])
def test_one_decision_gives_every_cell_of_a_silent_row_in_both_homes(passage):
    """The rule check's point and the AI review's line, same field and same found quote: the same kind, reason, action and note."""
    ctx = {"run_id": "r", "paper_document_id": "d", "readable": frozenset({"doc_std"})}
    row = {
        "row_kind": "missing_information",
        "finding_id": "f-9",
        "comment": "Contractor to state the body material.",
        "page_section": "Page 4 - Body material",
    }
    finding = {
        "compliance_status": "MISSING_INFORMATION",
        "contractor_evidence_text": passage,
        "standard_document_id": "doc_std",
    }
    sides = {"submittal": {"verified": True, "page": 4}, "standard": {}}
    rc = review_points.rule_point(row, ctx, finding, sides)
    line = silent_line(
        "absent",
        opinion=False,
        paper_quote=passage,
        field="Body material",
        field_roles=["body_material"],
    )
    ai = review_points.ai_point(line, CTX)
    want = crs_ai_actions.silent_row_words("Body material", passage)
    assert want.kind == crs_ai_actions.CONTRADICTS
    for point in (rc, ai):
        assert crs_one.reason_of(point) == want.reason
        assert point["action"] == want.action
        assert point["action"].startswith("Engineer to check Body material")
        assert crs_one.paper_shows(point) == point["paper_quote_note"] == want.note
        assert "not evidence" not in want.note.lower()
        assert "no value found" not in crs_one.reason_of(point)
        assert point["paper_quote"] is None and point["paper_value"] is None


#: the lead's probes (field, verified quote): a quote that may state the value, whatever its shape
PROBES = [
    ("Body material", "Carbon steel"),
    ("Quantity", "Qty 4"),
    ("Number of stages", "Stages: 4"),
    ("Flange rating", "Class 300"),
    ("Flange facing", "RF"),
    ("Painting", "Yes"),
]


@pytest.mark.parametrize(("field", "quote"), PROBES)
@pytest.mark.parametrize("opinion", [True, False])
def test_every_other_found_quote_on_a_silent_line_is_neutral_and_the_engineer_checks(
    field, quote, opinion
):
    role = field.lower().replace(" ", "_")
    line = silent_line(
        "absent", opinion=opinion, paper_quote=quote, field=field, field_roles=[role]
    )
    assert crs_ai_actions.silent_quote(line) == crs_ai_actions.CONTRADICTS
    point = review_points.ai_point(line, CTX)
    shows, reason = crs_one.paper_shows(point), crs_one.reason_of(point)
    assert "not evidence" not in shows.lower() and "may state it" in shows
    assert reason == crs_ai_actions.CONTRADICT_REASON
    assert point["action"].startswith(f"Engineer to check {field}")
    cell = wb.layout_comment(line, *wb.status_of(line))
    assert "not evidence" not in cell.lower() and "may state it" in cell


def test_the_older_ai_sheet_says_the_same_for_a_not_met_on_silence():
    line = silent_line("absent")
    cell = wb.layout_comment(
        line, crs_ai_words.STATUS_AI, crs_ai_words.ORDER_AI_NOT_MET
    )
    assert (
        f'The paper states "{OTHER_LABEL}"' not in cell
        and "a value is stated" not in cell
    )
    assert "looked here" in cell and "did not find" not in cell
    assert (
        crs_ai_actions.action_case(silent_line("sheet_silent", opinion=False))
        == "blank"
    )
    # the one rule of silence: a silence flag with another reason code says the same
    flagged = silent_line("needs_drawing_or_calc", silence_query=True)
    cell = wb.layout_comment(flagged, *wb.status_of(flagged))
    assert f'The paper states "{OTHER_LABEL}"' not in cell
    shows = cell.split("\n")[
        1
    ]  # the "what the paper shows" part says the silence and where it looked
    # FTU-16: the one cell says the reason once with where it looked, and never both "not evidence" and "does not state"
    assert (
        "looked here" in shows
        and "does not state this value" in shows
        and "not evidence" not in shows.lower()
    )


def test_the_ai_reviews_own_sheet_and_evidence_cell_never_say_a_looked_quote_is_stated():
    from app import agent_review_crs as arc

    flagged = silent_line("needs_drawing_or_calc", opinion=False, silence_query=True)
    assert arc.stated(flagged) == ""
    assert f'the sheet states "{OTHER_LABEL}"' not in arc.company_comment(flagged)
    check = arc.EVIDENCE_COLUMNS.index("Paper quote check")
    assert "not evidence" in arc._evidence_row(1, flagged, "Query")[check]
    may = silent_line("absent", opinion=False, paper_quote="Set pressure: 12 barg")
    said = arc.company_comment(may)
    assert "may state it" in said and "not shown on the sheet" not in said
    assert "Engineer to check" in said
    assert "engineer checks" in arc._paper_check_words(may)
    plain = mk("R-5", "Query", "Fail", paper_quote="Body: steel")
    assert arc.stated(plain) == "Body: steel"
    assert arc._paper_check_words(plain) == "verified"


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
        "page_section": "Page 4 - Design data",
    }
    finding = {
        "compliance_status": status,
        "contractor_evidence_text": "Design data",
        "standard_document_id": "doc_std",
    }
    sides = {"submittal": {"verified": True, "page": 4}, "standard": {}}
    point = review_points.rule_point(row, ctx, finding, sides)
    assert point["paper_quote"] is None and point["paper_looked"] == "Design data"
    assert (
        point["paper_value"] is None
    )  # never 'As stored (not verified by code)' beside it
    shows = crs_one.paper_shows(point)
    assert "not evidence" in shows.lower() and "Design data" in shows
    # the same ONE rule as the AI review's lines: anything but the field's own label alone may state it
    for passage in ("Design pressure 12 barg", "Body material: carbon steel"):
        other = review_points.rule_point(
            row, ctx, {**finding, "contractor_evidence_text": passage}, sides
        )
        assert "not evidence" not in crs_one.paper_shows(other).lower(), passage
        assert "may state it" in crs_one.paper_shows(other), passage
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
    assert name.endswith(crs_completeness.CUT_MARK) and "..." not in name
    assert len(name.split()) == 7


def test_a_quote_shortened_on_the_older_ai_sheet_ends_with_the_one_cut_mark():
    from app import agent_review_crs as arc

    got = arc.stated(mk("R-5", "Query", "Fail", paper_quote="word " * 30 + "end"))
    assert got.endswith(crs_completeness.CUT_MARK) and "..." not in got


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


def test_a_long_note_from_the_real_builder_is_marked_and_whole_in_full_text():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    lines = [
        mk(f"R-{i}", "Query", "Fail", why="x y", field="Shared field", clause=f"4.{i}")
        for i in range(1, 9)
    ]
    ai_run(doc, lines)
    data = crs_completeness.file_or_refuse(doc, scope_all(), "team")
    head, rows = rows_after(sheet(data), "Comment")
    row = next(r for r in rows if r[head.index("Points")] == 8)
    note, full = row[head.index("Note")], row[head.index("Full text")]
    assert note.endswith(crs_one.CUT_MARK) and len(note) <= crs_one.CELL_LIMIT
    assert "note: 8 points on this field" in full and full.count("Also:") == 7
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


def test_a_paper_with_no_review_but_an_engineers_own_point_gets_its_file():
    doc = _submittal()
    client = _client(doc)
    added = client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Add the tag plate", "page": 1},
    )
    assert added.status_code == 200, added.text
    got = client.get(f"/api/reviews/papers/{doc}/crs")
    assert got.status_code == 200 and got.content[:2] == b"PK"
    _head, rows = rows_after(sheet(got.content, crs_one.EVIDENCE_SHEET), "No")
    assert len(rows) == 1 and "Add the tag plate" in str(rows[0])


def test_a_paper_with_only_a_running_review_is_not_reviewed_yet():
    doc = _submittal()
    ai_run(doc, [mk("R-1", "Fail", "Fail")], status="running")
    assert _client(doc).get(f"/api/reviews/papers/{doc}/crs").status_code == 409


# ------------------------------------------------------------------------------------------------ 4. the review status is true


def test_the_documents_api_says_the_same_review_status_on_the_list_and_on_its_own_route():
    rc_only = _submittal()
    ai_only = _submittal("doc_ai", "ai.pdf")
    neither = _submittal("doc_none", "none.pdf")
    _run(rc_only)
    ai_run(ai_only, [mk("R-1", "Fail", "Fail")])
    client = _client(rc_only, ai_only, neither)
    want = {rc_only: "completed", ai_only: "completed", neither: "not_reviewed"}
    single = {
        d: client.get(f"/api/documents/{d}").json()["review_status"] for d in want
    }
    listed = {d["id"]: d["review_status"] for d in client.get("/api/documents").json()}
    assert single == want and listed == want


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


def test_a_document_number_the_classifier_only_suggested_is_not_the_file_name():
    doc, rc, ai, client = world_with_both()
    _set_number(doc, "XX-0001")
    evidence = '{"document_number": {"value": "XX-0001", "method": "label"}}'
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET field_evidence = ?, confirmed_at = NULL"
            " WHERE document_id = ?",
            (evidence, doc),
        )
    team = f"/api/reviews/papers/{doc}/crs?copy=team"
    assert _name_of(client.get(team)) == "crs-team-drum.xlsx"
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET confirmed_at = '2026-11-17'"
            " WHERE document_id = ?",
            (doc,),
        )
    assert _name_of(client.get(team)) == "crs-team-XX-0001.xlsx"


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


# ------------------------------------------------------------------------------------------------ review R5: two readers, code proof


def two_reader_line(field: str, quote: str, **kw) -> dict:
    """An invented two-reader "not stated" line (both readers, the code's own search of every page) whose first reader also quoted
    words that code found on the page."""
    from app import agent_review_two_reader as two
    from app import agent_review_verdict as v

    base = {
        "reason_code": "absent", "paper_quote": quote, "field": field, "field_roles": [field.lower().replace(" ", "_")],
        "pages_searched": [1, 2], "tier": sorted(v.USABLE_TIERS)[0], "why": "the paper is silent",
        "quotes_checked": {"paper": True, "clause": True, "clause_strong": True},
    }  # fmt: skip
    rec = {
        "verdict": two.A_NOT_STATED, "quotes_checked": {"clause": True, "clause_strong": True},
        "code_search": {"proven": True, "pages_checked": 2}, "pages_total": 2, "first_pages": [1, 2], "second_pages": [1, 2],
        "model": "zeta-other", "code_check": two.CHECK_SEARCHED,
    }  # fmt: skip
    return mk(
        "R-5",
        "Query",
        "Fail",
        paper_kind="datasheet",
        **{**base, two.ABSENCE_FIELD: rec, **kw},
    )


def test_two_readers_not_stated_against_a_quote_that_may_state_it_is_a_question_in_every_cell():
    line = two_reader_line("Body material", "Carbon steel")
    point = review_points.ai_point(line, CTX)
    want = crs_ai_actions.silent_row_words("Body material", "Carbon steel")
    assert point["rank"] == 4 and wb.status_of(line)[0] == crs_ai_words.STATUS_QUERY
    assert point["action"] == want.action and crs_one.reason_of(point) == want.reason
    assert crs_one.paper_shows(point) == want.note
    cell = wb.layout_comment(line, *wb.status_of(line))
    for gone in (
        "found no value",
        "Contractor to state",
        "Contractor to confirm",
        "did not find",
    ):
        assert gone not in cell, gone
    assert cell.split("\n")[2] == want.action


def test_two_readers_not_stated_on_the_fields_own_label_keeps_the_verdict_and_says_so_in_every_cell():
    line = two_reader_line("Body material", "Body material")
    point = review_points.ai_point(line, CTX)
    assert point["rank"] == 2
    assert crs_one.reason_of(point) == crs_ai_actions.AGREED_NOT_STATED_REASON
    assert (
        point["action"]
        == "Contractor to state Body material, or the page where it is shown."
    )
    assert "not evidence of a value" in crs_one.paper_shows(point).lower()
    cell = wb.layout_comment(line, *wb.status_of(line))
    assert "two AI readers" in cell and cell.split("\n")[2] == point["action"]


def test_a_code_proved_absence_says_its_proof_and_never_uses_the_readers_quote_in_both_files():
    from app import agent_review_crs as arc
    from app import agent_review_verdict as v

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    line = mk(
        "R-5", "Fail", "Fail", paper_kind="datasheet", reason_code="absent", paper_quote="Carbon steel", field="Body material",
        field_roles=["body_material"], pages_searched=[1, 2], decided_by=v.BY_ABSENCE, compare=None, why="the paper is silent",
    )  # fmt: skip
    assert crs_ai_actions.silent_row(line) is None
    assert "Engineer to check" not in arc.company_comment(line)
    ai_run(doc, [line])
    client = _client(doc, "doc_std")
    point = next(x for x in points_of(client, doc)["points"] if x["rank"] == 1)
    assert decide(client, doc, point["id"], "keep").status_code == 200
    team = crs_completeness.file_or_refuse(doc, scope_all(), "team")
    head, rows = rows_after(sheet(team, crs_one.EVIDENCE_SHEET), "No")
    row = next(r for r in rows if r[head.index("Pill")] == point["pill"])
    proof = "code searched every page for Body material and found no value (pages searched: 1, 2)"
    assert row[head.index("Reason")] == proof
    assert row[head.index("What the paper shows")] == f"C{proof[1:]}."
    assert row[head.index("What the contractor must do")].startswith(
        "Contractor to revise Body material"
    )
    assert "Carbon steel" not in " ".join(
        str(c) for c in row if c
    ) and "Engineer to check" not in str(row)
    contractor = crs_completeness.file_or_refuse(doc, scope_all(), "contractor")
    _h, crows = rows_after(sheet(contractor), "Item No")
    text = " ".join(str(c) for r in crows for c in r if c)
    assert len(crows) == 1 and "Contractor to revise Body material" in text
    assert (
        "Carbon steel" not in text
        and "Engineer to check" not in text
        and "reader" not in text
    )


def test_a_contractor_copy_never_carries_the_engineers_words_on_a_quote_that_may_state_it():
    from app import agent_review_crs as arc

    line = silent_line(
        "absent",
        opinion=False,
        paper_quote="Carbon steel",
        field="Body material",
        field_roles=["body_material"],
    )
    assert crs_ai_actions.silent_quote(line) == crs_ai_actions.CONTRADICTS
    said = arc.company_comment(line, contractor=True)
    assert (
        "Engineer" not in said and "reader" not in said and "Carbon steel" not in said
    )
    assert "Engineer to check" in arc.company_comment(line)


def test_every_part_of_the_older_sheet_cell_of_a_silent_row_comes_from_the_one_function():
    line = silent_line(
        "absent",
        opinion=False,
        paper_quote="Carbon steel",
        field="Body material",
        field_roles=["body_material"],
    )
    part1, part2, part3 = wb.layout_comment(line, *wb.status_of(line)).split("\n")[:3]
    want = crs_ai_actions.silent_row(line, where=", page 2")
    assert "Contractor" not in part1
    # FTU-16: the one cell of the older sheet is the function's own `cell` (the reason said once, with the quote)
    assert part2.startswith(want.cell) and "did not find" not in part2
    assert part2.lower().count("the reader says") == 1
    assert part3 == crs_ai_actions.silent_row(line).action


def test_a_code_proved_absence_with_no_readers_quote_shows_its_proof_in_the_team_file():
    from app import agent_review_verdict as v

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    line = mk(
        "R-5", "Fail", "Fail", paper_kind="datasheet", reason_code="absent", paper_quote=None, field="Body material",
        field_roles=["body_material"], pages_searched=[1, 2], decided_by=v.BY_ABSENCE, compare=None, why="the paper is silent",
        quotes_checked={"paper": False, "clause": True},
    )  # fmt: skip
    ai_run(doc, [line])
    client = _client(doc, "doc_std")
    point = next(x for x in points_of(client, doc)["points"] if x["rank"] == 1)
    proof = "Code searched every page for Body material and found no value (pages searched: 1, 2)."
    assert point["paper_quote_note"] == proof  # the page
    team = crs_completeness.file_or_refuse(doc, scope_all(), "team")
    head, rows = rows_after(sheet(team, crs_one.EVIDENCE_SHEET), "No")
    row = next(r for r in rows if r[head.index("Pill")] == point["pill"])
    assert (
        row[head.index("What the paper shows")] == proof
    )  # the team file, the same words
