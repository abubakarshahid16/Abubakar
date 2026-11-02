"""Owner-approved tier (#1584, owner's text of 2 Nov; switch `owner_approved_rules_decide_enabled`, OFF).

A rule whose approval tier is `owner` may decide, labelled exactly "AI-built, quote-verified, owner-approved",
never "engineer-approved". Code still compares a read value; a safety-tier COMPLIANT keeps the engineer's tick; a
missing, low-trust or deferred value is a query. Off, everything is byte-identical. Invented text only.

MUTATION PROOF (danger zone, CLAUDE.md rule 6): `scripts/mutations/pr1611_owner_approved_tier.py` (M1611-01..).
"""

from __future__ import annotations

import io
import json
import re

import openpyxl
import pytest
from tools import crs_bench

from app import (
    comparison,
    coverage_pair,
    datasheets,
    deferred_value,
    rule_eval,
    rule_trust,
)
from app.config import settings
from app.db import connect
from tests.test_947_rule_trust_wiring import (  # noqa: F401 - fixtures
    SPEC,
    SUB,
    _client,
    _findings,
    _rerun,
    review_run,
    temp_storage,
    world,
)
from tests.test_1475_planted_defects import _rule_facts as table_facts
from tests.test_rule_eval import _rule as table_rule
from tests.test_w5_677_scope_ledger import NOW, _req

WORDS = "AI-built, quote-verified, owner-approved"
APPROVAL = {"by": "owner", "at": "2026-11-02T10:00:00Z", "tier": "owner"}
SWITCH = "owner_approved_rules_decide_enabled"


def _rule(**extra) -> dict:
    return {
        "id": "r1",
        "requirement_text": "The bonnet thickness shall not exceed 12 mm.",
        "source_text": "The bonnet thickness shall not exceed 12 mm.",
        "field": "bonnet thickness",
        "operator": "<=",
        "value": 12.0,
        "unit": "mm",
        "raw_value": "12",
        "raw_unit": "mm",
        "requirement_type": "numeric_limit",
        "approval": dict(APPROVAL),
        **extra,
    }


def _fact(raw="10 mm", **extra) -> dict:
    value, _, unit = raw.partition(" ")
    return {
        "id": "f1",
        "field_name": "Bonnet thickness",
        "raw_value": value,
        "raw_unit": unit,
        "page": 1,
        **extra,
    }


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, SWITCH, True)


# ------------------------------------------------------------------ the function piece 3 calls


def test_owner_tier_with_a_verified_quote_gets_the_tier(on):
    assert rule_trust.tier_for_approved(APPROVAL, _rule()) == rule_trust.OWNER_APPROVED


def test_the_function_with_the_switch_off_gives_no_tier():
    assert getattr(settings, SWITCH) is False
    assert rule_trust.tier_for_approved(APPROVAL, _rule()) == rule_trust.UNPROVEN


@pytest.mark.parametrize(
    "approval",
    [
        None,
        {},
        {**APPROVAL, "tier": "engineer"},
        {**APPROVAL, "tier": "OWNER"},
        {**APPROVAL, "by": ""},
        {**APPROVAL, "at": None},
        {**APPROVAL, "by": " "},
        {**APPROVAL, "by": 7},
        {**APPROVAL, "by": True},
        {**APPROVAL, "at": "not a date"},
        {**APPROVAL, "at": " "},
        {**APPROVAL, "at": 20261102},
    ],
)
def test_anything_but_a_whole_owner_approval_gets_no_tier(on, approval):
    assert rule_trust.tier_for_approved(approval, _rule()) == rule_trust.UNPROVEN


@pytest.mark.parametrize("at", ["2026-11-02T10:00:00Z", "2026-11-02 10:00:00"])
def test_a_real_timestamp_is_read_either_way_it_is_stored(on, at):
    approval = {**APPROVAL, "at": at}
    assert rule_trust.tier_for_approved(approval, _rule()) == rule_trust.OWNER_APPROVED


