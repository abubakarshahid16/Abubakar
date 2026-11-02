"""#1649: with both switches on, a Word file never prints a reading part as a page, and a
held Word file gets an honest result. INVENTED documents only; no model: the writer of a
full-document answer and the picture engine are stubs."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    analysis,
    clause_review,
    comparison,
    conditions,
    crs_export,
    crs_mapping,
    datasheet_checks,
    db,
    fts_index,
    impossible_sign,
    procedure_text,
    reading_state,
    reports,
    review_audit,
    spec_kit,
    states,
    submittal_review,
    synthesis,
    transmittal_kit,
    word_pages,
)
from app import main as main_mod
from app.config import settings
from tests import test_reading_state as rs
from tests import test_word_pages_playbook as pb
from tests.fake_tokenizer import install_if_missing

PAGE_WORDS = re.compile(r"\b(?:pages? \d|pp?\.\s?\d|pg\.? ?\d)", re.IGNORECASE)
LONG = "shall be hydrostatically tested at one and a half times the design pressure"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "ready.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    monkeypatch.setattr(settings, "procedure_playbook_rows_enabled", True)
    install_if_missing(monkeypatch)
    word_pages._CACHE.clear()
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    submittal_review.ensure_schema()
    yield
    word_pages._CACHE.clear()
    db.reset_connection()


def _none(tmp_path) -> str:
    return pb._word_doc(tmp_path, "none", marks=False, saved_pages=None)


def _real(tmp_path) -> str:
    return pb._word_doc(
        tmp_path, "real", marks=True, saved_pages=len(pb.HAZOP_SECTIONS) + 1
    )


def _home_sentences() -> dict[str, str]:
    """What each home really writes, from its own code where it can be called alone."""
    pages = [(12, f"The vessel {LONG}.")]
    fact = {
        "field_name": "design_pressure",
        "field_label": "Design pressure",
        "field_value": "10",
        "raw_value": "10",
        "unit": "barg",
        "page": 12,
    }
    item = {
        "id": "hydrotest",
        "topic": "Hydrotest",
        "terms": [["hydrostatically", "tested"]],
        "held": None,
    }
    found = procedure_text.verdict({"source_text": f"Each vessel {LONG}."}, pages)
    return {
        "procedure_text": found["rationale"],
        "spec_kit": spec_kit.item_row(item, pages)["finding"],
        "transmittal_kit": transmittal_kit.header_rows(
            [(12, "Transmittal no:\n\nnothing")]
        )[0]["finding"].replace("no such label found", "the label is on page 12 with no value"),
        "comparison": comparison.qualify_by_pages(
            {"status": "MISSING_INFORMATION", "rationale": "x"},
            {
                "pages_total": 25,
                "fact_pages": [1, 2, 3, 7],
                "pages_not_read_into_fields": [12],
            },
        )["rationale"],
        "datasheet_checks": datasheet_checks._quoted(fact, "design_pressure"),
        "conditions": conditions._where(fact),
        "applicability": "the datasheet states API 610 as its code (page 12); it is a code",
        "clause_review": clause_review._row_text(
            "unverified", 12, None, {"requirement_text": "x", "clause": "1"}
        )[0],
        "impossible_sign": impossible_sign._why(fact, "design_pressure"),
    }


@pytest.mark.parametrize(
    "home",
    [
        "procedure_text",
        "spec_kit",
        "transmittal_kit",
        "comparison",
        "datasheet_checks",
        "conditions",
        "applicability",
        "clause_review",
        "impossible_sign",
    ],
)
def test_every_home_says_no_number_for_a_file_with_no_page_marks(tmp_path, home):
    doc = _none(tmp_path)
    sentence = _home_sentences()[home]
    # The case is real: the home does write a number here.
    assert PAGE_WORDS.search(sentence), sentence
    shown = word_pages.no_false_pages(sentence, doc)
    unquoted = re.sub(r'"[^"]*"', "", shown)
    assert not PAGE_WORDS.search(unquoted), shown


def test_a_number_on_a_part_that_exists_becomes_its_section(tmp_path):
    doc = _none(tmp_path)
    shown = word_pages.no_false_pages("found on page 1: engineer to confirm", doc)
    assert shown.startswith('found in section "')


@pytest.mark.parametrize(
    "said, kept",
    [
        ('the sheet says "see page 12 for details" here', '"see page 12 for details"'),
        ("SAES-L-100 cl. 4.2 (p.12) applies", "cl. 4.2 (p.12)"),
        ("per clause 4.2 page 12: the text", "clause 4.2 page 12"),
        ("read at page 12 of SAES-L-100", "page 12 of SAES-L-100"),
    ],
)
def test_a_quote_or_another_documents_page_stays(tmp_path, said, kept):
    assert kept in word_pages.no_false_pages(said, _none(tmp_path))


def test_another_documents_page_written_by_its_home_stays(tmp_path):
    doc = _none(tmp_path)
    said = f"the datasheet says 10 ({word_pages.other_document_page(5)}); resolve"
    assert word_pages.no_false_pages(said, doc) == said
    assert "page 5 of that document" in said


@pytest.mark.parametrize(
    "said",
    ["pages 1-3, 7 were not read", "Page 12", "pp. 3-4", "p.12", "pg 12", "(page 99)"],
)
def test_each_way_of_writing_a_page_goes(tmp_path, said):
    shown = word_pages.no_false_pages(said, _none(tmp_path))
    assert not PAGE_WORDS.search(shown), shown
    assert word_pages.NO_PAGE_SHORT in shown or "section" in shown


def test_real_marks_and_a_pdf_keep_their_pages(tmp_path):
    said = "found on page 1: engineer to confirm"
    assert word_pages.no_false_pages(said, _real(tmp_path)) == said
    assert word_pages.no_false_pages(said, "no-such-document") == said


def test_switch_off_nothing_changes(tmp_path, monkeypatch):
    doc = _none(tmp_path)
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    said = "found on page 1: x"
    assert word_pages.no_false_pages(said, doc) == said
    assert word_pages.other_document_page(5) == "page 5"
    finding = {"document_id": doc, "finding": said, "contractor_page": 1}
    assert word_pages.finding_for_reader(finding) is finding
    rows = [{"comment": said}]
    assert crs_mapping.for_reader(rows, {"submittal_document_id": doc})[0] == [
        {"comment": said}
    ]


def _stale(tmp_path) -> str:
    """A file with marks, stored as another cut: what a read before the switch leaves."""
    doc = _real(tmp_path)
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = 'another cut of the file', char_count = 23"
            " WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    return doc


def test_a_picture_read_later_does_not_look_like_another_cut(tmp_path):
    """A reading stored or lost after the read changes no page's own words."""
    doc = _real(tmp_path)
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = text || ' text from a picture', char_count = char_count + 21"
            " WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    assert word_pages.page_source(doc) != word_pages.PAGES_STALE


