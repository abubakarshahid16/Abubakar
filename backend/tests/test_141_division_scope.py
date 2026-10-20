"""#141: a division of a standard limited by its OWN scope sentence to one
construction ("This Part applies to vessels constructed of ...") applies only
to equipment of that construction.

Found on a vessel review (order 141): the requirements of a pressure-vessel
code's special-construction parts were checked against an ordinary vessel -
one false non-compliance and a run of nozzle-size lines. Order 143: no code
names a standard's parts; the model reads each division's own scope sentence,
code verifies the quotes and checks the equipment's stated construction;
unsure goes to the engineer; with the model off or failing nothing changes.
Invented standard text, part names and datasheet values only (rule 13).
"""

from __future__ import annotations

import json
import uuid

import pytest

from app import (
    ai_applicability,
    ai_task_runner,
    comparison,
    datasheets,
    db,
    scope_ledger,
    standards,
    subject_scope,
    submittal_review,
)
from app.config import settings
from app.reasoning_provider import ProviderRefused, Response

NOW = "2026-10-19T00:00:00Z"

ZZ_SCOPE = "The rules in Part ZZ are applicable to vessels constructed of graphite and graphite compounds."
TT_SCOPE = "The rules in Part TT are applicable to vessels constructed of titanium."
PAGES = [
    (
        1,
        "PART AA\nGENERAL REQUIREMENTS FOR ALL VESSELS\nAA-1 SCOPE\n"
        "The rules of Part AA apply to all vessels of this code.\n"
        "AA-2 The shell thickness shall be at least 6 mm.\n",
    ),
    (
        2,
        "PART ZZ\nREQUIREMENTS FOR VESSELS CONSTRUCTED OF GRAPHITE\nZZ-1 SCOPE\n"
        + ZZ_SCOPE
        + "\nZZ-2 Impregnated tubes shall withstand at least 20 bar.\n",
    ),
    (
        3,
        "PART TT\nREQUIREMENTS FOR VESSELS CONSTRUCTED OF TITANIUM\nTT-1 SCOPE\n"
        + TT_SCOPE
        + "\nTT-2 Titanium welds shall be shielded on both sides.\n",
    ),
]
GENERAL = {
    "id": "aa",
    "standard_document_id": "std",
    "page": 1,
    "requirement_text": "The shell thickness shall be at least 6 mm.",
    "source_text": "AA-2 The shell thickness shall be at least 6 mm.",
}
SPECIAL = {
    "id": "zz",
    "standard_document_id": "std",
    "page": 2,
    "requirement_text": "Impregnated tubes shall withstand at least 20 bar.",
    "source_text": "ZZ-2 Impregnated tubes shall withstand at least 20 bar.",
}
TITAN = {
    "id": "tt",
    "standard_document_id": "std",
    "page": 3,
    "requirement_text": "Titanium welds shall be shielded on both sides.",
    "source_text": "TT-2 Titanium welds shall be shielded on both sides.",
}

LIMITED = {
    "limited": "yes",
    "construction": "constructed of graphite and graphite compounds",
    "quote": ZZ_SCOPE,
}
LIMITED_TT = {
    "limited": "yes",
    "construction": "constructed of titanium",
    "quote": TT_SCOPE,
}
NOT_LIMITED = {"limited": "no", "construction": None, "quote": None}
STEEL = [
    {
        "field_name": "shell material",
        "field_label": "Shell material",
        "field_value": "Carbon steel plate XQ-70",
    }
]
GRAPHITE = [
    {
        "field_name": "shell material",
        "field_label": "Shell material",
        "field_value": "Impervious graphite block",
    }
]
NOT_GRAPHITE = {
    "equipment_is": "Carbon steel plate XQ-70",
    "quote": "Shell material: Carbon steel plate XQ-70",
    "is_that": "no",
}