def test_a_quote_code_cannot_verify_gets_no_tier(on):
    """The label says quote-verified, so code must have verified it: the number is not in the sentence."""
    assert (
        rule_trust.tier_for_approved(APPROVAL, _rule(raw_value="99", value=99.0))
        == rule_trust.UNPROVEN
    )
    assert (
        rule_trust.tier_for_approved(
            APPROVAL, _rule(source_text="", requirement_text="", quote="")
        )
        == rule_trust.UNPROVEN
    )


# ------------------------------------------------------------------ the label


def test_the_words_are_exact_and_the_other_labels_keep_theirs():
    assert rule_trust.TRUST_WORDS[rule_trust.OWNER_APPROVED] == WORDS
    assert (
        rule_trust.TRUST_WORDS[rule_trust.ENGINEER_CONFIRMED]
        == "engineer-approved rule"
    )
    assert rule_trust.TRUST_WORDS[rule_trust.AUTO_PROVEN] == "automatic (proven rule)"


@pytest.mark.parametrize("switch", [True, False])
def test_an_owner_rule_is_never_labelled_engineer_approved(monkeypatch, switch):
    """Even when the rule dict also says confirmed_by: that word means an engineer."""
    monkeypatch.setattr(settings, SWITCH, switch)
    label = rule_trust.trust_label(_rule(confirmed_by="owner"), None)
    assert label != rule_trust.ENGINEER_CONFIRMED
    assert label == (rule_trust.OWNER_APPROVED if switch else rule_trust.UNPROVEN)


# ------------------------------------------------------------------ the verdict


@pytest.mark.parametrize(
    ("raw", "status"),
    [("10 mm", "COMPLIANT"), ("15 mm", "NON_COMPLIANT"), ("12 mm", "COMPLIANT")],
)
def test_code_compares_the_value_and_the_owner_rule_may_decide(on, raw, status):
    fact, rule = _fact(raw), _rule()
    verdict = comparison.compare(rule, fact)
    assert verdict["status"] == status
    out = rule_trust.label_finding(verdict, rule, None, fact=fact)
    assert out["status"] == status
    assert out["trust_label"] == rule_trust.OWNER_APPROVED
    assert out["trust_words"] == WORDS
    assert out.get("rule_said") is None


def test_a_standard_tier_compliant_has_no_tick_and_a_safety_tier_compliant_keeps_it(on):
    plain = rule_trust.label_finding(
        {"status": "COMPLIANT"}, _rule(), None, fact=_fact()
    )
    assert (plain["tier"], plain["show_for_engineer_tick"]) == (
        rule_trust.STANDARD,
        False,
    )

    safety = _rule(
        field="set pressure",
        requirement_text="The set pressure shall not exceed 12 barg.",
        source_text="The set pressure shall not exceed 12 barg.",
        unit="barg",
        raw_unit="barg",
    )
    out = rule_trust.label_finding(
        {"status": "COMPLIANT"}, safety, None, fact=_fact("10 barg")
    )
    assert out["trust_label"] == rule_trust.OWNER_APPROVED
    assert (out["tier"], out["show_for_engineer_tick"]) == (rule_trust.SAFETY, True)
    breach = rule_trust.label_finding(
        {"status": "NON_COMPLIANT"}, safety, None, fact=_fact("15 barg")
    )
    assert (breach["status"], breach["show_for_engineer_tick"]) == (
        "NON_COMPLIANT",
        False,
    )


@pytest.mark.parametrize(
    "fact",
    [
        None,
        {"id": "f", "raw_value": ""},
        {"id": "f", "raw_value": None},
        {"id": "f", "raw_value": "10 mm", "is_blank": 1},
    ],
)
@pytest.mark.parametrize("status", ["COMPLIANT", "NON_COMPLIANT"])
def test_a_verdict_with_no_read_value_never_stands_on_an_owner_rule(on, fact, status):
    out = rule_trust.label_finding(
        {"status": status, "rationale": "x"}, _rule(), None, fact=fact
    )
    assert out["status"] == "NEEDS_ENGINEER_REVIEW"
    assert out["trust_label"] == rule_trust.OWNER_APPROVED
    assert out["show_for_engineer_tick"] is False
    # not `rule_said`: the screen would say "held until the rule is proven", which is not why
    assert out.get("rule_said") is None
    assert "no value was read" in out["rationale"]


