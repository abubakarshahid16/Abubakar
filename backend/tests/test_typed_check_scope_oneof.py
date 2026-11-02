"""A rule's equipment scope comes from its Part or Appendix's own scope clause; a one-of check on a free-text field never
fails on words it cannot read. Invented standards, sheets and values only; a temporary database; no model."""

from __future__ import annotations

import io
import json
import sqlite3

import openpyxl
import pytest

from app import (
    ai_applicability,
    ai_task_runner,
    coverage_pair,
    crs_export,
    datasheet_checks,
    db,
    division_text,
    rule_part_scope,
    rule_typed_check,
    rulebook_v2_crs,
    rulebook_v2_review,
    subject_scope,
)
from app.config import settings
from app.rule_part_scope import (
    GENERAL,
    NAMED,
    OUTSIDE,
    OUTSIDE_EQUIPMENT_SCOPE,
    SCOPE_NOT_ESTABLISHED,
    STANDARD,
    UNKNOWN,
)
from app.rule_typed_check import IS_NOT, IS_ONE_OF, decide
from tests.test_805_review_reads_v2 import (
    QUERY,
    SHEET,
    TYPE,
    _ours,
    _reason,
    _review,
    _sheet,
    switched_on,  # noqa: F401
)
from tests.test_805_rule_typed_check import _typed
from tests.test_1584_standards_compiler import lane  # noqa: F401

CODE = "std-invented-code"
PLAIN = "std-invented-plain"
MODEL = "invented-model"
STYLES = ["direct spring-loaded", "pilot-operated"]
SERVICES = ["clean gas", "thin liquid"]
GENERAL_RULE = (
    "Each invented valve shall be a direct spring-loaded one or a pilot-operated one."
)
LINED_RULE = "Base metal of a glazed drum shall comply with Rule A or Rule B."
POT_RULE = "Invented bar steel shall stay out of every heated invented pot."
VALVE_RULE = "The invented valve body shall not be cast iron."
SERVICE_RULE = "Invented valves shall be limited to clean gas and thin liquid service."

ALL_SENTENCE = "The rules of Part XG apply to all invented equipment and to its parts."
LINED_SENTENCE = (
    "The rules of Part XCL apply to glazed drums made of lined plate and strip."
)
POT_SENTENCE = (
    "This Appendix adds rules for heated jacketed pots of this invented code."
)
VALVE_SENTENCE = (
    "The rules of Part XV apply to pressure relief valves made of invented alloy."
)
GENERIC_SENTENCE = "The rules of Part XQ apply to valves made of invented alloy only."
NEGATED_SENTENCE = (
    "The rules of Part XA apply to glazed drums and do not apply to relief valves."
)
FOOTNOTED_SENTENCE = "The rules of Part XM apply to glazed drums made of lined plate.13"
UNSURE_SENTENCE = "Part XU may perhaps apply to some assemblies in some invented cases."


def _part(word, ident, title, sentence, *rest):
    return "\n".join((f"{word} {ident}", title, f"{ident}-1", "SCOPE", sentence, *rest))


