"""#844: on the LOCAL model the AI engineering check asks one datasheet page
per call.

F1 for #842 (copies of three real sheets): the whole-sheet packet was 30,000
to 60,000 characters - far past the local model's context window - and all
three runs timed out with nothing. Planner decision: a smaller packet, not a
longer limit. So, for the local engine only: one page per call, sizes capped,
items merged in code through the same gate, and a page whose call times out
is counted and named on the run - never asked again. The Claude lane keeps
its one whole-sheet call.

The local transport is a fake: no socket. Synthetic sheet only.
"""
from __future__ import annotations

import json

import pytest

from app import ai_engineering_check as aic
from app import comparison, datasheets, review_jobs
from app import reasoning_provider as rp
from app.config import settings
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import ASKS_A_BLANK, BLANK_FIELD, GOOD, Fake, _ai_rows, _blank_fields  # noqa: F401
from tests.test_review_ai_check import _local, _resolver  # noqa: F401

#: A question about page 2's blank field (the prose note page of the synthetic sheet).
NOTE_FIELD = "Inspection hold points"
BLANKS = {1: [BLANK_FIELD], 2: [NOTE_FIELD]}
GOOD_1 = ASKS_A_BLANK
NOTE_ITEM = {"topic": "Inspection", "page": 2, "field": NOTE_FIELD, "value": "",
             "observation": "The inspection hold points are not stated in the note.",
             "action": "Contractor to confirm the inspection hold points.",
             "relates_to": "API 610", "clause": None, "confidence": "low"}


class PageTransport:
    """The local model's transport, answering per page: `answers[page]` is a
    list of items, or an exception to raise. Records every body sent."""

    def __init__(self, answers):
        self.answers, self.bodies = answers, []

    def page_of(self, body) -> int:
        return int(body["prompt"].split("THIS CALL IS ABOUT PAGE ")[1].split(" ")[0])

    def __call__(self, path, body, timeout):
        self.bodies.append(body)
        answer = self.answers[self.page_of(body)]
        if isinstance(answer, Exception):
            raise answer
        return {"response": json.dumps({"items": answer}), "model": "local-test:1b",
                "done_reason": "stop"}


def _sheet_and_run(tmp_path):
    sub = _sheet(tmp_path, notes_page=True, extra_pages=1)
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert [p for p, t in aic.datasheet_pages(sub).items() if t.strip()] == [1, 2]
    return sub, run, scope


@pytest.fixture
def two_pages(tmp_path, monkeypatch):
    """Page 1 ruled fields, page 2 a prose note the readers took one value
    from, page 3 blank (never asked)."""
    world = _sheet_and_run(tmp_path)
    read = aic.datasheet_fields
    monkeypatch.setattr(aic, "datasheet_fields", lambda sub: read(sub) + [
        {"field": "Notes", "value": "subject to inspection", "unit": None, "page": 2}])
    return world


@pytest.fixture
def note_page_without_a_value(tmp_path):
    """The same sheet as the readers really leave it: no value from page 2."""
    world = _sheet_and_run(tmp_path)
    assert {f["page"] for f in aic.datasheet_fields(world[0]) if f["value"]} == {1}
    return world


