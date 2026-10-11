"""Owner order 2d: the AI engineering check (kind C) - drafts, never verdicts.

What these hold, each proved by a mutation (M1026-M1039):
  * the gate refuses, with a named reason, an item whose datasheet value is
    not on the page it cites, a number from memory, a clause it cannot
    verify, a quoted sentence not on the page, a pass/fail word, or a
    confidence above medium;
  * a kept item is stored pending, unconfirmed, with NO compliance status,
    and never moves the review code;
  * the flag is off by default, and off means nothing is sent;
  * on the CRS an unconfirmed item sits only in the last column "AI Review
    Comments" of the internal copy, never in COMPANY Comments and never in
    the "Issue to contractor" copy; an engineer's confirmation moves it to
    COMPANY Comments under their name; a rejected item is not on the sheet.

The model is a fake: no socket. Synthetic sheet only (tests/test_b3_page_ledger.py).
"""
from __future__ import annotations

import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import access, ai_engineering_check as aic, claude_spend, comparison, crs_export, db
from app import reasoning_provider as rp
from app import review_jobs
from app.config import Settings, settings
from app.main import app
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in

GOOD = {"topic": "Hydrotest pressure", "page": 1, "field": "Design pressure",
        "value": "23.5 barg",
        "observation": "The hydrotest pressure is not stated beside the design pressure of 23.5 barg.",
        "action": "Contractor to state the hydrotest pressure.",
        "relates_to": "API 610", "clause": None, "confidence": "medium"}
TEXT = "hydrotest pressure is not stated"


class Fake:
    """A provider answering with fixed items; records what it was sent."""

    def __init__(self, items=None, raises=None):
        self.items, self.raises, self.packets = items or [GOOD], raises, []

    def reason(self, packet):
        self.packets.append(packet)
        if self.raises:
            raise self.raises
        text = json.dumps({"items": self.items})
        return rp.Response(text=text, provider=rp.CLAUDE, model_tag="fake", digest="d",
                           finish_reason="stop", prompt_sha256=packet.sha256,
                           schema_errors=rp.schema_errors(text, packet.json_schema), cost_usd=0.0)


class SeqFake:
    """A provider answering a fixed TEXT + finish_reason per call, in order -
    for exercising the truncation/retry path, where each call in a run must
    answer something different from the last. Records every packet sent, so
    a test can inspect what the retry prompt actually asked for."""

    def __init__(self, replies):
        #: [(text, finish_reason), ...], one per expected call.
        self.replies = list(replies)
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        text, finish_reason = self.replies[len(self.packets) - 1]
        return rp.Response(text=text, provider=rp.CLAUDE, model_tag="fake", digest="d",
                           finish_reason=finish_reason, prompt_sha256=packet.sha256,
                           schema_errors=rp.schema_errors(text, packet.json_schema), cost_usd=0.01)


def _cut_off_after(items: list[dict]) -> str:
    """A reply that is valid JSON up to and including `items`, then cut off
    mid-way through one more object - exactly what `finish_reason: "length"`
    looks like on the wire."""
    body = '{"items": [' + ", ".join(json.dumps(i) for i in items)
    if items:
        body += ", "
    return body + '{"topic": "Cut off mid-object, never closes"'


@pytest.fixture(autouse=True)
def _resolver():
    yield
    access.set_user_resolver(None)


@pytest.fixture
def world(tmp_path):
    sub = _sheet(tmp_path, notes_page=False)
    from app import datasheets
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    return sub, run, scope


def _gate(world, **change):
    sub, run, _scope = world
    return aic.accept({**GOOD, **change}, aic.datasheet_pages(sub),
                      aic._held_standards(run), ["API 610"])


def _ai_rows(run):
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = ?", (run, aic.ORIGIN))]


# ------------------------------------------------------------------- gate

def test_a_true_item_passes_the_gate(world):
    assert _gate(world) == {"accepted": True, "reason": None, "item": {**GOOD}}


@pytest.mark.parametrize("change, reason", [
    ({"value": "25.0 barg"}, "value_not_on_page"),                                        # M1026
    ({"observation": "Typically 1.3 times the design pressure of 23.5 barg is used."},
     "number_not_on_page"),                                                               # M1027
    ({"clause": "6.3.1"}, "clause_not_verified"),                                         # M1028
    ({"observation": "Per clause 6.3.1 the hydrotest pressure should be stated."},
     "clause_not_verified"),                                                              # M1028
    ({"observation": 'The standard says "the hydrostatic test shall be witnessed by the purchaser".'},
     "quote_not_on_page"),                                                                # M1035
    ({"observation": "The design pressure of 23.5 barg complies with the service."},
     "pass_fail_word"),                                                                   # M1029
    ({"action": "Contractor to note the sheet is approved."}, "pass_fail_word"),
    ({"confidence": "high"}, "confidence_not_low_or_medium"),                              # M1030
    ({"page": 9}, "page_not_in_datasheet"),
    ({"relates_to": "Rule 1.5 margin",
      "observation": "Apply the Rule 1.5 margin to the design pressure of 23.5 barg."},
     "number_not_on_page"),                                                               # M1040
])
def test_the_gate_refuses_with_a_named_reason(world, change, reason):
    assert _gate(world, **change) == {"accepted": False, "reason": reason,
                                      "item": {**GOOD, **change}}