def test_a_stored_fact_reads_as_a_read_value(on):
    """A stored fact carries `field_value`, a test case `raw_value`: both are a read value."""
    out = rule_trust.label_finding(
        {"status": "COMPLIANT"}, _rule(), None, fact={"id": "f", "field_value": "10 mm"}
    )
    assert out["status"] == "COMPLIANT"


def test_not_mentioned_is_never_compliant(on):
    rule = _rule()
    verdict = comparison.compare(rule, None)
    assert verdict["status"] == comparison.MISSING_INFORMATION
    out = rule_trust.label_finding(verdict, rule, None, fact=None)
    assert out["status"] == comparison.MISSING_INFORMATION


@pytest.mark.parametrize("state", ["needs_engineer_review", "conflict"])
def test_a_low_trust_value_still_holds(on, state):
    fact, rule = _fact(validation_state=state), _rule()
    out = rule_trust.label_finding(
        comparison.compare(rule, fact), rule, None, fact=fact
    )
    assert out["status"] == "NEEDS_ENGINEER_REVIEW"
    assert out["show_for_engineer_tick"] is False


@pytest.mark.parametrize("raw", ["10 mm", "15 mm"])
def test_a_deferred_value_is_a_query_with_this_switch_alone(on, raw):
    """Owner's words: a deferred value gives Query. D2's own switch stays off here."""
    assert settings.deferred_value_is_query_enabled is False
    fact, rule = _fact(raw, value_note="By Contractor"), _rule()
    out = rule_trust.label_finding(
        comparison.compare(rule, fact), rule, None, fact=fact
    )
    assert out["status"] == "NEEDS_ENGINEER_REVIEW"
    assert out["show_for_engineer_tick"] is False


def test_a_deferred_input_of_a_table_rule_is_a_query(on):
    """The real table rule: D2's switch is off, so it decides; the owner's rule may not rest on that input."""
    rule = table_rule()
    verdict, fact = rule_eval.judge(rule, table_facts("1700", note="By Contractor"))
    assert verdict["status"] in ("COMPLIANT", "NON_COMPLIANT")
    assert verdict["input_deferred"] == "By Contractor"
    held = deferred_value.hold_owner_rule(verdict, fact)
    assert held["status"] == "NEEDS_ENGINEER_REVIEW"
    clean, fact = rule_eval.judge(rule, table_facts("1700"))
    assert "input_deferred" not in clean
    assert deferred_value.hold_owner_rule(clean, fact)["status"] == clean["status"]


def test_a_deferred_input_on_any_tag_holds_a_sheet_of_several_tags(on):
    """Tag B's input is deferred and both tags read Pass: tag A decides the row, and must not hide B."""
    tag_a, tag_b = table_facts("1700"), table_facts("1700", note="By Contractor")
    for row in tag_a:
        row["equipment_tag"] = "A"
    for row in tag_b:
        row["equipment_tag"] = "B"
    verdict, fact = rule_eval.judge(table_rule(), tag_a + tag_b)
    assert verdict["status"] == "COMPLIANT"
    assert (
        deferred_value.hold_owner_rule(verdict, fact)["status"]
        == "NEEDS_ENGINEER_REVIEW"
    )


def test_this_switch_does_not_widen_the_hold_to_another_rule(on):
    """A rule the owner has not approved judges a deferred value as it did: the tier changes only its own rules."""
    plain = {k: v for k, v in _rule().items() if k != "approval"}
    assert (
        comparison.compare(plain, _fact(value_note="By Contractor"))["status"]
        == "COMPLIANT"
    )


