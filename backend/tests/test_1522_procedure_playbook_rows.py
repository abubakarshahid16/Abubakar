"""#1522 (b): a procedure's CRS gets its playbook rows as engineer rows.

INVENTED documents only (CLAUDE.md rule 3). No model: the rows come from
`playbooks.review` with no proposer. Each test fails without the code it names.
"""

from __future__ import annotations

import pytest

from app import access, db, playbooks, procedure_playbook_rows, submittal_review
from app import main as main_mod
from app.config import settings
from tests.test_w5b_679_playbooks import HAZOP_SECTIONS, hold

NOW = "2026-11-01T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t1522.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(
    doc_id,
    sections,
    cover="HAZOP Procedure\nDocument HP-001 revision 0",
    kind="procedure",
):
    pages = [cover] + [f"{title}\n{text}" for title, text in sections]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'x','ready',?,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", len(pages), NOW),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, n, text, len(text)),
            )
            if n > 1:
                title, body = sections[n - 2]
                conn.execute(
                    "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
                    "text,token_count,content_hash,retrievable) VALUES (?,?,?,?,?,?,?,'prose',?,1,?,1)",
                    (
                        f"{doc_id}-c{n}",
                        doc_id,
                        f"{doc_id}.pdf",
                        n,
                        n,
                        n,
                        title,
                        f"{title}\n{body}",
                        f"h-{doc_id}-{n}",
                    ),
                )
        if kind:
            conn.execute(
                "INSERT INTO document_kinds (document_id,kind,state,routed_at) VALUES (?,?,'confirmed',?)",
                (doc_id, kind, NOW),
            )
    return doc_id


def _run(doc_id):
    return submittal_review.create_review_run(
        submittal_document_id=doc_id, allowed_document_ids=frozenset({doc_id})
    )


def _crs(run):
    rows, meta, _name, _stamp = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    return rows, meta


def _mine(rows):
    return [r for r in rows if r["row_kind"] == procedure_playbook_rows.ROW_KIND]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "procedure_playbook_rows_enabled", True)


def test_with_the_switch_off_the_crs_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "procedure_playbook_rows_enabled", False)
    run = _run(_doc("p1", HAZOP_SECTIONS))
    rows_off, meta_off = _crs(run)
    assert _mine(rows_off) == []
    assert all("Playbook check" not in n["note"] for n in meta_off["review_notes"])


def test_on_a_hazop_procedure_has_one_engineer_row_per_element_and_none_compliant(on):
    hold("IEC 61882")
    run = _run(_doc("p1", HAZOP_SECTIONS))
    rows, _meta = _crs(run)
    mine = _mine(rows)
    found, _ = playbooks.available()
    assert len(mine) == len(found["hazop_procedure"].elements)
    assert len({r["comment_key"] for r in mine}) == len(mine)
    for r in mine:
        assert r["engineer_confirmed"] is False
        assert "compliant" not in r["comment"].lower().replace("non-compliant", "")
        assert r["comment_by"] == procedure_playbook_rows.BY
        assert (
            "not been signed off" in r["comment"]
        )  # the draft notice travels with the row
        assert r["standard_reference"].startswith("IEC 61882")
    team = next(r for r in mine if "Team and roles" in r["comment"])
    assert "found at" in team["comment"] and "engineer to confirm" in team["comment"]
    assert team["page_section"]


def test_a_removed_section_makes_its_element_row_not_found(on):
    hold("IEC 61882")
    cut = [s for s in HAZOP_SECTIONS if s[0] != "Follow-up"]
    full = _mine(_crs(_run(_doc("p1", HAZOP_SECTIONS)))[0])
    short = _mine(_crs(_run(_doc("p2", cut)))[0])

    def follow(rows):
        return next(
            r
            for r in rows
            if "Recommendations and their follow-up" in r["comment"].split(":")[0]
        )

    assert "found at" in follow(full)["comment"]
    assert "found at" not in follow(short)["comment"]
    assert follow(short)["playbook_state"] in (playbooks.UNCLEAR, playbooks.MISSING)
    assert "engineer to check" in follow(short)["comment"]
    assert follow(short)["page_section"] == ""