def test_a_clause_of_a_held_standard_that_was_read_may_be_cited(world):
    """The one way a clause number is allowed: the standard is held for this
    run and a requirement was read from it at that clause."""
    held = _gate(world, relates_to="std", clause="5.3.3",
                 observation="See clause 5.3.3 of std on the noise level; none is stated.")
    assert held["accepted"], held


# ------------------------------------------------------------------ the run

def test_kept_items_are_pending_drafts_that_never_move_the_code(world):
    sub, run, scope = world
    before = comparison.run_outcome(run, allowed_document_ids=scope)["recommended_code"]
    fake = Fake([GOOD, {**GOOD, "observation": "The design pressure complies."}])

    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"], provider=fake)

    assert (result["proposed"], result["kept"], result["rejected"]) == (2, 1, {"pass_fail_word": 1})
    assert fake.packets[0].step == aic.STEP, "the spend must be booked to review_ai_check"
    [row] = _ai_rows(run)
    assert (row["compliance_status"], row["confirmed_by"], row["approval_status"]) == (
        None, None, "pending")
    assert row["contractor_page"] == 1 and row["contractor_evidence_text"] == "23.5 barg"
    assert aic.LABEL in row["ai_rationale"] and "Relates to: API 610" in row["ai_rationale"]
    assert comparison.run_outcome(run, allowed_document_ids=scope)["recommended_code"] == before


def test_a_rerun_replaces_drafts_but_never_an_engineers_confirmation(world):
    """M1036: a confirmed item is an engineer's decision; a rerun keeps it."""
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    [first] = _ai_rows(run)
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET confirmed_by = 'eng-x' WHERE id = ?", (first["id"],))

    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())

    ids = {r["id"] for r in _ai_rows(run)}
    assert first["id"] in ids and len(ids) == 2


def test_the_flag_is_off_by_default_and_off_sends_nothing(world, monkeypatch):
    """M1033: off, a review never reaches the provider."""
    assert Settings.model_fields["review_ai_check_enabled"].default is False
    _sub, run, scope = world
    fake = Fake()
    # The Claude lane is ON here, so the flag alone is what must stop it.
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: fake)
    review_jobs._ai_check(run, scope, [])
    assert fake.packets == [] and _ai_rows(run) == []
    assert aic.available() == (False, "the AI engineering check is off (REVIEW_AI_CHECK_ENABLED)")


def test_on_the_review_job_drafts_after_the_comparison(world, monkeypatch):
    _sub, run, scope = world
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: Fake())
    review_jobs._ai_check(run, scope, ["API 610"])
    assert len(_ai_rows(run)) == 1


def test_a_budget_refusal_never_fails_the_review(world, monkeypatch):
    """Spend caps are checked before the call leaves; a refusal leaves the
    review standing and stores nothing."""
    _sub, run, scope = world
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider",
                        lambda *a, **k: Fake(raises=claude_spend.BudgetExceeded("cap")))
    review_jobs._ai_check(run, scope, [])
    assert _ai_rows(run) == []


# ------------------------------------------------------- truncation & retry
# 2026-09-27: the live spend ledger showed every one of the 10 historical
# `review_ai_check` calls hitting output_tokens == 4000 with
# finish_reason == "length", and `review_findings.origin = 'ai_engineering_check'`
# has zero rows ever - the check was throwing the whole reply away, silently,
# on every single run.

ITEM_A = {**GOOD, "topic": "First observation",
          "observation": "The hydrotest pressure is not stated beside 23.5 barg (first).",
          "action": "Contractor to confirm the hydrotest pressure (first)."}
ITEM_B = {**GOOD, "topic": "Second observation",
          "observation": "No corrosion allowance is stated near 23.5 barg (second).",
          "action": "Contractor to state the corrosion allowance (second)."}
ITEM_C_BAD = {**GOOD, "topic": "Third observation",
              "observation": "The design pressure of 23.5 barg complies with the service."}