SUBJECT_RULE_WORDS = "Each one shall carry an invented mark."
PAGES = [
    (
        1,
        "Invented Code\nIntroduction\nX-1\nThe invented code holds invented rules.\nThe invented intro rule stands here.",
    ),
    (2, _part("PART", "XG", "GENERAL RULES", ALL_SENTENCE, "XG-20", GENERAL_RULE)),
    (3, _part("PART", "XCL", "GLAZED DRUMS", LINED_SENTENCE, "XCL-10", LINED_RULE)),
    (
        4,
        _part(
            "MANDATORY APPENDIX", "19", "HEATED POTS", POT_SENTENCE, "19-3", POT_RULE
        ),
    ),
    (5, _part("PART", "XV", "ALLOY VALVES", VALVE_SENTENCE, "XV-2", VALVE_RULE)),
    (6, _part("PART", "XQ", "ALLOY THINGS", GENERIC_SENTENCE, "XQ-2", VALVE_RULE)),
    (7, _part("PART", "XA", "DRUMS AGAIN", NEGATED_SENTENCE, "XA-2", VALVE_RULE)),
    (8, _part("PART", "XU", "SOME ASSEMBLIES", UNSURE_SENTENCE, "XU-2", VALVE_RULE)),
    (
        9,
        _part(
            "PART",
            "XN",
            "NEVER READ",
            "The rules in Part XN were never read by any model at all.",
            "XN-2",
            VALVE_RULE,
        ),
    ),
    (
        10,
        _part(
            "PART",
            "XF",
            "FALSE QUOTE",
            "The rules of Part XF hold a sentence the model did not copy here.",
            "XF-2",
            VALVE_RULE,
        ),
    ),
    (
        11,
        _part(
            "PART",
            "XD",
            "TWO MODELS",
            "The rules in Part XD were read twice by two models here.",
            "XD-2",
            VALVE_RULE,
        ),
    ),
    (
        12,
        _part(
            "PART",
            "XE",
            "NO SENTENCE",
            "The rules in Part XE were read as naming no limit at all.",
            "XE-2",
            VALVE_RULE,
        ),
    ),
    # a heading below the top of its page: a break, and what follows sits in no division
    (
        13,
        _part(
            "PART",
            "XM",
            "FOOTNOTED DRUMS",
            f"{FOOTNOTED_SENTENCE} These are invented words.",
            "XM-2",
            VALVE_RULE,
        ),
    ),
    (
        14,
        "\n".join(
            (
                "Plain words one",
                "Plain words two",
                "Plain words three",
                "Plain words four",
                "Plain words five",
                "Plain words six",
                "PART XW",
                "Plain words seven",
            )
        ),
    ),
    (
        15,
        "XM-50\nThe invented later rule of the part stands here.\n7.1\nThe invented stray rule stands here.",
    ),
]


SUBJECT_SENTENCE = (
    "The rules of Part XH apply to all pressure vessels and to their parts."
)
SECOND_SUBJECT_SENTENCE = (
    "The rules of Part XI apply to all pressure vessels and to their parts."
)
PAGES += [
    (
        16,
        _part("PART", "XH", "ALL DRUMS", SUBJECT_SENTENCE, "XH-2", SUBJECT_RULE_WORDS),
    ),
    (
        17,
        _part(
            "PART",
            "XI",
            "ALL DRUMS AGAIN",
            SECOND_SUBJECT_SENTENCE,
            "XI-2",
            SUBJECT_RULE_WORDS,
        ),
    ),
    (
        18,
        _part(
            "PART",
            "XS",
            "NOT ALL",
            "This Part describes invented methods used on invented days.",
            "XS-2",
            SUBJECT_RULE_WORDS,
        ),
    ),
    (
        19,
        _part(
            "PART",
            "XY",
            "NEXT ONE",
            "This Part describes other invented methods used on days.",
            "XY-2",
            SUBJECT_RULE_WORDS,
        ),
    ),
    (
        20,
        _part(
            "PART",
            "XZ",
            "AFTER IT",
            "The rules of Part XZ apply to glazed drums made of another lined plate.",
            "XZ-2",
            SUBJECT_RULE_WORDS,
        ),
    ),
]


def _store_pages(conn, document_id, pages):
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                document_id,
                f"{document_id}.pdf",
                document_id,
                1,
                "x",
                "ready",
                "2026-11-02",
            ),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,1)",
            [(document_id, n, text, len(text)) for n, text in pages],
        )


def _read(conn, ident, reply, model=MODEL):
    """A stored answer of the division gate's scope task, on the passage that task would be given."""
    text = subject_scope.StandardText(PAGES)
    tops = division_text._tops(text, division_text.divisions(text))
    at = next(i for i, t in enumerate(tops) if t["name"] and t["name"][1] == ident)
    end = tops[at + 1]["line"] if at + 1 < len(tops) else None
    passage = division_text.scope_passage(text, tops[at], end).strip()
    spec = ai_applicability.SCOPE_TASK
    ai_task_runner.ensure_schema()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO ai_task_cache (key, task, version, model, result_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                ai_task_runner.cache_key(spec, model, passage),
                spec.name,
                spec.version,
                model,
                json.dumps(reply),
                "2026-11-02",
            ),
        )


def _limited(sentence, words="invented"):
    return {"limited": "yes", "construction": words, "quote": sentence}


