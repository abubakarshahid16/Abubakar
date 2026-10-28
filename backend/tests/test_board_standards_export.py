"""Order 274.6, Tab 3 Standards: the board's data for the standards library. Invented standards only.
What is proven here: the export is read-only on a copy and refuses a live path, a folder inside the repository
and any file already saved; every number carries the file it came from; a verified converter row shows its
check, an unproven row never shows a limit, a rule the converter did not reach is grey and says why; a standard
the sheet cites but the library does not hold is listed by sheet."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from app import db, rule_roles, standards, submittal_review
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import board_standards_export as bse

NOW = "2026-10-28T00:00:00Z"
SENTENCE = "The casing design pressure shall not exceed 25 bar."
OTHER = "Bearings shall be lubricated."
ADVICE = "The pump should be installed on a rigid base."


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "library-copy.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, role: str, number: str | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',3,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role,document_number)"
            " VALUES (?,?,?,?)",
            (doc_id, "test", role, number),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
            (f"c-{doc_id}", doc_id, "f.pdf", f"h-{doc_id}"),
        )


def _req(doc_id: str, text: str, clause: str, rtype: str = "statement") -> None:
    standards.create_requirement(
        standard_document_id=doc_id,
        chunk_id=f"c-{doc_id}",
        requirement_text=text,
        source_text=text,
        clause=clause,
        page=1,
        structured={"requirement_type": rtype},
    )


@pytest.fixture
def library():
    _doc("std-a", "COMPANY_STANDARD", "SAES-G-005")
    _req("std-a", SENTENCE, "6.1")
    _req("std-a", OTHER, "6.2")
    _req("std-a", ADVICE, "6.3", "recommendation")
    _doc("std-b", "COMPANY_STANDARD", "SAES-K-503")
    _req("std-b", OTHER + " Twice.", "4.1")
    _doc("sheet-1", "CONTRACTOR_SUBMITTAL", None)
    with db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    return settings.db_path


def _drafts(tmp_path: Path, entries: list[dict], **header) -> Path:
    folder = tmp_path / "drafts"
    folder.mkdir(exist_ok=True)
    body = {
        "converter": True,
        "status": "draft",
        "equipment_type": "Centrifugal Pump",
        "standard": "SAES-G-005",
        "lane": "local",
        "model": "test-model",
        "prompt_version": "o286-convert-v2",
        "run": "complete",
        "usd_spent": 0.0,
        "calls": 1,
        "counts": {},
        "form_source": {"ref": "#1352", "sha": "b54474a2"},
        "entries": entries,
        **header,
    }
    (folder / "pump.SAES_G_005.json").write_text(json.dumps(body))
    return folder


def _entry(text: str, **over) -> dict:
    return {
        "text_sha256": rule_roles.text_hash(text),
        "clause": "6.1",
        "status": "verified",
        "applies": None,
        "condition": None,
        "reason": None,
        "field": "design_pressure",
        "comparator": "<=",
        "limit": "25",
        "unit": "bar",
        "quote": "design pressure shall not exceed 25 bar",
        **over,
    }


def _load(folder: Path, name: str) -> dict:
    text = (folder / name).read_text()
    start = text.index("= ", text.rindex("window.BOARD")) + 2
    return json.loads(text[start:].rstrip().rstrip(";"))


def _run(library, tmp_path, entries=None, **kw):
    drafts = _drafts(tmp_path, entries) if entries is not None else None
    out = tmp_path / "mirror" / "standards"
    counts = bse.export(library, out, drafts, **kw)
    return counts, out


def test_the_export_writes_one_row_per_standard_and_every_rule(library, tmp_path):
    counts, out = _run(library, tmp_path, [])
    assert (counts["standards"], counts["rules"]) == (2, 4)
    lib = _load(out, "library.js")
    by_id = {s["id"]: s for s in lib["standards"]}
    a = by_id["std-a"]
    assert a["label"] == "SAES-G-005" and a["pages"] == 3
    assert a["rules_by_type"] == {"recommendation": 1, "statement": 2}
    assert (
        a["recommendations"] == 1
    )  # its own line, never added to the rules a review compares
    nums = {n["label"]: n["value"] for n in a["numbers"]}
    assert nums["rules held (without recommendations)"] == 2
    rules = _load(out, "rules-std-a.js")["rules"]
    assert [r["clause"] for r in rules] == ["6.1", "6.2", "6.3"]


def test_every_number_names_its_file_and_where_in_it(library, tmp_path):
    _counts, out = _run(library, tmp_path, [_entry(SENTENCE)])
    lib = _load(out, "library.js")
    every = list(lib["numbers"]) + [n for s in lib["standards"] for n in s["numbers"]]
    assert every
    for n in every:
        assert n["source_file"] and n["source_path"], n
    assert "boundary" in lib and "library-copy.sqlite" in lib["boundary"]


def test_a_verified_row_shows_its_check_beside_the_rule(library, tmp_path):
    _counts, out = _run(library, tmp_path, [_entry(SENTENCE)])
    rules = {r["clause"]: r for r in _load(out, "rules-std-a.js")["rules"]}
    got = rules["6.1"]["converter"]
    assert (got["status"], got["colour"], got["limit"], got["unit"], got["field"]) == (
        "verified",
        "green",
        "25",
        "bar",
        "design_pressure",
    )
    assert got["model"] == "test-model" and got["source_file"] == "pump.SAES_G_005.json"
    assert (
        rules["6.2"]["converter"] is None
    )  # the converter said nothing about this rule
    lib = _load(out, "library.js")
    assert lib["numbers"][2]["value"] == 1  # rules the converter proved


def test_an_unproven_row_never_shows_a_limit(library, tmp_path):
    entry = _entry(SENTENCE, status="unproven", reason="unit_not_in_quote")
    _counts, out = _run(library, tmp_path, [entry])
    got = {r["clause"]: r for r in _load(out, "rules-std-a.js")["rules"]}["6.1"][
        "converter"
    ]
    assert (got["status"], got["colour"], got["note"], got["reason"]) == (
        "unproven",
        "amber",
        "engineer, please look",
        "unit_not_in_quote",
    )
    for key in ("limit", "comparator", "unit", "field", "quote"):
        assert key not in got


@pytest.mark.parametrize("status", ["no_check", "not_asked", "not_applicable"])
def test_a_rule_with_no_check_or_not_asked_is_grey_and_never_a_check(
    library, tmp_path, status
):
    entry = _entry(SENTENCE, status=status, reason="not asked: stopped at cap")
    _counts, out = _run(library, tmp_path, [entry])
    got = {r["clause"]: r for r in _load(out, "rules-std-a.js")["rules"]}["6.1"][
        "converter"
    ]
    assert got["colour"] == "grey" and "limit" not in got
    assert got["reason"] == "not asked: stopped at cap"
    lib = _load(out, "library.js")
    assert lib["numbers"][2]["value"] == 0


def test_the_converter_file_row_names_lane_model_prompt_and_how_the_run_ended(
    library, tmp_path
):
    drafts = _drafts(tmp_path, [_entry(SENTENCE)], run="stopped at cap", lane="claude")
    out = tmp_path / "mirror"
    bse.export(library, out, drafts)
    [row] = _load(out, "converter.js")["files"]
    assert (row["lane"], row["model"], row["prompt_version"], row["run"]) == (
        "claude",
        "test-model",
        "o286-convert-v2",
        "stopped at cap",
    )
    assert row["form_sha"] == "b54474a2" and row["source_file"] == row["file"]


def test_a_file_that_is_not_a_converter_draft_is_skipped_and_a_broken_one_is_listed(
    library, tmp_path
):
    drafts = _drafts(tmp_path, [_entry(SENTENCE)])
    (drafts / "notes.json").write_text(json.dumps({"hello": 1}))
    (drafts / "broken.json").write_text("{not json")
    out = tmp_path / "mirror"
    bse.export(library, out, drafts)
    rows = {r["file"]: r for r in _load(out, "converter.js")["files"]}
    assert set(rows) == {"pump.SAES_G_005.json", "broken.json"}
    assert rows["broken.json"]["readable"] is False


def test_a_draft_for_another_standard_is_not_attached(library, tmp_path):
    drafts = _drafts(tmp_path, [_entry(SENTENCE)], standard="SAES-K-503")
    out = tmp_path / "mirror"
    bse.export(library, out, drafts)
    got = {r["clause"]: r for r in _load(out, "rules-std-a.js")["rules"]}["6.1"]
    assert got["converter"] is None


def test_without_a_converter_folder_the_library_still_exports(library, tmp_path):
    out = tmp_path / "mirror"
    counts = bse.export(library, out, None)
    assert counts["converter_files"] == 0
    assert _load(out, "converter.js")["files"] == []


def test_the_missing_standards_are_listed_by_sheet(library, tmp_path, monkeypatch):
    from app import standards_inventory

    cited = [
        {
            "identifier": "API 610",
            "standard_family": "API",
            "licence_status": "licensed_not_held",
            "cited_by": [
                {
                    "source_type": "submittal",
                    "document_id": "sheet-1",
                    "filename": "sheet-1.pdf",
                },
                {
                    "source_type": "submittal",
                    "document_id": "sheet-1",
                    "filename": "sheet-1.pdf",
                },
                {"source_type": "requirement", "document_id": "std-a", "clause": "6.1"},
            ],
        }
    ]
    monkeypatch.setattr(standards_inventory, "cited_but_not_held", lambda **kw: cited)
    out = tmp_path / "mirror"
    bse.export(library, out, None)
    miss = _load(out, "missing.js")
    [sheet] = miss["by_sheet"]
    assert (
        sheet["document_id"] == "sheet-1" and len(sheet["missing"]) == 1
    )  # one gap, not two mentions
    assert miss["cited_by_other_standards"][0]["cited_in"] == "std-a"
    assert {n["label"]: n["value"] for n in miss["numbers"]} == {
        "sheets with a missing standard": 1,
        "standards cited but not held": 1,
    }


def test_the_database_is_not_changed_by_the_export(library, tmp_path):
    before = library.read_bytes()
    bse.export(library, tmp_path / "mirror", None)
    assert library.read_bytes() == before


def test_a_folder_inside_the_repository_is_refused_and_nothing_is_written(
    library, tmp_path, monkeypatch
):
    """Against a throwaway 'repository': a broken check must never write into the real checkout."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setattr(bse, "REPO", fake_repo)
    inside = fake_repo / "docs" / "board"
    with pytest.raises(ValueError, match="inside the repository"):
        bse.export(library, inside, None)
    assert not inside.exists()