def test_an_unclear_value_is_a_query(on):
    fact, rule = (
        {
            "id": "f1",
            "field_name": "Bonnet thickness",
            "raw_value": "see note",
            "page": 1,
        },
        _rule(),
    )
    out = rule_trust.label_finding(
        comparison.compare(rule, fact), rule, None, fact=fact
    )
    assert out["status"] not in ("COMPLIANT", "NON_COMPLIANT")


def test_a_tier_never_upgrades_a_held_verdict(on):
    """The gate only ever lets a verdict stand: it never makes one."""
    for status in ("NEEDS_ENGINEER_REVIEW", "MISSING_INFORMATION", "CONDITIONAL"):
        out = rule_trust.label_finding({"status": status}, _rule(), None, fact=_fact())
        assert out["status"] == status


# ------------------------------------------------------------------ the switch


def test_off_the_hook_returns_the_same_object():
    finding = {"status": "COMPLIANT"}
    assert rule_trust.label_finding(finding, _rule(), None, fact=_fact()) is finding


def test_this_switch_alone_leaves_every_other_rule_as_it_was(on):
    finding = {"status": "COMPLIANT"}
    plain = {k: v for k, v in _rule().items() if k != "approval"}
    assert rule_trust.label_finding(finding, plain, None, fact=_fact()) is finding


