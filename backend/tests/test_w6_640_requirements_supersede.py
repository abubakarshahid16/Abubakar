"""#640: requirements are superseded, never deleted, on re-extraction.

Before: `standards.extract_requirements(replace=True)` DELETED every
unconfirmed requirement of a standard and wrote new rows with new ids, and
`review_findings.requirement_id` has no foreign key - so a re-extraction
orphaned every finding citing the old rows (about 117,000 counted on a copy,
which is what blocked #599). Now, as #179 did for facts:

  1. a requirement the run produces again keeps its row and id; an
     unconfirmed one it no longer produces is marked `superseded_at` +
     `superseded_by_run`; a confirmed one is never touched; findings still
     resolve their rows and an old review still opens with its evidence;
  2. every reader of CURRENT requirements - a new or re-run review included -
     sees active rows only;
  3. `scripts/rehearse_requirement_reextraction.py` runs it for every
     standard on a COPY, refuses the live database, and prints the counts.

Invented documents only. Mutations M3601-M3620; M34 and M327 re-anchored here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import ai_engineering_check, comparison, db, keyword, standards, submittal_review
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.main import app

NOW = "2026-10-09T00:00:00Z"
NEW_COLUMNS = {"superseded_at", "superseded_by_run", "extraction_run_id"}
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w6.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


# ---------------------------------------------------------------- helpers

LINES = [
    "5.3.3 Noise",
    "The noise level of rotating equipment shall not exceed 90 dB(A) at",
    "one metre from the equipment surface under rated operating conditions.",
]


def _standard(name="std.pdf", lines=LINES) -> str:
    path = settings.data_dir / name
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 16), line)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    extract_document(doc_id)
    chunk_document(doc_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_classification"
            " (document_id, suggested_by, document_role) VALUES (?, 'test', 'COMPANY_STANDARD')",
            (doc_id,))
    return doc_id


def _chunk(std: str) -> str:
    return db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? ORDER BY ordinal LIMIT 1",
        (std,)).fetchone()["id"]


def _row(std: str, text: str, *, confirmed_by: str | None = None,
         requirement_type: str | None = None, identity_key: str | None = None,
         superseded: bool = False) -> str:
    req_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, clause,"
            " page, chunk_id, requirement_text, source_text, confirmed_by,"
            " requirement_type, identity_key, superseded_at, created_at, updated_at)"
            " VALUES (?,?,?,1,?,?,?,?,?,?,?,?,?)",
            (req_id, std, "5.3.3", _chunk(std), text, text, confirmed_by,
             requirement_type, identity_key, NOW if superseded else None, NOW, NOW))
    return req_id


def _user() -> str:
    user_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at)"
            " VALUES (?, ?, 'Engineer', 'x', ?)", (user_id, f"{user_id}@example.test", NOW))
    return user_id


def _finding_citing(req_id: str) -> str:
    sub = str(uuid.uuid4())
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (sub, "sub.pdf", f"sha-{sub}", "sub.pdf", NOW))
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'completed',?,?)", (run, sub, NOW, NOW))
    requirement = dict(db.connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?", (req_id,)).fetchone())
    comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=None, verdict=comparison.compare(requirement, None))
    return run


def _get(req_id: str) -> dict | None:
    row = db.connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?", (req_id,)).fetchone()
    return dict(row) if row else None


def _sentence_rows(std: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM standard_requirements WHERE standard_document_id = ?"
        " AND COALESCE(requirement_type, '') != 'table_value' ORDER BY id", (std,))]


def _scope(*ids):
    return frozenset(ids)


# ------------------------------------------------- 1a. the schema migration

def _columns(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[1]: r[2] for r in conn.execute("PRAGMA table_info(standard_requirements)")}


def test_a_fresh_database_has_the_supersede_columns():
    assert NEW_COLUMNS <= set(_columns(db.connect()))


def test_a_migrated_database_ends_with_the_same_columns_as_a_fresh_one(tmp_path, monkeypatch):
    """A database built before #640 has the table without the columns, and
    `CREATE TABLE IF NOT EXISTS` is a no-op there: only the migration adds
    them. Same names AND types as a fresh database."""
    fresh = _columns(db.connect())
    old_shape = {k: v for k, v in fresh.items() if k not in NEW_COLUMNS}
    db.reset_connection()
    monkeypatch.setattr(settings, "db_path", tmp_path / "old.sqlite")
    db.init_db()
    with db.connect() as conn:
        conn.execute("CREATE TABLE standard_requirements ("
                     + ", ".join(f"{k} {v}" for k, v in old_shape.items()) + ")")
    assert NEW_COLUMNS.isdisjoint(_columns(db.connect())), "precondition: the old shape"
    submittal_review.ensure_schema()
    assert _columns(db.connect()) == fresh


# ------------------------------------------- 1b. re-extraction keeps, marks

def test_a_requirement_met_again_keeps_its_row_and_its_id():
    """A finding citing an unchanged requirement must keep pointing at the
    LIVE row, not at a superseded copy of the same sentence."""
    std = _standard()
    first = standards.extract_requirements(std, allowed_document_ids=_scope(std))
    before = _sentence_rows(std)
    assert first["requirements"] == len(before) >= 1

    second = standards.extract_requirements(std, allowed_document_ids=_scope(std))
    after = _sentence_rows(std)

    assert [r["id"] for r in after] == [r["id"] for r in before]
    assert all(r["superseded_at"] is None for r in after)
    assert second["kept"] == len(before) and second["superseded"] == 0
    assert {r["extraction_run_id"] for r in after} == {second["extraction_run_id"]}


def test_a_row_no_longer_produced_is_superseded_with_time_and_run_never_deleted():
    std = _standard()
    gone = _row(std, "The colour of the casing shall be grey.")
    _finding_citing(gone)

    result = standards.extract_requirements(std, allowed_document_ids=_scope(std))

    row = _get(gone)
    assert row is not None, "the re-extraction deleted the row"
    assert row["superseded_at"] is not None
    assert row["superseded_by_run"] == result["extraction_run_id"]
    assert result["superseded"] == 1
    [event] = [dict(e) for e in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'requirements.superseded.re_extraction'")]
    assert event["detail"] == (f"run={result['extraction_run_id']} "
                               "requirements_superseded=1 findings_citing=1")


def test_a_confirmed_requirement_is_never_superseded_or_deleted():
    std = _standard()
    confirmed = _row(std, "The casing shall be painted by the vendor.", confirmed_by=_user())

    standards.extract_requirements(std, allowed_document_ids=_scope(std))
    standards.extract_table_values(std, allowed_document_ids=_scope(std))

    row = _get(confirmed)
    assert row is not None and row["superseded_at"] is None


def test_the_finding_still_resolves_and_the_old_review_opens_with_its_evidence():
    std = _standard()
    gone = _row(std, "The noise level shall not exceed 85 dB(A).")
    _finding_citing(gone)

    standards.extract_requirements(std, allowed_document_ids=_scope(std))

    [finding] = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE requirement_id = ?", (gone,))]
    assert _get(finding["requirement_id"])["requirement_text"] == (
        "The noise level shall not exceed 85 dB(A).")
    comparison.attach_crs_context([finding])
    assert finding.get("requirement_limit") is not None


def test_each_extractor_supersedes_only_its_own_rows():
    """A sentence run never marks a table cell; the table run marks the
    cells it no longer produces."""
    std = _standard()
    cell = _row(std, "Fan - Speed: 900", requirement_type="table_value",
                identity_key="sig\x1ffan\x1fspeed\x1f900")

    standards.extract_requirements(std, allowed_document_ids=_scope(std))
    assert _get(cell)["superseded_at"] is None

    result = standards.extract_table_values(std, allowed_document_ids=_scope(std))
    assert _get(cell)["superseded_at"] is not None
    assert _get(cell)["superseded_by_run"] == result["extraction_run_id"]


def test_without_replace_nothing_is_superseded():
    std = _standard()
    other = _row(std, "The colour of the casing shall be grey.")
    standards.extract_requirements(std, allowed_document_ids=_scope(std), replace=False)
    standards.extract_table_values(std, allowed_document_ids=_scope(std), replace=False)
    assert _get(other)["superseded_at"] is None


# ------------------------------------------------- 2. active rows only

def test_every_list_and_count_of_current_requirements_leaves_out_superseded_rows():
    std = _standard()
    active = _row(std, "The bearing temperature shall not exceed 95 C.")
    old = _row(std, "The bearing temperature shall not exceed 90 C.", superseded=True)
    scope = _scope(std)

    listed = {r["id"] for r in standards.list_requirements(std, allowed_document_ids=scope)}
    assert active in listed and old not in listed
    listed = {r["id"] for r in submittal_review.list_standard_requirements(
        allowed_document_ids=scope)}
    assert active in listed and old not in listed
    queue = {r["id"] for r in standards.verification_queue(allowed_document_ids=scope)}
    assert active in queue and old not in queue
    [row] = standards.list_standards(allowed_document_ids=scope)
    assert row["requirement_count"] == 1
    assert row["awaiting_verification"] == 1


def test_a_new_review_never_compares_a_superseded_requirement():
    std = _standard()
    active = _row(std, "The bearing temperature shall not exceed 95 C.")
    old = _row(std, "The bearing temperature shall not exceed 90 C.", superseded=True)
    sub = str(uuid.uuid4())
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (sub, "sub.pdf", f"sha-{sub}", "sub.pdf", NOW))
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)", (run, sub, NOW, NOW))
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_method,included,created_at)"
            " VALUES (?,?,?,'rule',1,?)", (str(uuid.uuid4()), run, std, NOW))

    result = comparison.run_comparison(run, allowed_document_ids=_scope(std, sub))

    cited = {f["requirement_id"] for f in result["findings"]}
    assert active in cited and old not in cited


def test_the_held_clauses_of_a_review_leave_out_superseded_rows():
    std = _standard()
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET clause = '9.9' WHERE id = ?",
            (_row(std, "The old clause shall be gone.", superseded=True),))
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)", (run, std, NOW, NOW))
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_method,included,created_at)"
            " VALUES (?,?,?,'rule',1,?)", (str(uuid.uuid4()), run, std, NOW))
    held = ai_engineering_check._held_standards(run)
    assert "9.9" not in [c for clauses in held.values() for c in clauses]


def test_a_table_cell_met_again_merges_into_the_active_row_not_a_superseded_one():
    std = _standard()
    key = "sig\x1fpump\x1fspeed\x1f1500"
    _row(std, "Pump - Speed: 1500", requirement_type="table_value",
         identity_key=key, superseded=True)
    stored = standards.create_requirement(
        standard_document_id=std, chunk_id=_chunk(std), requirement_text="Pump - Speed: 1500",
        source_text="Pump | Speed | 1500", clause=None, page=1,
        structured={"requirement_type": "table_value", "identity_key": key})
    assert stored["upserted"] == "created"


# ------------------------------------------------- 3. the rehearsal script

def _script():
    spec = importlib.util.spec_from_file_location(
        "rehearse", REPO / "scripts" / "rehearse_requirement_reextraction.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rehearsal_refuses_a_live_database_path(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    before = live.stat().st_mtime_ns
    with pytest.raises(SystemExit, match="refusing"):
        _script().main(["--db", str(live)])
    assert live.read_bytes() == b"" and live.stat().st_mtime_ns == before


def test_the_rehearsal_refuses_this_checkouts_live_file_by_identity(tmp_path, monkeypatch):
    """A copy that IS the live file under another name (a link) is refused."""
    script = _script()
    target = tmp_path / "copy.sqlite"
    target.write_bytes(b"")
    monkeypatch.setattr(script, "LIVE", target)
    with pytest.raises(SystemExit, match="this checkout's live database"):
        script.refuse_live(target)


def test_the_rehearsal_reports_before_and_after_and_loses_nothing(capsys):
    std = _standard()
    confirmed = _row(std, "The casing shall be painted by the vendor.", confirmed_by=_user())
    gone = _row(std, "The colour of the casing shall be grey.")
    _finding_citing(gone)
    key = "sig\x1ffan\x1fspeed\x1f900"
    for _ in range(2):   # a duplicate within a table, as #594 found on a copy
        _row(std, "Fan - Speed: 900", requirement_type="table_value", identity_key=key)
    path = Path(settings.db_path)
    db.reset_connection()

    code = _script().main(["--db", str(path)])
    out = capsys.readouterr().out

    assert code == 0 and "SAFE" in out
    db.reset_connection()
    summary = _script().rehearse(path)   # a second run: the numbers are stable
    assert summary["before"]["confirmed"] == summary["after"]["confirmed"] == 1
    assert summary["after"]["findings_requirement_unresolved"] == 0
    assert summary["after"]["duplicate_table_cells_active"] == 0
    assert summary["after"]["requirements_superseded"] >= 3
    db.reset_connection()
    assert _get(confirmed)["superseded_at"] is None
    assert _get(gone)["superseded_at"] is not None
    for word in ("requirements_active", "duplicate_table_cells_active", "confirmed",
                 "findings_requirement_unresolved"):
        assert word in out


def test_search_conflicts_and_missing_standards_read_active_rows_only(monkeypatch):
    """The three remaining readers of current requirements. Each one's own
    logic is stubbed; only the rows it is handed are checked."""
    from app import requirements_3b, standards_inventory
    from app import search as search_mod

    std = _standard()
    active = _row(std, "The pump shall be designed in accordance with API 610.")
    old = _row(std, "The pump shall be designed in accordance with API 674.", superseded=True)
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET value = 1, field = 'temperature',"
                     " requirement_type = ?", (requirements_3b.APPLICABILITY_TRIGGER,))
    scope = _scope(std)

    monkeypatch.setattr(search_mod, "search", lambda *a, **k: {
        "hits": [{"chunk_id": _chunk(std), "document_id": std, "score": 1.0,
                  "bm25": None, "cosine": None}],
        "mode": "hybrid", "reranked": False, "timings": {}, "total": 1, "seconds": 0.0})
    found = {r["id"] for r in standards.search_requirements("bearing", allowed_document_ids=scope)}
    assert active in found and old not in found

    handed: list[str] = []
    monkeypatch.setattr(requirements_3b, "find_conflicts",
                        lambda rows: handed.extend(r["id"] for r in rows) or [])
    standards.conflicts(allowed_document_ids=scope)
    assert active in handed and old not in handed

    cited = str(standards_inventory._requirement_citations(allowed_document_ids=scope))
    assert "610" in cited, cited
    assert "674" not in cited


# ------------------------------------------------- #673 the repeats are counted

def _bare_standard() -> str:
    """A standard built from rows alone: these counts do not need the chunker."""
    doc_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'s.pdf','ready',1,?)", (doc_id, "s.pdf", f"sha-{doc_id}", NOW))
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, kind,"
            " text, token_count, content_hash) VALUES (?,?,?,?,1,1,'prose','t',1,?)",
            (f"c-{doc_id}", doc_id, "s.pdf", 0, f"h-{doc_id}"))
    return doc_id


def test_the_rehearsal_counts_old_style_repeats_that_the_narrow_counts_miss():
    """Rows written before #594 have no identity key, and a repeat can sit under
    another clause. The two narrow counts said 0 for both; the plain count
    (same standard, same text) must see them, and count superseded ones apart."""
    std = _bare_standard()
    for _ in range(3):      # a table cell met three times, no identity key
        _row(std, "Fan - Speed: 900", requirement_type="table_value", identity_key=None)
    first = _row(std, "The casing shall be painted.")
    second = _row(std, "The casing shall be painted.")
    with db.connect() as conn:    # the repeat is filed under another clause
        conn.execute("UPDATE standard_requirements SET clause = '7.1' WHERE id = ?", (second,))
    _row(std, "The shaft shall be balanced.")
    _row(std, "The shaft shall be balanced.", superseded=True)
    counted = _script().counts(db.connect())
    assert counted["duplicate_table_cells_active"] == 0     # the old blind spots,
    assert counted["duplicate_sentences_active"] == 0       # kept as they were
    assert counted["repeated_rows_active"] == 3             # 2 extra cells + 1 sentence
    assert counted["repeated_table_cell_rows_active"] == 2
    assert counted["repeated_rows_including_superseded"] == 4
    assert first != second


def test_the_rehearsal_prints_the_repeated_share_with_its_denominator(capsys):
    std = _bare_standard()
    for _ in range(2):
        _row(std, "Fan - Speed: 900", requirement_type="table_value")
    path = Path(settings.db_path)
    db.reset_connection()
    _script().main(["--db", str(path)])
    out = capsys.readouterr().out
    assert "repeated rows before:" in out and "active rows" in out