def test_parse_partial_keeps_only_complete_items_before_the_cut_off(world):
    text = _cut_off_after([ITEM_A, ITEM_B])
    assert aic.parse_partial(text) == [ITEM_A, ITEM_B]
    assert aic.parse_partial(_cut_off_after([])) == []
    assert aic.parse_partial('{"items": []}') == []
    assert aic.parse_partial("not json at all") == []


def test_a_truncated_reply_is_completed_by_one_capped_retry(world, monkeypatch):
    """M-new: the first call is cut off after ITEM_A; the retry, told what
    is already covered, supplies ITEM_B and finishes cleanly. Both are kept,
    two calls were made, and the run's own status says it is complete."""
    _sub, run, scope = world
    fake = SeqFake([
        (_cut_off_after([ITEM_A]), "length"),
        (json.dumps({"items": [ITEM_B]}), "stop"),
    ])

    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"], provider=fake)

    assert result["calls_made"] == 2
    assert result["complete"] is True
    assert result["kept"] == 2
    topics = {row["requirement"] for row in _ai_rows(run)}
    assert topics == {"First observation", "Second observation"}, \
        "both the recovered first item and the retry's item are stored"
    # THE RETRY WAS TOLD WHAT WAS ALREADY COVERED, so it does not repeat work.
    assert len(fake.packets) == 2
    assert "ALREADY RAISED" in fake.packets[1].prompt
    assert "First observation" in fake.packets[1].prompt
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is True and status["calls_made"] == 2
    assert status["kept_items"] == 2


def test_retry_is_capped_and_still_incomplete_is_recorded_and_visible(world):
    """M-new: BOTH calls are cut off. `MAX_CALLS` stops a third attempt, and
    the run's status says plainly that it is incomplete - never silence."""
    _sub, run, scope = world
    fake = SeqFake([
        (_cut_off_after([ITEM_A]), "length"),
        (_cut_off_after([ITEM_B]), "length"),
    ])

    result = aic.run_check(run, allowed_document_ids=scope, cited=[], provider=fake)

    assert result["calls_made"] == aic.MAX_CALLS == 2
    assert result["complete"] is False
    assert result["kept"] == 2, "the complete item from EACH call is still kept, not discarded"
    assert "cut off" in result["reason"]
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["complete"] is False
    assert status["kept_items"] == 2 and status["calls_made"] == 2
    assert "2" in status["plain"] and "cut off" in status["plain"]


def test_retry_only_triggers_on_truncation_not_on_other_malformed_replies(world):
    """M-new: a reply that finished normally (`finish_reason: "stop"`) but is
    not valid JSON is genuinely malformed, not truncated - retrying the same
    prompt is not expected to fix it, so this must NOT retry. `SeqFake` has
    only one reply queued; a second call would raise IndexError and fail the
    test, proving no retry was attempted."""
    _sub, run, scope = world
    fake = SeqFake([("this is not json at all", "stop")])

    result = aic.run_check(run, allowed_document_ids=scope, cited=[], provider=fake)

    assert result["calls_made"] == 1
    assert result["complete"] is False
    assert result["reason"] == aic.Reason.MALFORMED.value
    assert result["rejected"] == {aic.Reason.MALFORMED.value: 1}


def test_accept_still_gates_items_recovered_from_a_retry(world):
    """M-new: an item recovered from the retry call goes through the SAME
    gate as a first-call item - a pass/fail word from the retry is rejected,
    never stored, just like one from the first call."""
    _sub, run, scope = world
    fake = SeqFake([
        (_cut_off_after([ITEM_A]), "length"),
        (json.dumps({"items": [ITEM_C_BAD]}), "stop"),
    ])

    result = aic.run_check(run, allowed_document_ids=scope, cited=[], provider=fake)

    assert result["kept"] == 1
    assert result["rejected"] == {"pass_fail_word": 1}
    [row] = _ai_rows(run)
    assert row["contractor_evidence_text"] == "23.5 barg"


def test_the_route_is_409_when_off_and_404_outside_scope(world, monkeypatch):
    """M1037."""
    sub, run, scope = world
    _signed_in(monkeypatch, scope)
    assert TestClient(app).post(f"/api/reviews/runs/{run}/ai-check").status_code == 409
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(rp, "claude_available", lambda: (True, "claude"))
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: Fake())
    ok = TestClient(app).post(f"/api/reviews/runs/{run}/ai-check")
    assert ok.status_code == 200 and ok.json()["kept"] == 1, ok.text
    assert TEXT not in ok.text, "the route answers counts, never the model's text"
    _signed_in(monkeypatch, frozenset(), user_id="outsider")
    assert TestClient(app).post(f"/api/reviews/runs/{run}/ai-check").status_code == 404