def test_a_different_count_of_pages_is_another_cut(tmp_path):
    doc = _real(tmp_path)
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ? AND page_no = 2", (doc,))
    assert word_pages.page_source(doc) == word_pages.PAGES_STALE


def test_a_file_read_before_the_switch_prints_no_page(tmp_path):
    doc = _stale(tmp_path)
    assert word_pages.page_source(doc) == word_pages.PAGES_STALE
    assert word_pages.unit(doc) == "part"
    assert word_pages.no_false_pages("found on page 1: x", doc) == (
        f"found in a part with {word_pages.NO_PAGE_SHORT}: x"
    )
    cell = word_pages.page_cell("p.1", [1], [{"document_id": doc}])
    assert not PAGE_WORDS.search(cell)
    assert word_pages.READ_BEFORE_MARKS in cell
    assert word_pages.read_proof(doc)["pages"] is None


def test_a_word_file_that_cannot_be_opened_prints_no_page(tmp_path):
    doc = _real(tmp_path)
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET stored_path = ? WHERE id = ?",
            (str(tmp_path / "gone.docx"), doc),
        )
    assert word_pages.numbers_are_not_pages(doc)
    assert word_pages.page_cell("p.1", [1], [{"document_id": doc}]) == (
        word_pages.NO_PAGE_UNREADABLE
    )
    assert not PAGE_WORDS.search(word_pages.no_false_pages("(page 1)", doc))