def test_the_old_switch_alone_gives_an_owner_rule_no_tier(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    out = rule_trust.label_finding({"status": "COMPLIANT"}, _rule(), None, fact=_fact())
    assert out["trust_label"] == rule_trust.UNPROVEN
    assert out["status"] == "NEEDS_ENGINEER_REVIEW"


# ------------------------------------------------------------------ from where it is set to the cell


@pytest.fixture
def owner_world(world, monkeypatch):  # noqa: F811
    """`world` plus a non-safety limit the sheet breaks; `approved` marks rule ids as owner-approved on the way to
    the label, which is where piece 3's `approved_rules` dicts arrive."""
    chunk = (
        connect()
        .execute(
            "SELECT chunk_id FROM standard_requirements WHERE id = ?", (world["limit"],)
        )
        .fetchone()[0]
    )
    fact_chunk = (
        connect()
        .execute("SELECT id FROM chunks WHERE document_id = ? LIMIT 1", (SUB,))
        .fetchone()[0]
    )
    world["breach"] = _req(
        SPEC,
        chunk,
        "The bonnet thickness shall not exceed 12 mm.",
        requirement_type="numeric_limit",
        operator="<=",
        value=12.0,
        unit="mm",
        raw_value="12",
        raw_unit="mm",
        field="bonnet thickness",
        subject="bonnet thickness",
    )
    datasheets.create_fact(
        submittal_document_id=SUB,
        chunk_id=fact_chunk,
        field_label="Bonnet thickness",
        raw_value="15 mm",
        page=1,
    )
    real = comparison._RuleTrust.label

    def label(self, verdict, rule, fact=None):
        if rule.get("id") in world["approved"]:
            rule = {**rule, "approval": dict(APPROVAL)}
        return real(self, verdict, rule, fact)

    world["approved"] = {world["limit"], world["breach"]}
    monkeypatch.setattr(comparison._RuleTrust, "label", label)
    return world


def _crs(world, copy=""):  # noqa: F811
    query = f"?copy={copy}" if copy else ""
    return (
        _client(world["scope"])
        .get(f"/api/reviews/runs/{world['run']}/crs/preview{query}")
        .json()
    )


def test_the_words_reach_the_cell_the_engineer_reads(owner_world, monkeypatch):
    monkeypatch.setattr(settings, SWITCH, True)
    _rerun(owner_world)
    rows = _findings(owner_world["run"])
    breach = rows[owner_world["breach"]]
    assert (
        breach["compliance_status"],
        breach["trust_label"],
        breach["show_for_engineer_tick"],
    ) == (
        "NON_COMPLIANT",
        rule_trust.OWNER_APPROVED,
        0,
    )
    tick = rows[owner_world["limit"]]
    assert (
        tick["compliance_status"],
        tick["tier"],
        tick["show_for_engineer_tick"],
    ) == (
        "COMPLIANT",
        rule_trust.SAFETY,
        1,
    )
    sheet = _crs(owner_world)
    labelled = [r for r in sheet["rows"] if r.get("rule_trust")]
    assert {r["rule_trust"] for r in labelled} == {WORDS}
    kinds = {r["row_kind"] for r in labelled}
    assert "safety_tick" in kinds and len(kinds) > 1  # the tick row and the breach row
    tick_row = next(r for r in labelled if r["row_kind"] == "safety_tick")
    assert WORDS in tick_row["comment"]
    assert not re.search(r"engineer[- ]approved|proven", json.dumps(labelled), re.I)
    # an owner-approved row is not an engineer's confirmation on the sheet
    assert not any(r.get("engineer_confirmed") for r in labelled)
    # the issue copy drops the internal column, as for every label
    assert WORDS not in json.dumps(_crs(owner_world, "issue")["rows"])


def test_the_words_reach_the_downloaded_crs_file_in_its_own_column(
    owner_world, monkeypatch
):
    monkeypatch.setattr(settings, SWITCH, True)
    _rerun(owner_world)
    got = _client(owner_world["scope"]).get(
        f"/api/reviews/runs/{owner_world['run']}/crs"
    )
    assert got.status_code == 200
    book = openpyxl.load_workbook(io.BytesIO(got.content))
    title = "Rule trust (internal)"
    cells = [
        (sheet, cell)
        for sheet in book.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value == title
    ]
    assert len(cells) == 1
    sheet, head = cells[0]
    below = {
        sheet.cell(i, head.column).value for i in range(head.row + 1, sheet.max_row + 1)
    }
    assert below - {None, ""} == {WORDS}


def test_the_owner_tier_is_not_drawn_as_a_proven_family(owner_world, monkeypatch):
    monkeypatch.setattr(settings, SWITCH, True)
    out = _rerun(owner_world)["rule_trust"]
    assert out["auto_proven"] == 0 and out["audit_sample"] == []
    assert out["labels"][rule_trust.OWNER_APPROVED] == 2


def test_the_run_record_states_who_decided(owner_world, monkeypatch):
    monkeypatch.setattr(settings, SWITCH, True)
    out = _rerun(owner_world)
    tiers = out["rule_trust"]["decided_by_tier"]
    assert tiers == {
        "owner_approved": 1,  # the breach; the safety Pass waits for its tick
        "owner_approved_awaiting_tick": 1,
        "engineer_approved": 0,
    }
    stored = comparison.run_outcome(
        owner_world["run"], allowed_document_ids=owner_world["scope"]
    )
    assert stored["rule_trust"]["decided_by_tier"] == tiers
    note = next(
        n
        for n in rule_trust.review_notes(stored, [])
        if n["note"] == rule_trust.NOTE_OWNER_APPROVED
    )
    assert note["count"] == 1
    assert WORDS in note["detail"]
    assert "0 by engineer-approved rules" in note["detail"]


def test_the_pair_states_owner_approved_apart_from_engineer_approved(
    owner_world, monkeypatch
):
    monkeypatch.setattr(settings, SWITCH, True)
    _rerun(owner_world)
    pair = coverage_pair.for_run(connect(), owner_world["run"], case=None)
    assert pair["decided_by_tier"] == {"owner_approved": 1, "engineer_approved": 0}
    assert pair["decided"] == 1  # the tick row is not among them
    assert f"1 by rules labelled {WORDS}" in pair["line"]
    assert "0 by engineer-approved rules" in pair["line"]
    assert coverage_pair.public_view(pair)["decided_by_tier"] == pair["decided_by_tier"]


def test_an_engineer_approved_rule_beside_it_is_counted_apart(owner_world, monkeypatch):
    """Both switches on: an engineer's rule and the owner's, each in its own count, each in its own words."""
    monkeypatch.setattr(settings, SWITCH, True)
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    chunk = (
        connect()
        .execute(
            "SELECT chunk_id FROM standard_requirements WHERE id = ?",
            (owner_world["limit"],),
        )
        .fetchone()[0]
    )
    fact_chunk = (
        connect()
        .execute("SELECT id FROM chunks WHERE document_id = ? LIMIT 1", (SUB,))
        .fetchone()[0]
    )
    theirs = _req(
        SPEC,
        chunk,
        "The gland length shall not exceed 5 mm.",
        requirement_type="numeric_limit",
        operator="<=",
        value=5.0,
        unit="mm",
        raw_value="5",
        raw_unit="mm",
        field="gland length",
        subject="gland length",
    )
    datasheets.create_fact(
        submittal_document_id=SUB,
        chunk_id=fact_chunk,
        field_label="Gland length",
        raw_value="6 mm",
        page=1,
    )
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at)"
            " VALUES ('eng', 'eng@example.invalid', 'Eng', 'x', ?)",
            (NOW,),
        )
        conn.execute(
            "UPDATE standard_requirements SET confirmed_by = 'eng' WHERE id = ?",
            (theirs,),
        )
    out = _rerun(owner_world)["rule_trust"]["decided_by_tier"]
    assert (out["owner_approved"], out["engineer_approved"]) == (1, 1)
    pair = coverage_pair.for_run(connect(), owner_world["run"], case=None)
    assert pair["decided_by_tier"] == {"owner_approved": 1, "engineer_approved": 1}
    assert "1 by engineer-approved rules" in pair["line"]
    by_row = {
        r["page_section"]: r["rule_trust"]
        for r in _crs(owner_world)["rows"]
        if r["row_kind"] != "safety_tick"
    }
    assert by_row["p.1 - Bonnet thickness"] == WORDS
    assert by_row["p.1 - Gland length"] == "engineer-approved rule"