def test_a_saved_file_is_never_overwritten(library, tmp_path):
    out = tmp_path / "mirror"
    bse.export(library, out, None)
    first = (out / "library.js").read_text()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        bse.export(library, out, None)
    assert (out / "library.js").read_text() == first


def test_a_live_shaped_database_path_is_refused(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"x")
    with pytest.raises(SystemExit, match="live database"):
        bse.export(live, tmp_path / "mirror", None)
    assert not (tmp_path / "mirror").exists()


def test_the_command_prints_counts_only(library, tmp_path, capsys):
    drafts = _drafts(tmp_path, [_entry(SENTENCE)])
    assert (
        bse.main(
            [
                "--db",
                str(library),
                "--out",
                str(tmp_path / "m"),
                "--converter-dir",
                str(drafts),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "casing" not in printed and "SAES" not in printed and "bar" not in printed
    assert re.search(r'"standards": 2', printed)


def test_a_recommendation_the_converter_answered_is_never_shown_as_a_check_or_counted(
    library, tmp_path
):
    """A converter run made before the recommendation fix may hold a verified-looking answer for a "should"
    sentence. The board never shows it as a check and never counts it as proved."""
    advice = _entry(
        ADVICE, status="verified", field="design_pressure", limit="25", unit="bar"
    )
    _counts, out = _run(library, tmp_path, [advice, _entry(SENTENCE)])
    lib = _load(out, "library.js")
    a = {s["id"]: s for s in lib["standards"]}["std-a"]
    assert a["converter_by_status"] == {
        "verified": 1
    }  # the one real rule, not the advice
    assert a["recommendations_answered_by_converter_not_counted"] == 1
    rules = {r["clause"]: r for r in _load(out, "rules-std-a.js")["rules"]}
    assert (
        rules["6.3"]["converter"] is None and rules["6.3"]["type"] == "recommendation"
    )
    assert lib["numbers"][2]["value"] == 1