class FakeModel:
    """Answers each task by its instruction; counts the calls (no weights)."""

    def __init__(self, scope=None, construction=None, *, fail=None):
        self.requested_model = "test-model"
        self.replies = {"division": scope, "construction": construction, "titles": None}
        self.fail = fail
        self.calls: list[str] = []

    def reason(self, packet):
        prompt = packet.prompt
        if prompt.startswith(ai_applicability.SCOPE_INSTRUCTION[:40]):
            kind, passage = "division", prompt.split("TEXT:\n", 1)[1]
            default = (
                LIMITED
                if "Part ZZ" in passage
                else LIMITED_TT
                if "Part TT" in passage
                else NOT_LIMITED
            )
        elif prompt.startswith("The TEXT is a list of sub-heading titles"):
            kind, default = "titles", {"titles": []}
        else:
            kind, default = "construction", NOT_GRAPHITE
        if kind != "titles":
            self.calls.append(kind)
        if self.fail:
            raise ProviderRefused(self.fail)
        reply = self.replies[kind]
        reply = reply(prompt) if callable(reply) else reply
        return Response(
            text=json.dumps(reply or default),
            provider="ollama",
            model_tag=self.requested_model,
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "division_scope.sqlite")
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _gate(
    model,
    facts=STEEL,
    pages=PAGES,
    reqs=(GENERAL, SPECIAL, TITAN),
    equipment="Pressure vessel",
):
    return ai_applicability.division_gate(
        [dict(r) for r in reqs],
        classification={"equipment_type": equipment},
        facts=facts,
        standard_labels={"std": "XYZ code"},
        provider=model,
        pages_of=lambda sid: pages,
    )


def _ids(rows):
    return [r["requirement"]["id"] if "requirement" in r else r["id"] for r in rows]


# ------------------------------------------------------- the decision, by the gate


def test_a_titanium_only_part_does_not_apply_to_a_carbon_steel_vessel(temp_storage):
    model = FakeModel()
    out = _gate(model)
    assert _ids(out["items"]) == ["tt"]
    [item] = out["items"]
    assert item["code"] == "outside_division_scope"
    # the reason quotes the division's own scope sentence and the stated line,
    # and says truthfully who decided what
    assert TT_SCOPE in item["detail"] and "Carbon steel plate XQ-70" in item["detail"]
    assert "names carbon steel" in item["detail"] and "code decided" in item["detail"]
    assert item["decided_by"] == "ai:test-model+code"
    assert (
        scope_ledger.REASONS["outside_division_scope"][0] == scope_ledger.DOES_NOT_APPLY
    )
    # one scope read per division, one construction read per limited division
    assert sorted(model.calls) == ["construction"] * 2 + ["division"] * 3
    assert out["summary"]["does_not_apply"] == 1 and out["summary"]["limited"] == 2


def test_the_models_no_alone_never_excludes_a_graphite_only_part(temp_storage):
    # code cannot tell from the stated material that the vessel is not graphite
    # (graphite is in no exclusive material family): the engineer decides
    out = _gate(FakeModel())
    assert _ids(out["kept"]) == ["aa"]
    [held] = out["held"]
    assert held["requirement"]["id"] == "zz" and held["code"] == "applicability_unsure"
    assert ZZ_SCOPE in held["detail"] and "an engineer decides" in held["detail"]


def test_a_graphite_only_part_applies_to_a_graphite_vessel(temp_storage):
    yes = {
        "equipment_is": "Impervious graphite block",
        "quote": "Shell material: Impervious graphite block",
        "is_that": "yes",
    }
    # the model's "yes" is taken from the stated line only when that line names
    # the part's construction: it is read for the graphite part, and for the
    # titanium part the same answer names nothing, so that one is held
    out = _gate(FakeModel(construction=yes), facts=GRAPHITE)
    assert _ids(out["kept"]) == ["aa", "zz"]
    assert out["items"] == [] and _ids(out["held"]) == ["tt"]


def test_no_construction_stated_goes_to_the_engineer(temp_storage):
    model = FakeModel()
    out = _gate(model, facts=[], equipment=None)
    assert _ids(out["kept"]) == ["aa"] and _ids(out["held"]) == ["zz", "tt"]
    assert (
        scope_ledger.REASONS["applicability_unsure"][0]
        == scope_ledger.APPLIES_NOT_CHECKED
    )
    # nothing stated: the equipment is not asked about
    assert "construction" not in model.calls