def test_with_the_switch_on_a_run_with_no_owner_rule_is_byte_identical(
    owner_world, monkeypatch
):
    """No stored record, no "Not checked by any rule" note, no other change: on or off, the same output."""
    owner_world["approved"] = set()
    _rerun(owner_world)
    off = _picture(owner_world)
    off_notes = _crs(owner_world)["review_notes"]
    monkeypatch.setattr(settings, SWITCH, True)
    _rerun(owner_world)
    assert _picture(owner_world) == off
    assert _crs(owner_world)["review_notes"] == off_notes
    assert "rule_trust" not in json.loads(off[2])


CODES = comparison.DEFAULT_CODES
ENOUGH = {"sufficient": True, "extraction_coverage": 1.0}


def _code(*findings, **kw):
    rows = [{"compliance_status": "COMPLIANT"}, *findings]
    return comparison.recommend_code(rows, ENOUGH, codes=CODES, **kw)


def _tick(**extra):
    return {
        "compliance_status": "COMPLIANT",
        "trust_label": rule_trust.OWNER_APPROVED,
        "show_for_engineer_tick": 1,
        **extra,
    }


def test_an_unticked_safety_pass_is_never_an_approved_code():
    assert _code()["code"] == CODES[0]  # the same sheet with no open tick is approved
    out = _code(_tick())
    assert out["code"] == CODES[3]
    assert out["open_safety_ticks"] == 1
    assert "1 safety value" in out["reason"] and "tick" in out["reason"]
    # stored, so it says when it was true: a tick after this time does not rewrite it
    assert re.search(
        r"at \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC, when this review ran", out["reason"]
    )
    assert "waits" not in out["reason"]


def test_an_unticked_safety_pass_is_never_approved_with_comments():
    gap = {"compliance_status": comparison.MISSING_INFORMATION}
    assert _code(gap)["code"] == CODES[1]
    assert _code(gap, _tick())["code"] == CODES[3]


def test_a_ticked_safety_pass_no_longer_holds_the_code():
    assert _code(_tick(confirmed_by="eng"))["code"] == CODES[0]


