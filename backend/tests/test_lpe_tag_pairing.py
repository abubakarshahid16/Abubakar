"""LPE (owner, 17 Nov 2026): with `equipment_rule_books_enabled` ON, the rule check pairs a rule with a field of the paper ONLY
when the rule's equipment tag fits the paper's equipment (the AI reviewer's own `equipment_decision`).

Found on live update 19a: the books the route `equipment_rules` kept were matched by the old field matcher, one field word at a
time, with unrelated rules (a grout manufacturer's rule on the pump manufacturer, a fire-hydrant barrel on a pump barrel, a
painting pressure on a relief valve's operating pressure). Now: a rule the AI reviewer's filter leaves out (another equipment, or
a tagged rule on a paper whose equipment is not usable) is paired with no field in any book; a book kept ONLY by that route pairs
none of its rules (the AI reviewer reads them); a general or untagged rule of a cited book pairs as before; switch OFF changes
nothing. No tier pairs a marked rule: containment (`_resolve_hits`), the field-name tier, the AI matcher (never asked), a table
rule's output field. Invented documents and values only."""

from __future__ import annotations

import uuid

import pytest

from app import (
    absence,
    comparison,
    datasheets,
    db,
    rule_equipment,
    rule_eval,
    standards,
    submittal_review,
)
from app import (
    equipment_rule_books as erb,
)
from app.config import settings

NOW = "2026-11-17T00:00:00Z"
STD, SUB = "std-lpe", "sub-lpe"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "lpe.sqlite")
    for name in (
        "geometry_reader_enabled",
        "field_naming_enabled",
        "match_enabled",
        "ai_clause_checks_enabled",
    ):
        monkeypatch.setattr(settings, name, False)
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "equipment_rule_books_enabled", True)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    rule_equipment.create_tables(db.connect())
    with db.connect() as conn:
        for doc_id, role, equipment in (
            (STD, "COMPANY_STANDARD", None),
            (SUB, "CONTRACTOR_SUBMITTAL", "pump"),
        ):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,document_role,equipment_type)"
                " VALUES (?,?,?,?)",
                (doc_id, "test", role, equipment),
            )
        for chunk_id, doc_id in (("sc", STD), ("fc", SUB)):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,token_count,"
                "content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
                (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"),
            )
    yield
    db.reset_connection()


def _label(rule_id: str, *, typ=None, fam=None, general=0, state="agreed") -> None:
    agreed = state == "agreed"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO rule_equipment_label (source, rule_ref, equip_family, equip_type, equip_general, equip_state,"
            " model_a, model_b, prompt_version, list_sha, labelled_at) VALUES ('requirement', ?, ?, ?, ?, ?, ?, ?, ?, ?, 't')",
            (rule_id, fam, typ, general, state, "model-one" if agreed else None, "model-two" if agreed else None,
             "p1" if agreed else None, "a" * 64 if agreed else None),
        )  # fmt: skip


def _limit(subject: str, value: str, unit: str) -> dict:
    return {"subject": subject, "operator": "<=", "raw_value": value, "raw_unit": unit,
            "requirement_type": "numeric_limit"}  # fmt: skip


RATED_FLOW = (
    "The rated flow shall not exceed 100 m3/h.",
    _limit("the rated flow", "100", "m3/h"),
)
NO_FIELD = (
    "The suction margin shall not exceed 3 m.",
    _limit("the suction margin", "3", "m"),
)


def _rule(text_structured=RATED_FLOW, **label) -> dict:
    text, structured = text_structured
    req = standards.create_requirement(
        standard_document_id=STD, chunk_id="sc", requirement_text=text, source_text=text, clause="4.1", page=1,
        structured=structured,
    )  # fmt: skip
    if label:
        _label(req["id"], **label)
    return req


def _run(method: str = "equipment_rules") -> str:
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at) VALUES (?,?,'pending',?,?)",
            (run_id, SUB, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
            "selection_method,included,created_at) VALUES (?,?,?,'invented','"
            + method
            + "',1,?)",
            (str(uuid.uuid4()), run_id, STD, NOW),
        )
    return run_id


def _flow_fact() -> dict:
    return datasheets.create_fact(
        submittal_document_id=SUB,
        chunk_id="fc",
        field_label="Rated flow",
        raw_value="80 m3/h",
        page=1,
    )


