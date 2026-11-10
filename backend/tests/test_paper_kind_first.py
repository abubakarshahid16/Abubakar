"""Owner order 11 Nov step 2 (#805): paper kind first.

Every paper gets ONE kind of a closed list from its own cover and title words,
before the equipment type; a procedure or a contract never takes an equipment
type as its MAIN label (it may keep a secondary one). Behind
PAPER_KIND_FIRST_ENABLED (off). Invented documents only; no model.
"""

from __future__ import annotations

import json

import pytest

from app import classification, db, paper_kind
from app.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", False)
    db.reset_connection()
    db.reset_schema_memo()
    db.init_db()
    yield
    db.reset_connection()


def _filler(prefix: str, n: int = 14) -> str:
    return "\n".join(f"{prefix} line {i}" for i in range(n))


def _page(*title_lines: str) -> dict:
    return {"page_no": 1, "text": "\n".join(title_lines) + "\n" + _filler("Body")}


#: A procedure whose title names equipment and whose body mentions more.
PROCEDURE = (
    "ACME PLANT PROJECT\nCENTRIFUGAL COMPRESSOR HAZARD STUDY PROCEDURE\n"
    "PAGE 1 OF 9\nREV.: 00\n"
    + _filler("Filler")
    + "\n5.2 The relief valve shall be checked before the study starts.\n"
    + _filler("Closing")
)
CONTRACT = (
    'SCHEDULE "K"\nATTACHMENT IX\nSUPPLY OF SPARE ITEMS\n'
    "1.0 CONTRACTOR shall submit a plan within thirty days of this CONTRACT.\n"
    + _filler("Clause")
)
DATASHEET = "ACME PLANT PROJECT\nCENTRIFUGAL PUMP DATA SHEET\nREV.: 00\n" + _filler(
    "Row"
)


def _doc(doc_id, pages, *, role="CONTRACTOR_SUBMITTAL", filename=None):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                doc_id,
                filename or f"{doc_id}.pdf",
                doc_id,
                1,
                "x",
                "ready",
                "2026-11-11",
            ),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
                " VALUES (?,?,?,?,0)",
                (doc_id, n, text, len(text)),
            )
            conn.execute(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
                " page_end, text, token_count, content_hash, retrievable)"
                " VALUES (?,?,?,?,?,?,?,1,?,1)",
                (f"{doc_id}_c{n}", doc_id, "f", n, n, n, text, f"{doc_id}{n}"),
            )
        if role is not None:
            conn.execute(
                "INSERT INTO document_classification (document_id, suggested_by,"
                " document_role) VALUES (?,?,?)",
                (doc_id, "t", role),
            )


def _equipment(doc_id):
    row = (
        db.connect()
        .execute(
            "SELECT equipment_type, equipment_type_evidence FROM document_classification"
            " WHERE document_id = ?",
            (doc_id,),
        )
        .fetchone()
    )
    return row["equipment_type"], json.loads(row["equipment_type_evidence"] or "null")


# ----------------------------------------------------------- the decision


@pytest.mark.parametrize(
    ("lines", "want"),
    [
        (("ACME", "HAZARD STUDY PROCEDURE"), "procedure"),
        (("ACME", 'SCHEDULE "K"', "SUPPLY OF SPARE ITEMS"), "contract"),
        (("ACME", "GENERAL CONDITIONS OF CONTRACT"), "contract"),
        (("ACME", "PROCESS DATA SHEET"), "datasheet"),
        (("ACME", "PLOT GENERAL ARRANGEMENT"), "drawing"),
        (("ACME", "HYDROSTATIC TEST REPORT"), "test_record"),
        (("ACME", "CERTIFICATE OF CONFORMITY"), "test_record"),
        (("ACME", "PRESSURE TEST PROCEDURE"), "procedure"),
        (("ACME", "INSPECTION AND TEST PLAN"), "procedure"),
        (("ACME", "PIPING MATERIAL SPECIFICATION"), "other"),
        (("ACME", "MINUTES OF THE KICK-OFF"), "other"),
    ],
)
def test_kind_from_the_papers_own_title(lines, want):
    got = paper_kind.decide_paper_kind([_page(*lines)])
    assert got.paper_kind == want
    assert got.paper_kind in paper_kind.PAPER_KINDS


def test_the_list_is_closed():
    assert paper_kind.PAPER_KINDS == (
        "datasheet",
        "procedure",
        "contract",
        "drawing",
        "test_record",
        "other",
    )
    for kind in (
        "specification",
        "transmittal",
        "feed",
        "standard",
        "unknown",
        None,
        "letter",
    ):
        assert paper_kind.to_paper_kind(kind) == "other"


def test_a_standard_is_other():
    got = paper_kind.decide_paper_kind(
        [_page("ACME", "HAZARD STUDY PROCEDURE")], document_role="COMPANY_STANDARD"
    )
    assert got.paper_kind == "other"