@pytest.fixture
def code(lane, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "answer_model", MODEL)
    conn = db.connect()
    _store_pages(conn, CODE, PAGES)
    _read(conn, "XG", {"limited": "no", "construction": None, "quote": ALL_SENTENCE})
    _read(conn, "XCL", _limited(LINED_SENTENCE, "glazed drums"))
    _read(conn, "19", _limited(POT_SENTENCE, "heated jacketed pots"))
    _read(conn, "XV", _limited(VALVE_SENTENCE, "invented alloy"))
    _read(conn, "XQ", _limited(GENERIC_SENTENCE, "invented alloy"))
    _read(conn, "XA", _limited(NEGATED_SENTENCE, "glazed drums"))
    _read(conn, "XU", {"limited": "unsure", "construction": None, "quote": None})
    _read(
        conn,
        "XF",
        _limited(
            "The rules of Part XF apply only to invented drums of lined plate.", "drums"
        ),
    )
    _read(
        conn,
        "XD",
        {
            "limited": "no",
            "construction": None,
            "quote": "The rules in Part XD were read twice by two models here.",
        },
    )
    _read(
        conn,
        "XD",
        _limited("The rules in Part XD were read twice by two models here.", "models"),
        model="another-model",
    )
    _read(conn, "XE", {"limited": "no", "construction": None, "quote": None})
    _read(
        conn, "XH", {"limited": "no", "construction": None, "quote": SUBJECT_SENTENCE}
    )
    _read(conn, "XI", {"limited": "no", "construction": None, "quote": None})
    _read(conn, "XS", {"limited": "no", "construction": None, "quote": None})
    _read(
        conn,
        "XY",
        _limited(
            "The rules of Part XZ apply to glazed drums made of another lined plate.",
            "glazed drums",
        ),
    )
    _read(conn, "XM", _limited(FOOTNOTED_SENTENCE, "glazed drums"))
    _store_pages(
        conn,
        PLAIN,
        [
            (
                1,
                "Invented Plain Standard\n1 Scope\nThis standard covers invented valves.",
            ),
            (9, f"6.1.1\n{VALVE_RULE}"),
        ],
    )
    return conn


def _run(monkeypatch, run, scope, rule):
    """A review by a reader who may read these invented standards."""
    return _review(monkeypatch, run, frozenset(scope) | {CODE, PLAIN}, rule)


def _every_cell(data):
    book = openpyxl.load_workbook(io.BytesIO(data))
    return [str(c.value) for s in book.worksheets for r in s.iter_rows() for c in r]


def _in(document_id, clause, page, quote=VALVE_RULE):
    return {"document_id": document_id, "clause": clause, "page": page, "quote": quote}


# ------------------------------------------------------------------------------------- finding (a): wrong equipment


@pytest.mark.parametrize(
    ("clause", "page", "quote"),
    [("XCL-10", 3, LINED_RULE), ("XA-2", 7, "Each one shall carry an invented mark.")],
)
def test_a_part_whose_own_clause_names_other_equipment_is_outside(
    code, clause, page, quote
):
    said = rule_part_scope.of_rule(code, _in(CODE, clause, page, quote), TYPE)
    assert (said.state, said.reason) == (OUTSIDE, OUTSIDE_EQUIPMENT_SCOPE), said.words
    assert said.division and str(page) in said.words


def test_a_footnote_number_after_the_full_stop_leaves_the_sentence_whole(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "XM-2", 13), TYPE)
    assert said.state == OUTSIDE, said.words


def test_an_outside_rule_is_not_paired_and_names_its_reason(code, monkeypatch):
    _sheet(label="Body material", value="carbon steel")
    rule = {**_in(CODE, "XCL-10", 3, LINED_RULE), "field": "Body material"}
    said = rulebook_v2_review.pair_rule_to_document(_ro(), SHEET, rule)
    assert said["paired"] is False and said["reason"] == OUTSIDE_EQUIPMENT_SCOPE
    assert (
        said["value_read"] is None
        and said["values_read"] == []
        and said["tags_paired"] == 0
    )
    assert said["scope_words"]


def test_an_outside_rule_never_decides_and_the_run_counts_it(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="carbon steel")
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    typed = {**_typed(rule["quote"], IS_NOT, ["invented bar steel"]), **rule}
    result = _run(monkeypatch, run, scope, typed)
    assert _ours(result) == []
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert part["rules"] == 0 and part["decided"] == 0
    assert "1 outside this equipment type's scope" in part["line"]


def test_a_rule_in_a_part_for_this_equipment_type_stays_in_scope(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "XV-2", 5), TYPE)
    assert (said.state, said.reason) == (NAMED, None), said.words


