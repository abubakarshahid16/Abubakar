"""Lane 6, part 2: the AI engineering review pass runner, with a STUB model. Invented rows and pages only.

What must hold: off means no model is asked and nothing is stored but the summary; a verified proposal is stored accepted;
an unverified one is stored refused with its reason; nothing the model says changes the rows; a failing or unusable model
stops the pass and never raises; a removal can be restored and the restore undone; the claude engine falls back to local.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import ai_review_pass as arpass
from app.config import settings

PAGES = {
    1: "Tag P-101A  MAWP 14 barg\nTag P-101B  MAWP 16 barg",
    2: "Relief valve PSV-9901  Set pressure 10 barg",
}
ROW = {
    "row_kind": "needs_engineer_review",
    "crs_row_key": "k-rev",
    "page_section": "p.1 - MAWP",
    "standard_reference": "SAES-X-100 cl. 4.2 (p.9)",
    "comment": "Engineer to check MAWP: tags P-101A and P-101B state 14 barg and 16 barg.",
}
FAIL = {
    "row_kind": "non_compliant",
    "crs_row_key": "k-fail",
    "page_section": "p.2 - Relief capacity",
    "standard_reference": "SAES-X-100 cl. 4.2 (p.9)",
    "comment": "Set pressure states 10 barg; requires 12 barg.",
}
HELD = {"SAES-X-100.pdf": ["4.2", "5.1"]}

REMOVE = {
    "id": "p1",
    "type": "remove",
    "row_key": "k-rev",
    "page": 1,
    "basis": "tag_difference",
    "value": "16 barg",
    "reason": "Different tags have different MAWP; that is normal.",
    "confidence": "medium",
    "evidence": [{"page": 1, "quote": "Tag P-101B  MAWP 16 barg"}],
}
ADD = {
    "id": "p2",
    "type": "add",
    "page": 2,
    "field": "Set pressure",
    "value": "10 barg",
    "clause": "5.1",
    "standard": "SAES-X-100",
    "text": "Contractor to confirm the set pressure of PSV-9901.",
    "reason": "Set pressure should be confirmed.",
    "confidence": "low",
}
BAD_VALUE = dict(ADD, id="p3", value="99 barg")
KILL_FAIL = {
    "id": "p4",
    "type": "remove",
    "row_key": "k-fail",
    "page": 2,
    "basis": "tag_difference",
    "value": "10 barg",
    "reason": "A different tag.",
    "confidence": "medium",
    "evidence": [{"page": 2, "quote": "Set pressure 10 barg"}],
}


class Stub:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def reason(self, packet):
        self.asked.append(packet)
        if isinstance(self.answer, Exception):
            raise self.answer
        text = (
            self.answer
            if isinstance(self.answer, str)
            else json.dumps({"proposals": self.answer})
        )
        return SimpleNamespace(
            text=text,
            provider="stub",
            model_tag="s-1",
            schema_errors=(),
            finish_reason="stop",
        )


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)


def go(run_id, answer, rows=(ROW, FAIL)):
    stub = Stub(answer)
    return stub, arpass.run(run_id, list(rows), pages=PAGES, held=HELD, provider=stub)


def test_it_is_off_by_default_and_asks_nothing():
    assert settings.ai_engineering_review_pass_enabled is False
    stub = Stub([REMOVE])
    summary = arpass.run("r-off", [ROW], pages=PAGES, held=HELD, provider=stub)
    assert (
        stub.asked == []
        and summary["stopped"].startswith("off")
        and arpass.accepted("r-off") == []
    )


def test_verified_proposals_are_stored_accepted_and_unverified_ones_refused_with_the_reason(
    on,
):
    stub, summary = go("r1", [REMOVE, ADD, BAD_VALUE, KILL_FAIL])
    assert len(stub.asked) == 1 and summary["proposed"] == 4
    assert summary["accepted"]["remove"] == 1 and summary["accepted"]["add"] == 1
    assert summary["refused"] == {
        "value_not_on_page": 1,
        "fail_kept_no_verified_reason": 1,
    }
    got = {a["proposal_id"]: a for a in arpass.accepted("r1")}
    assert set(got) == {"p1", "p2"} and got["p2"]["row_kind"] == "needs_engineer_review"
    assert arpass.summary_of("r1") == summary


def test_the_pass_changes_no_row(on):
    rows = [dict(ROW), dict(FAIL)]
    before = json.dumps(rows, sort_keys=True)
    go("r2", [REMOVE, KILL_FAIL], rows=rows)
    assert json.dumps(rows, sort_keys=True) == before


def test_a_failing_model_stops_the_pass_and_never_raises(on):
    _stub, summary = go("r3", TimeoutError("slow"))
    assert "TimeoutError" in summary["stopped"] and arpass.accepted("r3") == []


@pytest.mark.parametrize(
    "answer", ["not json", json.dumps({"proposals": "no"}), json.dumps({"other": []})]
)
def test_an_unusable_answer_stops_the_pass(on, answer):
    _stub, summary = go("r4", answer)
    assert (
        "not usable" in summary["stopped"]
        and summary["proposed"] == 0
        and arpass.accepted("r4") == []
    )


def test_a_rerun_replaces_the_stored_proposals(on):
    go("r5", [REMOVE, ADD])
    go("r5", [ADD])
    assert [a["proposal_id"] for a in arpass.accepted("r5")] == ["p2"]


def test_a_removal_can_be_restored_and_the_restore_undone(on):
    go("r6", [REMOVE, ADD])
    assert arpass.restore("r6", "p1", "Eng One") and arpass.restored_ids("r6") == {"p1"}
    assert (
        arpass.restore("r6", "p1", "Eng One", undo=True)
        and arpass.restored_ids("r6") == set()
    )
    assert not arpass.restore("r6", "p2", "Eng One")  # an add is not a removal
    assert not arpass.restore("r6", "p1", "  ")  # who restored it is always recorded
    assert (
        arpass.accepted("r6")[0]["proposal_id"] == "p1"
    )  # the removal's record is never deleted


def test_the_local_packet_carries_only_the_pages_the_rows_cite(on):
    stub, _ = go("r7", [], rows=(ROW,))
    prompt = stub.asked[0].prompt
    assert "page 1" in prompt and "page 2" not in prompt


def test_the_claude_engine_falls_back_to_local_when_documents_are_not_approved(
    on, monkeypatch
):
    from app import claude_approved
    from app import reasoning_provider as rp

    class Cloud(rp.ClaudeProvider):
        def __init__(self):
            pass

    monkeypatch.setattr(settings, "ai_engineering_review_pass_engine", "claude")
    monkeypatch.setattr(rp, "claude_for_task", lambda *a, **k: Cloud())
    monkeypatch.setattr(
        claude_approved,
        "local_instead",
        lambda: "documents not approved: local model used",
    )
    provider, note = arpass._provider()
    assert isinstance(provider, rp.OllamaProvider) and "not approved" in note


def test_the_review_job_hook_is_a_no_op_when_off_and_never_raises_when_on(monkeypatch):
    from app import main

    called = []
    monkeypatch.setattr(
        main, "_crs_content", lambda *a, **k: called.append(1) or ([], {}, "", "")
    )
    assert arpass.run_for_job("no-such-run", None) is None
    assert called == []  # off: the CRS is not even read
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    assert (
        arpass.run_for_job("no-such-run", None) is None
    )  # on, but the run is not there: logged, not raised
    assert called == [1]
