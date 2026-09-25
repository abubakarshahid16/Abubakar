"""#193 plan B4 items 1-3, wired: page images through the one request
builder, vision readings in `extract_facts`, the code-only noise filter, and
field naming / pairing that now covers blank fields.

Synthetic PDFs, fake providers, no network, no client document (CLAUDE.md
rules 1 and 3). Mutation proofs: M640-M659 (scripts/mutations/*.py).
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from app import (claude_spend, comparison, datasheets, db, field_naming, reader_api,
                 reasoning_provider as rp, row_noise, submittal_review, vision_reader)
from app.config import settings
from app.reasoning_provider import PageImage, Response

NOW = "2026-09-25T00:00:00Z"
KEY = "sk-ant-test-NEVER-0123456789"
IMG = PageImage("image/png", "iVBORw0KGgo=", 1000, 1500)


# ======================================================= the request builder

ON = {"STANDARDS_READER_ENABLED": "true", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "true",
      "ANTHROPIC_API_KEY": KEY}


def test_images_ride_in_the_one_request_builder():
    """THE MUTATION TARGET (M640): image blocks first, then the text."""
    req = reader_api.build_request("read it", env=ON, images=[("image/png", "AAAA")])
    content = req["body"]["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64",
                                                      "media_type": "image/png", "data": "AAAA"}}
    assert content[-1] == {"type": "text", "text": "read it"}
    # no image: the text-only request is unchanged
    assert reader_api.build_request("x", env=ON)["body"]["messages"][0]["content"] == "x"


def test_an_image_request_keeps_every_gate():
    """THE MUTATION TARGET (M641): flags off still refuse; a non-image type
    is refused before a request exists."""
    with pytest.raises(reader_api.ReaderRefused):
        reader_api.build_request("x", env={"ANTHROPIC_API_KEY": KEY}, images=[("image/png", "A")])
    with pytest.raises(reader_api.ReaderRefused):
        reader_api.build_request("x", env=ON, images=[("application/pdf", "A")])
    with pytest.raises(reader_api.ReaderRefused):
        reader_api.build_request("x", env=ON, images=[("image/png", "")])


@pytest.fixture
def claude_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
                 "ANTHROPIC_API_KEY", "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _send(seen):
    def send(url, *, headers, body, timeout):
        seen.append({"body": body, "timeout": timeout})
        return {"model": "claude-sonnet-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "{}"}],
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    return send


def test_the_claude_provider_sends_the_image_and_the_effort(claude_env):
    """THE MUTATION TARGET (M642)."""
    seen = []
    packet = rp.Packet(prompt="p", num_ctx=1, num_predict=100, step="s", images=(IMG,),
                       effort="low", timeout_s=300.0)
    rp.ClaudeProvider("claude-sonnet-5", transport=_send(seen)).reason(packet)
    body = seen[0]["body"]
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert body["output_config"] == {"effort": "low"} and seen[0]["timeout"] == 300.0
    # a text packet sends neither
    rp.ClaudeProvider("claude-sonnet-5", transport=_send(seen)).reason(
        rp.Packet(prompt="q", num_ctx=1, num_predict=100, step="s"))
    assert "output_config" not in seen[1]["body"]
    assert seen[1]["body"]["messages"][0]["content"] == "q"


def test_the_image_is_part_of_the_digest_and_the_cache_key():
    """THE MUTATION TARGET (M643): two pages never share a cached answer."""
    a = rp.Packet(prompt="p", num_ctx=1, num_predict=1, images=(IMG,))
    b = rp.Packet(prompt="p", num_ctx=1, num_predict=1,
                  images=(PageImage("image/png", "OTHER", 1000, 1500),))
    plain = rp.Packet(prompt="p", num_ctx=1, num_predict=1)
    assert len({a.sha256, b.sha256, plain.sha256}) == 3
    assert rp.cache_key("m", a) != rp.cache_key("m", b)
    # the key of a packet without effort is what it was before effort existed
    assert rp.cache_key("m", plain) == rp.cache_key("m", rp.Packet(prompt="p", num_ctx=1,
                                                                    num_predict=1, effort=None))
    assert rp.cache_key("m", plain) != rp.cache_key("m", rp.Packet(prompt="p", num_ctx=1,
                                                                    num_predict=1, effort="low"))


def test_the_worst_case_counts_the_image(claude_env, monkeypatch):
    """THE MUTATION TARGET (M644): an image the cap cannot afford never leaves."""
    assert claude_spend.worst_case_usd("claude-sonnet-5", 10, 10, image_tokens=IMG.tokens) > \
        claude_spend.worst_case_usd("claude-sonnet-5", 10, 10)
    text_only = claude_spend.worst_case_usd("claude-sonnet-5", 1, 100)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", text_only * 2)
    seen = []
    with pytest.raises(claude_spend.BudgetExceeded):
        rp.ClaudeProvider("claude-sonnet-5", transport=_send(seen)).reason(
            rp.Packet(prompt="p", num_ctx=1, num_predict=100, step="s",
                      images=(PageImage("image/png", "A", 4000, 4000),)))
    assert seen == []


def test_the_local_engine_refuses_an_image():
    with pytest.raises(rp.ProviderRefused):
        rp.OllamaProvider().reason(rp.Packet(prompt="p", num_ctx=1, num_predict=1, images=(IMG,)))


# ================================================================ row noise

@pytest.mark.parametrize("label,value,rule", [
    ("1 2 3 4 5 6 7 8 DATA SHEET NO.: X", "Rev.", row_noise.RULER),
    ("Comments incorporated AR", "SB", row_noise.REVISION),
    ("A SERVICE ORDER NO. 1", "Issued for Review", row_noise.REVISION),
    ("CONTRACTOR DOC NO", "X100-0003", row_noise.DOCUMENT_ID),
    ("NO.: ABC - 1234567 ATA SHEE", "Sheet 5", row_noise.DOCUMENT_ID),
    ("TITLE", "of 7", row_noise.DOCUMENT_ID),
    ("RANGE OF AMBIENT TEMPS", "MIN/MAX", row_noise.HEADER_AS_VALUE),
    ("X", "Note", row_noise.HEADER_AS_VALUE),
    ("DISCHARGE PRESSURE", "[Note - 3]", row_noise.REFERENCE_ONLY),
    ("Wind load (L10)", "Note A3", row_noise.REFERENCE_ONLY),
    ("PREFERRED REGION", "(6.1.11)", row_noise.REFERENCE_ONLY),
    ("MAX", "8.5 bar g", row_noise.FRAGMENT_LABEL),
    ("1 Facing", "RF", row_noise.FRAGMENT_LABEL),
    ("A B C D E F G H I J K L M N O P", "x", row_noise.MERGED_BLOCK),
])
def test_each_noise_rule(label, value, rule):
    """THE MUTATION TARGET (M645-M647)."""
    assert row_noise.noise_reason(label, value) == rule


@pytest.mark.parametrize("label,value", [
    ("Compressibility factor", "0.911"),        # a decimal is not a clause number
    ("Design specific gravity :", "1.07"),
    ("FOR", "Example Company"),               # a real one-word label
    ("4 HR. MECH RUN TEST", "WIT"),              # a number opening a real label
    ("Item No.", "09-G-411 A/B"),
    ("Reverse rotation", "YES"),                 # 'rev' only as a word
    ("TEMP CLASS", "T3"),
])
def test_real_fields_are_not_noise(label, value):
    """THE MUTATION TARGET (M648): measured on the regression sheets, the
    first clause-number rule dropped 8 real PSV/vessel values."""
    assert row_noise.noise_reason(label, value) is None


# ======================================================== extract_facts wiring

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b4q.sqlite")
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield tmp_path
    db.reset_connection()


ITEMS = [
    (50, 100, "DESIGN PRESSURE:"), (180, 100, "10 barg"),
    (50, 140, "VOLTAGE"), (220, 140, "440"),
    (50, 180, "PHASE"), (220, 180, "3"),
    (50, 220, "MAX:"), (180, 220, "8.5 bar g"),
]


def _store(tmp_path, items=ITEMS, doc_id="doc_q") -> str:
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=10)
    pdf.save(str(path))
    text = pdf[0].get_text()
    pdf.close()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                     (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), NOW))
        conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                     " VALUES (?,1,?,?,0,0)", (doc_id, text, len(text)))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "section,kind,text,token_count,content_hash,retrievable) VALUES "
                     "(?,?,?,1,1,1,NULL,'prose',?,1,?,1)",
                     (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    return doc_id


def _extract(doc):
    return datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}), replace=True)


def _facts(doc):
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL",
        (doc,))]


class VisionFake:
    def __init__(self, fields, kind="datasheet"):
        self.text = json.dumps({"page_kind": kind, "fields": fields})
        self.calls = 0

    def reason(self, packet):
        self.calls += 1
        return Response(text=self.text, provider="claude", model_tag="claude-sonnet-5",
                        digest="d", finish_reason="stop", prompt_sha256=packet.sha256)


def _with_vision(monkeypatch, fake):
    monkeypatch.setattr(vision_reader, "provider", lambda: (fake, None))


def test_off_never_asks_the_vision_reader(world, monkeypatch):
    """THE MUTATION TARGET (M649): the flag off is the pre-B4 extraction -
    no image leaves, no vision or noise key in the result."""
    doc = _store(world)

    def explode():
        raise AssertionError("vision provider asked with the flag off")
    monkeypatch.setattr(vision_reader, "provider", explode)
    result = _extract(doc)
    assert not [f for f in _facts(doc) if f["extraction_method"] == "vision"]
    assert "vision_facts" not in result


def test_on_records_proved_vision_readings_and_the_rule_reader_wins(world, monkeypatch):
    """THE MUTATION TARGET (M650): a proved reading is written as
    extraction_method='vision' with its proof; one the page does not prove is
    never stored; one that disagrees with a rule-reader fact is dropped."""
    doc = _store(world)
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    fake = VisionFake([
        {"label": "VOLTAGE", "value": "440", "unit": None},
        {"label": "PHASE", "value": "1", "unit": None},             # not on the page
        {"label": "DESIGN PRESSURE", "value": "10", "unit": "bar"},  # disagrees in unit
    ])
    _with_vision(monkeypatch, fake)
    result = _extract(doc)
    vision = [f for f in _facts(doc) if f["extraction_method"] == "vision"]
    assert [(f["field_label"], f["raw_value"]) for f in vision] == [("VOLTAGE", "440")]
    box = json.loads(vision[0]["bbox"])
    assert box["reader"] == "vision_reader" and box["proof"].startswith("text layer")
    assert result["vision_facts"] == 1 and fake.calls == 1
    # "1" is printed only inside "10"; "bar" only inside "barg" (and "bar g" is
    # on another line)
    assert result["vision_proposals_dropped"] == {vision_reader.VALUE_NOT_BESIDE_LABEL: 1,
                                                  vision_reader.UNIT_NOT_PROVEN: 1}


def test_a_vision_reading_that_disagrees_with_the_rule_reader_is_dropped(world, monkeypatch):
    """THE MUTATION TARGET (M658): proved on the page or not, a vision value
    for a label the rule reader already read is never stored beside it."""
    doc = _store(world, [(50, 100, "SPEED:"), (140, 100, "2950 rpm")], "doc_d")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    reading = vision_reader.PageReading(page=1, asked=True, page_kind="datasheet", proposed=1)
    reading.kept.append({"label": "SPEED", "value": "3000", "unit": "rpm", "proof": "p",
                         "value_bbox": None, "label_bbox": None})
    monkeypatch.setattr(datasheets, "_vision_reading", lambda *_a: reading)
    _with_vision(monkeypatch, object())
    result = _extract(doc)
    assert [f["extraction_method"] for f in _facts(doc)] == ["extracted"]
    assert result["vision_dropped"] == {"disagrees with rule/geometry reader (not stored)": 1}


def test_a_vision_reading_of_a_rule_fact_label_is_never_a_second_row(world, monkeypatch):
    items = [(50, 100, "SPEED:"), (140, 100, "2950 rpm")]
    doc = _store(world, items, "doc_s")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    _with_vision(monkeypatch, VisionFake([{"label": "SPEED", "value": "2950", "unit": "rpm"}]))
    result = _extract(doc)
    assert [f["extraction_method"] for f in _facts(doc)] == ["extracted"]
    assert result["vision_dropped"] == {"same as rule/geometry reader": 1}


def test_the_noise_filter_runs_only_with_the_flag_on(world, monkeypatch):
    """THE MUTATION TARGET (M651): title-block furniture is dropped with the
    flag on, and counted; with it off the rule reader is untouched."""
    doc = _store(world)
    _extract(doc)
    off = {f["field_label"] for f in _facts(doc)}
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    _with_vision(monkeypatch, None)
    _extract(doc)
    on = {f["field_label"] for f in _facts(doc)}
    assert "MAX:" in off and "MAX:" not in on
    assert "DESIGN PRESSURE:" in on


def test_a_page_with_only_vision_readings_is_not_read_and_says_why(world, monkeypatch):
    """THE MUTATION TARGET (M652): the ledger keeps the geometry rule - a
    vision reading is recorded, it does not make the page read - and the
    reason names what the vision reader did, in the model's word."""
    from app import page_ledger
    doc = _store(world, [(50, 100, "VOLTAGE"), (220, 100, "440")], "doc_v")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    _with_vision(monkeypatch, VisionFake([{"label": "VOLTAGE", "value": "440"}], kind="table"))
    _extract(doc)
    cover = page_ledger.coverage(doc)
    assert 1 in cover["pages_not_read_into_fields"]
    reason = cover["not_read_reasons"][1] if 1 in cover["not_read_reasons"] \
        else cover["not_read_reasons"]["1"]
    assert "vision reader: page kind 'table'" in reason and "1 recorded" in reason