def test_the_same_part_is_outside_for_another_equipment_type(code):
    assert (
        rule_part_scope.of_rule(code, _in(CODE, "XV-2", 5), "Centrifugal Pump").state
        == OUTSIDE
    )


# ----------------------------------------------------------------------------------------- a general Part stays in


def test_a_general_part_covers_every_equipment_type(code):
    rule = _in(CODE, "XG-20", 2, GENERAL_RULE)
    for equipment in (TYPE, "Centrifugal Pump"):
        said = rule_part_scope.of_rule(code, rule, equipment)
        assert (said.state, said.reason) == (GENERAL, None), said.words


def test_a_rule_past_a_break_still_belongs_to_the_part_its_clause_number_names(code):
    rule = _in(CODE, "XM-50", 15, "The invented later rule of the part stands here.")
    said = rule_part_scope.of_rule(code, rule, TYPE)
    assert said.division == "Part XM" and said.state == OUTSIDE


def test_a_general_part_decides_end_to_end(code, monkeypatch):
    run, scope = _sheet(label="Valve type", value="pilot-operated")
    rule = _typed(GENERAL_RULE, IS_ONE_OF, STYLES, role_field="Valve type")
    rows = _ours(
        _run(monkeypatch, run, scope, {**rule, **_in(CODE, "XG-20", 2, GENERAL_RULE)})
    )
    assert [r["compliance_status"] for r in rows] == ["COMPLIANT"], rows


# --------------------------------------------------------------------------------------- scope that is not established


@pytest.mark.parametrize(
    ("rule", "why"),
    [
        (_in(CODE, "XN-2", 9), "no stored reading"),
        (_in(CODE, "XU-2", 8), "the model is unsure"),
        (_in(CODE, "XF-2", 10), "the quote is not on the page"),
        (_in(CODE, "XD-2", 11), "two readings disagree"),
        (_in(CODE, "XE-2", 12), "a no whose text does not say all"),
        (_in(CODE, "XQ-2", 6), "only a word shared with other types"),
        (
            _in(CODE, "7.1", 15, "The invented stray rule stands here."),
            "past a break, no clause number",
        ),
        ({"clause": "XG-20", "page": 2, "quote": GENERAL_RULE}, "no standard named"),
        (_in("std-with-no-stored-text", "4.1", 3), "no page text"),
    ],
)
def test_scope_that_cannot_be_established_is_never_in_scope(code, rule, why):
    said = rule_part_scope.of_rule(code, rule, TYPE)
    assert (said.state, said.reason) == (UNKNOWN, SCOPE_NOT_ESTABLISHED), why
    assert said.words


def test_a_limited_part_with_no_equipment_type_is_not_established(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "XV-2", 5), None)
    assert said.state == UNKNOWN


def test_unknown_scope_is_a_query_on_each_tag_with_the_value_shown(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="cast iron")
    typed = {**_typed(VALVE_RULE, IS_NOT, ["cast iron"]), **_in(CODE, "XN-2", 9)}
    rows = _ours(_run(monkeypatch, run, scope, typed))
    assert [r["compliance_status"] for r in rows] == [QUERY]
    assert _reason(rows[0]) == SCOPE_NOT_ESTABLISHED
    assert rows[0]["contractor_evidence_text"] == "cast iron"


def test_unknown_scope_is_not_paired_on_the_checklist(code):
    _sheet(label="Body material", value="cast iron")
    said = rulebook_v2_review.pair_rule_to_document(
        _ro(), SHEET, {**_in(CODE, "XN-2", 9), "field": "Body material"}
    )
    assert said["paired"] is False and said["reason"] == SCOPE_NOT_ESTABLISHED


def test_a_limit_naming_no_known_equipment_is_a_question_not_outside(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "19-3", 4, POT_RULE), TYPE)
    assert (said.state, said.reason) == (UNKNOWN, SCOPE_NOT_ESTABLISHED), said.words


def test_a_type_that_may_be_a_kind_of_what_the_clause_names_is_a_question(code):
    """The sentence names a vessel. A valve is in another family; an exchanger is not."""
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    assert rule_part_scope.of_rule(code, rule, TYPE).state == OUTSIDE
    assert rule_part_scope.of_rule(code, rule, "Heat Exchanger").state == UNKNOWN
    assert rule_part_scope.of_rule(code, rule, "Pressure Vessel").state == NAMED


