"""Leftovers of the 2026-09-30 audit: items the fixing batch left "not done".

Synthetic data only - made-up standards, sheets and values; no client text,
no network. Each test stands where its fix can fail it, with a positive
control showing the machinery still reaches the result it guards. Mutations
M1600-M1619 (`scripts/mutations/audit_leftovers.py`), run with
`python scripts/mutation_check.py --only M1600,...`.

The chat cost item is in `test_audit_leftovers_chat.py` and the risk scope
item in `test_access_audit_security.py` (each needs its own storage fixture).
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app import chat_stream, claude_recheck, comparison, datasheets, db, submittal_review
from app.main import app
from app.market_phrase import market_phrase, vouched_for
from tests.test_audit_crs_fixes import _noise_run, _noise_status
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_comparison import _chunk, _doc, _fact, _requirement
from tests.test_model_matching import _signed_in
from tests.test_review_screen import _first_comment, _noise_rows, world  # noqa: F401

LOW_TRUST = ({"validation_state": datasheets.NEEDS_ENGINEER_REVIEW},
             {"validation_state": datasheets.GEOMETRY_CONFLICT},
             {"extraction_method": "model"})


# ============================================ 1. no verdict on a low-trust value

def test_a_compliant_result_on_an_untrusted_value_is_held_too():
    """M1600. "80 dB(A) is within 90" read by OCR fallback / the model was
    accepted as COMPLIANT - the same unchecked guess as a breach."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    trusted = _fact(sub, fc, raw_value="80", field_value="80 dB(A)")
    assert comparison.compare(_requirement(std, sc), trusted)["status"] == comparison.COMPLIANT
    for extra in LOW_TRUST:
        held = comparison.compare(_requirement(std, sc), {**trusted, **extra})
        assert held["status"] == comparison.NEEDS_ENGINEER_REVIEW, extra
        assert held["rationale"].startswith(comparison.LOW_TRUST_VALUE)
        assert "neither compliant nor a breach" in held["rationale"]
        assert "within" in held["rationale"], "the arithmetic is kept in the words"
    confirmed = {**trusted, "extraction_method": "model", "confirmed_by": "eng"}
    assert comparison.compare(_requirement(std, sc), confirmed)["status"] == comparison.COMPLIANT


def test_a_held_compliance_is_a_crs_question_that_says_why():
    """M1600, M1601. Through the pipeline and onto the CRS: 100 dB(A) is within
    the PSV exception's 115, but the value is low-trust, so the run states no
    verdict and the CRS row asks the engineer, naming the reason in words
    (no machine code)."""
    run, scope = _noise_run("Pressure Safety Valve")
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _noise_status(run) == comparison.COMPLIANT, "positive control"

    # The same run again, with the value now a low-trust reading.
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET validation_state = ?",
                     (datasheets.NEEDS_ENGINEER_REVIEW,))
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _noise_status(run) == comparison.NEEDS_ENGINEER_REVIEW
    rows = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview").json()["rows"]
    [row] = [r for r in rows if "100 dB(A)" in r["comment"]]
    assert row["row_kind"] == "needs_engineer_review"
    assert "Engineer to check: the value was read with validation state" in row["comment"]
    assert "neither compliant nor a breach" in row["comment"]
    assert comparison.LOW_TRUST_VALUE not in row["comment"]


# ============================================ 2. no unit is not "unit ''"

def _unitless(req_unit: str, fact_unit: str) -> str:
    req = dict(raw_value="3", raw_unit=req_unit, operator=">=",
               requirement_type="numeric_limit", source_text="x")
    fact = dict(raw_value="5", raw_unit=fact_unit, field_value=f"5 {fact_unit}".strip(),
                field_name="x")
    out = comparison.compare(req, fact, submittal_facts=[fact])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    return out["rationale"]


def test_two_values_with_no_unit_are_not_blamed_on_two_empty_units():
    """M1602, M1603."""
    both = _unitless("", "")
    assert "unit ''" not in both
    assert both.startswith("neither the submitted value nor the requirement states a unit")
    one = _unitless("mm", "")
    assert "unit ''" not in one and one.startswith("the submitted value states no unit")
    assert "'mm'" in one
    # Positive control: two real, different units still name both.
    assert "unit 'psi' and the required unit 'mm'" in _unitless("mm", "psi")


def test_a_missing_unit_refusal_is_still_blocked_for_the_recheck():
    """M1604. The recheck matched the old sentence's fixed words; the new
    sentences must still read as "nothing was compared"."""
    finding = {"compliance_status": comparison.NEEDS_ENGINEER_REVIEW,
               "ai_rationale": _unitless("", ""), "unresolved_evidence": []}
    assert claude_recheck.requirement_state(finding) == claude_recheck.BLOCKED


# ============================================ 3. carried-forward bylines

