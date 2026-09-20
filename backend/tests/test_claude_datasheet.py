"""`claude_datasheet`: the model proposes datasheet facts, Python verifies.

Every test runs against a FAKE MODEL - a callable returning a string - and
none opens a socket. The gate is exercised through `accept` and `read_page`,
and the storage path through a real ingested one-page PDF, exactly as
`test_datasheets.py` builds one.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app import claude_datasheet as cd
from app import datasheets, db, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "cd.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


PAGE = """PRESSURE SAFETY VALVE DATASHEET            Page 1 of 1
5 | Design/Operating pressure | 23.5 / 9 barg (Note - 3)
8 | Set pressure | 340 psig
9 | Relieving temperature | 121 C
12 | Casing material | Carbon steel
Required flow      Offered flow
9,970 kg/hr        10,200 kg/hr
Hydrotest result: 51 barg held for 30 min
"""


def _fact(field, value, quote, unit=None, kind="offered"):
    return {"field": field, "value": value, "unit": unit, "quote": quote, "kind": kind}


def _answer(*facts):
    return json.dumps({"facts": list(facts)})


def _fake(*facts):
    """A model that always answers the same thing."""
    text = _answer(*facts)
    return lambda prompt: text


def _scope(*ids): return frozenset(ids)


# ------------------------------------------------------------------ prompt

def test_the_prompt_carries_the_page_and_the_skip_list():
    prompt = cd.build_prompt(PAGE, 3, ["Set pressure", "Casing material"])
    assert "PAGE 3:" in prompt
    assert "340 psig" in prompt
    assert "SKIP THESE FIELDS" in prompt
    assert "- Set pressure" in prompt and "- Casing material" in prompt
    for kind in cd.KINDS:
        assert kind in prompt


def test_the_prompt_has_no_skip_list_when_nothing_is_known():
    assert "SKIP THESE FIELDS" not in cd.build_prompt(PAGE, 1, [])


# ------------------------------------------------------------------- parse

def test_non_json_is_model_malformed():
    proposals, err = cd.parse_response("Sure! Here are the facts:")
    assert proposals == [] and err == cd.Reason.MODEL_MALFORMED.value


def test_json_without_a_facts_list_is_malformed():
    assert cd.parse_response(json.dumps({"rows": []}))[1] == cd.Reason.MODEL_MALFORMED.value


def test_a_bare_single_fact_is_accepted_as_one_proposal():
    proposals, err = cd.parse_response(json.dumps(_fact("Set pressure", "340", "Set pressure | 340 psig")))
    assert err is None and len(proposals) == 1
    assert proposals[0]["field"] == "Set pressure"


def test_an_entry_with_no_quote_is_not_a_proposal():
    proposals, _ = cd.parse_response(_answer({"field": "Set pressure", "value": "340", "kind": "offered"}))
    assert proposals == []


# ---------------------------------------------------------------- the gate

def _gate(*facts, known=None):
    proposals, _ = cd.parse_response(_answer(*facts))
    return cd.accept(proposals, PAGE, known or [])


def test_a_true_reading_passes_the_gate():
    out = _gate(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"))
    assert len(out["accepted"]) == 1 and out["rejected"] == []
    assert out["accepted"][0]["field_name"] == "set pressure"


def test_a_quote_not_on_the_page_is_rejected():
    out = _gate(_fact("Set pressure", "340", "Set pressure shall be 340 psig", unit="psig"))
    assert out["accepted"] == []
    assert out["counts"] == {cd.Reason.QUOTE_NOT_ON_PAGE.value: 1}


def test_a_quote_is_matched_whitespace_and_case_folded():
    out = _gate(_fact("Set pressure", "340", "8 |   SET PRESSURE |\n340 psig", unit="psig"))
    assert len(out["accepted"]) == 1


def test_a_value_not_in_the_quote_is_rejected():
    out = _gate(_fact("Set pressure", "350", "8 | Set pressure | 340 psig", unit="psig"))
    assert out["counts"] == {cd.Reason.VALUE_NOT_IN_QUOTE.value: 1}


def test_a_thousands_separator_is_not_a_different_number():
    quote = "Required flow      Offered flow\n9,970 kg/hr"
    out = _gate(_fact("Required flow", "9970", quote, kind="required"))
    assert len(out["accepted"]) == 1
    # The same row with its printed unit: `claims` does not know "kg/hr"
    # (measured, see `datasheets.measure_value`), so the gate names THAT and
    # not the number.
    out = _gate(_fact("Required flow", "9970", quote, unit="kg/hr", kind="required"))
    assert out["counts"] == {cd.Reason.UNIT_UNRECOGNISED.value: 1}


def test_a_field_not_in_the_quote_is_rejected():
    out = _gate(_fact("Relieving temperature", "340", "8 | Set pressure | 340 psig", unit="psig"))
    assert out["counts"] == {cd.Reason.FIELD_NOT_IN_QUOTE.value: 1}


def test_the_field_check_is_lenient_about_the_labels_spelling():
    """The sheet writes "Design/Operating pressure (Note - 3)"; the model
    answers "Design pressure". One noun in common is enough."""
    out = _gate(_fact("Design pressure", "23.5", "Design/Operating pressure | 23.5 / 9 barg", unit="barg"))
    assert len(out["accepted"]) == 1


def test_an_unrecognised_unit_is_rejected_but_a_null_unit_is_fine():
    bad = _gate(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="furlongs"))
    assert bad["counts"] == {cd.Reason.UNIT_UNRECOGNISED.value: 1}
    none = _gate(_fact("Casing material", "Carbon steel", "12 | Casing material | Carbon steel"))
    assert len(none["accepted"]) == 1 and none["accepted"][0]["unit"] is None


def test_a_unit_with_no_dimension_but_in_the_recognised_set_passes():
    out = _gate(_fact("Chloride content", "50", "chloride content 50 ppm", unit="ppm"))
    # ppm has no dimension in `claims` and is still a unit - but the quote is
    # not on this page, so the rejection must be the quote's, not the unit's.
    assert out["counts"] == {cd.Reason.QUOTE_NOT_ON_PAGE.value: 1}


def test_a_field_the_extractor_already_found_is_already_extracted():
    out = _gate(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"),
                known=["SET PRESSURE:"])
    assert out["counts"] == {cd.Reason.ALREADY_EXTRACTED.value: 1}


def test_field_and_value_missing_are_named():
    out = _gate({"field": "", "value": "340", "quote": "340 psig", "kind": "offered"},
                {"field": "Set pressure", "value": None, "quote": "340 psig", "kind": "offered"})
    assert out["counts"] == {cd.Reason.FIELD_MISSING.value: 1, cd.Reason.VALUE_MISSING.value: 1}


def test_an_unknown_kind_is_rejected_and_every_known_kind_passes():
    bad = _gate(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig", kind="guessed"))
    assert bad["counts"] == {cd.Reason.KIND_UNKNOWN.value: 1}
    for kind in ("required", "offered", "measured"):
        out = _gate(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig", kind=kind))
        assert out["accepted"][0]["kind"] == kind


def test_every_rejection_carries_a_reason_and_counts_add_up():
    out = _gate(
        _fact("Set pressure", "340", "not on the page"),
        _fact("Set pressure", "999", "8 | Set pressure | 340 psig"),
        _fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"),
    )
    assert len(out["accepted"]) == 1 and len(out["rejected"]) == 2
    assert all(r["reason"] for r in out["rejected"])
    assert sum(out["counts"].values()) == 2


# ------------------------------------------------------------ the two runs

def test_two_runs_that_disagree_report_model_unstable_not_silence():
    first = _fake(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"))
    second = _fake(_fact("Set pressure", "341", "8 | Set pressure | 340 psig", unit="psig"))
    out = cd.read_page(PAGE, 1, [], first, second_call=second)
    assert out["accepted"] == []
    assert out["counts"] == {cd.Reason.MODEL_UNSTABLE.value: 1}
    assert out["page"] == 1


def test_two_runs_that_agree_pass_and_the_quote_need_not_match():
    first = _fake(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"))
    second = _fake(_fact("Set pressure", "340", "Set pressure | 340 psig", unit="psig"))
    out = cd.read_page(PAGE, 1, [], first, second_call=second)
    assert len(out["accepted"]) == 1


def test_a_malformed_second_run_is_an_error_not_a_fact():
    first = _fake(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"))
    out = cd.read_page(PAGE, 1, [], first, second_call=lambda p: "no")
    assert out["accepted"] == [] and out["error"] == cd.Reason.MODEL_MALFORMED.value


def test_the_model_is_called_twice_by_default():
    calls = []

    def model(prompt):
        calls.append(prompt)
        return _answer(_fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"))

    out = cd.read_page(PAGE, 1, [], model)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(out["accepted"]) == 1


# ------------------------------------------------------- a whole fake page

THREE = (
    _fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig"),
    _fact("Relieving temperature", "121", "9 | Relieving temperature | 121 C", unit="C"),
    _fact("Hydrotest result", "51", "Hydrotest result: 51 barg held for 30 min",
          unit="barg", kind="measured"),
)


def test_a_whole_page_with_three_findable_facts_yields_three_accepted():
    out = cd.read_page(PAGE, 2, [], _fake(*THREE))
    assert len(out["accepted"]) == 3 and out["rejected"] == []
    assert {p["field_name"] for p in out["accepted"]} == {
        "set pressure", "relieving temperature", "hydrotest result"}


def test_read_datasheet_walks_the_pages_it_is_given_and_stamps_them():
    texts = {1: PAGE, 2: "Page two says nothing usable", 3: PAGE}
    doc = _ingest_page(pathlib.Path(settings.data_dir) / "d.pdf")
    out = cd.read_datasheet(doc, allowed_document_ids=_scope(doc), model_call=_fake(*THREE),
                            page_text_of=texts.__getitem__, pages=[1, 2, 3])
    pages = {p["page"]: p for p in out["pages"]}
    assert pages[1]["accepted"] == 3
    assert pages[3]["accepted"] == 3
    # Page 2 carries none of the quotes, so all three are quote-not-on-page.
    assert pages[2]["counts"] == {cd.Reason.QUOTE_NOT_ON_PAGE.value: 3}
    assert sorted(p["page"] for p in out["accepted"]) == [1, 1, 1, 3, 3, 3]
    assert out["rejection_counts"] == {cd.Reason.QUOTE_NOT_ON_PAGE.value: 3}


# ------------------------------------------------------------------ storage

def _ingest_page(path, doc_id="doc_cd", text=PAGE) -> str:
    import fitz
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=500)
    page.insert_text((44, 60), "Set pressure   340 psig", fontsize=9)
    pdf.save(str(path)); pdf.close()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
            (doc_id, "EF-DAS-CD.pdf", f"sha-{doc_id}", str(path), "2026-09-18T00:00:00Z"))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, "EF-DAS-CD.pdf", text, f"h{doc_id}"))
    return doc_id


def test_the_default_page_text_comes_from_the_stored_chunks():
    doc = _ingest_page(pathlib.Path(settings.data_dir) / "d.pdf")
    assert cd.stored_page_text(doc, 1, allowed_document_ids=_scope(doc)) == PAGE.strip()
    assert cd.stored_page_text(doc, 1, allowed_document_ids=_scope()) == ""


def test_read_datasheet_uses_stored_text_and_known_fields_by_default():
    doc = _ingest_page(pathlib.Path(settings.data_dir) / "d.pdf")
    datasheets.create_fact(submittal_document_id=doc, chunk_id=f"{doc}-c1",
                           field_label="Set pressure", raw_value="340 psig", page=1)
    seen = []

    def model(prompt):
        seen.append(prompt)
        return _answer(*THREE)

    out = cd.read_datasheet(doc, allowed_document_ids=_scope(doc), model_call=model)
    assert "- Set pressure" in seen[0], "the extractor's field was not passed as known"
    assert len(out["accepted"]) == 2
    assert out["counts"] == {cd.Reason.ALREADY_EXTRACTED.value: 1}


def test_stored_facts_are_marked_as_the_models_and_never_overwrite():
    doc = _ingest_page(pathlib.Path(settings.data_dir) / "d.pdf")
    existing = datasheets.create_fact(submittal_document_id=doc, chunk_id=f"{doc}-c1",
                                      field_label="Set pressure", raw_value="340 psig", page=1)
    out = cd.read_page(PAGE, 1, [], _fake(*THREE))
    accepted = [{**p, "page": 1} for p in out["accepted"]]
    stored = cd.store_facts(None, doc, accepted, allowed_document_ids=_scope(doc))
    assert stored["written"] == 2 and stored["kept_existing"] == 1 and stored["refused"] == []

    rows = {r["field_name"]: r for r in datasheets.list_facts(doc, allowed_document_ids=_scope(doc))}
    assert len(rows) == 3
    # The extractor's row is untouched.
    assert rows["set pressure"]["id"] == existing["id"]
    assert rows["set pressure"]["extraction_method"] == "extracted"
    # The model's rows say so, carry the quote, and carry the kind.
    hydro = rows["hydrotest result"]
    assert hydro["extraction_method"] == "model"
    assert hydro["confidence"] == 0.5
    assert hydro["source_text"] == "Hydrotest result: 51 barg held for 30 min"
    assert hydro["section"] == "model:measured"
    assert hydro["raw_value"] == "51" and hydro["unit"] == "bar"
    assert hydro["unit_reference"] == "gauge"
    assert hydro["page"] == 1 and hydro["confirmed_by"] is None
    # A second store of the same proposals writes nothing more.
    again = cd.store_facts(None, doc, accepted, allowed_document_ids=_scope(doc))
    assert again["written"] == 0 and again["kept_existing"] == 3


def test_a_proposal_for_a_page_no_chunk_covers_is_refused_not_invented():
    doc = _ingest_page(pathlib.Path(settings.data_dir) / "d.pdf")
    out = cd.store_facts(None, doc, [{**THREE[0], "page": 7, "field_name": "set pressure"}],
                         allowed_document_ids=_scope(doc))
    assert out["written"] == 0 and len(out["refused"]) == 1


# ---------------------------------------------------------------- hygiene

def test_the_module_imports_no_http_library():
    source = pathlib.Path(cd.__file__).read_text()
    for name in ("httpx", "requests", "urllib", "aiohttp", "socket"):
        assert f"import {name}" not in source and f"from {name}" not in source