def test_a_type_with_no_family_is_never_outside(code, monkeypatch):
    held = rule_part_scope._families()
    del held["relief valve"]
    monkeypatch.setattr(rule_part_scope, "_families", lambda: held)
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    assert rule_part_scope.of_rule(code, rule, TYPE).state == UNKNOWN


def test_every_equipment_type_has_a_family_and_no_component_does():
    vocab = subject_scope.vocabulary()
    for name, kind in vocab.kind.items():
        family = rule_part_scope._families().get(name)
        assert bool(family) == (kind == subject_scope.EQUIPMENT), name


def test_a_rule_that_names_the_type_is_not_left_out_by_a_clause_naming_other_equipment(
    code,
):
    rule = _in(
        CODE, "XCL-10", 3, "A pressure relief valve shall carry an invented mark."
    )
    assert rule_part_scope.of_rule(code, rule, TYPE).state == UNKNOWN


SUBJECT_RULE = "Each one shall carry an invented mark."
NAMING_RULE = "A pressure relief valve shall carry an invented mark."


@pytest.mark.parametrize("ident", ["XH", "XI"])
def test_a_part_general_for_its_subject_is_general_only_for_it(code, ident):
    """Part XH's reading quotes its sentence and Part XI's quotes none: the two are treated the same."""
    page = {"XH": 16, "XI": 17}[ident]
    other = rule_part_scope.of_rule(
        code, _in(CODE, f"{ident}-2", page, SUBJECT_RULE), TYPE
    )
    assert (other.state, other.reason) == (UNKNOWN, SCOPE_NOT_ESTABLISHED), other.words
    assert "general for its own subject" in other.words
    named = rule_part_scope.of_rule(
        code, _in(CODE, f"{ident}-2", page, NAMING_RULE), TYPE
    )
    assert named.state == GENERAL, named.words
    own = rule_part_scope.of_rule(
        code, _in(CODE, f"{ident}-2", page, SUBJECT_RULE), "Pressure Vessel"
    )
    assert own.state == GENERAL, own.words


def test_a_no_whose_text_does_not_say_all_is_not_general(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "XS-2", 18, NAMING_RULE), TYPE)
    assert said.state == UNKNOWN and "does not say so" in said.words


def test_the_next_parts_sentence_is_not_this_parts(code):
    said = rule_part_scope.of_rule(code, _in(CODE, "XY-2", 19, SUBJECT_RULE), TYPE)
    assert said.state == UNKNOWN and "not in its own text" in said.words


def test_a_lesser_model_alone_does_not_set_scope(code):
    conn = code
    _read(
        conn,
        "XN",
        _limited("The rules in Part XN were never read by any model at all."),
        model="lesser-model",
    )
    said = rule_part_scope.of_rule(conn, _in(CODE, "XN-2", 9), TYPE)
    assert said.state == UNKNOWN and "does not set scope" in said.words


@pytest.mark.parametrize("stored", ["[1, 2]", "not json at all", "null", '"words"'])
def test_a_stored_row_that_is_not_a_reading_does_not_stop_the_review(code, stored):
    _read(code, "XN", {"limited": "yes"})
    with code:
        code.execute(
            "UPDATE ai_task_cache SET result_json = ? WHERE result_json = ?",
            (stored, json.dumps({"limited": "yes"})),
        )
    said = rule_part_scope.of_rule(code, _in(CODE, "XN-2", 9), TYPE)
    assert said.state == UNKNOWN and "has not been read" in said.words


# ------------------------------------------------------------- a clause in a standard with no Part of its own: unchanged


def test_a_standard_with_no_part_keeps_its_own_scope(code):
    said = rule_part_scope.of_rule(code, _in(PLAIN, "6.1.1", 9), TYPE)
    assert (said.state, said.reason) == (STANDARD, None), said.words


def test_a_rule_before_the_first_part_is_the_standards_own(code):
    rule = _in(CODE, "X-1", 1, "The invented intro rule stands here.")
    assert rule_part_scope.of_rule(code, rule, TYPE).state == STANDARD


def _not_cast_iron():
    return {**_typed(VALVE_RULE, IS_NOT, ["cast iron"]), **_in(PLAIN, "6.1.1", 9)}