# -------------------------------------------------------------------- CRS

def _preview(run, copy="internal"):
    return TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview", params={"copy": copy}).json()


def _workbook_text(run, copy):
    response = TestClient(app).get(f"/api/reviews/runs/{run}/crs", params={"copy": copy})
    assert response.status_code == 200, response.text
    book = openpyxl.load_workbook(io.BytesIO(response.content))
    cells = [str(c.value) for ws in book for row in ws.iter_rows() for c in row if c.value]
    return response.headers["content-disposition"], book["CRS"], " ".join(cells)


def test_an_unconfirmed_item_is_only_in_the_ai_column_of_the_internal_copy(world):
    """M1032: never in COMPANY Comments. The existing seven columns keep their order."""
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())

    view = _preview(run)
    # CRS quick wins: "Standard Reference" follows the seven; AI stays last.
    assert view["columns"] == [*crs_export.HEADERS, "Standard Reference", "Severity", "AI Review Comments"]
    [row] = [r for r in view["rows"] if TEXT in r["ai_review_comment"]]
    assert TEXT not in row["comment"]
    # Honesty audit entry 71: "Comment By" is never blank - unconfirmed is a
    # state to name, not an absence to leave silent.
    assert row["comment_by"] == "AI - engineer to confirm"
    # CRS quick wins: Page/Section is the datasheet's page and field, in the
    # one shape every row of the sheet uses.
    assert row["page_section"] == "p.1 - Design pressure"
    assert "Relates to API 610" in row["ai_review_comment"]
    name, sheet, _text = _workbook_text(run, "internal")
    assert "internal-review-copy" in name
    assert sheet.cell(row=crs_export.COLUMN_HEADER_ROW, column=10).value == "AI Review Comments"  # #725 F7: Severity is column 9


def test_an_unconfirmed_items_comment_by_is_never_blank(world):
    """HONESTY GROUP (2026-09-27), M1132. Before this fix, an unconfirmed kind
    C item's `comment_by` was `""` - not "not mentioned", not a status, just
    silently absent on a row the sheet otherwise clearly attributes to the AI
    (its text sits in "AI Review Comments"). A reader scanning the Comment By
    column would see a blank cell rather than something to act on."""
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())

    view = _preview(run)
    [row] = [r for r in view["rows"] if TEXT in r["ai_review_comment"]]
    assert row["comment_by"], "an unconfirmed item's Comment By was blank"
    assert row["comment_by"] == "AI - engineer to confirm"
    # And the workbook (not just the preview) carries the same text - the
    # preview and the .xlsx are one builder, never two that can disagree.
    _name, sheet, text = _workbook_text(run, "internal")
    assert "AI - engineer to confirm" in text


def test_the_issue_copy_carries_no_ai_column_and_no_unconfirmed_text(world):
    """M1031: the contractor's copy - only confirmed comments leave the building."""
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    # The safety gate (2026-09-27): copy=issue is refused with 409 until an
    # engineer records the final code - not what this test is about, so it is
    # satisfied here rather than worked around.
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET engineer_final_code='Approved'"
                     " WHERE id = ?", (run,))

    view = _preview(run, "issue")
    assert view["columns"] == [*crs_export.HEADERS, "Standard Reference", "Severity"]
    assert TEXT not in json.dumps(view)
    assert not [r for r in view["rows"] if r["row_kind"] == "ai_engineering_check"], \
        "an unconfirmed item's row was issued, emptied"
    name, sheet, text = _workbook_text(run, "issue")
    assert "issue-to-contractor" in name
    assert sheet.cell(row=crs_export.COLUMN_HEADER_ROW, column=10).value is None
    assert TEXT not in text


def test_confirmation_moves_the_text_to_company_comments_under_the_engineers_name(world, monkeypatch):
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    [item] = _ai_rows(run)
    _signed_in(monkeypatch, scope)

    assert TestClient(app).patch(f"/api/reviews/findings/{item['id']}",
                                 json={"confirmed": True}).status_code == 200

    [row] = [r for r in _preview(run)["rows"] if TEXT in r["comment"]]
    assert row["comment_by"] == "AI engineering check, confirmed by Engineer"
    assert row["ai_review_comment"] == ""
    assert TEXT in json.dumps(_preview(run, "issue")), "a confirmed comment is issued"


def test_a_rejected_item_is_not_on_the_sheet(world, monkeypatch):
    """M1038."""
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    [item] = _ai_rows(run)
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(f"/api/reviews/findings/{item['id']}",
                                 json={"approval_status": "rejected"}).status_code == 200
    assert TEXT not in json.dumps(_preview(run))
