"""Orders 180 / 180.1 (items 1 and 7): which standard sentences may stand behind a row.

A sentence that states no requirement (a list of items with no must, shall,
limit or number) is never a supporting clause; a sentence that names its own
service, application or seal plan applies only when the datasheet states the
same one, else it is held for the engineer. Invented standard text and sheets
only (rule 13).
"""

from __future__ import annotations

import uuid

import pytest

from app import (
    clause_support,
    comparison,
    datasheets,
    db,
    scope_ledger,
    service_scope,
    standards,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-20T00:00:00Z"


def req(rid, text, kind="statement"):
    return {
        "id": rid,
        "requirement_type": kind,
        "source_text": text,
        "requirement_text": text,
    }


def fact(label, value, blank=False):
    return {"field_label": label, "raw_value": value, "is_blank": blank}


LIST = req("l", "Gaskets, bolts, studs, nuts and flange protectors.")
SHALL = req("s", "Gaskets, bolts, studs and nuts shall be supplied.")
NUMBER = req("n", "Gaskets, bolts, studs, 4 pieces.")
ONE_ITEM = req("o", "Gaskets and bolts.")
TABLE = req("t", "Gaskets, bolts, studs, nuts.", kind="table_row")


# ------------------------------------------------------------- rule 1: no requirement


def test_a_list_with_no_requirement_word_and_no_number_states_no_requirement():
    assert clause_support.states_no_requirement(LIST)


@pytest.mark.parametrize("r", [SHALL, NUMBER, ONE_ITEM, TABLE])
def test_a_sentence_with_a_requirement_word_a_number_one_item_or_another_type_is_kept(
    r,
):
    assert not clause_support.states_no_requirement(r)


@pytest.mark.parametrize(
    "word",
    [
        "shall",
        "must",
        "should",
        "is required",
        "are to be",
        "not less than",
        "minimum",
        "only",
    ],
)
def test_every_requirement_word_keeps_the_sentence(word):
    assert not clause_support.states_no_requirement(
        req("x", f"Gaskets {word} fit, bolts, studs, nuts")
    )


def test_the_gate_holds_a_list_with_its_reason_and_keeps_the_rest():
    out = clause_support.gate([LIST, SHALL], facts=[fact("Type", "centrifugal")])
    assert [r["id"] for r in out["kept"]] == ["s"]
    [item] = out["held"]
    # unsure is held, never excluded (order 143)
    assert item["code"] == "applicability_unsure"
    assert "states no requirement" in item["detail"]
    assert "items" not in out


@pytest.mark.parametrize(
    "text",
    [
        "Provide a drain, a vent, and a pressure gauge connection on the casing.",
        "Equip the casing with a drain, a vent and a gauge connection.",
        "The casing includes a drain, a vent, and a gauge connection.",
        "Fit a drain, vent and gauge connection.",
        "Supply gaskets, bolts, and studs with each flange.",
        "Seal flush lines shall be tubing, valves, and fittings.",
    ],
)
def test_a_sentence_with_an_obligation_or_an_imperative_verb_is_not_a_list(text):
    assert not clause_support.states_no_requirement(req("x", text))


# ------------------------------------------------- rule 2: a service the sheet must state


SEAL = req("p", "The seal flush shall follow Plan 32 with a clean external fluid.")
DUTY = req("d", "Bearings shall be oil lubricated for main firewater pumps.")
APP = req(
    "a", "Wetted parts shall be corrosion resistant for molten sulfur application."
)
GENERIC_PHRASE = req("g", "The pump shall be suitable for continuous service.")
FACTS = [fact("Service", "crude oil transfer"), fact("Seal plan", "Plan 11")]


def test_a_named_service_plan_or_duty_is_read_from_the_sentences_own_words():
    assert clause_support.named_conditions(SEAL) == ["plan 32"]
    assert clause_support.named_conditions(DUTY) == ["firewater"]
    assert clause_support.named_conditions(APP) == ["molten sulfur"]
    assert clause_support.named_conditions(GENERIC_PHRASE) == []


def test_a_sentence_naming_a_service_the_sheet_does_not_state_is_held_not_listed():
    out = clause_support.gate([SEAL, DUTY, APP, GENERIC_PHRASE], facts=FACTS)
    assert [r["id"] for r in out["kept"]] == ["g"]
    assert {h["requirement"]["id"] for h in out["held"]} == {"p", "d", "a"}
    assert {h["code"] for h in out["held"]} == {"service_unknown"}
    assert any('"plan 32"' in h["detail"] for h in out["held"])


def test_a_service_word_inside_a_longer_word_or_split_across_fields_is_not_stated():
    water = req("w", "Seals shall be flushed for water service.")
    assert clause_support.named_conditions(water) == ["water"]
    assert clause_support.gate([water], facts=[fact("Fluid", "seawater")])["held"]
    split = req("m", "Parts shall resist corrosion in molten sulfur application.")
    apart = [fact("Medium", "molten salt"), fact("Contaminant", "sulfur")]
    assert clause_support.gate([split], facts=apart)["held"]
    assert (
        clause_support.gate([split], facts=[fact("Medium", "Molten sulfur")])["held"]
        == []
    )
    assert (
        clause_support.gate([water], facts=[fact("Fluid", "water, treated")])["held"]
        == []
    )


def test_the_same_service_on_the_sheet_keeps_the_sentence():
    facts = [fact("Seal plan", "Plan 32"), fact("Duty", "main firewater duty")]
    assert [
        r["id"] for r in clause_support.gate([SEAL, DUTY], facts=facts)["kept"]
    ] == [
        "p",
        "d",
    ]


def test_a_blank_field_states_nothing_and_a_sheet_with_no_text_holds_nothing():
    assert clause_support.sheet_text([fact("Seal plan", "Plan 32", blank=True)]) == ""
    assert clause_support.gate([SEAL], facts=[])["held"] == []


def test_the_service_gate_carries_both_results_to_the_run():
    out = service_scope.gate([LIST, SEAL, SHALL], facts=FACTS)
    assert [r["id"] for r in out["kept"]] == ["s"]
    assert out["items"] == []
    assert [h["requirement"]["id"] for h in out["held"]] == ["l", "p"]


# ------------------------------------------------------------------- on a review


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "support.sqlite")
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    monkeypatch.setattr(settings, "ai_division_scope_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, text, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,?,?,?,0,0)",
            (doc_id, 1, text, len(text)),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose',"
            "?,1,?,1)",
            (f"{doc_id}-1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )


def test_a_review_holds_a_list_and_a_sentence_for_another_service(
    temp_storage,
):
    _doc("std", "COMPANY_STANDARD", "x", document_number="STD-1")
    _doc(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        "Fittings\nSeal plan Plan 11\n",
        equipment_type="Pump",
    )
    ids = {}
    for key, text in (
        ("list", "Gaskets, bolts, studs, nuts and flange protectors."),
        ("plan", "The seal flush shall follow Plan 32 with a clean external fluid."),
        ("plain", "The seal flush shall follow Plan 11."),
    ):
        ids[key] = standards.create_requirement(
            standard_document_id="std",
            chunk_id="std-1",
            clause=None,
            page=1,
            requirement_text=text,
            source_text=text,
            structured={"requirement_type": "statement"},
        )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Seal plan",
        raw_value="Plan 11",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES (?,?,?,'manual',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({"std", "sub"})
    )
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    assert stored[ids["list"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert stored[ids["list"]]["reason_code"] == "applicability_unsure"
    assert "states no requirement" in stored[ids["list"]]["reason"]
    assert stored[ids["plan"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert stored[ids["plan"]]["reason_code"] == "service_unknown"
    assert "plan 32" in stored[ids["plan"]]["reason"]
    assert stored[ids["plain"]]["state"] == scope_ledger.CHECKED
    assert not any(f.get("requirement_id") == ids["list"] for f in result["findings"])
    # order 210 fix 3: the held sentence reaches the engineer as a row, not a pass
    (row,) = [f for f in result["findings"] if f.get("requirement_id") == ids["plan"]]
    assert row["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_a_service_the_vocabulary_already_decides_is_left_to_it():
    sour = req("m", "Materials for sour service shall resist cracking.")
    facts = [fact("H2S service", "Yes")]
    assert [r["id"] for r in service_scope.gate([sour], facts=facts)["kept"]] == ["m"]
    # the same sentence, with the vocabulary not told about it, would be held
    assert clause_support.hold_unstated_services([sour], facts=facts)["held"]