def test_a_breach_stays_rejected_beside_an_open_tick():
    breach = {"compliance_status": "NON_COMPLIANT"}
    assert _code(breach, _tick())["code"] == CODES[2]


def test_another_labels_tick_is_as_it_was():
    """Only the owner's tier is held here: with this switch off nothing about a code may change."""
    assert _code(_tick(trust_label=rule_trust.AUTO_PROVEN))["code"] == CODES[0]


def test_the_issue_gate_blocks_until_the_owner_rules_safety_pass_is_ticked(
    owner_world, monkeypatch
):
    monkeypatch.setattr(settings, SWITCH, True)
    owner_world["approved"] = {owner_world["limit"]}
    _rerun(owner_world)
    run, client = owner_world["run"], _client(owner_world["scope"])
    fid = _findings(run)[owner_world["limit"]]["id"]
    gate = client.get(f"/api/reviews/runs/{run}/crs/issue-gate").json()
    assert fid in {o["finding_id"] for o in gate["open_findings"]}
    assert gate["issuable"] is False
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at)"
            " VALUES ('eng', 'eng@example.invalid', 'Eng', 'x', ?)",
            (NOW,),
        )
    tick = client.post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision",
        json={
            "decision": "accept",
            "reason": "read the clause and the value on the page",
        },
    )
    assert tick.status_code == 200
    gate = client.get(f"/api/reviews/runs/{run}/crs/issue-gate").json()
    assert fid not in {o["finding_id"] for o in gate["open_findings"]}
    rows = connect().execute(
        "SELECT confirmed_by, show_for_engineer_tick FROM review_findings"
        " WHERE review_run_id = ? AND requirement_id = ?",
        (run, owner_world["limit"]),
    )
    assert [tuple(r) for r in rows] == [("eng", 1)]
    # a re-run keeps the ticked row and writes a new one to tick: its Pass is a new reading of the sheet
    _rerun(owner_world)
    rows = connect().execute(
        "SELECT confirmed_by FROM review_findings"
        " WHERE review_run_id = ? AND requirement_id = ? AND show_for_engineer_tick = 1",
        (run, owner_world["limit"]),
    )
    assert sorted(str(r[0]) for r in rows) == ["None", "eng"]


def test_the_bench_fingerprint_names_the_switch(monkeypatch):
    assert SWITCH in crs_bench.BENCH_SWITCHES
    off = crs_bench.fingerprint()
    monkeypatch.setattr(settings, SWITCH, True)
    assert crs_bench.fingerprint() != off


def test_a_pair_with_no_owner_rule_is_as_it_was(owner_world):
    _rerun(owner_world)
    pair = coverage_pair.for_run(connect(), owner_world["run"], case=None)
    assert "decided_by_tier" not in pair
    assert "owner-approved" not in pair["line"]


_COLUMNS = (
    "requirement_id, fact_id, compliance_status, trust_label, tier, show_for_engineer_tick,"
    " rule_said, ai_rationale, origin"
)


def _picture(world):  # noqa: F811
    rows = connect().execute(
        f"SELECT {_COLUMNS} FROM review_findings WHERE review_run_id = ?"
        " ORDER BY requirement_id, fact_id, origin",
        (world["run"],),
    )
    sheet = _crs(world)
    keep = [
        {k: v for k, v in r.items() if k not in ("finding_id", "row_ref")}
        for r in sheet["rows"]
    ]
    outcome = comparison.run_outcome(world["run"], allowed_document_ids=world["scope"])
    return (
        [tuple(r) for r in rows],
        keep,
        json.dumps(outcome, sort_keys=True, default=str),
    )


def test_off_a_run_with_owner_rules_is_byte_identical(owner_world):
    """Off, the approval on the dict changes nothing at all: findings, CRS rows, the stored outcome."""
    _rerun(owner_world)
    with_approval = _picture(owner_world)
    owner_world["approved"] = set()
    _rerun(owner_world)
    assert _picture(owner_world) == with_approval
    assert "rule_trust" not in json.loads(with_approval[2])