def test_a_vision_value_keeps_a_unit_the_quantity_reader_cannot_join(world, monkeypatch):
    """THE MUTATION TARGET (M653): '0.35' + 'bar a' - measured on a copy, the
    unit was lost; a number without its unit is a wrong value."""
    doc = _store(world, [(50, 100, "VAPOR PRESSURE bar a"), (220, 100, "0.35"),
                         (50, 140, "DRAIN Size"), (220, 140, "¾")], "doc_u")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    _with_vision(monkeypatch, VisionFake([{"label": "VAPOR PRESSURE", "value": "0.35",
                                           "unit": "bar a"},
                                          {"label": "DRAIN Size", "value": "¾"}]))
    _extract(doc)
    got = {f["field_label"]: f for f in _facts(doc) if f["extraction_method"] == "vision"}
    assert (got["VAPOR PRESSURE"]["raw_value"], got["VAPOR PRESSURE"]["raw_unit"]) == ("0.35", "bar a")
    assert got["DRAIN Size"]["field_value"] == "3/4"


# ============================================================ naming, pairing

class NamingFake:
    name = "ollama"

    def __init__(self, answers):
        self.answers, self.packets = answers, []

    def reason(self, packet):
        self.packets.append(packet)
        items = json.loads(packet.prompt)["items"]
        return Response(text=json.dumps({"names": self.answers(packet, items)}),
                        provider="ollama", model_tag="fake:1", digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


def _req(rid, text, subject, value="85", unit="C"):
    return {"id": rid, "requirement_text": text, "subject": subject, "raw_value": value,
            "raw_unit": unit, "unit": unit, "requirement_type": "numeric_limit", "operator": "<="}


def test_blank_fields_are_named_and_a_fact_is_its_own_name(world):
    """THE MUTATION TARGET (M654): a BLANK field's label is in the sheet
    dictionary, listed first and preferred; a requirement named to it pairs
    with it by code (the fact's own name), with no second model answer."""
    reqs = [_req("r1", "bearing temperature shall not exceed 85 C", "bearing temperature")]
    facts = [{"id": "f1", "field_name": "bearing temp", "field_label": "BEARING TEMP.",
              "raw_value": None, "is_blank": 1},
             {"id": "f2", "field_name": "remarks", "field_label": "REMARKS", "raw_value": None,
              "is_blank": 0}]
    assert field_naming.build_dictionary(reqs, facts) == ["bearing temp", "bearing temperature"]

    def answers(packet, items):
        if json.loads(packet.prompt)["kind"] == "requirement":
            assert "DATASHEET FIELDS (prefer these)" in packet.system
            return [{"i": 0, "field": 0, "quote": "bearing temperature"}]
        return [{"i": i, "field": None, "quote": ""} for i, _ in enumerate(items)]
    got = field_naming.ensure_names(reqs, facts, provider=NamingFake(answers))
    assert got["requirements"] == {"r1": "bearing temp"}
    assert got["facts"] == {"f1": "bearing temp"}


def test_a_grouped_label_is_also_named_by_its_row():
    assert field_naming.own_names({"field_name": "differential pressure rated",
                                   "field_label": "DIFFERENTIAL PRESSURE - Rated"}) == \
        ["differential pressure rated", "differential pressure"]
    assert field_naming.own_names({"field_name": "voltage", "field_label": "VOLTAGE"}) == ["voltage"]


def test_naming_is_charged_to_its_own_step():
    assert field_naming.NAMING_STEP == "b4-naming2"


def _fact(fid, value="2950", unit="rpm", page=2, blank=0, label=None):
    return {"id": fid, "field_name": "speed", "field_label": label or f"SPEED {fid}",
            "raw_value": value, "raw_unit": unit, "unit": unit, "page": page, "is_blank": blank,
            "submittal_document_id": "doc_s", "equipment_tag": None,
            "value_min": None, "value_max": None}


def _speed_req():
    return {"id": "r1", "requirement_text": "Maximum pump speed shall be 5,000 RPM",
            "subject": "Maximum pump speed", "raw_value": "5000", "raw_unit": "rpm", "unit": "rpm",
            "requirement_type": "numeric_limit", "operator": "<="}


def test_a_blank_field_pairs_and_one_filled_value_beats_blanks():
    """THE MUTATION TARGET (M655): a blank field under the name pairs; one
    filled value among blanks is not a tie; two filled values still are."""
    req = _speed_req()
    names = lambda ids: {"requirements": {"r1": "speed"}, "facts": {i: "speed" for i in ids}}  # noqa: E731
    blank = comparison.match_by_field_name(req, [_fact("f1", None, None, blank=1)], names(["f1"]))
    assert blank["fact"]["id"] == "f1" and blank["method"] == comparison.METHOD_FIELD_NAME
    mixed = comparison.match_by_field_name(
        req, [_fact("f1", None, None, blank=1), _fact("f2")], names(["f1", "f2"]))
    assert mixed["fact"]["id"] == "f2" and mixed["candidates"] == ["SPEED f1 (page 2)"]
    tie = comparison.match_by_field_name(req, [_fact("f1"), _fact("f2", "3000")],
                                         names(["f1", "f2"]))
    assert tie["fact"] is None and tie["reason"] == comparison.AMBIGUOUS_MATCH
    # a free-text (non-numeric, non-blank) fact still never pairs
    assert comparison.match_by_field_name(req, [_fact("f1", None, None)], names(["f1"])) is None


def test_all_blank_cites_the_one_whose_own_label_is_the_name():
    """THE MUTATION TARGET (M656): whichever blank is cited the answer is the
    same; the one that IS the named field comes first, the rest are named."""
    req = _speed_req()
    names = {"requirements": {"r1": "speed"}, "facts": {"f1": "speed", "f2": "speed"}}
    other = dict(_fact("f1", None, None, page=1, blank=1, label="MAX SPEED AT TRIP"),
                 field_name="max speed at trip")
    own = _fact("f2", None, None, page=3, blank=1, label="SPEED")
    got = comparison.match_by_field_name(req, [other, own], names)
    assert got["fact"]["id"] == "f2" and got["candidates"] == ["MAX SPEED AT TRIP (page 1)"]


def _world():
    import uuid

    from app import standards
    std, sub = "std-1", "sub-1"
    with db.connect() as conn:
        for doc_id, role in ((std, "COMPANY_STANDARD"), (sub, "CONTRACTOR_SUBMITTAL")):
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                         "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                         (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))
            conn.execute("INSERT INTO document_classification (document_id,suggested_by,"
                         "document_role) VALUES (?,?,?)", (doc_id, "test", role))
        for chunk_id, doc_id in (("sc", std), ("fc", sub)):
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                         "section,kind,text,token_count,content_hash,retrievable) VALUES "
                         "(?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
                         (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"))
    req = standards.create_requirement(
        standard_document_id=std, chunk_id="sc",
        requirement_text="The maximum allowable working pressure shall be 10 bar.",
        source_text="The maximum allowable working pressure shall be 10 bar.", clause="6.4.1",
        page=1, structured={"subject": "the maximum allowable working pressure",
                            "operator": "<=", "raw_value": "10", "raw_unit": "bar",
                            "requirement_type": "numeric_limit"})
    fact = datasheets.create_fact(submittal_document_id=sub, chunk_id="fc",
                                  field_label="Shell working press.", raw_value="______", page=1)
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
                     "updated_at) VALUES (?,?,'pending',?,?)", (run_id, sub, NOW, NOW))
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,"
                     "standard_document_id,selection_reason,selection_method,included,"
                     "created_at) VALUES (?,?,?,'cited','referenced',1,?)",
                     (str(uuid.uuid4()), run_id, std, NOW))
    return req, fact, run_id, frozenset({std, sub})


def test_a_blank_field_pairing_is_held_for_an_engineer(world, monkeypatch):
    """THE MUTATION TARGET (M657): the comparison reads MISSING_INFORMATION
    (the field is blank), but the pairing is model-named, so the finding is
    NEEDS_ENGINEER_REVIEW with the comparison's own words kept."""
    req, fact, run, scope = _world()
    assert fact["is_blank"]
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(field_naming, "ensure_names", lambda *_a, **_k: {
        "requirements": {str(req["id"]): "working pressure"},
        "facts": {str(fact["id"]): "working pressure"}})
    found = comparison.run_comparison(run, allowed_document_ids=scope)["findings"][0]
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "The comparison read MISSING_INFORMATION, held for an engineer" in found["ai_rationale"]
    assert "leaves this field to be provided" in found["ai_rationale"]