def test_an_unsure_model_goes_to_the_engineer(temp_storage):
    unsure = {"equipment_is": None, "quote": None, "is_that": "unsure"}
    out = _gate(FakeModel(construction=unsure))
    assert _ids(out["kept"]) == ["aa"] and _ids(out["held"]) == ["zz", "tt"]
    assert out["items"] == []


def test_with_the_model_failing_nothing_is_excluded_and_nothing_is_compared(
    temp_storage,
):
    out = _gate(FakeModel(fail="the model could not be reached"))
    # order 173.2: a scope step that did not run is never a pass. Nothing is
    # excluded, and every requirement of a division it could not screen is HELD
    # for the engineer instead of being compared to a verdict.
    assert out["kept"] == [] and out["items"] == []
    assert _ids(out["held"]) == ["aa", "zz", "tt"]
    assert {h["code"] for h in out["held"]} == {"applicability_unsure"}
    assert all("could not be read" in h["detail"] for h in out["held"])
    assert all(h["decided_by"] == "code:scope-not-read" for h in out["held"])
    assert out["summary"]["could_not_read"] == 3


def test_a_model_that_stops_answering_is_not_asked_again_in_the_run(temp_storage):
    model = FakeModel(fail="read timeout")
    out = _gate(model)
    assert model.calls == ["division"]
    assert out["kept"] == [] and out["items"] == []
    assert _ids(out["held"]) == ["aa", "zz", "tt"]
    assert out["summary"]["could_not_read"] == 3
    assert "the divisions after it were not read" in out["summary"]["stopped"]


def test_a_scope_quote_not_in_the_standard_is_ignored(temp_storage):
    made_up = {
        "limited": "yes",
        "construction": "constructed of titanium",
        "quote": "Part TT applies only to vessels constructed of titanium.",
    }
    model = FakeModel(scope=lambda p: made_up if "Part TT" in p else NOT_LIMITED)
    out = _gate(model)
    # the invented quote is not used to exclude anything; the division it was
    # about is held (its scope was not read), the others are untouched
    assert _ids(out["kept"]) == ["aa", "zz"] and out["items"] == []
    assert _ids(out["held"]) == ["tt"]
    # read twice (one retry naming the problem), then refused; never asked further
    assert model.calls.count("division") == 4 and "construction" not in model.calls


def test_a_construction_not_in_the_scope_sentence_is_ignored(temp_storage):
    wrong = {**LIMITED_TT, "construction": "constructed of cast iron"}
    out = _gate(FakeModel(scope=lambda p: wrong if "Part TT" in p else NOT_LIMITED))
    assert _ids(out["kept"]) == ["aa", "zz"] and out["items"] == []
    assert _ids(out["held"]) == ["tt"]


def test_a_no_resting_on_a_line_that_is_not_stated_is_ignored(temp_storage):
    invented = {**NOT_GRAPHITE, "quote": "Shell material: stainless steel"}
    out = _gate(FakeModel(construction=invented))
    assert _ids(out["kept"]) == ["aa", "zz", "tt"] and out["items"] == []


def test_any_stated_value_naming_the_construction_sends_it_to_the_engineer(
    temp_storage,
):
    # a main part or only a seal? Not for code to say. Every stated value is
    # read, not only the lines the model was shown: forty other material lines
    # come first here
    filler = [
        {
            "field_name": f"n{k} flange material",
            "field_label": f"N{k} flange material",
            "field_value": f"Forged carbon steel grade QF{k}",
        }
        for k in range(40)
    ]
    facts = [
        *STEEL,
        *filler,
        {
            "field_name": "tube material",
            "field_label": "Tube material",
            "field_value": "Seamless titanium tubes",
        },
    ]
    assert not any(
        "titanium" in s for s in ai_applicability.stated_construction({}, facts)
    )
    out = _gate(FakeModel(), facts=facts)
    assert "tt" in _ids(out["held"]) and out["items"] == []