@pytest.mark.parametrize(
    ("stated", "status"),
    [("stainless steel", "COMPLIANT"), ("cast iron", "NON_COMPLIANT")],
)
def test_an_is_not_rule_on_a_plain_standard_decides_as_before(
    code, monkeypatch, stated, status
):
    run, scope = _sheet(label="Body material", value=stated)
    rows = _ours(_run(monkeypatch, run, scope, _not_cast_iron()))
    assert [r["compliance_status"] for r in rows] == [status], rows


def test_is_not_is_never_read_as_free_text():
    assert (
        decide(IS_NOT, ["cast iron"], "cast iron", free_text=True)[0] == "NON_COMPLIANT"
    )
    assert (
        decide(IS_NOT, ["cast iron"], "stainless steel", free_text=True)[0]
        == "COMPLIANT"
    )
    assert (
        decide(IS_NOT, ["invented alloy"], "another invented alloy", free_text=True)[0]
        is None
    )


# ---------------------------------------------------------------- finding (b): a one-of check on a free-text field


@pytest.mark.parametrize(
    ("stated", "status"),
    [
        ("invented crude", None),
        (
            "carbon steel",
            None,
        ),  # a word a typed reader knows is still no breach on a free-text field
        ("Clean Gas", "COMPLIANT"),
        ("clean gas / invented crude", None),
        ("clean gas / thin liquid", "COMPLIANT"),
    ],
)
def test_a_one_of_on_free_text_never_fails(stated, status):
    assert decide(IS_ONE_OF, SERVICES, stated, free_text=True)[0] == status


def test_a_listed_material_is_no_proof_of_a_breach_on_a_free_text_field():
    listed = ["carbon steel", "stainless steel"]
    assert decide(IS_ONE_OF, listed, "cast iron", free_text=True)[0] is None
    assert decide(IS_ONE_OF, listed, "cast iron")[0] == "NON_COMPLIANT"


def _service_rule():
    return {
        **_typed(SERVICE_RULE, IS_ONE_OF, SERVICES, role_field="Fluid"),
        **_in(PLAIN, "5.5.2", 9, SERVICE_RULE),
    }


def test_a_fluid_name_is_a_query_end_to_end(code, monkeypatch):
    run, scope = _sheet(label="Fluid", value="invented crude")
    rows = _ours(_run(monkeypatch, run, scope, _service_rule()))
    assert [r["compliance_status"] for r in rows] == [QUERY], rows


def test_a_listed_fluid_passes_end_to_end(code, monkeypatch):
    run, scope = _sheet(label="Fluid", value="clean gas")
    rows = _ours(_run(monkeypatch, run, scope, _service_rule()))
    assert [r["compliance_status"] for r in rows] == ["COMPLIANT"], rows


# ------------------------------------------------------------------------ a field that is typed still gives a Fail


def test_a_typed_field_still_fails_end_to_end(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="cast iron")
    quote = "The invented valve body shall be carbon steel or stainless steel."
    rule = {
        **_typed(quote, IS_ONE_OF, ["carbon steel", "stainless steel"]),
        **_in(PLAIN, "6.2", 9, quote),
    }
    rows = _ours(_run(monkeypatch, run, scope, rule))
    assert [r["compliance_status"] for r in rows] == ["NON_COMPLIANT"], rows


def test_free_text_comes_from_the_role_table_never_a_label():
    roles = datasheet_checks.load_rules()["roles"]
    typed = {name for name, role in roles.items() if role.get("reads_as")}
    assert "body_material" in typed and all(
        name.endswith("_material") for name in typed
    )
    assert rule_typed_check.is_free_text("fluid") and rule_typed_check.is_free_text(
        "valve_type"
    )
    assert not rule_typed_check.is_free_text("body_material")
    # no role at all: nothing says the value can be read, so nothing can fail it
    assert rule_typed_check.is_free_text(None)


# ------------------------------------------------------------------- finding (c): the subtypes of one listed term


@pytest.mark.parametrize(
    ("stated", "status"),
    [
        ("Conventional", "COMPLIANT"),
        ("Balanced Bellows", "COMPLIANT"),
        ("conventional / balanced bellows", "COMPLIANT"),
        ("pilot-operated", "COMPLIANT"),
        ("invented style", None),
        ("conventional / invented style", None),
        ("mostly conventional", None),
    ],
)
def test_a_signed_synonym_passes_and_nothing_else_does(stated, status):
    words = rule_typed_check.signed_synonyms("valve_type")
    assert (
        decide(IS_ONE_OF, STYLES, stated, free_text=True, synonyms=words)[0] == status
    )