def test_each_page_is_asked_in_a_call_of_its_own_and_the_items_are_merged(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    transport = PageTransport({1: [GOOD_1], 2: [NOTE_ITEM]})
    _local(monkeypatch, transport, BLANKS)
    review_jobs._ai_check(run, scope, ["API 610"])
    assert [transport.page_of(b) for b in transport.bodies] == [1, 2]
    first, second = (b["prompt"] for b in transport.bodies)
    assert "--- page 1 ---" in first and "--- page 2 ---" not in first
    assert "--- page 2 ---" in second and "--- page 1 ---" not in second
    assert f"| {BLANK_FIELD} |" in first and f"| {BLANK_FIELD} |" not in second     # a page's own blank fields
    assert "| Design pressure |" not in first                                   # a field with a value is not listed
    assert all(b["options"]["num_predict"] == aic.LOCAL_PAGE_OUTPUT_TOKENS for b in transport.bodies)
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is True and status["calls_made"] == 2
    assert (status["proposed_items"], status["kept_items"]) == (2, 2)
    assert status["local_pages"] == {"pages": 2, "done": [1, 2], "timed_out": [], "failed": [],
                                     "not_tried": [], "no_value_read": [], "no_blank_field": []}
    assert status["local_scope"] == "local model: questions about blank fields only"
    assert status["plain"].endswith("Scope on this run - local model: questions about blank fields only.")
    assert sorted(r["contractor_page"] for r in _ai_rows(run)) == [1, 2]


def test_a_page_that_times_out_is_named_and_not_asked_again(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    transport = PageTransport({1: TimeoutError("slow"), 2: [NOTE_ITEM]})
    _local(monkeypatch, transport, BLANKS)
    monkeypatch.setattr(settings, "review_ai_check_local_timeout_s", 300.0)
    review_jobs._ai_check(run, scope, ["API 610"])
    assert [transport.page_of(b) for b in transport.bodies] == [1, 2]         # no second try of page 1
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is False and status["kept_items"] == 1
    assert status["reason"] == ("1 of 2 page(s) were not checked on the local model: "
                                "1 timed out after 300 s (page 1)")
    assert status["local_pages"]["done"] == [2] and status["local_pages"]["timed_out"] == [1]
    assert "incomplete" in status["plain"] and "1 of 2 page(s)" in status["plain"]
    assert [r["contractor_page"] for r in _ai_rows(run)] == [2]


def test_pages_left_when_the_runs_time_is_spent_are_named_and_never_asked(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    transport = PageTransport({1: [GOOD_1], 2: [NOTE_ITEM]})
    _local(monkeypatch, transport, BLANKS)
    monkeypatch.setattr(settings, "review_ai_check_local_max_seconds", 0.0)
    review_jobs._ai_check(run, scope, [])
    assert transport.bodies == []
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is False and status["calls_made"] == 0
    assert status["reason"] == ("2 of 2 page(s) were not checked on the local model: "
                                "2 not asked because the run's time was spent (page 1, 2)")


def test_an_item_about_another_page_than_the_one_asked_is_refused(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    transport = PageTransport({1: [GOOD_1, NOTE_ITEM], 2: []})                  # page 1's call answers about page 2
    _local(monkeypatch, transport, BLANKS)
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["rejected"] == {"page_not_the_one_asked": 1} and status["kept_items"] == 1
    assert [r["contractor_page"] for r in _ai_rows(run)] == [1]


def test_a_call_keeps_at_most_the_few_items_it_asked_for(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    many = [dict(GOOD_1, topic=f"Hydrotest pressure {n}") for n in range(aic.LOCAL_ITEMS_PER_PAGE + 4)]
    _local(monkeypatch, PageTransport({1: many, 2: []}), BLANKS)
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["proposed_items"] == aic.LOCAL_ITEMS_PER_PAGE == status["requested_items"]


def test_a_page_the_readers_took_no_value_from_is_not_asked_and_is_named(
        note_page_without_a_value, monkeypatch):
    """Planner decision on #846: a title page, a contents page, a sketch page
    carry no value. On three real sheets they cost 9 of 22 calls and gave 18
    of 49 drafts, 13 of them noise."""
    _sub, run, scope = note_page_without_a_value
    transport = PageTransport({1: [GOOD_1], 2: [NOTE_ITEM]})
    _local(monkeypatch, transport, {1: [BLANK_FIELD]})
    review_jobs._ai_check(run, scope, ["API 610"])
    assert [transport.page_of(b) for b in transport.bodies] == [1]
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is True and status["calls_made"] == 1
    assert status["local_pages"]["pages"] == 1 and status["local_pages"]["no_value_read"] == [2]
    assert [r["contractor_page"] for r in _ai_rows(run)] == [1]


def test_a_page_with_values_but_nothing_blank_is_not_asked_and_is_named(two_pages, monkeypatch):
    """The local scope: a page with nothing blank has nothing to ask."""
    _sub, run, scope = two_pages
    transport = PageTransport({1: [GOOD_1], 2: [NOTE_ITEM]})
    _local(monkeypatch, transport, {1: [BLANK_FIELD]})          # page 2 has a value and no blank field
    review_jobs._ai_check(run, scope, ["API 610"])
    assert [transport.page_of(b) for b in transport.bodies] == [1]
    pages = aic.ai_check_status(run, allowed_document_ids=scope)["local_pages"]
    assert pages["no_blank_field"] == [2] and pages["no_value_read"] == [] and pages["done"] == [1]


def test_on_the_local_model_a_draft_about_a_field_that_has_a_value_is_refused(two_pages, monkeypatch):
    """THE RULE THAT MEETS THE BAR (planner, 12 Oct). With the full scope the
    4B model called normal values "unusual" or "impossible": about 30 of 49
    drafts on three real sheets were wrong or noise. A local draft must name
    a field the code readers read as blank on that page - proved against the
    stored facts, not the model's word."""
    _sub, run, scope = two_pages
    opinion = dict(GOOD, observation="The design pressure of 23.5 barg is unusual for this service.",
                   action="Contractor to confirm the design pressure.")       # field: Design pressure, has a value
    elsewhere = dict(GOOD_1, field=NOTE_FIELD)                                # blank, but on page 2
    _local(monkeypatch, PageTransport({1: [opinion, GOOD_1, elsewhere], 2: []}), BLANKS)
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["rejected"] == {"not_a_blank_field_question": 2} and status["kept_items"] == 1
    assert [r["contractor_section"] for r in _ai_rows(run)] == [BLANK_FIELD]


@pytest.mark.parametrize("field, names_it", [
    ("Hydrotest pressure", True),
    ("HYDROTEST PRESSURE:", True),
    ("Hydrotest pressure (6.3.6)", True),            # the model kept a clause reference
    ("Hydrotest", False),                            # one shared word is not the field
    ("Pressure", False),
    ("Design pressure", False),
    ("", False),
])
def test_naming_a_blank_field_is_the_whole_name(field, names_it):
    assert aic._names_one_of(field, [{"field": "Hydrotest pressure"}]) is names_it


def test_the_cloud_path_keeps_the_full_scope(two_pages, monkeypatch):
    """Not narrowed: a draft about a field that has a value is kept there."""
    _sub, run, scope = two_pages
    _blank_fields(monkeypatch, BLANKS)
    fake = Fake(items=[GOOD])                                                 # field: Design pressure, has a value
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: fake)
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["kept_items"] == 1 and status["rejected"] == {}
    assert status["local_scope"] is None and "Scope on this run" not in status["plain"]
    assert "Design pressure" in fake.packets[0].prompt and "FIELDS LEFT BLANK" not in fake.packets[0].prompt


@pytest.mark.parametrize("field, value", [
    ("Rev. 00", "Rev. 00"),
    ("Revision", "B"),
    ("Contract No: AB123CD45", "AB123CD45"),
    ("Document No.", "SYN-0001"),
    ("DRAWING NO", ""),
    ("REV NO", ""),
    ("Sheet title", "Mechanical datasheet"),
    ("Date", "11/00"),
    ("Checked by", "A.B."),
    ("Process and mechanical data - Sht", "4 to 5"),
    ("Nozzle table Sht", "6"),
    ("MECHANICAL DATASHEET SYNTHETIC PLANT DRUMS (0000-00-V-0001)",
     "MECHANICAL DATASHEET SYNTHETIC PLANT DRUMS (0000-00-V-0001)"),
])
def test_a_draft_about_the_sheets_furniture_is_layout(field, value):
    assert aic.about_layout({"field": field, "value": value})


@pytest.mark.parametrize("field, value", [
    ("Design pressure", "23.5 barg"),
    ("Hydrotest date", ""),
    ("Tube sheet", "25 mm"),
    ("Revision of design code", "2019"),
    ("Sheet thickness", "6"),
    ("Notes", "All valves shall be stamped."),
    ("N7 Flange Rating", "CL-150"),
    ("Document control", "By vendor"),
])
def test_an_engineering_field_is_not_layout(field, value):
    assert not aic.about_layout({"field": field, "value": value})


def test_a_layout_draft_is_refused_under_its_own_reason_on_either_engine(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    revision = dict(GOOD_1, topic="Revision", field="Rev. 00", value="",
                    observation="The revision box is not filled in.",
                    action="Contractor to fill in the revision box.")
    _local(monkeypatch, PageTransport({1: [GOOD_1, revision], 2: []}), {1: [BLANK_FIELD, "Rev. 00"], 2: [NOTE_FIELD]})
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["rejected"] == {"layout_not_engineering": 1} and status["kept_items"] == 1
    # and through the cloud provider's path: the same gate
    fake = Fake(items=[GOOD, revision])
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: fake)
    review_jobs._ai_check(run, scope, ["API 610"])
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["rejected"] == {"layout_not_engineering": 1} and status["kept_items"] == 1


def test_the_local_packet_has_a_fixed_ceiling_whatever_the_sheet():
    fields = [{"page": 1, "field": f"Field {n}", "value": "1", "unit": "bar"} for n in range(500)]
    held = {f"STD-{n}": [f"{n}.{m}" for m in range(200)] for n in range(60)}
    prompt = aic.build_local_prompt(1, "word " * 20000, fields, [f"CITED-{n}" for n in range(80)], held)
    assert prompt.count("p1 | Field ") == aic.LOCAL_FIELDS_PER_PAGE
    assert prompt.count("- STD-") == aic.LOCAL_STANDARDS and prompt.count("- CITED-") == aic.LOCAL_STANDARDS
    assert "0.5" in prompt and f"0.{aic.LOCAL_CLAUSES_PER_STANDARD}" not in prompt   # clauses capped per standard
    assert len(prompt.split("--- page 1 ---")[1]) <= aic.LOCAL_PAGE_CHARS + 1
    assert len(prompt) < 9000                                    # about 2,300 tokens: inside a 4,096 window
    assert f"At most {aic.LOCAL_ITEMS_PER_PAGE} items" in prompt


def test_the_claude_lane_still_makes_one_whole_sheet_call(two_pages, monkeypatch):
    _sub, run, scope = two_pages
    fake = Fake()
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: fake)
    review_jobs._ai_check(run, scope, [])
    assert len(fake.packets) == 1
    prompt = fake.packets[0].prompt
    assert "--- page 1 ---" in prompt and "--- page 2 ---" in prompt and "THIS CALL IS ABOUT" not in prompt
    assert fake.packets[0].prompt_version == "review-ai-check-v2"
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["local_pages"] is None and status["requested_items"] == aic.MAX_ITEMS
