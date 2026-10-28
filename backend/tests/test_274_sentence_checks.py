"""Order 274.1: the review reads the standards converter's SENTENCE checks.

A clause sentence (requirement_type 'statement') the converter proved - verified, applies "yes" - is compared
through that check in its own place, on the same road as an AI clause-check draft (`auto_use_rules`, owner
decision 14 Oct, `rule_auto_use_enabled`, off by default) and ONLY when `standards_converter_dir` names the
folder of the drafts. Code checks the row again against the sentence stored now; `rule_trust` decides what its
verdict may say: an unproven family never decides (NEEDS_ENGINEER_REVIEW, the arithmetic shown). Invented
standards and an invented sheet only; nothing here calls a model."""

from __future__ import annotations

import json

import pytest

from app import (
    ai_requirements as air,
)
from app import (
    claude_spend,
    comparison,
    converter_review,
    datasheets,
    rule_trust,
    standards_converter,
)
from app.config import settings
from app.db import connect
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixtures
    _chunk,
    _req,
    review_run,
    temp_storage,
)

SPEC, SUB = "spec", "sub"
LABEL = "SPEC-X-valves.pdf"  # the label the review world gives the spec document
PSV = "Pressure Safety Valve"
SENTENCE = "The design pressure shall not exceed 16 barg."
QUOTE = "design pressure shall not exceed 16 barg"
SHA = "b54474a2"


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")


def _row(text: str, **over) -> dict:
    """One converter row for `text`, verified and applies "yes" unless `over` says otherwise."""
    check = standards_converter.Check("design_pressure", "<=", "16", "barg", QUOTE)
    row = standards_converter._row(
        {"requirement_text": text, "clause": "5.1", "requirement_type": "statement"},
        "verified",
        None,
        "yes",
        None,
        check,
    )
    return {**row, **over}


def _mirror(tmp_path, rows, *, standard=LABEL, equipment_type=PSV):
    result = standards_converter.Result(
        standard, equipment_type, rows=rows, model="claude-sonnet-5"
    )
    standards_converter.write(result, tmp_path / "mirror", form_sha=SHA)
    return tmp_path / "mirror"


@pytest.fixture
def cworld(review_run, tmp_path, monkeypatch):  # noqa: F811
    """The review world with one clause sentence and a sheet that states the field it limits."""
    run, ids, scope = review_run
    stmt = _req(SPEC, "sc", SENTENCE, requirement_type="statement")
    datasheets.create_fact(
        submittal_document_id=SUB,
        chunk_id="fc",
        field_label="Design pressure",
        raw_value="15 barg",
        page=1,
    )
    folder = _mirror(tmp_path, [_row(SENTENCE)])
    yield {"run": run, "scope": scope, "stmt": stmt, "folder": folder, "ids": ids}


def _on(cworld, monkeypatch, *, dir_set=True, auto=True):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", auto)
    monkeypatch.setattr(
        settings, "standards_converter_dir", str(cworld["folder"]) if dir_set else ""
    )


def _rules(cworld, equipment_type=PSV, scope=None):
    return converter_review.converter_rules(
        SPEC, equipment_type, allowed_document_ids=scope or cworld["scope"]
    )


def _findings(run):
    return {
        r["requirement_id"]: dict(r)
        for r in connect().execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? AND requirement_id IS NOT NULL",
            (run,),
        )
    }


def _rerun(cworld):
    return comparison.run_comparison(
        cworld["run"], allowed_document_ids=cworld["scope"]
    )


# ------------------------------------------------------------------ 1. what is read, and what is not


