"""Order 14 lane C: each kind of paper gets only its governing books, at the RULE level too. A rule whose book's role does not
govern the paper's kind is never asked, however the rule was labelled and however the book reached the candidates (named by
the paper, kept by a stored run's per-rule decisions). Invented books, rules and table; read only; no model, no network."""

from __future__ import annotations

import pytest

from app import agent_review_rules as R
from app import kind_standards
from app.config import settings
from tests.test_agent_review_rules import (  # noqa: F401  (fixture and helper)
    conn,
    label,
)

TABLE = {
    "roles": {"equipment design": "", "process/method": "", "general": ""},
    "kinds_apply": {
        "datasheet": ["equipment design", "general"],
        "drawing": ["equipment design", "general"],
        "procedure": ["process/method", "general"],
        "contract": ["equipment design", "process/method", "general"],
    },
    "standards": {"SAES-Z-100": "equipment design", "SAEP-901": "process/method"},
}


def _books(c):
    c.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    c.execute(
        "CREATE TABLE document_classification (document_id TEXT PRIMARY KEY, document_number TEXT)"
    )
    c.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT)"
    )
    for doc, name in (
        ("d-eq", "SAES-Z-100"),
        ("d-me", "SAEP-901"),
        ("d-un", "SAES-Z-999"),
    ):
        c.execute("INSERT INTO documents VALUES (?, ?)", (doc, f"{name}.pdf"))
        c.execute("INSERT INTO document_classification VALUES (?, ?)", (doc, name))
    for rid, doc in (("eq", "d-eq"), ("me", "d-me"), ("un", "d-un")):
        c.execute("INSERT INTO standard_requirements VALUES (?, ?)", (rid, doc))
        label(c, rid, kind="procedure")
        label(c, f"{rid}-ds", kind="datasheet")
        c.execute("INSERT INTO standard_requirements VALUES (?, ?)", (f"{rid}-ds", doc))


@pytest.fixture
def books(conn, monkeypatch):  # noqa: F811
    _books(conn)
    monkeypatch.setattr(kind_standards, "table", lambda path=None: TABLE)
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", True)
    return conn


def test_an_equipment_design_rule_labelled_procedure_is_not_asked_of_a_procedure(books):
    """The door V3 found: two models labelled equipment design rules as procedure rules; the book's role still decides."""
    out = R.decide_rule(books, "eq", "procedure")
    assert out["ask"] is False and out["reason"] == R.ANOTHER_PAPER
    assert (
        out["needs_kind"] == "datasheet or drawing"
        and out["book_role"] == "equipment design"
    )
    kept, left, _ = R.filter_rows(books, [{"id": "eq", "item_id": "R-eq"}], "procedure")
    assert kept == [] and left[0]["book_role"] == "equipment design"
    counts = R.count_left_out(left)
    assert counts[R.ANOTHER_PAPER] == {
        "total": 1,
        "by_kind": {"datasheet or drawing": 1},
    }


def test_method_rules_and_unmapped_books_are_still_asked_of_a_procedure(books):
    assert R.decide_rule(books, "me", "procedure")["ask"] is True
    assert (
        R.decide_rule(books, "un", "procedure")["ask"] is True
    )  # an unmapped book is never left out (only narrows)


def test_a_datasheet_keeps_its_equipment_design_rules(books):
    assert R.decide_rule(books, "eq-ds", "datasheet")["ask"] is True
    assert R.decide_rule(books, "un-ds", "datasheet")["ask"] is True


def test_off_changes_nothing(books, monkeypatch):
    monkeypatch.setattr(settings, "standard_roles_by_kind_enabled", False)
    out = R.decide_rule(books, "eq", "procedure")
    assert out["ask"] is True and "book_role" not in out
    kept, left, _ = R.filter_rows(books, [{"id": "eq", "item_id": "R-eq"}], "procedure")
    assert len(kept) == 1 and left == []


def test_a_stored_pass_of_such_a_rule_cannot_stand(books):
    """`tier_lookup` reads the same decision: a rule the kind does not take has no tier, so no stored verdict stands."""
    look = R.tier_lookup(books, "procedure")
    assert look({"rule_version_id": "eq"}) is None
    assert look({"rule_version_id": "me"}) == "AI approved"