def _run_with_finding(doc: str, words: str) -> str:
    run = submittal_review.create_review_run(
        submittal_document_id=doc, allowed_document_ids=frozenset({doc})
    )
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO review_findings
               (id, document_id, review_run_id, compliance_status, category, severity,
                requirement, finding, required_action, governing_sources,
                unresolved_evidence, citation_ids, status, approval_status,
                contractor_page, ai_rationale, created_at, updated_at, origin)
               VALUES ('f1', ?, ?, 'NEEDS_ENGINEER_REVIEW', 'technical_query', 'minor',
                       'The vessel is tested.', ?, 'Engineer to check', '[]', '[]', '[]',
                       'open', 'pending', 1, ?, ?, ?, ?)""",
            (doc, run, words, words, pb.NOW, pb.NOW, clause_review.ORIGIN),
        )
    return run


def test_the_crs_as_drawn_has_no_false_page_in_cells_or_comments(tmp_path):
    """Through the real composition, on the stored words of an older run."""
    doc = _none(tmp_path)
    run = _run_with_finding(doc, "Found on page 1: value (page 1); see pages 1-3.")
    rows, meta, _name, _stamp = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    # The composition keeps the stored words: numbering compares them.
    mine = next(r for r in rows if r.get("finding_id") == "f1")
    assert PAGE_WORDS.search(mine["ai_review_comment"])
    meta["review_notes"].append(
        {"note": "n", "standard": "", "count": 1, "detail": "pages 1-3 not read"}
    )
    meta["unchecked_parts"] = ["page 2 was not read"]
    meta["run_status_note"] = "page 2 was not read"
    rows, meta = crs_mapping.for_reader(rows, meta)
    for row in rows:
        for key in ("comment", "ai_review_comment", "reasoning", "page_section"):
            assert not PAGE_WORDS.search(str(row.get(key) or "")), (key, row[key])
    assert not PAGE_WORDS.search(meta["review_notes"][-1]["detail"])
    assert not PAGE_WORDS.search(meta["unchecked_parts"][0])
    assert not PAGE_WORDS.search(meta["run_status_note"])
    view = crs_export.build_crs_view(rows, meta)
    cells = [r.get("page_section") or "" for r in view["rows"]]
    assert cells and not any(PAGE_WORDS.search(c) for c in cells)


def test_the_export_routes_draw_the_safe_rows(tmp_path):
    doc = _none(tmp_path)
    run = _run_with_finding(doc, "Found on page 1: value")
    scope = access.unrestricted_scope()
    workbook, _name = main_mod._crs_workbook(run, scope, "internal")
    from io import BytesIO

    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(workbook)).worksheets[0]
    text = " ".join(str(c.value) for r in sheet.iter_rows() for c in r if c.value)
    assert "Found on page 1" not in text
    assert "Found in section" in text


def test_an_engineers_own_words_are_not_changed_but_the_page_cell_is(tmp_path):
    doc = _none(tmp_path)
    rows = [
        {
            "comment": "I saw it on page 3",
            "page_section": "p.3",
            "engineer_worded": True,
        }
    ]
    out = word_pages.crs_rows_for_reader(rows, doc)
    assert out[0]["comment"] == "I saw it on page 3"
    assert not PAGE_WORDS.search(out[0]["page_section"])


def test_the_findings_screen_has_no_false_page_and_stored_words_stay(tmp_path):
    doc = _none(tmp_path)
    run = _run_with_finding(doc, "Found on page 1: value")
    shown = TestClient(main_mod.app).get(
        "/api/reviews/findings", params={"review_run_id": run}
    )
    assert shown.status_code == 200
    got = shown.json()["findings"][0]
    assert got["contractor_page"] is None
    for key in ("finding", "ai_rationale"):
        assert not PAGE_WORDS.search(got[key]), got[key]
    stored = db.connect().execute(
        "SELECT finding, contractor_page FROM review_findings WHERE review_run_id = ?",
        (run,),
    )
    row = stored.fetchone()
    assert "page 1" in row["finding"] and row["contractor_page"] == 1


def test_the_evidence_report_cites_a_word_passage_by_its_locator(monkeypatch):
    passage = {
        "filename": "a.docx",
        "page_start": 7,
        "page_end": 7,
        "locator": "4.2 > para 3",
        "text": "x",
    }
    assert "page 7" not in reports._passage_html(passage, 1)
    assert "4.2 &gt; para 3" in reports._passage_html(passage, 1)
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    assert "page 7" in reports._passage_html(passage, 1)


def test_the_audit_names_no_part_as_a_page():
    pages = {"word_read": {"page_source": word_pages.PAGES_NONE}}
    assert "12" not in review_audit._page_of({"page": 12}, pages)
    assert review_audit._page_of({"page": 12}, {}) == "page 12"


# What was read, Ready, and a held file's answer.


def test_a_part_is_not_named_as_a_page_in_the_reading_line():
    got = reading_state.assess(
        2,
        [rs._row(1), rs._row(2, native_status="not_extracted")],
        [],
        0,
        True,
        page_unit=reading_state.UNIT_PART,
        page_source="none",
    )
    assert got["unaccounted"] == 1
    assert "reading parts" in got["line"]
    assert not PAGE_WORDS.search(got["line"]), got["line"]


def test_a_stale_files_line_says_why_it_has_no_pages():
    got = reading_state.assess(
        1,
        [rs._row(1)],
        [],
        0,
        True,
        page_unit=reading_state.UNIT_PART,
        page_source=word_pages.PAGES_STALE,
    )
    assert "read before its page marks" in got["line"]


def test_every_picture_answered_is_ready_and_says_what_was_not_read(
    tmp_path, monkeypatch
):
    """Both switches on: one picture with text, one with none. Listed, so Ready."""
    rs._stub(monkeypatch, {1: "text on the picture", 2: ""})
    doc = rs._ingest(rs._word_file(tmp_path, pictures=2))
    assert rs._finish(monkeypatch, doc) == states.READY
    said = reading_state.report(doc)
    assert said["ready"] and not said["fully_read"]
    assert (said["pictures_read"], said["pictures_total"]) == (1, 2)
    assert "1 of 2 pictures" in said["line"]
    assert any(i["kind"] == "picture" for i in said["not_read"])


def _two_documents(tmp_path, monkeypatch) -> tuple[str, str]:
    """A held Word file (its picture has no answer) and a ready one."""
    held = rs._held(tmp_path, monkeypatch)
    other = rs._ingest(rs._word_file(tmp_path, pictures=0, name="o.docx"), "other")
    assert rs._finish(monkeypatch, other) == states.READY
    return held, other


def _answer(ids, writes):
    def writer(system, prompt):
        writes.append(prompt)
        return synthesis.Generation("x", truncated=False, model="stub")

    return analysis.collection_summary(
        "Summarize these 2 documents in 100 words.",
        frozenset(ids),
        allowed_document_ids=frozenset(ids),
        generate=writer,
    )


def test_a_held_word_file_says_the_plain_reason_and_the_way_forward(
    tmp_path, monkeypatch
):
    held = rs._held(tmp_path, monkeypatch)
    line = reading_state.stored(held)["line"]
    assert reading_state.WHY_NO_ANSWER in line
    assert reading_state.WAY_FORWARD_REREAD in line


def test_a_held_word_file_goes_ahead_on_its_text_and_says_so(tmp_path, monkeypatch):
    held, other = _two_documents(tmp_path, monkeypatch)
    captured = {}

    def fake(_fn, _question, evidence, _writer, **_kw):
        captured["evidence"] = evidence
        return SimpleNamespace(text="word " * 100, refusal=None, dropped_sentences=())

    monkeypatch.setattr(analysis, "_generate_or_refuse", fake)
    monkeypatch.setattr(
        synthesis,
        "original_citations",
        lambda summary, ledger: (
            summary,
            [
                {**item, "document_id": d, "chunk_id": item["chunk_id"]}
                for d in (held, other)
                for item in [next(iter(ledger.values()))]
            ],
        ),
    )
    got = _answer([held, other], [])
    assert got["answer_type"] == "generated"
    notice = got["notices"][0]
    assert "not fully accounted for" in notice
    assert "covers its text only" in notice
    assert reading_state.WAY_FORWARD_REREAD in notice
    by_id = {d["document_id"]: d for d in got["summary_coverage"]["documents"]}
    assert by_id[held]["read_in_part"]
    assert "read_in_part" not in by_id[other]


def test_switch_off_a_held_status_is_refused_as_on_main(tmp_path, monkeypatch):
    held, other = _two_documents(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.text_only_answer(held, states.PARTIALLY_SEARCHABLE) is None
    got = _answer([held, other], [])
    assert got["answer_type"] == "insufficient_evidence"


def test_a_held_file_with_an_unread_page_is_still_refused_with_its_reason(
    tmp_path, monkeypatch
):
    held = rs._held(tmp_path, monkeypatch)
    saved = reading_state.stored(held)
    saved["unaccounted_list"].append({"kind": "page", "page": 1, "reason": "x"})
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_reading SET summary = ? WHERE document_id = ?",
            (json.dumps(saved), held),
        )
    assert reading_state.text_only_answer(held, states.PARTIALLY_SEARCHABLE) is None
    other = rs._ingest(rs._word_file(tmp_path, pictures=0, name="o.docx"), "other")
    assert rs._finish(monkeypatch, other) == states.READY
    got = _answer([held, other], [])
    assert got["answer_type"] == "insufficient_evidence"
    assert "not fully accounted for" in got["reason"]


def test_a_held_pdf_is_not_given_a_text_only_answer(tmp_path, monkeypatch):
    held = rs._held(tmp_path, monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET stored_path = ? WHERE id = ?",
            (str(tmp_path / "a.pdf"), held),
        )
    assert reading_state.text_only_answer(held, states.PARTIALLY_SEARCHABLE) is None