def test_number_outside_the_list_and_title_inside_takes_the_title_as_a_guess():
    page = _page("Document No. 99999-00-SP-0001", "AIR COOLER DATA SHEET")
    got = paper_kind.decide_paper_kind([page])
    assert (got.paper_kind, got.guess, got.source_kind) == (
        "datasheet",
        True,
        "specification",
    )


def test_engineer_confirmed_kind_decides():
    got = paper_kind.decide_paper_kind(
        [_page("ACME", "HAZARD STUDY PROCEDURE")], confirmed_kind="contract"
    )
    assert (got.paper_kind, got.method, got.guess) == (
        "contract",
        "engineer_confirmed",
        False,
    )


def test_file_name_never_decides(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("d1", [PROCEDURE], filename="CENTRIFUGAL PUMP DATA SHEET.pdf")
    assert paper_kind.classify_paper_kind("d1").paper_kind == "procedure"


# ------------------------------------------------------------- the switch


def test_switch_off_writes_no_kind():
    _doc("d1", [CONTRACT], role=None)
    assert paper_kind.classify_paper_kind("d1") is None
    tables = {r[0] for r in db.connect().execute("SELECT name FROM sqlite_master")}
    assert "paper_kinds" not in tables


def test_switch_on_every_paper_gets_a_kind(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("c1", [CONTRACT], role=None)
    _doc("p1", [PROCEDURE])
    _doc("s1", [_page("ACME", "STANDARD FOR WELDING")["text"]], role="COMPANY_STANDARD")
    for doc_id in ("c1", "p1", "s1"):
        paper_kind.classify_paper_kind(doc_id)
    assert [paper_kind.stored(d) for d in ("c1", "p1", "s1")] == [
        "contract",
        "procedure",
        "other",
    ]


# --------------------------------------------- the equipment type comes second


def test_switch_off_a_procedure_keeps_its_equipment_type_as_before():
    _doc("p1", [PROCEDURE])
    classification.classify_equipment_type_for_submittal("p1")
    assert _equipment("p1")[0] == "Centrifugal Compressor"


def test_procedure_gets_no_main_equipment_type_only_a_secondary(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("p1", [PROCEDURE])
    assert classification.classify_equipment_type_for_submittal("p1") is None
    equipment, evidence = _equipment("p1")
    assert equipment is None
    assert evidence["main_label"] == "procedure"
    assert evidence["secondary_equipment"]["equipment_type"] == "Centrifugal Compressor"
    assert paper_kind.main_label("p1") == "procedure"


def test_contract_gets_no_main_equipment_type(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("c1", [CONTRACT.replace("SUPPLY OF SPARE ITEMS", "CENTRIFUGAL PUMP SPARES")])
    classification.classify_equipment_type_for_submittal("c1")
    equipment, evidence = _equipment("c1")
    assert equipment is None and evidence["main_label"] == "contract"
    assert paper_kind.main_label("c1") == "contract"


def test_a_datasheet_keeps_its_main_equipment_type(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("d1", [DATASHEET])
    classification.classify_equipment_type_for_submittal("d1")
    assert _equipment("d1")[0] == "Centrifugal Pump"
    assert paper_kind.stored("d1") == "datasheet"
    assert paper_kind.main_label("d1") == "Centrifugal Pump"


def test_a_cleared_main_type_is_audited(monkeypatch):
    _doc("p1", [PROCEDURE])
    classification.classify_equipment_type_for_submittal("p1")  # switch off: a type
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    classification.classify_equipment_type_for_submittal("p1")
    rows = (
        db.connect()
        .execute(
            "SELECT detail FROM audit_events WHERE action = 'equipment_type_reclassified'"
            " AND resource_id = 'p1'"
        )
        .fetchall()
    )
    details = [json.loads(r["detail"]) for r in rows]
    assert {
        "old": "Centrifugal Compressor",
        "new": "none (procedure)",
    }.items() <= details[-1].items()


def test_kind_never_changes_who_may_read(monkeypatch):
    """Rule 5: classification is not access control. No access row is written."""
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("p1", [PROCEDURE])
    conn = db.connect()
    grant_tables = ["document_role_access", "user_roles", "roles"]
    before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in grant_tables
    }
    classification.classify_equipment_type_for_submittal("p1")
    after = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in grant_tables
    }
    assert grant_tables and before == after


def test_ingest_labels_every_paper_after_routing(monkeypatch):
    from app import ingest

    _doc("c1", [CONTRACT], role=None)
    result: dict = {}
    ingest._route_document_kind("c1", result)
    tables = {r[0] for r in db.connect().execute("SELECT name FROM sqlite_master")}
    assert "paper_kinds" not in tables  # switch off: as it was
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    ingest._route_document_kind("c1", result)
    assert paper_kind.stored("c1") == "contract"


def test_main_label_of_a_procedure_is_never_its_stored_type(monkeypatch):
    """A record nobody may reclassify (confirmed) can still hold a type: the main label is the kind."""
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("p1", [PROCEDURE])
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = 'Centrifugal Compressor'"
            " WHERE document_id = 'p1'"
        )
    paper_kind.classify_paper_kind("p1")
    assert paper_kind.main_label("p1") == "procedure"


def test_a_failed_kind_decision_stores_no_main_type(monkeypatch):
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("p1", [PROCEDURE])

    def boom(_document_id):
        raise RuntimeError("disk")

    monkeypatch.setattr(paper_kind, "classify_paper_kind", boom)
    assert classification.classify_equipment_type_for_submittal("p1") is None
    assert _equipment("p1")[0] is None


# ------------------------------------------------ an engineer confirms a kind


def _confirmer():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at)"
            " VALUES ('u1','u@x.test','u','x','2026-11-11')"
        )
    return "u1"