def test_the_real_table_maps_the_equipment_design_books_away_from_a_procedure():
    """The shipped table: SAES-J-601 and SAES-B-006 are equipment design; a procedure takes process/method and general only;
    the HAZOP / SIL method books are process/method."""
    data = kind_standards.table()
    assert kind_standards.role_of(["SAES-J-601"], data) == "equipment design"
    assert kind_standards.role_of(["SAES-B-006"], data) == "equipment design"
    assert "equipment design" not in data["kinds_apply"]["procedure"]
    for book in ("IEC 61882", "IEC 61511-1"):
        assert kind_standards.role_of([book], data) == "process/method"


# ---- the kind-to-book file gate G2 reads (reference/kind_books.json) -------------------------------------------------------


def _kind_books() -> dict:
    import json
    from pathlib import Path

    return json.loads(
        (
            Path(kind_standards.__file__).parent / "reference" / "kind_books.json"
        ).read_text(encoding="utf-8")
    )


def test_the_kind_books_file_never_lists_fewer_books_than_the_apps_tables_for_a_type():
    """Every book the review selects for an equipment type (governing, materials, in part) is in the type's entry: the
    file can add a company book, never drop one the app uses."""
    from app import applicability
    from app.standard_ids import same_standard

    data, gov = _kind_books(), applicability.governing_table()
    assert data["format"] == "crs-gates-kind-books/1"
    for key, entries in data["kinds"].items():
        _kind, _, etype = key.partition("|")
        if not etype or etype.startswith("playbook:"):
            continue  # order 14 lane P: a "<kind>|playbook:<id>" key is a procedure type, not an equipment type
        listed = [e["book"] for e in entries]
        want = list(gov["equipment_types"].get(etype, [])) + list(
            gov["materials_standards"]
        )
        want += [p["standard"] for p in gov["partial_standards"].get(etype, [])]
        missing = [b for b in want if not any(same_standard(b, x) for x in listed)]
        assert not missing, (key, missing)


def test_a_procedure_is_governed_by_its_method_books_only():
    from app.standard_ids import same_standard

    data, roles = _kind_books(), kind_standards.table()
    design = [s for s, r in roles["standards"].items() if r == "equipment design"]
    for kind in ("procedure", "study"):
        listed = [e["book"] for e in data["kinds"][kind]]
        assert not [b for b in listed if any(same_standard(b, d) for d in design)]
        for book in roles["method_standards"][kind]:
            assert any(same_standard(book, x) for x in listed), book


def test_asme_viii_governs_a_relief_valve_only_from_ug_150_to_ug_156():
    import sys
    from pathlib import Path

    sys.path.insert(
        0, str(Path(kind_standards.__file__).resolve().parents[2] / "scripts")
    )
    import crs_gates

    path = Path(kind_standards.__file__).parent / "reference" / "kind_books.json"
    books = crs_gates.mapping_from_file(path, "datasheet", "relief valve")
    asme = "ASME-Sec-VIII-Div1-2023"
    assert (
        books.judge(asme, "UG-155")[0] == "pass"
        and books.judge(asme, "UG-150(a)")[0] == "pass"
    )
    for wrong in ("7.16", "2.5", "0.3", "UG-24", "44-2", "UG-1500"):
        assert books.judge(asme, wrong)[0] == "fail", wrong
    assert (
        crs_gates.mapping_from_file(path, "procedure", None).judge(
            "SAES-J-601", "9.2.1"
        )[0]
        == "fail"
    )


def test_a_book_that_governs_an_equipment_type_is_equipment_design_for_a_procedure(
    books, monkeypatch
):
    """A procedure whose equipment type was read from a phrase got that equipment's governing book; with
    `governing_books_role` the book takes that role unless the table names it, so the procedure does not get its rules
    and a datasheet still does."""
    monkeypatch.setattr(
        kind_standards,
        "table",
        lambda path=None: {**TABLE, "governing_books_role": "equipment design"},
    )
    monkeypatch.setattr(kind_standards, "_governing_books", lambda: ["SAES-Z-999"])
    out = R.decide_rule(books, "un", "procedure")
    assert out["ask"] is False and out["book_role"] == "equipment design"
    assert R.decide_rule(books, "un-ds", "datasheet")["ask"] is True
    assert (
        R.decide_rule(books, "me", "procedure")["ask"] is True
    )  # a named role wins over the fallback
    monkeypatch.setattr(
        kind_standards, "table", lambda path=None: TABLE
    )  # no fallback in the table: unmapped stays asked
    assert R.decide_rule(books, "un", "procedure")["ask"] is True