def test_a_general_division_applies_whatever_the_construction(temp_storage):
    out = _gate(FakeModel(), reqs=(GENERAL,))
    assert _ids(out["kept"]) == ["aa"] and out["items"] == [] and out["held"] == []


def test_a_heading_that_starts_no_division_ends_the_one_before_it(temp_storage):
    # a missed heading (below the top of its page) must not lend the titanium
    # part's scope to a general appendix
    appendix = (
        4,
        "TT-9 Titanium parts shall be marked.\nTT-10 Marks shall be stamped.\n"
        "TT-11 More rules for marks.\nTT-12 Still more.\nTT-13 And more.\n"
        "MANDATORY APPENDIX 1\nSUPPLEMENTARY DESIGN FORMULAS\n"
        "1-1 Cylindrical shells shall be designed with formula one.\n",
    )
    formula = {
        "id": "f",
        "standard_document_id": "std",
        "page": 4,
        "requirement_text": "Cylindrical shells shall be designed with formula one.",
        "source_text": "1-1 Cylindrical shells shall be designed with formula one.",
    }
    out = _gate(FakeModel(), pages=[*PAGES, appendix], reqs=(GENERAL, TITAN, formula))
    assert _ids(out["items"]) == ["tt"]
    # the break opens no part the model confirms; what follows it inherits the
    # titanium part's exclusion DOWNGRADED to a hold, never kept, never excluded
    assert "f" not in _ids(out["kept"]) and _ids(out["held"]) == ["f"]


def test_a_page_with_two_headings_starts_no_division_and_ends_the_one_before(
    temp_storage,
):
    both = (
        4,
        "MANDATORY APPENDIX 1\nSUPPLEMENTARY DESIGN FORMULAS\n"
        "Appendix 9 (jacketed vessels)\nwhere a jacket is used.\n"
        "1-1 Cylindrical shells shall be designed with formula one.\n",
    )
    formula = {
        "id": "f",
        "standard_document_id": "std",
        "page": 4,
        "requirement_text": "Cylindrical shells shall be designed with formula one.",
        "source_text": "1-1 Cylindrical shells shall be designed with formula one.",
    }
    out = _gate(FakeModel(), pages=[*PAGES, both], reqs=(TITAN, formula))
    assert _ids(out["items"]) == ["tt"] and _ids(out["held"]) == ["f"]
    assert out["kept"] == []


def test_the_division_s_own_scope_is_read_never_a_sub_clause_s():
    text = subject_scope.StandardText(
        [
            (
                1,
                "PART AA\nTITLE\nAA-1 SCOPE\n"
                "The rules of Part AA apply to all vessels.\n"
                "AA-2 GENERAL\nWords.\nAA-30 SCOPE OF JACKET RULES\n"
                "These apply only to vessels constructed with jackets.\n",
            )
        ]
    )
    [div] = ai_applicability.divisions(text)
    passage = ai_applicability.scope_passage(text, div, None)
    assert "apply to all vessels" in passage and "jackets" not in passage


def test_a_scope_line_of_the_second_sub_clause_is_not_the_division_s():
    text = subject_scope.StandardText(
        [
            (
                1,
                "PART AA\nGENERAL REQUIREMENTS\nAA-1 GENERAL\n"
                "The rules of Part AA apply to all vessels.\n"
                "AA-2 SCOPE OF STEEL RULES\n"
                "AA-2 to AA-5 apply only to vessels constructed of carbon and low alloy steels.\n",
            )
        ]
    )
    [div] = ai_applicability.divisions(text)
    passage = ai_applicability.scope_passage(text, div, None)
    assert "apply to all vessels" in passage and "low alloy" not in passage