def test_the_verdict_says_a_synonym_carried_it():
    words = rule_typed_check.signed_synonyms("valve_type")
    assert (
        "signed synonym of direct spring-loaded"
        in decide(IS_ONE_OF, STYLES, "conventional", free_text=True, synonyms=words)[1]
    )


def test_a_synonym_only_counts_for_the_listed_term_it_belongs_to():
    words = rule_typed_check.signed_synonyms("valve_type")
    assert (
        decide(
            IS_ONE_OF,
            ["pilot-operated", "weighted"],
            "conventional",
            free_text=True,
            synonyms=words,
        )[0]
        is None
    )


def test_a_synonym_belongs_to_its_role():
    assert rule_typed_check.signed_synonyms("fluid") == {}


def test_a_subtype_passes_end_to_end_and_says_so(code, monkeypatch):
    run, scope = _sheet(label="Valve type", value="balanced bellows")
    rule = _typed(GENERAL_RULE, IS_ONE_OF, STYLES, role_field="Valve type")
    rows = _ours(
        _run(monkeypatch, run, scope, {**rule, **_in(CODE, "XG-20", 2, GENERAL_RULE)})
    )
    assert [r["compliance_status"] for r in rows] == ["COMPLIANT"], rows
    assert "signed synonym" in rows[0]["finding"]


def test_the_cell_the_engineer_reads_says_what_a_subtype_rests_on(code, monkeypatch):
    run, scope = _sheet(label="Valve type", value="balanced bellows")
    rule = _typed(GENERAL_RULE, IS_ONE_OF, STYLES, role_field="Valve type")
    _run(monkeypatch, run, scope, {**rule, **_in(CODE, "XG-20", 2, GENERAL_RULE)})
    meta = rulebook_v2_crs.part({}, db.connect(), run, frozenset({CODE}))
    assert [r["comment"] for r in meta["rulebook_v2_rows"]] == [
        "Meets: Rulebook v2: the sheet states balanced bellows: balanced bellows against one of"
        " direct spring-loaded; pilot-operated: a signed synonym of direct spring-loaded"
    ]


def test_the_note_the_engineer_reads_counts_a_rule_left_out(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="carbon steel")
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    typed = {**_typed(rule["quote"], IS_NOT, ["invented bar steel"]), **rule}
    _run(monkeypatch, run, scope, typed)
    meta = rulebook_v2_crs.part(
        {"copy": crs_export.COPY_INTERNAL}, db.connect(), run, frozenset({CODE})
    )
    for said in (meta["review_notes"][0]["detail"], meta["rulebook_v2_note"]):
        assert "1 outside this equipment type's scope" in said
        assert "(Part XCL 1)" in said and str(typed["rule_id"]) in said


def test_rule_ids_and_part_labels_reach_the_internal_copy_only(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="carbon steel")
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    typed = {**_typed(rule["quote"], IS_NOT, ["invented bar steel"]), **rule}
    _run(monkeypatch, run, scope, typed)
    allowed = frozenset(scope) | {CODE, PLAIN}
    rule_id = str(typed["rule_id"])
    internal, issue = (
        _every_cell(
            crs_export.build_crs(
                [], rulebook_v2_crs.part({"copy": copy}, db.connect(), run, allowed)
            )
        )
        for copy in (crs_export.COPY_INTERNAL, crs_export.COPY_ISSUE)
    )
    assert any(rule_id in str(c) and "Part XCL" in str(c) for c in internal)
    assert not any(rule_id in str(c) or "Part XCL" in str(c) for c in issue)


def test_the_run_line_says_a_plain_count_with_no_ids_or_parts(code, monkeypatch):
    run, scope = _sheet(label="Body material", value="carbon steel")
    rule = _in(CODE, "XCL-10", 3, LINED_RULE)
    typed = {**_typed(rule["quote"], IS_NOT, ["invented bar steel"]), **rule}
    _run(monkeypatch, run, scope, typed)
    line = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]["line"]
    assert "1 outside this equipment type's scope" in line
    assert str(typed["rule_id"]) not in line and "Part XCL" not in line