def test_confirm_after_routing_gives_the_new_kind_and_main_label(monkeypatch):
    from app import doc_router

    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("d1", [DATASHEET])
    doc_router.route_document("d1")
    classification.classify_equipment_type_for_submittal("d1")
    assert paper_kind.main_label("d1") == "Centrifugal Pump"
    doc_router.confirm("d1", "procedure", _confirmer())
    assert paper_kind.stored("d1") == "procedure"
    assert paper_kind.main_label("d1") == "procedure"


def test_a_confirmed_procedure_has_no_main_equipment_type(monkeypatch):
    from app import doc_router

    _doc("d1", [DATASHEET])
    classification.classify_equipment_type_for_submittal("d1")  # switch off: a type
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    doc_router.confirm("d1", "procedure", _confirmer())
    equipment, evidence = _equipment("d1")
    assert equipment is None and evidence["main_label"] == "procedure"
    audit = (
        db.connect()
        .execute(
            "SELECT detail FROM audit_events WHERE resource_id = 'd1'"
            " AND action = 'equipment_type_reclassified'"
        )
        .fetchall()
    )
    assert json.loads(audit[-1]["detail"])["old"] == "Centrifugal Pump"


def test_confirming_back_to_a_datasheet_gives_the_type_back(monkeypatch):
    from app import doc_router

    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("p1", [PROCEDURE])
    classification.classify_equipment_type_for_submittal("p1")
    doc_router.confirm("p1", "datasheet", _confirmer())
    assert paper_kind.stored("p1") == "datasheet"
    assert _equipment("p1")[0] == "Centrifugal Compressor"


def test_confirm_with_the_switch_off_is_unchanged():
    from app import doc_router

    _doc("d1", [DATASHEET])
    classification.classify_equipment_type_for_submittal("d1")
    doc_router.confirm("d1", "procedure", _confirmer())
    assert _equipment("d1")[0] == "Centrifugal Pump"
    tables = {r[0] for r in db.connect().execute("SELECT name FROM sqlite_master")}
    assert "paper_kinds" not in tables


def test_an_engineer_may_confirm_a_test_record(monkeypatch):
    from app import doc_router

    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    _doc("d1", [DATASHEET])
    assert "test_record" in [k["id"] for k in doc_router.kinds()]
    doc_router.confirm("d1", "test_record", _confirmer())
    assert paper_kind.stored("d1") == "test_record"
    assert (
        paper_kind.main_label("d1") == "Centrifugal Pump"
    )  # a test record keeps its type


def test_a_confirmed_procedure_loses_its_main_type_even_on_a_confirmed_record(
    monkeypatch,
):
    """The equipment classifier leaves a confirmed record alone; the kind confirmation still applies the rule."""
    from app import doc_router

    _doc("d1", [DATASHEET])
    classification.classify_equipment_type_for_submittal("d1")  # switch off: a type
    user = _confirmer()
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET confirmed_by = ? WHERE document_id = 'd1'",
            (user,),
        )
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    doc_router.confirm("d1", "contract", user)
    assert _equipment("d1")[0] is None
    assert paper_kind.main_label("d1") == "contract"


MAIN_KINDS = [
    "specification",
    "transmittal",
    "contract",
    "drawing",
    "datasheet",
    "procedure",
    "study",
    "report",
    "feed",
    "standard",
    "letter",
]


def test_switch_off_the_confirm_list_is_as_on_main(monkeypatch):
    from app import doc_router

    _doc("d1", [DATASHEET])
    assert [k["id"] for k in doc_router.kinds()] == MAIN_KINDS
    with pytest.raises(doc_router.UnknownKind):
        doc_router.confirm("d1", "test_record", _confirmer())
    monkeypatch.setattr(settings, "paper_kind_first_enabled", True)
    assert [k["id"] for k in doc_router.kinds()] == [*MAIN_KINDS, "test_record"]