def test_the_shipped_tables_give_the_relief_valve_books_the_equipment_design_role():
    data = kind_standards.table()
    for name in ("SAES-J-600", "API 520 Part I", "ASME BPVC Section VIII Division 1"):
        assert kind_standards.role_of([name], data) == "equipment design", name


def test_asme_viii_governs_a_pump_only_in_its_casing_weld_radiography_clauses():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(kind_standards.__file__).resolve().parents[2] / "scripts"))
    import crs_gates

    path = Path(kind_standards.__file__).parent / "reference" / "kind_books.json"
    books = crs_gates.mapping_from_file(path, "datasheet", "pump")
    asme = "ASME-Sec-VIII-Div1-2023"
    assert books.judge(asme, "UW-51")[0] == "pass" and books.judge(asme, "UW-52(b)")[0] == "pass"
    for wrong in ("UG-118", "19-3", "7.16"):
        assert books.judge(asme, wrong)[0] == "fail", wrong


# ---- the clause limit at rule choice: the same kind_books.json G2 reads -------------------------------------------------------


@pytest.fixture
def limited(conn, monkeypatch, tmp_path):  # noqa: F811
    """Book d-eq is "SAES-Z-100"; a pump datasheet takes it only in ZZ-51 and ZZ-52."""
    import json

    from app import agent_review_rule_choice as rc

    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    conn.execute("CREATE TABLE document_classification (document_id TEXT PRIMARY KEY, document_number TEXT)")
    conn.execute("CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, clause TEXT)")
    conn.execute("INSERT INTO documents VALUES ('d-eq', 'SAES-Z-100.pdf')")
    conn.execute("INSERT INTO document_classification VALUES ('d-eq', 'SAES-Z-100')")
    for rid, clause in (("in", "ZZ-51(b)"), ("in2", "ZZ-52"), ("out", "ZZ-118"), ("nil", None), ("far", "ZZ-510")):
        conn.execute("INSERT INTO standard_requirements VALUES (?, 'd-eq', ?)", (rid, clause))
        label(conn, rid, kind="datasheet")
    path = tmp_path / "kind_books.json"
    path.write_text(json.dumps({"format": rc.KIND_BOOKS_FORMAT, "kinds": {
        "datasheet|pump": [{"book": "SAES-Z-100", "clauses": ["ZZ-51", "ZZ-52"]}],
        "datasheet|relief valve": [{"book": "SAES-Z-100"}]}}))
    monkeypatch.setattr(rc, "KIND_BOOKS_PATH", path)
    monkeypatch.setattr(settings, "kind_book_clause_limit_enabled", True, raising=False)
    return conn


def test_a_book_limited_to_clauses_for_a_kind_is_asked_only_in_them(limited):
    from app import agent_review_rule_choice as rc

    ask = {r: R.decide_rule(limited, r, "datasheet", equipment_type="pump") for r in ("in", "in2", "out", "nil", "far")}
    assert ask["in"]["ask"] and ask["in2"]["ask"]
    for r in ("out", "nil", "far"):
        assert ask[r]["ask"] is False and ask[r]["reason"] == rc.PART_OUTSIDE, r
    assert "only in ZZ-51, ZZ-52" in ask["out"]["part_note"]
    # another type that takes the whole book, and a type with no entry: nothing is left out
    assert R.decide_rule(limited, "out", "datasheet", equipment_type="relief valve")["ask"] is True
    assert R.decide_rule(limited, "out", "datasheet", equipment_type="compressor")["ask"] is True


def test_the_clause_limit_off_changes_nothing(limited, monkeypatch):
    monkeypatch.setattr(settings, "kind_book_clause_limit_enabled", False, raising=False)
    assert R.decide_rule(limited, "out", "datasheet", equipment_type="pump")["ask"] is True


def test_rule_choice_and_gate_g2_read_clauses_the_same_way():
    import sys
    from pathlib import Path

    from app import agent_review_rule_choice as rc

    sys.path.insert(0, str(Path(kind_standards.__file__).resolve().parents[2] / "scripts"))
    import crs_gates

    prefixes = ["UG-150", "UG-156", "UW-51", "4.1"]
    for clause in ("UG-150", "UG-150(a)", "UG-150.1", "UG-1500", "UG-15", "uw-51 (b)", "Clause 4.1.2", "4.10", "", "7.16"):
        assert rc.clause_in(clause, prefixes) == crs_gates.clause_in(clause, prefixes), clause
    assert rc.KIND_BOOKS_FORMAT == crs_gates.MAPPING_FORMAT