def test_a_layer_on_the_stated_material_is_held_never_an_exclusion(temp_storage):
    # cladding, an overlay or a coating is in the material family of #920, but
    # a layer does not change the base material: the engineer decides
    scope = (
        "The rules in Part CS are applicable to vessels constructed of carbon steel."
    )
    pages = [
        (
            1,
            "PART CS\nCARBON STEEL VESSELS\nCS-1 SCOPE\n"
            + scope
            + "\nCS-2 Welds shall be ground.\n",
        )
    ]
    weld = {
        "id": "cs",
        "standard_document_id": "std",
        "page": 1,
        "requirement_text": "Welds shall be ground.",
        "source_text": "CS-2 Welds shall be ground.",
    }
    clad = [
        {
            "field_name": "shell material",
            "field_label": "Shell material",
            "field_value": "Grade QX-70 clad",
        }
    ]
    no = {
        "equipment_is": "Grade QX-70 clad",
        "quote": "Shell material: Grade QX-70 clad",
        "is_that": "no",
    }
    limited = {
        "limited": "yes",
        "construction": "constructed of carbon steel",
        "quote": scope,
    }
    out = _gate(
        FakeModel(scope=limited, construction=no), facts=clad, pages=pages, reqs=(weld,)
    )
    assert out["items"] == [] and _ids(out["held"]) == ["cs"]


# ------------------------------------------------------ where a requirement sits


def _divisions(pages):
    text = subject_scope.StandardText(pages)
    return text, [d["name"] for d in ai_applicability.divisions(text) if d["name"]]


def test_a_division_starts_a_page_and_a_reference_in_a_sentence_ends_it():
    text, names = _divisions(
        [
            *PAGES,
            (
                3,
                "ZZ-3 Tubes\nshall be\nmarked and\nthen tested\nas in the rules of\n"
                "Part AA\nand marked.\nZZ-4 More rules.\n",
            ),
        ]
    )
    assert names == [("part", "AA"), ("part", "ZZ")]
    # the reference opens nothing, and what follows it sits in no division
    third = {"id": "x", "page": 3, "source_text": "ZZ-4 More rules."}
    assert (
        ai_applicability.division_of(third, text, ai_applicability.divisions(text))
        is None
    )


def test_a_contents_page_opens_no_division_and_what_precedes_the_first_is_in_none():
    contents = (1, "CONTENTS\nPart AA\nGeneral\nPart ZZ\nGraphite\n")
    intro = (2, "FOREWORD\nThe vessel shall be marked with the code symbol.\n")
    pages = [contents, intro, (3, PAGES[0][1]), (4, PAGES[1][1])]
    text, names = _divisions(pages)
    assert names == [("part", "AA"), ("part", "ZZ")]
    marked = {
        "id": "m",
        "page": 2,
        "source_text": "The vessel shall be marked with the code symbol.",
    }
    assert (
        ai_applicability.division_of(marked, text, ai_applicability.divisions(text))
        is None
    )
    # and a requirement in no division is never asked about or narrowed
    out = ai_applicability.division_gate(
        [marked],
        classification={},
        facts=STEEL,
        provider=FakeModel(fail="down"),
        pages_of=lambda sid: pages,
    )
    assert _ids(out["kept"]) == ["m"]


def test_an_appendix_and_its_continued_heading_are_one_division():
    _text, names = _divisions(
        [
            (
                1,
                "MANDATORY APPENDIX 7\nRULES FOR WIDGETS\n7-1 SCOPE\nThese rules apply to widgets.\n",
            ),
            (
                2,
                "MANDATORY APPENDIX 7 RULES FOR WIDGETS (Cont'd)\n7-2 Widgets shall be blue.\n",
            ),
            (3, "Annex B (normative)\nTests\nB.1 Tests shall be run.\n"),
        ]
    )
    assert names == [("appendix", "7"), ("annex", "B")]


def test_the_model_reads_the_divisions_own_scope_clause():
    text = subject_scope.StandardText(
        [
            (
                1,
                "PART ZZ\nTITLE\nINTRODUCTION\n"
                + "Background words. " * 40
                + "\nZZ-1 SCOPE\n"
                + ZZ_SCOPE
                + "\n",
            )
        ]
    )
    [div] = ai_applicability.divisions(text)
    passage = ai_applicability.scope_passage(text, div, None)
    assert passage.startswith("PART ZZ TITLE INTRODUCTION")
    assert ai_applicability.folded_in(ZZ_SCOPE, passage)
    assert len(passage.split()) <= ai_applicability.SCOPE_WORDS