def _finding(run_id: str, req: dict) -> dict:
    found = [
        f
        for f in comparison.run_comparison(
            run_id, allowed_document_ids=frozenset({STD, SUB})
        )["findings"]
        if f.get("requirement_id") == req["id"]
    ]
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------- the one decision
@pytest.mark.parametrize(
    "method, label, code",
    [
        (
            "referenced",
            {"typ": "motor", "fam": "rotating"},
            erb.OTHER_EQUIPMENT,
        ),  # another type: in any book
        ("equipment_rules", {"typ": "motor", "fam": "rotating"}, erb.OTHER_EQUIPMENT),
        (
            "referenced",
            {"typ": "pump", "fam": "rotating"},
            None,
        ),  # the paper's own: a cited book pairs it
        (
            "referenced",
            {"general": 1},
            None,
        ),  # general: a cited book pairs it as before
        ("referenced", {"state": "needs_human"}, None),  # not agreed: as before
        ("referenced", {}, None),  # no label at all: as before
        ("scope", {}, None),
        ("governing_standard", {"general": 1}, None),
        (
            "equipment_rules",
            {"typ": "pump", "fam": "rotating"},
            erb.BOOK_KEPT_BY_TAGS,
        ),  # a book kept only by tags: none
        ("equipment_rules", {"general": 1}, erb.BOOK_KEPT_BY_TAGS),
        ("equipment_rules", {}, erb.BOOK_KEPT_BY_TAGS),
    ],
)
def test_the_gate_follows_the_ai_reviewers_equipment_decision(
    world, method, label, code
):
    req, run_id = _rule(**label), _run(method)
    [marked] = erb.mark_unpaired(db.connect(), SUB, run_id, [req])
    assert marked.get(erb.NOT_PAIRED) == code


def test_a_tagged_rule_on_a_paper_whose_equipment_is_not_known_is_not_paired(world):
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = NULL WHERE document_id = ?",
            (SUB,),
        )
    req, run_id = _rule(typ="pump", fam="rotating"), _run("referenced")
    [marked] = erb.mark_unpaired(db.connect(), SUB, run_id, [req])
    assert marked[erb.NOT_PAIRED] == erb.PAPER_EQUIPMENT_UNKNOWN


def test_switch_off_marks_nothing_and_returns_the_same_list(world, monkeypatch):
    monkeypatch.setattr(settings, "equipment_rule_books_enabled", False)
    req, run_id = _rule(typ="motor", fam="rotating"), _run("equipment_rules")
    rows = [req]
    assert erb.pairing_gate(db.connect(), SUB, run_id) is None
    assert erb.mark_unpaired(db.connect(), SUB, run_id, rows) is rows


# ---------------------------------------------------------------- every pairing tier reads it
def test_containment_pairs_no_field_with_a_rule_of_a_book_kept_only_by_tags(world):
    """THE LIVE DEFECT: a field word matched a rule of a book the route kept; now nothing is paired."""
    req, _fact, run_id = (
        _rule(typ="pump", fam="rotating"),
        _flow_fact(),
        _run("equipment_rules"),
    )
    found = _finding(run_id, req)
    assert found["fact_id"] is None and found["match_method"] is None
    assert (
        found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    )  # never the contractor's omission
    assert found["ai_rationale"].startswith(comparison.PAIRING_NOT_CHECKED)
    assert erb.BOOK_KEPT_BY_TAGS in found["ai_rationale"]


def test_containment_pairs_no_field_with_a_rule_for_another_equipment_of_a_cited_book(
    world,
):
    req, _fact, run_id = (
        _rule(typ="motor", fam="rotating"),
        _flow_fact(),
        _run("referenced"),
    )
    found = _finding(run_id, req)
    assert found["fact_id"] is None and erb.OTHER_EQUIPMENT in found["ai_rationale"]


def test_a_general_rule_of_a_cited_book_still_pairs_and_decides(world):
    """What was right stays right: the cited book's general rule meets the field and code decides."""
    req, fact, run_id = _rule(general=1), _flow_fact(), _run("referenced")
    found = _finding(run_id, req)
    assert (
        found["fact_id"] == fact["id"]
        and found["match_method"] == comparison.METHOD_CONTAINMENT
    )
    assert found["compliance_status"] == comparison.COMPLIANT