def test_a_standard_not_held_keeps_the_playbooks_wording_and_is_never_met(on):
    run = _run(_doc("p1", HAZOP_SECTIONS))  # IEC 61882 is not in the library
    mine = _mine(_crs(run)[0])
    assert mine and all(
        r["playbook_state"] == playbooks.STANDARD_NOT_HELD for r in mine
    )
    assert all(
        "is not in the library" in r["comment"]
        and "not a finding that it is met" in r["comment"]
        for r in mine
    )


def test_a_non_procedure_kind_gets_no_rows_and_no_note(on):
    for kind in ("datasheet", None):
        run = _run(_doc(f"d-{kind}", HAZOP_SECTIONS, kind=kind))
        rows, meta = _crs(run)
        assert _mine(rows) == []
        assert all("Playbook check" not in n["note"] for n in meta["review_notes"])


def test_no_matching_playbook_means_no_rows_and_a_note_saying_so(on):
    run = _run(
        _doc(
            "p1", HAZOP_SECTIONS, cover="Pipe cleaning method statement\nDocument PC-9"
        )
    )
    rows, meta = _crs(run)
    assert _mine(rows) == []
    notes = [n for n in meta["review_notes"] if "no playbook matched" in n["note"]]
    assert len(notes) == 1


def test_the_playbook_is_chosen_by_its_title_cue_and_only_the_run_scope_is_read(
    on, monkeypatch
):
    hold("IEC 61511-1")
    seen = []
    real = playbooks.review

    def spy(document_id, playbook, *, allowed_document_ids, proposer=None):
        seen.append((playbook.id, allowed_document_ids, proposer))
        return real(
            document_id,
            playbook,
            allowed_document_ids=allowed_document_ids,
            proposer=proposer,
        )

    monkeypatch.setattr(playbooks, "review", spy)
    run = _run(
        _doc("p1", HAZOP_SECTIONS, cover="SIL assessment procedure\nDocument S-1")
    )
    rows, _meta = _crs(run)
    assert [s[0] for s in seen] == ["sil_procedure"]
    assert (
        seen[0][1] == frozenset({"p1", "std_iec615111"}) and seen[0][2] is None
    )  # the caller's scope, no model
    assert len(_mine(rows)) == len(playbooks.available()[0]["sil_procedure"].elements)


def test_off_the_whole_crs_equals_the_crs_without_the_wiring(monkeypatch):
    # #1528 review: compare the WHOLE CRS (rows and meta) with what it is when
    # the playbook step is not wired at all, not only "no playbook rows".
    run = _run(_doc("p1", HAZOP_SECTIONS))
    rows_off, meta_off = _crs(run)
    monkeypatch.setattr(
        procedure_playbook_rows, "merge", lambda rows, *_a, **_k: (rows, [])
    )
    rows_unwired, meta_unwired = _crs(run)
    assert rows_off == rows_unwired
    assert meta_off == meta_unwired


def _chosen_ids(cover, monkeypatch):
    seen = []
    real = playbooks.review

    def spy(document_id, playbook, *, allowed_document_ids, proposer=None):
        seen.append(playbook.id)
        return real(
            document_id,
            playbook,
            allowed_document_ids=allowed_document_ids,
            proposer=proposer,
        )

    monkeypatch.setattr(playbooks, "review", spy)
    _crs(_run(_doc("p1", HAZOP_SECTIONS, cover=cover)))
    return sorted(seen)


def test_a_cover_sentence_that_only_mentions_hazop_does_not_choose_the_hazop_playbook(
    on, monkeypatch
):
    cover = (
        "SIL assessment procedure\n"
        "This procedure is issued following the HAZOP study of the plant\n"
        "Document S-1"
    )
    assert _chosen_ids(cover, monkeypatch) == ["sil_procedure"]


def test_a_combined_title_chooses_both_playbooks(on, monkeypatch):
    cover = "HAZOP & SIL ASSESSMENT PROCEDURE\nDocument HS-1"
    assert _chosen_ids(cover, monkeypatch) == ["hazop_procedure", "sil_procedure"]


def test_a_hazop_title_chooses_only_the_hazop_playbook(on, monkeypatch):
    assert _chosen_ids("HAZOP Study Procedure\nDocument H-1", monkeypatch) == [
        "hazop_procedure"
    ]