def test_a_verified_yes_sentence_check_becomes_a_rule_in_its_sentences_place(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    rules = _rules(cworld)
    assert list(rules) == [cworld["stmt"]]
    rule = rules[cworld["stmt"]]
    assert (
        rule["requirement_type"],
        rule["operator"],
        rule["raw_value"],
        rule["raw_unit"],
    ) == (
        "numeric_limit",
        "<=",
        "16",
        "barg",
    )
    assert (
        rule["value"] == pytest.approx(1.6)
        and rule["unit"] == "MPa"
        and rule["subject"] == "design pressure"
    )
    assert (rule["extraction_method"], rule["confirmed_by"], rule["model"]) == (
        "model",
        None,
        "claude-sonnet-5",
    )
    assert rule["quote"] == QUOTE and rule["rule_draft_id"].startswith("converter:")


def test_nothing_is_read_with_the_folder_unset(cworld, monkeypatch):
    _on(cworld, monkeypatch, dir_set=False)
    assert _rules(cworld) == {}


@pytest.mark.parametrize(
    "over",
    [
        {"status": "unproven", "reason": "no_field"},
        {"status": "not_applicable", "applies": "no"},
        {"applies": "depends", "condition": "for sour service"},
        {"field": None},
        {"text_sha256": "0" * 64},
    ],
)
def test_only_a_verified_yes_row_for_this_sentence_is_read(
    cworld, monkeypatch, tmp_path, over
):
    cworld["folder"] = _mirror(tmp_path / "other", [_row(SENTENCE, **over)])
    _on(cworld, monkeypatch)
    assert _rules(cworld) == {}


def test_a_check_for_another_equipment_type_or_standard_is_not_read(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    assert _rules(cworld, "Pressure Vessel") == {} and _rules(cworld, None) == {}
    other = standards_converter.Result(
        "SAES-G-005", PSV, rows=[_row(SENTENCE)], model="m"
    )
    standards_converter.write(
        other, cworld["folder"].parent / "elsewhere", form_sha=SHA
    )
    monkeypatch.setattr(
        settings, "standards_converter_dir", str(cworld["folder"].parent / "elsewhere")
    )
    assert (
        _rules(cworld) == {}
    )  # the file is for SAES-G-005, this standard is SPEC-X-valves


def test_a_sentence_edited_since_the_draft_is_not_read(cworld, monkeypatch):
    _on(cworld, monkeypatch)
    with connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET requirement_text = ? WHERE id = ?",
            (SENTENCE.replace("16", "10"), cworld["stmt"]),
        )
    assert _rules(cworld) == {}


# ------------------------------------------------------------------ 2. code checks it AGAIN against the stored sentence


def _set_sentence(stmt, text, source=None):
    with connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET requirement_text = ?, source_text = ? WHERE id = ?",
            (text, source or text, stmt),
        )


def test_a_quote_not_in_the_sentence_now_stored_is_refused_by_code(cworld, monkeypatch):
    _on(cworld, monkeypatch)
    with (
        connect() as conn
    ):  # the text hash still matches (requirement_text), the source it came from differs
        conn.execute(
            "UPDATE standard_requirements SET source_text = ? WHERE id = ?",
            ("The design pressure shall be reported.", cworld["stmt"]),
        )
    assert _rules(cworld) == {}


def test_a_sentence_that_holds_only_under_a_condition_is_refused_by_code(
    cworld, monkeypatch, tmp_path
):
    conditional = "For sour service the design pressure shall not exceed 16 barg."
    _set_sentence(cworld["stmt"], conditional)
    cworld["folder"] = _mirror(tmp_path / "cond", [_row(conditional)])
    _on(cworld, monkeypatch)
    assert _rules(cworld) == {}


@pytest.mark.parametrize(
    "tail",
    [
        " for services other than sour service.",
        " for pumps of the vertical type.",
        " when the pump runs at rated flow.",
    ],
)
def test_a_scope_written_after_the_limit_is_refused_by_the_review_even_in_an_old_file(
    cworld, monkeypatch, tmp_path, tail
):
    """s3 on #1412: `ai_requirements.limit_from_draft` accepts the first two as an unconditional limit (it reads
    leading conditions); a file made before the converter's own gate, or edited by hand, must not carry one in."""
    sentence = f"The design pressure shall not exceed 16 barg{tail}"
    _set_sentence(cworld["stmt"], sentence)
    cworld["folder"] = _mirror(tmp_path / "scope", [_row(sentence)])
    _on(cworld, monkeypatch)
    assert _rules(cworld) == {}


@pytest.mark.parametrize(
    "tail", [".", " at the discharge flange.", " measured at the inlet.", " (232 psi)."]
)
def test_a_location_or_a_bracketed_conversion_after_the_limit_is_kept(
    cworld, monkeypatch, tmp_path, tail
):
    """A location is not a case: said here so nobody tightens it by accident (it would send most clauses to
    the engineer)."""
    sentence = f"The design pressure shall not exceed 16 barg{tail}"
    _set_sentence(cworld["stmt"], sentence)
    cworld["folder"] = _mirror(tmp_path / "loc", [_row(sentence)])
    _on(cworld, monkeypatch)
    assert list(_rules(cworld)) == [cworld["stmt"]]