def test_switch_off_a_rule_of_a_book_kept_by_tags_pairs_as_before(world, monkeypatch):
    monkeypatch.setattr(settings, "equipment_rule_books_enabled", False)
    req, fact, run_id = (
        _rule(typ="motor", fam="rotating"),
        _flow_fact(),
        _run("equipment_rules"),
    )
    assert _finding(run_id, req)["fact_id"] == fact["id"]


def test_the_ai_matcher_is_never_asked_about_a_marked_rule(world, monkeypatch):
    monkeypatch.setattr(settings, "match_enabled", True)
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)
    asked: list[str] = []

    def proposes(requirement, facts, **_kw):
        asked.append(requirement["id"])
        return {"fact": facts[0], "matched_phrase": facts[0]["field_name"], "method": comparison.METHOD_MODEL_CHOICE,
                "reason": "invented", "candidates": []}  # fmt: skip

    monkeypatch.setattr(comparison, "match_by_model", proposes)
    req, _fact, run_id = (
        _rule(NO_FIELD, typ="pump", fam="rotating"),
        _flow_fact(),
        _run("equipment_rules"),
    )
    found = _finding(run_id, req)
    assert asked == [] and found["fact_id"] is None
    # not "no field answers this": the step decided not to pair, and says why
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert erb.NOT_PAIRED_WORDS[erb.BOOK_KEPT_BY_TAGS] in found["ai_rationale"]


def test_the_ai_matcher_is_still_asked_about_a_rule_of_a_cited_book(world, monkeypatch):
    monkeypatch.setattr(settings, "match_enabled", True)
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)
    asked: list[str] = []
    monkeypatch.setattr(comparison, "match_by_model", lambda r, f, **_k: asked.append(r["id"]) or comparison._none_match(
        comparison.MODEL_DECLINED))  # fmt: skip
    req, _fact, run_id = _rule(NO_FIELD, general=1), _flow_fact(), _run("referenced")
    _finding(run_id, req)
    assert asked == [req["id"]]


def test_the_field_name_tier_pairs_no_field_with_a_marked_rule(world, monkeypatch):
    from app import field_vocabulary

    monkeypatch.setattr(settings, "field_naming_enabled", True)
    req, fact, run_id = (
        _rule(typ="pump", fam="rotating"),
        _flow_fact(),
        _run("equipment_rules"),
    )
    names = {
        "requirements": {req["id"]: "rated_flow"},
        "facts": {fact["id"]: "rated_flow"},
    }
    monkeypatch.setattr(field_vocabulary, "names_for", lambda *_a, **_k: names)
    found = _finding(run_id, req)
    assert found["fact_id"] is None and found["match_method"] is None


def test_resolve_hits_refuses_every_hit_of_a_marked_rule_by_its_code():
    req = {
        "id": "r",
        "requirement_type": "numeric_limit",
        "raw_value": "1",
        erb.NOT_PAIRED: erb.OTHER_EQUIPMENT,
    }
    fact = {"id": "f", "field_name": "rated flow", "raw_value": "1", "raw_unit": None}
    hit = {
        "fact": fact,
        "name": "rated flow",
        "key": "rated flow",
        "item": None,
        "synonym": None,
    }
    out = comparison._resolve_hits(req, [fact], [hit], sheet_kind=None)
    assert out["fact"] is None and out["reason"] == comparison.REFUSED_BY_RULE
    assert out["refused"] == [{"name": "rated flow", "reason": erb.OTHER_EQUIPMENT}]


def test_a_table_rule_pairs_no_output_field_when_marked():
    req = {
        "requirement_type": "table_row",
        "rule_json": '{"output": "design pressure"}',
        erb.NOT_PAIRED: "x",
    }
    assert rule_eval.rule_for(req) == (None, None)
    assert rule_eval.rule_for({k: v for k, v in req.items() if k != erb.NOT_PAIRED})[
        0
    ] == {"output": "design pressure"}


@pytest.mark.parametrize("code", sorted(erb.NOT_PAIRED_WORDS))
def test_each_code_is_a_step_that_decided_not_to_pair_never_an_absence(code):
    assert absence.pairing_not_checked(None, code, None) == erb.NOT_PAIRED_WORDS[code]