# ---------------------------------------------------------------- on a review


def _doc(doc_id, filename, role, pages, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, len(pages), NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        for page, text in pages:
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, page, text, len(text)),
            )
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,?,?,?,NULL,'prose',"
                "?,1,?,1)",
                (
                    f"{doc_id}-{page}",
                    doc_id,
                    filename,
                    page,
                    page,
                    page,
                    text,
                    f"h-{doc_id}-{page}",
                ),
            )


def _review(monkeypatch, model, *, enabled=True):
    monkeypatch.setattr(settings, "ai_division_scope_enabled", enabled)
    monkeypatch.setattr(ai_task_runner, "make_provider", lambda model_name=None: model)
    _doc("std", "XYZ-code.pdf", "COMPANY_STANDARD", PAGES, document_number="XYZ-100")
    _doc(
        "sub",
        "sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        [(1, "SHELL MATERIAL Carbon steel plate XQ-70\nDESIGN PRESSURE 10 barg\n")],
        equipment_type="Pressure vessel",
    )
    ids = {}
    for req in (GENERAL, SPECIAL, TITAN):
        ids[req["id"]] = standards.create_requirement(
            standard_document_id="std",
            chunk_id=f"std-{req['page']}",
            clause=None,
            page=req["page"],
            requirement_text=req["requirement_text"],
            source_text=req["source_text"],
            structured={"requirement_type": "statement"},
        )["id"]
    for label, value in (
        ("Shell material", "Carbon steel plate XQ-70"),
        ("Design pressure", "10 barg"),
    ):
        datasheets.create_fact(
            submittal_document_id="sub",
            chunk_id="sub-1",
            field_label=label,
            raw_value=value,
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
    return (
        result,
        {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)},
        ids,
    )


def test_a_review_does_not_apply_a_division_limited_to_another_construction(
    temp_storage, monkeypatch
):
    result, stored, ids = _review(monkeypatch, FakeModel())
    assert stored[ids["aa"]]["state"] == scope_ledger.CHECKED
    assert stored[ids["tt"]]["state"] == scope_ledger.DOES_NOT_APPLY
    assert stored[ids["tt"]]["reason_code"] == "outside_division_scope"
    assert TT_SCOPE in stored[ids["tt"]]["reason"]
    assert not any(f.get("requirement_id") == ids["tt"] for f in result["findings"])
    assert result["requirement_split"]["division_scope"]["does_not_apply"] == 1


def test_a_review_holds_an_unsure_division_for_the_engineer(temp_storage, monkeypatch):
    unsure = {"equipment_is": None, "quote": None, "is_that": "unsure"}
    result, stored, ids = _review(monkeypatch, FakeModel(construction=unsure))
    assert stored[ids["zz"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert stored[ids["zz"]]["reason_code"] == "applicability_unsure"
    assert not any(f.get("requirement_id") == ids["zz"] for f in result["findings"])


def test_a_review_with_the_division_reader_off_changes_nothing(
    temp_storage, monkeypatch
):
    model = FakeModel(construction=NOT_GRAPHITE)
    result, stored, ids = _review(monkeypatch, model, enabled=False)
    assert {stored[i]["state"] for i in ids.values()} == {scope_ledger.CHECKED}
    assert model.calls == [] and "division_scope" not in result["requirement_split"]


def test_a_review_whose_scope_step_could_not_run_holds_the_division_not_a_verdict(
    temp_storage, monkeypatch
):
    # order 173.2: the model could not be reached, so the scope step never ran.
    # The special parts are HELD for the engineer; they are not compared.
    result, stored, ids = _review(
        monkeypatch, FakeModel(fail="the model could not be reached")
    )
    for name in ("zz", "tt"):
        assert stored[ids[name]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
        assert stored[ids[name]]["reason_code"] == "applicability_unsure"
        assert "could not be read" in stored[ids[name]]["reason"]
        assert not any(f.get("requirement_id") == ids[name] for f in result["findings"])
    assert result["requirement_split"]["division_scope"]["could_not_read"] == 3