def test_an_operator_that_points_the_other_way_is_refused_by_code(
    cworld, monkeypatch, tmp_path
):
    other_way = "The design pressure shall be at least 16 barg."
    _set_sentence(cworld["stmt"], other_way)
    row = _row(other_way)
    row["quote"] = "design pressure shall be at least 16 barg"
    cworld["folder"] = _mirror(
        tmp_path / "way", [row]
    )  # the file says "<=" for a sentence that says "at least"
    _on(cworld, monkeypatch)
    assert _rules(cworld) == {}


# ------------------------------------------------------------------ 3. the road: drafts first, switches, the review itself


def test_the_rule_is_given_only_with_both_switches_and_the_standard_in_scope(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    assert list(_rules(cworld)) == [cworld["stmt"]]
    assert (
        _rules(cworld, scope=frozenset({"nace"})) == {}
    )  # the standard is not in the reader's scope
    _on(cworld, monkeypatch, auto=False)
    assert _rules(cworld) == {}
    _on(cworld, monkeypatch, dir_set=False)
    assert _rules(cworld) == {}


def test_an_ai_clause_check_draft_for_the_same_sentence_wins(cworld, monkeypatch):
    """The draft's model is "local" and only "local" has a proof: the finding is AUTO_PROVEN only if the
    DRAFT stood in the sentence's place, not the converter's rule (model claude-sonnet-5, no proof)."""
    _on(cworld, monkeypatch)
    air.ensure_schema()
    with connect() as conn:
        conn.execute(
            "INSERT INTO clause_check_drafts (id, requirement_id, field, operator, value, unit, condition, quote, model)"
            " VALUES ('draft-1', ?, 'design pressure', '<=', '16', 'barg', NULL, ?, 'local')",
            (cworld["stmt"], QUOTE),
        )
    result = {"cases": 1, "correct": 1, "errors": [], "status": rule_trust.PROVEN}
    rule_trust.save_proof(
        rule_trust.family_key(SPEC, PSV),
        result,
        model_id="local",
        standard_revision=None,
    )
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert (
        row["trust_label"] == rule_trust.AUTO_PROVEN
        and row["compliance_status"] == "COMPLIANT"
    )


def test_off_the_sentence_is_compared_as_a_sentence_exactly_as_before(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch, dir_set=False, auto=False)
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert row["rule_said"] is None and row["trust_label"] is None
    assert (
        row["compliance_status"] != "COMPLIANT"
    )  # a sentence with no limit decides nothing


def test_the_folder_alone_without_the_auto_use_switch_changes_nothing(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch, dir_set=False, auto=False)
    _rerun(cworld)
    before = _findings(cworld["run"])[cworld["stmt"]]["compliance_status"]
    _on(cworld, monkeypatch, auto=False)
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert row["rule_said"] is None and row["trust_label"] is None
    # without the owner's switch there is no `rule_trust`: a converted rule would decide on the AI's word alone
    assert row["compliance_status"] == before != "COMPLIANT"


def test_on_an_unproven_family_the_sentence_check_is_compared_but_never_decides(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    out = _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    # the sheet states 15 barg against "not more than 16 barg": the rule says COMPLIANT, and is held for an engineer
    assert (row["compliance_status"], row["rule_said"], row["trust_label"]) == (
        "NEEDS_ENGINEER_REVIEW",
        "COMPLIANT",
        rule_trust.UNPROVEN,
    )
    assert rule_trust.UNPROVEN_REASON in row["ai_rationale"]
    assert out["rule_trust"]["held_unproven"] >= 1


def test_on_a_proven_family_under_the_converters_model_the_verdict_stands(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    key = rule_trust.family_key(SPEC, PSV)
    result = {"cases": 1, "correct": 1, "errors": [], "status": rule_trust.PROVEN}
    rule_trust.save_proof(
        key, result, model_id="claude-sonnet-5", standard_revision=None
    )
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert (row["compliance_status"], row["trust_label"]) == (
        "COMPLIANT",
        rule_trust.AUTO_PROVEN,
    )
    # a proof made for another model does not cover the converter's rule
    rule_trust.save_proof(key, result, model_id="another-model", standard_revision=None)
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert (row["compliance_status"], row["trust_label"]) == (
        "NEEDS_ENGINEER_REVIEW",
        rule_trust.UNPROVEN,
    )


def test_a_value_over_the_limit_is_held_never_a_pass(cworld, monkeypatch):
    with connect() as conn:
        conn.execute(
            "DELETE FROM submittal_facts WHERE field_label = 'Design pressure'"
        )
    datasheets.create_fact(
        submittal_document_id=SUB,
        chunk_id="fc",
        field_label="Design pressure",
        raw_value="20 barg",
        page=1,
    )
    _on(cworld, monkeypatch)
    _rerun(cworld)
    row = _findings(cworld["run"])[cworld["stmt"]]
    assert (
        row["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
        and row["rule_said"] == "NON_COMPLIANT"
    )


def test_the_scope_ledger_still_ends_every_requirement_in_one_state(
    cworld, monkeypatch
):
    _on(cworld, monkeypatch)
    out = _rerun(cworld)
    assert (
        out["scope"]["in_scope"] >= 6
    )  # the five of the world and the converted sentence, none lost or doubled


def test_the_spend_ledger_is_untouched_by_reading_a_draft(cworld, monkeypatch):
    _on(cworld, monkeypatch)
    _rerun(cworld)
    assert (
        claude_spend.entries() == []
    )  # the review reads a file; it never calls Claude


def test_the_draft_file_is_never_modified_by_a_review(cworld, monkeypatch):
    _on(cworld, monkeypatch)
    path = next(cworld["folder"].glob("*.json"))
    before = path.read_bytes()
    _rerun(cworld)
    assert path.read_bytes() == before and json.loads(before)["converter"] is True


# ------------------------------------------------------------------ 6. two rows for one sentence (cloud-3 on #1412)


def _second_file(cworld, tmp_path, name, **over):
    """A second draft file in the same folder holding the same sentence, optionally saying something else."""
    other = _mirror(
        tmp_path / name,
        [_row(SENTENCE, **over)],
    )
    for f in other.glob("*.json"):
        (cworld["folder"] / f"{name}.json").write_text(f.read_text())


def test_two_files_that_disagree_on_one_sentence_are_used_by_neither_in_any_order(
    cworld, monkeypatch, tmp_path
):
    _on(cworld, monkeypatch)
    assert list(_rules(cworld)) == [cworld["stmt"]]
    for name in (
        "a-first",
        "zz-last",
    ):  # the extra file sorts before, then after, the first
        _second_file(cworld, tmp_path, name, limit="10")
        assert _rules(cworld) == {}, name
        (cworld["folder"] / f"{name}.json").unlink()
    assert list(_rules(cworld)) == [cworld["stmt"]]


def test_two_files_that_say_the_same_thing_still_give_the_rule(
    cworld, monkeypatch, tmp_path
):
    _on(cworld, monkeypatch)
    _second_file(cworld, tmp_path, "same")
    assert list(_rules(cworld)) == [cworld["stmt"]]


# ------------------------------------------------------------------ 7. "applies: no" never drops a rule (s2 on SAES-K-503)


def _what_the_review_said(run):
    return {
        req: (row["compliance_status"], row["rule_said"], row["trust_label"])
        for req, row in _findings(run).items()
    }


@pytest.mark.parametrize(
    "over",
    [
        {"status": "not_applicable", "applies": "no", "field": None, "limit": None},
        {"status": "unproven", "applies": "yes"},
        {"status": "not_asked", "applies": None, "field": None, "limit": None},
    ],
)
def test_a_row_that_is_not_verified_yes_changes_nothing_in_the_review(
    cworld, monkeypatch, tmp_path, over
):
    """The model's "applies: no" (or an unproven, or a not-asked row) must never remove a rule from scope or
    move a verdict: with the folder and the auto-use switch on, the review says exactly what it says with
    the folder off."""
    _on(cworld, monkeypatch, dir_set=False)
    _rerun(cworld)
    off = _what_the_review_said(cworld["run"])
    cworld["folder"] = _mirror(tmp_path / "other", [_row(SENTENCE, **over)])
    _on(cworld, monkeypatch)
    _rerun(cworld)
    assert _what_the_review_said(cworld["run"]) == off