def test_the_family_field_says_where_it_came_from_and_its_one_use():
    data = json.loads(subject_scope.VOCABULARY_PATH.read_text(encoding="utf-8"))
    assert "Source:" in data["_family"] and "only across families" in data["_family"]


def test_an_unknown_word_is_a_query_end_to_end(code, monkeypatch):
    run, scope = _sheet(label="Valve type", value="invented style")
    rule = _typed(GENERAL_RULE, IS_ONE_OF, STYLES, role_field="Valve type")
    rows = _ours(
        _run(monkeypatch, run, scope, {**rule, **_in(CODE, "XG-20", 2, GENERAL_RULE)})
    )
    assert [r["compliance_status"] for r in rows] == [QUERY], rows


def test_an_unsigned_synonym_gives_no_pass(tmp_path):
    entry = {
        "role": "valve_type",
        "listed": "direct spring-loaded",
        "synonym": "invented subtype",
        "source": "invented",
    }
    path = tmp_path / "words.json"
    path.write_text(
        json.dumps({"entries": [{**entry, "status": "proposed"}]}), encoding="utf-8"
    )
    words = rule_typed_check.signed_synonyms("valve_type", path=path)
    assert (
        words == {}
        and decide(
            IS_ONE_OF, STYLES, "invented subtype", free_text=True, synonyms=words
        )[0]
        is None
    )
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        **entry,
                        "status": "signed",
                        "signed_by": "owner",
                        "signed_on": "2026-11-02",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    words = rule_typed_check.signed_synonyms("valve_type", path=path)
    assert (
        decide(IS_ONE_OF, STYLES, "invented subtype", free_text=True, synonyms=words)[0]
        == "COMPLIANT"
    )


def test_a_proposed_entry_with_a_name_and_date_is_still_not_signed(tmp_path):
    path = tmp_path / "words.json"
    entry = {
        "role": "valve_type",
        "listed": "direct spring-loaded",
        "synonym": "invented subtype",
        "status": "proposed",
        "signed_by": "owner",
        "signed_on": "2026-11-02",
    }
    path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    assert rule_typed_check.signed_synonyms("valve_type", path=path) == {}


@pytest.mark.parametrize("missing", ["signed_by", "signed_on"])
def test_a_status_without_a_signer_and_date_is_not_signed(tmp_path, missing):
    entry = {
        "role": "valve_type",
        "listed": "direct spring-loaded",
        "synonym": "invented subtype",
        "status": "signed",
        "signed_by": "owner",
        "signed_on": "2026-11-02",
    }
    del entry[missing]
    path = tmp_path / "words.json"
    path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    assert rule_typed_check.signed_synonyms("valve_type", path=path) == {}


def test_the_file_holds_exactly_the_two_entries_the_owner_signed():
    entries = json.loads(rule_typed_check.SYNONYMS_PATH.read_text(encoding="utf-8"))[
        "entries"
    ]
    assert sorted(e["synonym"] for e in entries) == ["balanced bellows", "conventional"]
    for entry in entries:
        assert entry["status"] == "signed" and entry["signed_by"] == "owner"
        assert (
            entry["signed_on"] == "2026-11-02"
            and entry["source"]
            and entry["signed_how"]
        )
        assert (
            entry["listed"] == "direct spring-loaded" and entry["role"] == "valve_type"
        )


# -------------------------------------------------------------------------------------------------- with the switch off


def test_with_the_switch_off_the_pairing_is_as_on_main(code, monkeypatch):
    monkeypatch.setattr(settings, "rulebook_v2_review_enabled", False)
    _sheet(label="Body material", value="cast iron")
    rule = {**_in(CODE, "XCL-10", 3, LINED_RULE), "field": "Body material"}
    said = rulebook_v2_review.pair_rule_to_document(_ro(), SHEET, rule)
    assert (
        said["paired"] is True
        and said["reason"] is None
        and said["value_read"] == "cast iron"
    )
    assert "scope" not in said and "scope_words" not in said


def test_the_decision_on_its_old_arguments_is_as_on_main():
    assert (
        decide(IS_ONE_OF, ["carbon steel", "stainless steel"], "cast iron")[0]
        == "NON_COMPLIANT"
    )
    assert decide(IS_ONE_OF, STYLES, "conventional")[0] is None


def _ro():
    return sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