def test_a_carried_forward_byline_names_the_engineer_not_the_id(world, monkeypatch):
    """M1605. A snapshot saved before bylines printed names still says
    "confirmed by eng-1"; the carried row prints the display name. An id
    with no user on record stays as it is - never an invented name."""
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    client = TestClient(app)
    client.patch(f"/api/reviews/findings/{finding_id}", json={"confirmed": True})
    with db.connect() as conn:
        # An OLD comment of this submittal the current run no longer raises,
        # snapshotted with a raw id, and one naming nobody on record.
        [(scope_key, label)] = conn.execute(
            "SELECT scope_key, label FROM crs_comment_numbers").fetchall()
        for seq, key, by in ((90, "old-comment-a", "AI Review, confirmed by eng-1"),
                             (91, "old-comment-b", "AI Review, confirmed by ghost-9")):
            conn.execute(
                "INSERT INTO crs_comment_numbers (scope_key, row_key, seq, label, status,"
                " comment, comment_by, assigned_at) VALUES (?,?,?,?,'Open',?,?,"
                "'2026-09-01T00:00:00Z')",
                (scope_key, key, seq, label, f"old comment {seq}", by))
    rows = client.get(f"/api/reviews/runs/{run}/crs/preview").json()["rows"]
    carried = {r["comment"]: r["comment_by"] for r in rows if r["comment"].startswith("old comment")}
    assert carried["old comment 90"] == ("AI Review, confirmed by Engineer - carried "
                                         "forward from an earlier review")
    assert carried["old comment 91"] == ("AI Review, confirmed by ghost-9 - carried "
                                         "forward from an earlier review")


# ============================================ 4. a re-raised rejection says so

def _new_run(sub, scope) -> str:
    again = submittal_review.create_review_run(submittal_document_id=sub,
                                               allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,'doc_std','cited','referenced',1,'2026-09-30T00:00:00Z')""",
                     (str(uuid.uuid4()), again))
    comparison.run_comparison(again, allowed_document_ids=scope)
    return again


def test_a_comment_rejected_on_an_earlier_run_is_marked_when_raised_again(world, monkeypatch):
    """M1606, M1607. The new run's draft is kept (not silently dropped), but
    its byline says who rejected it and when, so the engineer is not asked
    twice blind. Never on a confirmed row."""
    sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    client = TestClient(app)
    again = _new_run(sub, scope)
    [fresh] = _noise_rows(again)
    assert "previously rejected" not in fresh["comment_by"], "positive control: nothing rejected yet"

    assert client.patch(f"/api/reviews/findings/{finding_id}",
                        json={"approval_status": "rejected"}).status_code == 200
    when = db.connect().execute("SELECT approved_at FROM review_findings WHERE id = ?",
                                (finding_id,)).fetchone()[0][:10]
    third = _new_run(sub, scope)
    [draft] = _noise_rows(third)
    assert draft["comment_by"].endswith(f"previously rejected by Engineer on {when}")
    assert draft["comment_by"].startswith("AI Review")
    # Confirming the new draft makes it the engineer's: no longer marked.
    [draft_id] = [r[0] for r in db.connect().execute(
        "SELECT id FROM review_findings WHERE review_run_id = ? AND approval_status != 'rejected'"
        " AND compliance_status = 'NON_COMPLIANT'", (third,))]
    client.patch(f"/api/reviews/findings/{draft_id}", json={"confirmed": True})
    [mine] = _noise_rows(third)
    assert "previously rejected" not in mine["comment_by"]


# ============================================ 6. the market whitelist vouches

def test_an_unknown_word_is_dropped_from_the_market_phrase():
    """M1608, M1609. "Drops any word it cannot vouch for" - "zqx" and a
    made-up facility name are not ordinary English words."""
    assert market_phrase("zqx coating thickness", []) == "coating thickness"
    assert market_phrase("Qarvelle offshore platform corrosion", []) == (
        "offshore platform corrosion")
    assert market_phrase("zqx blorp", []) is None
    assert not vouched_for("zqx")
    # Positive controls: dictionary words, a British spelling, a public
    # engineering abbreviation from the supplement.
    assert market_phrase("galvanised flange colour", []) == "galvanised flange colour"
    assert market_phrase("what is the NDFT", []) == "ndft"


# ============================================ 7. the streamed label is the final label

IMAGE_PAGE = {"filename": "DS.pdf", "page_start": 4, "page_end": 4, "read_from_image": True,
              "has_text_layer": False, "text": "[page 4 read from image]", "document_id": "d1"}


def _streamed(sentence: str, passages: list[dict]) -> str:
    turn = chat_stream.Turn(id="t", owner=None, conversation_id="c")
    turn.prepare(passages=passages, verify=True, general=False)
    turn.text(sentence + " ")
    turn.flush()
    out = []
    while not turn.events.empty():
        event, data = turn.events.get()
        if event == "delta":
            out.append(data["text"])
    return "".join(out).strip()


def test_an_image_only_point_streams_with_its_read_from_image_label():
    """M1610. It streamed as a bare [S1] and changed label on "done"."""
    shown = _streamed("The nameplate shows a stamp from the inspector [S1].", [IMAGE_PAGE])
    assert shown == ("The nameplate shows a stamp from the inspector "
                     "[DS.pdf, page 4, read from image - check the page].")
    # Positive control: a text-layer source keeps its [S1] while streaming.
    text_page = {**IMAGE_PAGE, "read_from_image": False, "has_text_layer": True,
                 "text": "the stamp from the inspector is on the plate"}
    plain = _streamed('It has [S1 "the stamp from the inspector"].', [text_page])
    assert plain.startswith("It has [S1") and "read from image" not in plain
